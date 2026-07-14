# !/usr/bin/env python
# -*- coding: utf-8 -*-
"""ScreenshotStream：基于 Captures.startCaptureScreen 的推流截图与录屏。

通过独立 TCP 连接接收设备端持续推送的 JPEG 帧流，
与 RPC 控制通道隔离，避免数据混流。

工作流程：
1. 建立独立端口转发 + TCP 连接到设备端 uitest_socket
2. 通过截图 socket 发送 stopCaptureScreen（清理旧状态）
3. 通过截图 socket 发送 startCaptureScreen（启动推流）
4. 后台线程从截图 socket 持续读取并解析 JPEG 帧
5. 不录屏时：仅缓存最新一帧，get_frame() 返回 PIL Image
6. 录屏时：额外将帧序列写入临时目录，stop_recording() 合成视频

关键设计：stop/start 命令通过截图 socket 发送（UITest 协议帧），
不走 RPC 通道，因为设备端会将 JPEG 帧推送到发送命令的 socket 上。

使用完毕后调用 stop() 停止推流并释放资源。
"""
from __future__ import annotations

import io
import json
import logging
import os
import random
import socket
import struct
import subprocess
import threading
import time
from datetime import datetime
from typing import Optional, Tuple, TYPE_CHECKING

from PIL import Image as PILImage

from devhelmkit.exceptions import DevhelmError
from devhelmkit.harmony.device.hdc import (
    UITEST_SOCKET_NAME, RPC_PORT, RPC_HEAD, RPC_TAIL, HdcDevice
)

logger = logging.getLogger(__name__)

if TYPE_CHECKING:
    from PIL.Image import Image


# JPEG 帧标记
JPEG_SOI = b'\xff\xd8'
JPEG_EOI = b'\xff\xd9'

# 录屏合成 fps 下限与上限，防止异常帧率
MIN_RECORD_FPS = 1
MAX_RECORD_FPS = 30

# 性能排查日志开关：与 uiviewer.perf 使用同一环境变量，开启后周期性输出
# 生产端（设备到帧）实际帧率与帧间隔，用于定位投屏卡顿是采集侧还是推流侧。
# 用可变全局 + setter，支持 CLI --perf 在运行时开启（而非仅环境变量）。
_PERF_ENABLED = os.environ.get("DEVHELM_UIVIEWER_PERF", "").strip().lower() in (
    "1", "true", "yes", "on"
)


def set_perf_enabled(value: bool) -> None:
    """运行时开启/关闭生产端帧率性能日志。"""
    global _PERF_ENABLED
    _PERF_ENABLED = bool(value)

# 补帧最大间隔（秒）：当实际帧间隔超过此值时，按此值的倒数作为最低 fps 补帧
# 确保静置画面不会产生过长的单帧停留
MAX_FRAME_GAP = 0.5

# 单帧最大字节数：超过此限制仍未找到帧尾时，丢弃已累积数据防止缓冲区无限增长
MAX_FRAME_SIZE = 10 * 1024 * 1024

# UITest 协议体上限及性能日志聚合周期
MAX_PROTOCOL_BODY_SIZE = 4 * 1024 * 1024
PERF_LOG_INTERVAL = 2.0


class _CaptureDiagnostics:
    """采集 socket 与分帧器的低开销周期聚合统计。"""

    def __init__(self) -> None:
        """初始化一个新的聚合周期。"""
        self.reset()

    def reset(self) -> None:
        """清空周期计数，同时重新建立统计起点。"""
        self.period_start = time.perf_counter()
        self.last_recv_ts: Optional[float] = None
        self.recv_chunks = 0
        self.recv_bytes = 0
        self.recv_wait_total_ms = 0.0
        self.recv_wait_max_ms = 0.0
        self.recv_interval_max_ms = 0.0
        self.buffer_peak = 0
        self.parse_calls = 0
        self.parse_total_ms = 0.0
        self.parse_max_ms = 0.0
        self.protocol_frames = 0
        self.protocol_jpegs = 0
        self.protocol_other = 0
        self.raw_jpegs = 0
        self.protocol_waits = 0
        self.raw_waits = 0
        self.invalid_lengths = 0
        self.invalid_tails = 0
        self.raw_oversized = 0
        self.resync_events = 0
        self.discarded_bytes = 0

    def record_recv(self, wait_ms: float, chunk_bytes: int,
                    buffer_size: int, recv_ts: float) -> None:
        """聚合一次 socket 接收的等待、字节和缓冲区水位。"""
        if self.last_recv_ts is not None:
            interval_ms = (recv_ts - self.last_recv_ts) * 1000.0
            self.recv_interval_max_ms = max(
                self.recv_interval_max_ms, interval_ms
            )
        self.last_recv_ts = recv_ts
        self.recv_chunks += 1
        self.recv_bytes += chunk_bytes
        self.recv_wait_total_ms += wait_ms
        self.recv_wait_max_ms = max(self.recv_wait_max_ms, wait_ms)
        self.buffer_peak = max(self.buffer_peak, buffer_size)

    def record_parse(self, elapsed_ms: float, buffer_size: int) -> None:
        """聚合一次分帧解析耗时和解析后的缓冲区水位。"""
        self.parse_calls += 1
        self.parse_total_ms += elapsed_ms
        self.parse_max_ms = max(self.parse_max_ms, elapsed_ms)
        self.buffer_peak = max(self.buffer_peak, buffer_size)

    def record_discard(self, byte_count: int) -> None:
        """统计为恢复帧边界而丢弃的有效字节数。"""
        if byte_count <= 0:
            return
        self.resync_events += 1
        self.discarded_bytes += byte_count

    def maybe_log(self, buffer_size: int, force: bool = False) -> None:
        """达到聚合周期后输出统计；force 用于线程退出前刷新残余样本。"""
        now = time.perf_counter()
        elapsed = now - self.period_start
        if not force and elapsed < PERF_LOG_INTERVAL:
            return
        if self.recv_chunks == 0 and self.parse_calls == 0:
            self.period_start = now
            return

        avg_chunk_kb = (
            self.recv_bytes / max(self.recv_chunks, 1) / 1024.0
        )
        avg_wait_ms = self.recv_wait_total_ms / max(self.recv_chunks, 1)
        logger.info(
            "[perf] capture-io: recv=%.1f/s chunks=%d bytes=%.1fKB "
            "avg_chunk=%.1fKB avg_wait=%.1fms max_wait=%.1fms "
            "max_interval=%.1fms buffer=%dB peak=%dB",
            self.recv_chunks / max(elapsed, 0.001),
            self.recv_chunks,
            self.recv_bytes / 1024.0,
            avg_chunk_kb,
            avg_wait_ms,
            self.recv_wait_max_ms,
            self.recv_interval_max_ms,
            buffer_size,
            self.buffer_peak,
        )
        logger.info(
            "[perf] capture-parse: calls=%d total=%.2fms max=%.2fms "
            "protocol=%d(jpeg=%d other=%d wait=%d) "
            "raw_jpeg=%d raw_wait=%d invalid_len=%d invalid_tail=%d "
            "raw_oversized=%d resync=%d discarded=%dB",
            self.parse_calls,
            self.parse_total_ms,
            self.parse_max_ms,
            self.protocol_frames,
            self.protocol_jpegs,
            self.protocol_other,
            self.protocol_waits,
            self.raw_jpegs,
            self.raw_waits,
            self.invalid_lengths,
            self.invalid_tails,
            self.raw_oversized,
            self.resync_events,
            self.discarded_bytes,
        )
        last_recv_ts = self.last_recv_ts
        self.reset()
        # 保留上次到达时间，让跨统计周期的 recv 空窗仍计入 max_interval。
        self.last_recv_ts = last_recv_ts


class ScreenshotStream:
    """推流截图管理器，独立端口+socket，与 RPC 通道隔离。

    后台线程通过 _frame_cond 更新帧缓存并唤醒消费端；录屏状态由同一
    生产线程追加，停止流程先关闭 socket，再回收线程和端口转发。
    """

    def __init__(self, device: 'HdcDevice', scale: float = 0.99):
        """初始化连接、帧缓存、性能统计和录屏状态。"""
        self._device = device
        self._scale = scale
        self._local_port: Optional[int] = None
        self._sock: Optional[socket.socket] = None
        self._fport_established = False
        self._streaming = False
        self._thread: Optional[threading.Thread] = None
        self._latest_frame: Optional[bytes] = None
        self._frame_seq: int = 0
        self._frame_lock = threading.Lock()
        # 复用 _frame_lock 作为底层锁：新帧到达时唤醒 wait_frame_bytes_seq 的
        # 消费者（MJPEG 推流循环），消除固定轮询延迟，实现帧到即推。
        self._frame_cond = threading.Condition(self._frame_lock)
        self._frame_event = threading.Event()
        self._recv_buffer = bytearray()

        # 生产端帧率统计（性能排查用，受 DEVHELM_UIVIEWER_PERF 控制）
        self._perf_frames = 0
        self._perf_bytes = 0
        self._perf_last_ts: Optional[float] = None
        self._perf_gap_max = 0.0
        self._perf_period_start = 0.0
        self._perf_diagnostics = _CaptureDiagnostics()

        # 录屏状态
        self._recording: bool = False
        self._record_dir: Optional[str] = None
        self._record_output_dir: Optional[str] = None
        self._record_frame_count: int = 0
        self._record_start_time: float = 0.0
        self._record_end_time: float = 0.0
        # 每帧时间戳列表（相对录屏开始的秒数），用于补帧
        self._record_timestamps: list = []

    def start(self, timeout: float = 10.0) -> bool:
        """启动推流：建立独立连接 -> stop -> start -> 后台接收。

        Args:
            timeout: 等待首帧的超时秒数

        Returns:
            True 如果成功收到首帧
        """
        if self._streaming:
            return True

        max_retries = 2
        for attempt in range(1, max_retries + 1):
            try:
                self._setup_connection()
                self._send_stop_then_start()
                self._start_recv_thread()

                # 等待首帧
                if self._frame_event.wait(timeout=timeout):
                    logger.debug("ScreenshotStream 推流已启动 (port=%d, scale=%.4f)",
                                self._local_port, self._scale)
                    return True
                logger.warning("ScreenshotStream 等待首帧超时 (尝试 %d/%d)", attempt, max_retries)
                self.stop()
            except Exception as e:
                logger.warning("ScreenshotStream 启动失败 (尝试 %d/%d): %s", attempt, max_retries, e)
                self.stop()

            if attempt < max_retries:
                try:
                    logger.info("ScreenshotStream 尝试清理设备端 uitest 残留进程...")
                    self._device.shell("killall -9 uitest")
                except Exception as ex:
                    logger.warning("清理设备端 uitest 进程异常: %s", ex)
                time.sleep(1.0)

        logger.error("ScreenshotStream 最终启动失败")
        return False

    def get_frame(self) -> Optional['Image']:
        """获取最新一帧截图。

        Returns:
            PIL.Image 或 None（尚未收到帧）
        """
        with self._frame_lock:
            frame_data = self._latest_frame
        if frame_data is None:
            return None
        return PILImage.open(io.BytesIO(frame_data))

    def get_frame_bytes(self) -> Optional[bytes]:
        """获取最新一帧的原始 JPEG bytes，未推流或暂无帧时返回 None。

        跳过 PIL 解码+重编码，供 MJPEG 直推等低延迟场景使用。
        """
        if not self._streaming:
            return None
        with self._frame_lock:
            return self._latest_frame

    def get_frame_bytes_seq(self) -> Tuple[int, Optional[bytes]]:
        """返回 (帧序号, 最新帧 bytes)。

        序号单调递增，消费方可据此判断帧是否变化，避免重复推送同一帧。
        未推流时返回 (当前序号, None)。
        """
        if not self._streaming:
            return self._frame_seq, None
        with self._frame_lock:
            return self._frame_seq, self._latest_frame

    def wait_frame_bytes_seq(self, last_seq: int,
                             timeout: float) -> Tuple[int, Optional[bytes]]:
        """阻塞等待比 last_seq 更新的帧，返回 (帧序号, 最新帧 bytes)。

        帧到即返回，消除消费端固定轮询延迟；timeout 秒内无新帧则返回当前
        (seq, frame)，供消费端做心跳与断连探测。未推流返回 (当前序号, None)。
        并发 stop() 会 notify 唤醒等待者，避免卡满整个 timeout。
        """
        if not self._streaming:
            return self._frame_seq, None
        with self._frame_cond:
            if self._frame_seq == last_seq and self._streaming:
                self._frame_cond.wait(timeout)
            return self._frame_seq, self._latest_frame

    # ============================================================
    # 录屏
    # ============================================================

    def start_recording(self, output_dir: str) -> None:
        """开始录屏，将后续帧序列写入指定目录。

        必须在推流已启动（start() 成功）后调用。
        JPEG 帧存放在 output_dir/frames/ 子目录，mp4 存放在 output_dir/。

        Args:
            output_dir: 录屏输出目录（JPEG 帧和最终 mp4 都在此目录下）
        """
        if not self._streaming:
            raise DevhelmError("推流未启动，无法开始录屏")

        if self._recording:
            logger.warning("录屏已在进行中，忽略重复调用")
            return

        # 预检 OpenCV 可用性，避免录屏结束后合成阶段才发现依赖缺失
        try:
            import cv2  # noqa: F401
        except ImportError:
            raise DevhelmError(
                "录屏依赖 opencv-python 未安装，请执行 pip install devhelmkit[cv]"
            )

        frames_dir = os.path.join(output_dir, "frames")
        os.makedirs(frames_dir, exist_ok=True)
        self._record_dir = frames_dir
        self._record_output_dir = output_dir
        self._record_frame_count = 0
        self._record_start_time = time.time()
        self._record_timestamps = []
        self._recording = True

        # 将当前缓存帧落盘作为首帧，避免静置画面时录屏 0 帧
        with self._frame_lock:
            current_frame = self._latest_frame
        if current_frame is not None:
            frame_path = os.path.join(self._record_dir, "frame_000000.jpg")
            try:
                with open(frame_path, 'wb') as f:
                    f.write(current_frame)
                self._record_timestamps.append(0.0)
                self._record_frame_count = 1
            except OSError as e:
                logger.warning("录屏首帧写入失败: %s", e)

        logger.debug("录屏开始 (dir=%s)", self._record_dir)

    def stop_recording(self, output_path: str) -> str:
        """停止录屏并将帧序列合成为视频文件。

        Args:
            output_path: 输出视频文件路径（.mp4 或 .avi）

        Returns:
            实际保存的视频文件路径

        Raises:
            DevhelmError: 未在录屏或无帧数据
        """
        if not self._recording:
            raise DevhelmError("未在录屏状态")

        self._recording = False
        self._record_end_time = time.time()
        frame_count = self._record_frame_count
        record_dir = self._record_dir
        timestamps = self._record_timestamps
        self._record_frame_count = 0
        self._record_dir = None
        self._record_output_dir = None
        self._record_timestamps = []

        if frame_count == 0:
            raise DevhelmError("录屏期间未捕获到任何帧")

        duration = self._record_end_time - self._record_start_time
        logger.debug("录屏结束: %d 帧, %.1fs, 合成中（含补帧）...",
                    frame_count, duration)

        total_frames = self._compose_video(
            record_dir, frame_count, timestamps,
            self._record_start_time, self._record_end_time,
            output_path
        )

        logger.debug("视频已保存: %s (原始 %d 帧, 补帧后 %d 帧)",
                    output_path, frame_count, total_frames)
        return output_path

    def _compose_video(self, record_dir: str, frame_count: int,
                       timestamps: list, start_time: float,
                       end_time: float, output_path: str) -> int:
        """用 OpenCV VideoWriter 将 JPEG 帧序列合成为视频，含自适应补帧。

        补帧策略：
        1. 从实际帧时间戳计算帧间隔中位数，推导自适应 fps
        2. 按该 fps 等间隔生成时间轴，每个时间点取最近的实际帧
        3. 静置无数据时重复上一帧，确保视频时长与实际一致

        Args:
            record_dir: 帧文件临时目录
            frame_count: 实际捕获的帧数
            timestamps: 每帧相对 start_time 的秒数列表
            start_time: 录屏开始时间戳
            end_time: 录屏结束时间戳
            output_path: 输出视频路径

        Returns:
            合成视频的总帧数（含补帧）
        """
        import cv2
        import numpy as np

        # 从第一帧获取尺寸
        first_frame_path = os.path.join(record_dir, "frame_000000.jpg")
        first = cv2.imread(first_frame_path)
        if first is None:
            raise DevhelmError("无法读取首帧: %s" % first_frame_path)
        h, w = first.shape[:2]

        total_duration = end_time - start_time
        if total_duration <= 0:
            total_duration = 0.1

        # 自适应 fps：从帧间隔中位数推导
        if frame_count >= 2:
            ts_array = np.array(timestamps)
            intervals = np.diff(ts_array)
            median_interval = float(np.median(intervals))
            # 帧间隔过大（静置）时用 MAX_FRAME_GAP 兜底，避免 fps 过低
            median_interval = min(median_interval, MAX_FRAME_GAP)
            adaptive_fps = 1.0 / median_interval if median_interval > 0 else 10.0
        else:
            adaptive_fps = 10.0
        adaptive_fps = max(MIN_RECORD_FPS, min(MAX_RECORD_FPS, adaptive_fps))
        frame_interval = 1.0 / adaptive_fps

        # 总帧数 = 时长 * 自适应 fps
        total_frames = max(1, int(round(total_duration * adaptive_fps)))

        logger.debug("自适应帧率: %.1f fps, 总帧数: %d (原始 %d, 补帧 %d)",
                    adaptive_fps, total_frames, frame_count,
                    total_frames - frame_count)

        fourcc = cv2.VideoWriter_fourcc(*'mp4v')
        writer = cv2.VideoWriter(output_path, fourcc, adaptive_fps, (w, h))
        if not writer.isOpened():
            raise DevhelmError("VideoWriter 打开失败: %s" % output_path)

        # 将时间戳转为 numpy 数组便于搜索
        if frame_count >= 2:
            ts_array = np.array(timestamps)
        else:
            ts_array = np.array([0.0])

        # 帧缓存：避免补帧时重复 imread 同一文件
        frame_cache: dict = {}

        try:
            for i in range(total_frames):
                # 当前帧对应的时间点（秒）
                target_t = i * frame_interval

                # 找到时间 <= target_t 的最后一帧（即当前应显示的帧）
                idx = int(np.searchsorted(ts_array, target_t, side='right') - 1)
                if idx < 0:
                    idx = 0
                if idx >= frame_count:
                    idx = frame_count - 1

                # 从缓存读取，避免重复磁盘 IO
                if idx not in frame_cache:
                    frame_path = os.path.join(record_dir, "frame_%06d.jpg" % idx)
                    frame_cache[idx] = cv2.imread(frame_path)
                frame = frame_cache[idx]
                if frame is not None:
                    writer.write(frame)
        finally:
            writer.release()

        return total_frames

    def stop(self) -> None:
        """停止推流并释放资源。"""
        # 如果正在录屏，先停止录屏（不合成视频）
        self._recording = False
        self._record_dir = None
        self._record_output_dir = None
        self._record_frame_count = 0
        self._record_timestamps = []

        self._streaming = False

        # 唤醒 wait_frame_bytes_seq 的等待者，避免推流停止后仍卡满 timeout
        with self._frame_cond:
            self._frame_cond.notify_all()

        # 先发送 stopCaptureScreen 停止推流
        try:
            self._send_captures_on_sock('stopCaptureScreen', {})
        except Exception as e:
            logger.debug("发送 stopCaptureScreen 异常（忽略）: %s", e)

        # 关闭 socket 解除 recv 阻塞，接收线程才能退出
        self._close_socket()

        # 等待接收线程退出（socket 已关，应立即返回）
        if self._thread is not None:
            self._thread.join(timeout=1.0)
            self._thread = None

        # 清理端口转发
        self._cleanup_fport()

        with self._frame_lock:
            self._latest_frame = None
        self._frame_event.clear()
        self._recv_buffer.clear()

        logger.debug("ScreenshotStream 已停止")

    # ============================================================
    # 内部实现
    # ============================================================

    def _setup_connection(self) -> None:
        """建立独立端口转发 + TCP 连接。

        并行优化：启动 uitest 守护进程（秒级，最重）与本地端口分配 + hdc fport
        （毫秒级）互不依赖，可并行执行，把 fport 开销藏进 daemon 启动等待窗口。
        socket.connect 需设备端 socket 已监听，故放在两者 join 之后。
        """
        agent = self._device._agent
        # 先探测协议版本：fport 目标名依赖 protocol_version，且需在并行前就绪，
        # 避免 daemon 线程与主线程竞争写 _abi/_protocol_version。
        if agent.protocol_version is None:
            agent.detect_device_info()

        # 后台线程：启动/复用 uitest 守护进程（最重的一步）
        daemon_error = []

        def _start_daemon():
            """在线程中启动守护进程，并把异常交回主线程统一处理。"""
            try:
                agent.ensure_daemon_running()
            except Exception as e:  # 捕获后在主线程重抛，保留原异常
                daemon_error.append(e)

        daemon_thread = threading.Thread(target=_start_daemon, daemon=True)
        daemon_thread.start()

        # 主线程并行：分配本地端口 + 建立 fport（不依赖 daemon 是否已监听）
        s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        s.bind(("127.0.0.1", 0))
        self._local_port = s.getsockname()[1]
        s.close()

        target = self._get_fport_target()
        subprocess.run(
            self._device._hdc_cmd("fport", "tcp:%d" % self._local_port, target),
            check=True
        )
        self._fport_established = True

        # 等 daemon 就绪；连接前必须确保设备端 socket 已监听
        daemon_thread.join()
        if daemon_error:
            raise daemon_error[0]

        # 建立独立 TCP 连接（仅接收 JPEG 帧流）
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.settimeout(5.0)
        sock.connect(("127.0.0.1", self._local_port))
        sock.settimeout(None)  # 后台线程阻塞读取
        self._sock = sock

    def _send_stop_then_start(self) -> None:
        """通过截图 socket 发送 stop -> start 命令。

        命令使用 UITest 协议帧格式发送到截图 socket，
        设备端会将 JPEG 帧推送到该 socket 上。
        不走 RPC 通道，避免数据混流。
        """
        # 先 stop 清理旧状态
        self._send_captures_on_sock('stopCaptureScreen', {})
        time.sleep(0.1)

        # 再 start 启动推流
        self._send_captures_on_sock('startCaptureScreen', {
            'options': {
                'displayId': 0,
                'scale': self._scale
            }
        })

    def _send_captures_on_sock(self, api: str, args: dict) -> None:
        """通过截图 socket 直接发送 Captures 命令（UITest 协议帧）。

        不读取响应——发送后设备端开始推送 JPEG 帧流，
        响应帧和 JPEG 数据混在同一 socket，由后台线程解析。
        """
        msg = json.dumps({
            'module': 'com.ohos.devicetest.hypiumApiHelper',
            'method': 'Captures',
            'params': {
                'api': api,
                'args': args
            },
            'request_id': datetime.now().strftime("%Y%m%d%H%M%S%f")
        }, ensure_ascii=False, separators=(',', ':'))

        frame = self._build_protocol_frame(msg)
        if self._sock is not None:
            self._sock.sendall(frame)

    @staticmethod
    def _build_protocol_frame(msg: str) -> bytes:
        """构造 UITest 协议帧: HEAD + sessionId(4) + length(4) + body + TAIL。"""
        body = msg.encode('utf-8')
        session_id = random.randint(0, 0xFFFFFFFF)
        return RPC_HEAD + struct.pack('>II', session_id, len(body)) + body + RPC_TAIL

    def _start_recv_thread(self) -> None:
        """启动后台接收线程。"""
        if _PERF_ENABLED:
            self._perf_frames = 0
            self._perf_bytes = 0
            self._perf_last_ts = None
            self._perf_gap_max = 0.0
            self._perf_period_start = 0.0
            self._perf_diagnostics.reset()
        self._streaming = True
        self._thread = threading.Thread(target=self._recv_loop, daemon=True)
        self._thread.start()

    def _recv_loop(self) -> None:
        """后台接收循环：从 socket 读取数据，解析 JPEG 帧，缓存最新帧。"""
        logger.debug("ScreenshotStream 接收线程启动")
        while self._streaming and self._sock is not None:
            try:
                recv_started = time.perf_counter() if _PERF_ENABLED else 0.0
                chunk = self._sock.recv(65536)
                recv_finished = time.perf_counter() if _PERF_ENABLED else 0.0
                if not chunk:
                    logger.warning("ScreenshotStream socket 对端关闭")
                    break
                self._recv_buffer.extend(chunk)
                if _PERF_ENABLED:
                    self._perf_diagnostics.record_recv(
                        (recv_finished - recv_started) * 1000.0,
                        len(chunk),
                        len(self._recv_buffer),
                        recv_finished,
                    )
                    parse_started = time.perf_counter()
                self._parse_frames()
                if _PERF_ENABLED:
                    parse_ms = (time.perf_counter() - parse_started) * 1000.0
                    self._perf_diagnostics.record_parse(
                        parse_ms, len(self._recv_buffer)
                    )
                    self._perf_diagnostics.maybe_log(len(self._recv_buffer))
            except OSError as e:
                if self._streaming:
                    logger.warning("ScreenshotStream 接收异常: %s", e)
                break

        if _PERF_ENABLED:
            self._perf_diagnostics.maybe_log(
                len(self._recv_buffer), force=True
            )
        with self._frame_cond:
            self._streaming = False
            self._frame_cond.notify_all()
        logger.debug("ScreenshotStream 接收线程退出")

    def _parse_frames(self) -> None:
        """从接收缓冲区中解析数据帧。

        设备端通过截图 socket 返回的数据有两种形态：
        1. UITest 协议帧（HEAD + sessionId + length + body + TAIL）
           - 命令响应：body 是 JSON（含 result/exception 字段），跳过
           - 图像数据：body 是 JPEG bytes，提取
        2. 裸 JPEG 流（FFD8...FFD9）
           - 部分设备直接推裸 JPEG，不带协议帧包装

        优先尝试协议帧解析，失败再尝试裸 JPEG 解析。
        """
        while True:
            if len(self._recv_buffer) == 0:
                return

            # 检查缓冲区是否以协议帧 HEAD 开头
            head_pos = self._recv_buffer.find(RPC_HEAD)
            soi_pos = self._recv_buffer.find(JPEG_SOI)

            # 如果 HEAD 在 JPEG SOI 之前（或没有 SOI），优先走协议帧解析
            if head_pos >= 0 and (soi_pos < 0 or head_pos <= soi_pos):
                consumed = self._try_parse_protocol_frame()
                if consumed > 0:
                    continue
                # 协议帧不完整，等待更多数据
                return

            # 否则尝试裸 JPEG
            consumed = self._try_parse_raw_jpeg()
            if consumed > 0:
                continue

            # 两种都解析不出完整帧，等待更多数据
            return

    def _try_parse_protocol_frame(self) -> int:
        """尝试解析 UITest 协议帧，返回消费的字节数。

        成功提取 JPEG body 时更新最新帧；JSON 响应直接跳过。
        无法解析（数据不完整或不是协议帧）返回 0。
        """
        head_len = len(RPC_HEAD)
        tail_len = len(RPC_TAIL)
        aux_len = head_len + 4 + 4 + tail_len  # HEAD + sessionId + length + TAIL

        # 查找 HEAD 在缓冲区中的位置
        head_pos = self._recv_buffer.find(RPC_HEAD)
        if head_pos < 0:
            return 0

        # 丢弃 HEAD 之前的垃圾数据
        if head_pos > 0:
            if _PERF_ENABLED:
                self._perf_diagnostics.record_discard(head_pos)
            del self._recv_buffer[:head_pos]

        # 检查是否有足够的数据读取 sessionId + length
        if len(self._recv_buffer) < head_len + 8:
            if _PERF_ENABLED:
                self._perf_diagnostics.protocol_waits += 1
            return 0

        # 读取 body 长度
        body_len = struct.unpack('>I', self._recv_buffer[head_len + 4:head_len + 8])[0]
        total_len = aux_len + body_len

        if body_len > MAX_PROTOCOL_BODY_SIZE:
            if _PERF_ENABLED:
                self._perf_diagnostics.invalid_lengths += 1
                self._perf_diagnostics.record_discard(head_len)
            del self._recv_buffer[:head_len]
            return head_len

        # 检查是否有完整帧
        if len(self._recv_buffer) < total_len:
            if _PERF_ENABLED:
                self._perf_diagnostics.protocol_waits += 1
            return 0

        # 提取 body
        body_start = head_len + 8
        body = bytes(self._recv_buffer[body_start:body_start + body_len])

        # 验证 TAIL
        tail_pos = body_start + body_len
        if self._recv_buffer[tail_pos:tail_pos + tail_len] != RPC_TAIL:
            if _PERF_ENABLED:
                self._perf_diagnostics.invalid_tails += 1
                self._perf_diagnostics.record_discard(head_len)
            del self._recv_buffer[:head_len]
            return head_len

        # 消费完整帧
        del self._recv_buffer[:total_len]
        if _PERF_ENABLED:
            self._perf_diagnostics.protocol_frames += 1

        # 判断 body 是 JPEG 还是 JSON 响应
        if len(body) >= 2 and body[0] == 0xFF and body[1] == 0xD8:
            if _PERF_ENABLED:
                self._perf_diagnostics.protocol_jpegs += 1
            self._on_jpeg_frame(body)
        elif _PERF_ENABLED:
            self._perf_diagnostics.protocol_other += 1

        return total_len

    def _try_parse_raw_jpeg(self) -> int:
        """尝试解析裸 JPEG 帧（不带协议帧包装），返回消费的字节数。

        JPEG 格式：SOI(FFD8) ... EOI(FFD9)
        无法解析（数据不完整或不是 JPEG）返回 0。
        """
        soi = self._recv_buffer.find(JPEG_SOI)
        if soi < 0:
            # 没有 JPEG 开头，也没有协议帧 HEAD，清空垃圾数据
            # 但保留最后几个字节防止跨 chunk 的标记被截断
            if len(self._recv_buffer) > 4:
                discarded = len(self._recv_buffer) - 4
                if _PERF_ENABLED:
                    self._perf_diagnostics.record_discard(discarded)
                del self._recv_buffer[:-4]
            if _PERF_ENABLED:
                self._perf_diagnostics.raw_waits += 1
            return 0

        eoi = self._recv_buffer.find(JPEG_EOI, soi + 2)
        if eoi < 0:
            # 超过最大帧大小仍未找到 EOI，丢弃 SOI 及之前数据防止缓冲区无限增长
            if len(self._recv_buffer) - soi > MAX_FRAME_SIZE:
                discarded = soi + 2
                if _PERF_ENABLED:
                    self._perf_diagnostics.raw_oversized += 1
                    self._perf_diagnostics.record_discard(discarded)
                del self._recv_buffer[:discarded]
                logger.warning("裸 JPEG 帧超过 %dMB 未闭合，丢弃残余数据", MAX_FRAME_SIZE // (1024 * 1024))
                return discarded
            # JPEG 不完整，丢弃 SOI 之前的数据，等待更多数据
            if soi > 0:
                if _PERF_ENABLED:
                    self._perf_diagnostics.record_discard(soi)
                del self._recv_buffer[:soi]
            if _PERF_ENABLED:
                self._perf_diagnostics.raw_waits += 1
            return 0

        # 提取完整 JPEG 帧
        frame_end = eoi + 2
        frame_data = bytes(self._recv_buffer[soi:frame_end])
        if _PERF_ENABLED:
            self._perf_diagnostics.raw_jpegs += 1
            self._perf_diagnostics.record_discard(soi)
        del self._recv_buffer[:frame_end]

        self._on_jpeg_frame(frame_data)
        return frame_end

    def _on_jpeg_frame(self, frame_data: bytes) -> None:
        """处理一个完整的 JPEG 帧：缓存 + 录屏落盘。"""

        with self._frame_cond:
            self._latest_frame = frame_data
            self._frame_seq += 1
            self._frame_cond.notify_all()
        self._frame_event.set()

        if _PERF_ENABLED:
            self._perf_on_frame(len(frame_data))

        if self._recording and self._record_dir is not None:
            frame_path = os.path.join(
                self._record_dir,
                "frame_%06d.jpg" % self._record_frame_count
            )
            try:
                with open(frame_path, 'wb') as f:
                    f.write(frame_data)
                self._record_timestamps.append(time.time() - self._record_start_time)
                self._record_frame_count += 1
            except OSError as e:
                logger.warning("录屏帧写入失败: %s", e)

    def _perf_on_frame(self, frame_bytes: int) -> None:
        """生产端帧率统计：周期性输出设备到帧的实际 fps 与帧间隔。

        每 ~2 秒聚合一次，定位投屏卡顿在采集侧（设备推帧慢）还是推流侧。
        """
        t = time.perf_counter()
        if self._perf_period_start == 0.0:
            self._perf_period_start = t
        if self._perf_last_ts is not None:
            gap = (t - self._perf_last_ts) * 1000.0
            if gap > self._perf_gap_max:
                self._perf_gap_max = gap
        self._perf_last_ts = t
        self._perf_frames += 1
        self._perf_bytes += frame_bytes

        elapsed = t - self._perf_period_start
        if elapsed >= 2.0 and self._perf_frames > 0:
            fps = self._perf_frames / elapsed
            avg_kb = (self._perf_bytes / self._perf_frames) / 1024.0
            logger.info(
                "[perf] capture: fps=%.1f frames=%d max_gap=%.1fms avg_size=%.1fKB",
                fps, self._perf_frames, self._perf_gap_max, avg_kb,
            )
            self._perf_frames = 0
            self._perf_bytes = 0
            self._perf_gap_max = 0.0
            self._perf_period_start = t

    def _close_socket(self) -> None:
        """关闭截图 socket。"""
        if self._sock is not None:
            try:
                self._sock.close()
            except Exception as e:
                logger.debug("关闭截图 socket 异常（忽略）: %s", e)
            self._sock = None

    def _cleanup_fport(self) -> None:
        """清理端口转发。"""
        if not self._fport_established or self._local_port is None:
            return

        target = self._get_fport_target()
        try:
            subprocess.run(
                self._device._hdc_cmd("fport", "rm",
                                      "tcp:%d" % self._local_port, target),
                check=False
            )
        except Exception as e:
            logger.debug("清理截图端口转发异常（忽略）: %s", e)

        self._fport_established = False
        self._local_port = None

    def _get_fport_target(self) -> str:
        """获取 fport 转发目标地址，与 RPC 通道使用相同设备端 socket。"""
        if self._device._agent.protocol_version and \
                self._device._agent.protocol_version >= 2:
            return "localabstract:%s" % UITEST_SOCKET_NAME
        return "tcp:%d" % RPC_PORT