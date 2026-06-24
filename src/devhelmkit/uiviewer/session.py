# !/usr/bin/env python
# -*- coding: utf-8 -*-
"""UiViewerSession：单设备采集会话状态机。

管理 snapshot/live 模式切换、截图获取、控件树获取和触控操作。
不直接处理 HTTP 协议，只暴露数据入口。
"""
from __future__ import annotations

import io
import logging
import random
import threading
import time
from typing import Any, Dict, Optional, Tuple

from PIL import Image

from devhelmkit.uiviewer.protocol import (
    CaptureMode,
    CleanupPolicy,
    FrameMeta,
    HierarchySnapshot,
    TouchEventType,
    flatten_hierarchy,
)
from devhelmkit.uiviewer import perf

logger = logging.getLogger(__name__)


def _encode_jpeg(img: 'Image.Image') -> Tuple[bytes, Tuple[int, int]]:
    """将 PIL Image 编码为 JPEG bytes，返回 (bytes, (w, h))。"""
    buf = io.BytesIO()
    img.save(buf, format="JPEG")
    return buf.getvalue(), img.size


class UiViewerSession:
    """单设备会话。

    线程安全：多线程访问截图和触控时通过 _lock 保护状态切换。
    """

    def __init__(self, serial: str):
        self._serial = serial
        self._mode = CaptureMode.SNAPSHOT
        self._cleanup_policy = CleanupPolicy.KEEP
        self._driver = None
        self._lock = threading.Lock()
        self._frame_counter = 0
        self._hierarchy_counter = 0
        self._display_size: Optional[Tuple[int, int]] = None
        self._active = False
        self._used_live_capability = False
        self._last_jpeg_bytes: Optional[bytes] = None
        self._last_frame_meta: Optional[FrameMeta] = None
        self._last_hierarchy: Optional[HierarchySnapshot] = None

    @property
    def serial(self) -> str:
        return self._serial

    @property
    def mode(self) -> CaptureMode:
        return self._mode

    @property
    def cleanup_policy(self) -> CleanupPolicy:
        return self._cleanup_policy

    @property
    def active(self) -> bool:
        return self._active

    @property
    def display_size(self) -> Optional[Tuple[int, int]]:
        return self._display_size

    # ============================================================
    # 生命周期
    # ============================================================

    def start(self) -> None:
        """创建 HarmonyDriver 实例，不启动 uitest RPC。"""
        with self._lock:
            if self._driver is not None:
                return
            from devhelmkit.harmony.config import HarmonyDriverConfig, ScreenshotMode
            config = HarmonyDriverConfig(
                screenshot_mode=ScreenshotMode.HDC,
                stop_daemon_on_close=False,
            )
            from devhelmkit.harmony.driver import HarmonyDriver
            self._driver = HarmonyDriver(self._serial, config=config)
            self._active = True
            try:
                self._display_size = self._driver.get_display_size()
            except Exception as e:
                logger.warning("获取设备屏幕尺寸失败: %s", e)
                self._display_size = None

    def stop(self) -> None:
        """释放本会话资源。"""
        with self._lock:
            self._active = False
            if self._driver is None:
                return
            stop_daemon = (
                self._cleanup_policy == CleanupPolicy.STOP and
                self._used_live_capability
            )
            try:
                self._driver.close(stop_daemon=stop_daemon)
            except Exception as e:
                logger.warning("关闭 driver 异常: %s", e)
            self._driver = None
            self._used_live_capability = False

    # ============================================================
    # 模式切换
    # ============================================================

    def set_mode(self, mode: CaptureMode) -> None:
        """切换采集模式。

        snapshot -> live: 预热截图流，避免首次拉流黑屏
        live -> snapshot: 停止截图流，并清空遗留帧/控件树缓存
        """
        with self._lock:
            if self._mode == mode:
                return
            if self._driver is not None:
                if mode == CaptureMode.LIVE:
                    self._warmup_stream_locked()
                else:
                    self._stop_stream_locked()
            self._mode = mode
            self._last_jpeg_bytes = None
            self._last_frame_meta = None
            self._last_hierarchy = None

    def set_cleanup_policy(self, policy: CleanupPolicy) -> None:
        with self._lock:
            self._cleanup_policy = policy

    # ============================================================
    # 截图
    # ============================================================

    def capture_jpeg(self) -> Tuple[bytes, FrameMeta]:
        """获取一帧 JPEG 和元信息。

        snapshot 模式：HDC 单次截图
        live 模式：从 uitest 截图流获取最新帧
        """
        with self._lock:
            if self._driver is None:
                raise RuntimeError("会话未启动")

            if self._mode == CaptureMode.SNAPSHOT:
                jpeg_bytes, meta = self._capture_hdc_locked()
            else:
                jpeg_bytes, meta = self._capture_stream_locked()
            self._last_jpeg_bytes = jpeg_bytes
            self._last_frame_meta = meta
            return jpeg_bytes, meta

    def _capture_hdc_locked(self) -> Tuple[bytes, FrameMeta]:
        """HDC 单次截图。"""
        jpeg_bytes = self._driver.capture_hdc_jpeg_bytes()
        img = Image.open(io.BytesIO(jpeg_bytes))
        img.load()
        img_w, img_h = img.size
        self._frame_counter += 1
        meta = FrameMeta(
            frame_id=self._frame_counter,
            timestamp_ms=int(time.time() * 1000),
            display_size=self._display_size or (img_w, img_h),
            image_size=(img_w, img_h),
            mode=CaptureMode.SNAPSHOT,
        )
        return jpeg_bytes, meta

    def _capture_stream_locked(self) -> Tuple[bytes, FrameMeta]:
        """从 uitest 截图流获取最新帧。"""
        self._used_live_capability = True
        img = self._driver.get_screenshot_stream_frame()
        if img is None:
            raise RuntimeError("截图流未获取到帧")
        jpeg_bytes, (img_w, img_h) = _encode_jpeg(img)
        self._frame_counter += 1
        meta = FrameMeta(
            frame_id=self._frame_counter,
            timestamp_ms=int(time.time() * 1000),
            display_size=self._display_size or (img_w, img_h),
            image_size=(img_w, img_h),
            mode=CaptureMode.LIVE,
        )
        return jpeg_bytes, meta

    def get_stream_frame(self) -> Optional[bytes]:
        """获取截图流当前帧的原始 JPEG bytes，无帧时返回 None。

        仅供 MJPEG 服务轮询使用，走无锁快路径（见 get_stream_frame_seq 说明）。
        """
        driver = self._driver
        if driver is None or self._mode != CaptureMode.LIVE:
            return None
        self._used_live_capability = True
        return driver.get_screenshot_stream_frame_bytes()

    def get_stream_frame_seq(self) -> Tuple[int, Optional[bytes]]:
        """获取截图流 (帧序号, 当前帧 bytes)，非 live 或未启动返回 (0, None)。

        序号单调递增，供 MJPEG 服务按帧变化去重，避免重复推送同一帧。

        无锁快路径：MJPEG 循环每秒高频调用此方法，若持 self._lock 会与 touch
        争锁（实测 lock_wait 可达数十毫秒，导致拖动发涩）。本方法只做只读访问——
        依赖 GIL 保证 self._driver / self._mode 的原子读取，底层帧缓存由
        ScreenshotStream 自己的 _frame_lock 保护，故无需 session 级锁。
        并发 stop()/set_mode() 时最坏返回 (0, None)，对 MJPEG 是良性降级。
        """
        driver = self._driver  # 原子快照，避免与 stop() 置 None 竞争
        if driver is None or self._mode != CaptureMode.LIVE:
            return 0, None
        self._used_live_capability = True
        return driver.get_screenshot_stream_frame_bytes_seq()

    def refresh_live_frame(self) -> bool:
        """实时模式下触发一次画面刷新，让 MJPEG 立即更新一帧。

        uitest startCaptureScreen 为变化驱动：屏幕静止时设备端不产生新帧，
        导致初次进入实时模式或长时间静止时黑屏、卡首帧。此处以极小位移的鼠标移动
        触发画面变化，唤醒屏幕合成器输出一帧，uitest 随即推送该真实帧，画面来源
        仍为推流本身。起终点取 1~10 范围内的随机坐标（保证有位移且落在屏幕左上角
        极小区域，避免误触内容区）。仅实时模式且推流通道已启动时有效，返回是否触发成功。
        """
        with self._lock:
            if self._driver is None:
                raise RuntimeError("会话未启动")
            if self._mode != CaptureMode.LIVE:
                raise RuntimeError("仅实时模式支持刷新画面")
            if not self._driver.is_screenshot_stream_active():
                return False
            self._used_live_capability = True
            x1 = random.randint(1, 10)
            y1 = random.randint(1, 10)
            x2 = random.randint(1, 10)
            y2 = random.randint(1, 10)
            try:
                self._driver.uinput_mouse_move(x1, y1, x2, y2, duration_ms=300)
            except Exception as e:
                logger.warning("refresh_live_frame 触发失败: %s", e)
                return False
            return True

    def get_cached_jpeg(self, frame_id: Optional[int] = None) -> Optional[bytes]:
        """读取最近一次采集的 JPEG；frame_id 不匹配时返回 None。"""
        with self._lock:
            if self._last_jpeg_bytes is None or self._last_frame_meta is None:
                return None
            if frame_id is not None and self._last_frame_meta.frame_id != frame_id:
                return None
            return self._last_jpeg_bytes

    # ============================================================
    # 控件树
    # ============================================================

    def dump_hierarchy(self) -> HierarchySnapshot:
        """获取控件树快照。

        snapshot 模式：source="hdc"
        live 模式：source="rpc"
        """
        with self._lock:
            if self._driver is None:
                raise RuntimeError("会话未启动")
            source = "hdc" if self._mode == CaptureMode.SNAPSHOT else "rpc"
            data = self._driver.dump_hierarchy(source=source)
            if self._mode == CaptureMode.LIVE:
                self._used_live_capability = True
            if data is None:
                data = {}
            self._hierarchy_counter += 1
            nodes = flatten_hierarchy(data) if isinstance(data, dict) else {}
            snapshot = HierarchySnapshot(
                snapshot_id=self._hierarchy_counter,
                timestamp_ms=int(time.time() * 1000),
                source=source,
                root=data if isinstance(data, dict) else {},
                nodes=nodes,
            )
            self._last_hierarchy = snapshot
            return snapshot

    # ============================================================
    # 触控
    # ============================================================

    def touch(self, events: list) -> None:
        """执行触控事件序列。

        仅 live 模式可用；snapshot 模式调用会抛异常。
        前端需按 down/move/up 顺序串行提交，本方法不做跨调用排序保证。
        """
        t_enter = perf.now_ms() if perf.enabled() else 0.0
        with self._lock:
            if self._driver is None:
                raise RuntimeError("会话未启动")
            if self._mode != CaptureMode.LIVE:
                raise RuntimeError("snapshot 模式不支持触控操作")
            self._used_live_capability = True

            perf_on = perf.enabled()
            t_start = perf.now_ms() if perf_on else 0.0
            lock_wait = (t_start - t_enter) if perf_on else 0.0
            rpc_total = 0.0
            for ev in events:
                try:
                    event_type = TouchEventType(ev.get("type", ""))
                except ValueError:
                    raise RuntimeError("未知 touch 事件类型: %s" % ev.get("type"))
                x, y = self._normalize_touch_point(ev)
                t_rpc = perf.now_ms() if perf_on else 0.0
                if event_type == TouchEventType.DOWN:
                    self._driver.touch_down(x, y)
                elif event_type == TouchEventType.MOVE:
                    self._driver.touch_move(x, y)
                elif event_type == TouchEventType.UP:
                    self._driver.touch_up(x, y)
                if perf_on:
                    dt = perf.now_ms() - t_rpc
                    rpc_total += dt
                    perf.log("[perf] touch rpc %s (%d,%d) %.1fms",
                             event_type.value, x, y, dt)
            if perf_on:
                total = perf.now_ms() - t_start
                perf.log("[perf] touch batch: events=%d lock_wait=%.1fms "
                         "rpc_sum=%.1fms total=%.1fms",
                         len(events), lock_wait, rpc_total, total)

    # ============================================================
    # 设备按键
    # ============================================================

    def press_key(self, key: str) -> None:
        """执行设备导航按键：back / home / recent。

        仅 live 模式可用；snapshot 模式调用会抛异常。
        使用设备端专用 API（pressBack/pressHome/多任务组合键），比坐标手势更稳定。
        """
        with self._lock:
            if self._driver is None:
                raise RuntimeError("会话未启动")
            if self._mode != CaptureMode.LIVE:
                raise RuntimeError("snapshot 模式不支持按键操作")
            self._used_live_capability = True

            if key == "back":
                self._driver.go_back()
            elif key == "home":
                self._driver.go_home()
            elif key == "recent":
                self._driver.go_recent_task()
            else:
                raise RuntimeError("未知按键: %s" % key)

    # ============================================================
    # 内部
    # ============================================================

    def _normalize_touch_point(self, event: Dict[str, Any]) -> Tuple[int, int]:
        """将前端坐标裁剪到当前设备屏幕范围内。"""
        try:
            x = int(event.get("x", 0))
            y = int(event.get("y", 0))
        except (TypeError, ValueError):
            raise RuntimeError("touch 坐标必须是整数")

        display_size = self._display_size
        if display_size is None and self._driver is not None:
            try:
                display_size = self._driver.get_display_size()
                self._display_size = display_size
            except Exception as e:
                logger.debug("获取屏幕尺寸失败，跳过坐标归一化: %s", e)
                display_size = None
        if display_size is None:
            return x, y

        width, height = display_size
        return (
            max(0, min(x, max(width - 1, 0))),
            max(0, min(y, max(height - 1, 0))),
        )

    def _stop_stream_locked(self) -> None:
        """停止截图流（切回 snapshot 时调用）。"""
        try:
            self._driver.stop_screenshot_stream()
        except Exception as e:
            logger.warning("停止截图流异常: %s", e)

    def _warmup_stream_locked(self) -> None:
        """预热截图流，让 MJPEG 首帧立即可用。"""
        try:
            self._driver.get_screenshot_stream_frame()
            self._used_live_capability = True
        except Exception as e:
            logger.warning("预热截图流异常: %s", e)

    def get_state(self) -> Dict[str, Any]:
        """获取当前会话状态。"""
        with self._lock:
            state = {
                "serial": self._serial,
                "mode": self._mode.value,
                "cleanup_policy": self._cleanup_policy.value,
                "active": self._active,
                "display_size": list(self._display_size) if self._display_size else None,
            }
            if self._last_frame_meta is not None:
                state["last_frame"] = self._last_frame_meta.to_dict()
            if self._last_hierarchy is not None:
                state["last_hierarchy"] = self._last_hierarchy.to_dict()
            return state
