# !/usr/bin/env python
# -*- coding: utf-8 -*-
"""PerfMonitor：通过 SP_daemon 采集应用性能数据。

采集命令：
hdc shell SP_daemon -N 99999 -PKG <pkg> -c -g -f -r -net
"""
from __future__ import annotations

import logging
import shlex
import subprocess
import threading
import time
from datetime import datetime
from typing import TYPE_CHECKING, List, Optional

from devhelmkit.exceptions import DevhelmError
from devhelmkit.harmony.perf.models import (
    CpuCoreSample,
    CpuSample,
    FpsSample,
    GpuSample,
    MemorySample,
    NetworkSample,
    PerfDataPoint,
)

if TYPE_CHECKING:
    from devhelmkit.harmony.device.hdc import HdcDevice

logger = logging.getLogger(__name__)

_MAX_BUFFER_LINES = 200
_STOP_CLEANUP_WAIT = 0.5


def _parse_number(value: Optional[str]) -> Optional[float]:
    """解析数值；空值或 NA 返回 None。"""
    if not value or value == "NA":
        return None
    try:
        return float(value)
    except ValueError:
        return None


def _parse_jitter(jitters: Optional[str], refresh_rate: float) -> Optional[int]:
    """解析 fpsJitters，统计卡顿次数。

    jitters 为纳秒帧间隔，以 ``;;`` 分隔；间隔超过目标帧时间 2 倍计为一次卡顿。
    """
    if not jitters or jitters == "NA":
        return None
    if refresh_rate <= 0:
        refresh_rate = 120.0
    threshold = (1e9 / refresh_rate) * 2
    values = []
    for part in jitters.split(";;"):
        try:
            values.append(float(part))
        except ValueError:
            continue
    if not values:
        return 0
    return sum(1 for v in values if v > threshold)


def _format_time_label(ts_ms: float) -> str:
    """将毫秒时间戳格式化为 HH:MM:SS.mmm。"""
    dt = datetime.fromtimestamp(ts_ms / 1000.0)
    return "%s.%03d" % (dt.strftime("%H:%M:%S"), int(ts_ms) % 1000)


def parse_raw_block(
    raw: dict,
    last_network: Optional[dict],
) -> tuple[PerfDataPoint, Optional[dict]]:
    """将 SP_daemon KV 块解析为 PerfDataPoint。

    Returns:
        (数据点, 更新后的网络累计值状态)
    """
    wall_ts = time.time() * 1000
    device_ts = _parse_number(raw.get("timestamp"))
    # 优先使用设备侧毫秒时间戳，避免本机墙钟截断到秒导致间隔错乱/重复
    sample_ts = device_ts if device_ts is not None else wall_ts
    time_label = _format_time_label(sample_ts)

    cores: List[CpuCoreSample] = []
    for i in range(16):
        usage_key = "cpu%dUsage" % i
        if usage_key not in raw:
            break
        cores.append(CpuCoreSample(
            index=i,
            usage=_parse_number(raw.get(usage_key)),
            frequency=_parse_number(raw.get("cpu%dFrequency" % i)),
        ))

    current_down = _parse_number(raw.get("networkDown")) or 0.0
    current_up = _parse_number(raw.get("networkUp")) or 0.0
    network_down: Optional[float] = None
    network_up: Optional[float] = None
    if last_network is not None:
        time_diff = (sample_ts - last_network["timestamp"]) / 1000.0
        if time_diff > 0:
            network_down = max(
                0.0, (current_down - last_network["down"]) / 1024.0 / time_diff)
            network_up = max(
                0.0, (current_up - last_network["up"]) / 1024.0 / time_diff)

    new_network = {
        "down": current_down,
        "up": current_up,
        "timestamp": sample_ts,
    }

    def _kb_to_mb(key: str) -> Optional[float]:
        kb = _parse_number(raw.get(key))
        return None if kb is None else kb / 1024.0

    refresh = _parse_number(raw.get("refreshrate"))
    point = PerfDataPoint(
        timestamp=sample_ts,
        time_label=time_label,
        fps=FpsSample(
            fps=_parse_number(raw.get("fps")),
            refresh_rate=refresh,
            jank_count=_parse_jitter(raw.get("fpsJitters"), refresh or 120.0),
        ),
        cpu=CpuSample(
            proc_usage=_parse_number(raw.get("ProcCpuUsage")),
            total_usage=_parse_number(raw.get("TotalcpuUsage")),
            cores=cores,
        ),
        gpu=GpuSample(load=_parse_number(raw.get("gpuLoad"))),
        memory=MemorySample(
            pss=_kb_to_mb("pss"),
            heap_size=_kb_to_mb("heapSize"),
            heap_alloc=_kb_to_mb("heapAlloc"),
            mem_available=_kb_to_mb("memAvailable"),
            mem_total=_kb_to_mb("memTotal"),
        ),
        network=NetworkSample(down=network_down, up=network_up),
    )
    return point, new_network


class PerfMonitor:
    """设备端应用性能监控（单路，同时仅一个包）。"""

    def __init__(self, device: "HdcDevice"):
        self._device = device
        self._process: Optional[subprocess.Popen] = None
        self._reader: Optional[threading.Thread] = None
        self._stderr_reader: Optional[threading.Thread] = None
        self._package_name: Optional[str] = None
        self._start_time: float = 0.0
        self._data_buffer: List[str] = []
        self._last_network: Optional[dict] = None
        self._points: List[PerfDataPoint] = []
        self._lock = threading.Lock()
        self._running = False
        # 首条采样常为暖机脏数据（Total CPU/核占用不准），丢弃但仍用于网络差分基准
        self._warmup_skipped = False

    @property
    def running(self) -> bool:
        return self._running

    @property
    def package_name(self) -> Optional[str]:
        return self._package_name

    @property
    def points(self) -> List[PerfDataPoint]:
        with self._lock:
            return list(self._points)

    def start(self, package_name: str) -> None:
        """启动性能监控。

        Args:
            package_name: 目标应用包名（用户手动传入）
        """
        package_name = (package_name or "").strip()
        if not package_name:
            raise DevhelmError("package_name 不能为空")

        if self._running:
            self.stop()

        logger.info("启动性能监控: package=%s", package_name)
        try:
            self._device.shell("SP_daemon stop", timeout=10)
        except Exception as e:
            logger.debug("预清理 SP_daemon stop 忽略: %s", e)
        time.sleep(_STOP_CLEANUP_WAIT)

        cmd = (
            "SP_daemon -N 99999 -PKG %s -c -g -f -r -net"
            % shlex.quote(package_name)
        )
        process = self._device.spawn_shell(cmd)

        with self._lock:
            self._process = process
            self._package_name = package_name
            self._start_time = time.time()
            self._data_buffer = []
            self._last_network = None
            self._points = []
            self._warmup_skipped = False
            self._running = True

        self._reader = threading.Thread(
            target=self._read_stdout,
            name="perf-monitor-reader",
            daemon=True,
        )
        self._stderr_reader = threading.Thread(
            target=self._drain_stderr,
            name="perf-monitor-stderr",
            daemon=True,
        )
        self._reader.start()
        self._stderr_reader.start()
        logger.info("性能监控已启动")

    def stop(self) -> List[PerfDataPoint]:
        """停止监控并返回已采集数据点。"""
        if not self._running and self._process is None:
            with self._lock:
                return list(self._points)

        logger.info("停止性能监控")
        process = self._process
        if process is not None and process.poll() is None:
            try:
                process.terminate()
            except OSError as e:
                logger.debug("terminate 监控进程失败: %s", e)
            try:
                process.wait(timeout=3)
            except subprocess.TimeoutExpired:
                try:
                    process.kill()
                except OSError:
                    pass

        try:
            self._device.shell("SP_daemon stop", timeout=10)
        except Exception as e:
            logger.warning("执行 SP_daemon stop 失败: %s", e)

        if self._reader is not None and self._reader.is_alive():
            self._reader.join(timeout=2.0)
        if self._stderr_reader is not None and self._stderr_reader.is_alive():
            self._stderr_reader.join(timeout=1.0)

        with self._lock:
            if self._data_buffer:
                self._process_block(list(self._data_buffer))
                self._data_buffer = []
            self._process = None
            self._reader = None
            self._stderr_reader = None
            self._running = False
            self._start_time = 0.0
            points = list(self._points)

        logger.info("性能监控已停止，共 %d 个采样点", len(points))
        return points

    def _drain_stderr(self) -> None:
        """排空 stderr，避免管道填满导致子进程阻塞。"""
        process = self._process
        if process is None or process.stderr is None:
            return
        try:
            for line in process.stderr:
                text = line.rstrip("\r\n")
                if text:
                    logger.debug("SP_daemon stderr: %s", text)
        except Exception as e:
            logger.debug("性能监控 stderr 读线程结束: %s", e)

    def _read_stdout(self) -> None:
        """后台线程：按行读取 SP_daemon stdout。"""
        process = self._process
        if process is None or process.stdout is None:
            return
        try:
            for line in process.stdout:
                line = line.rstrip("\r\n")
                if not line:
                    continue
                self._handle_line(line)
        except Exception as e:
            logger.warning("性能监控读线程异常: %s", e)
        finally:
            # 进程自然退出时收尾缓冲
            with self._lock:
                if self._data_buffer:
                    self._process_block(list(self._data_buffer))
                    self._data_buffer = []
                if self._process is process:
                    self._running = False

    def _handle_line(self, line: str) -> None:
        with self._lock:
            if line.startswith("order:0 "):
                if self._data_buffer:
                    self._process_block(list(self._data_buffer))
                    self._data_buffer = []
            self._data_buffer.append(line)
            if len(self._data_buffer) > _MAX_BUFFER_LINES:
                logger.warning("性能数据缓冲区溢出，强制处理")
                self._process_block(list(self._data_buffer))
                self._data_buffer = []

    def _process_block(self, lines: List[str]) -> None:
        """解析完整数据块并追加到 points（调用方需已持锁）。"""
        raw: dict = {}
        for line in lines:
            space_idx = line.find(" ")
            if space_idx < 0:
                continue
            kv = line[space_idx + 1:].strip()
            eq_idx = kv.find("=")
            if eq_idx < 0:
                continue
            key = kv[:eq_idx].strip()
            value = kv[eq_idx + 1:].strip()
            if key:
                raw[key] = value
        if not raw:
            return
        point, self._last_network = parse_raw_block(raw, self._last_network)
        if not self._warmup_skipped:
            self._warmup_skipped = True
            logger.debug(
                "丢弃首条暖机采样: FPS=%s TotalCPU=%s",
                point.fps.fps, point.cpu.total_usage,
            )
            return
        self._points.append(point)
        logger.debug(
            "性能采样: FPS=%s CPU=%s%% GPU=%s%%",
            point.fps.fps, point.cpu.proc_usage, point.gpu.load,
        )
