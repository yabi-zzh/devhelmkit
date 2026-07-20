# !/usr/bin/env python
# -*- coding: utf-8 -*-
"""UiViewerSession：单设备采集会话状态机。

管理 snapshot/live 模式切换、截图获取、控件树获取和触控操作。
不直接处理 HTTP 协议，只暴露数据入口。
"""
from __future__ import annotations

import io
import logging
import math
import random
import threading
import time
from collections import deque
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
from devhelmkit.uiviewer.recorder import (
    generate_action_code,
    generate_key_code,
    generate_selector,
)

logger = logging.getLogger(__name__)


def _encode_jpeg(img: 'Image.Image') -> Tuple[bytes, Tuple[int, int]]:
    """将 PIL Image 编码为 JPEG bytes，返回 (bytes, (w, h))。"""
    buf = io.BytesIO()
    img.save(buf, format="JPEG")
    return buf.getvalue(), img.size


def _normalize_recording_params(action: str, params: Dict[str, Any]) -> Dict[str, Any]:
    """校验并归一化录制事件，避免无效输入生成可执行脚本。"""
    normalized = dict(params)
    if action == "key":
        key = str(params.get("key", ""))
        if key not in {"back", "home", "recent"}:
            raise RuntimeError("不支持的录制按键: %s" % key)
        normalized["key"] = key
        return normalized

    required_coordinates = ["x", "y"]
    if action == "swipe":
        required_coordinates.extend(["ex", "ey"])
    for name in required_coordinates:
        if name not in params:
            raise RuntimeError("录制动作缺少坐标: %s" % name)
        try:
            value = int(params[name])
        except (TypeError, ValueError):
            raise RuntimeError("录制动作坐标必须是整数: %s" % name)
        if value < 0:
            raise RuntimeError("录制动作坐标不能为负数: %s" % name)
        normalized[name] = value

    snapshot_id = params.get("snapshot_id")
    if snapshot_id is not None:
        try:
            normalized["snapshot_id"] = int(snapshot_id)
        except (TypeError, ValueError):
            raise RuntimeError("snapshot_id 必须是整数")

    if action in {"long_click", "swipe"} and "duration" in params:
        try:
            duration = float(params["duration"])
        except (TypeError, ValueError):
            raise RuntimeError("录制动作 duration 必须是数字")
        if not math.isfinite(duration) or duration <= 0:
            raise RuntimeError("录制动作 duration 必须是有限正数")
        normalized["duration"] = duration

    if action == "input":
        if "text" not in params:
            raise RuntimeError("输入动作缺少 text")
        normalized["text"] = str(params["text"])

    return normalized


class UiViewerSession:
    """单设备会话。

    线程安全：多线程访问截图和触控时通过 _lock 保护状态切换。
    """

    def __init__(self, serial: str):
        """初始化会话状态；设备资源由 start() 延迟创建。"""
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
        self._hierarchy_history = deque(maxlen=8)
        self._recording = False
        self._recording_events: list = []
        self._recording_event_counter = 0
        self._recording_error: Optional[str] = None

    @property
    def serial(self) -> str:
        """返回会话绑定的设备序列号。"""
        return self._serial

    @property
    def mode(self) -> CaptureMode:
        """返回当前截图采集模式。"""
        return self._mode

    @property
    def cleanup_policy(self) -> CleanupPolicy:
        """返回会话关闭时的设备端清理策略。"""
        return self._cleanup_policy

    @property
    def active(self) -> bool:
        """返回会话是否已完成设备资源初始化。"""
        return self._active

    @property
    def display_size(self) -> Optional[Tuple[int, int]]:
        """返回设备显示尺寸；读取失败时为 None。"""
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
                screenshot_stream_scale=0.5,
                stop_daemon_on_close=False,
            )
            from devhelmkit.harmony.driver import HarmonyDriver
            self._driver = HarmonyDriver(self._serial, config=config)
            self._active = True
            try:
                self._driver.screen_on()
            except Exception as e:
                logger.warning("Session 启动时触发设备亮屏异常: %s", e)
            try:
                self._display_size = self._driver.get_display_size()
            except Exception as e:
                logger.warning("获取设备屏幕尺寸失败: %s", e)
                self._display_size = None

    def stop(self) -> None:
        """释放本会话资源。"""
        with self._lock:
            self._active = False
            self._stop_recording_locked()
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

    def start_recording(self) -> None:
        """开始收集 Viewer 自己发出的操作，不启动设备端录制通道。"""
        with self._lock:
            if self._driver is None:
                raise RuntimeError("会话未启动")
            if self._mode != CaptureMode.LIVE:
                raise RuntimeError("脚本录制需要先开启实时投屏")
            if self._recording:
                raise RuntimeError("脚本录制已在进行中")
            self._recording = True
            self._recording_events = []
            self._recording_event_counter = 0
            self._recording_error = None
            logger.info("Web 操作录制已启动: %s", self._serial)

    def stop_recording(self) -> Dict[str, Any]:
        """停止收集 Web 操作并返回已生成的脚本事件。"""
        with self._lock:
            self._recording = False
            events = list(self._recording_events)
            error = self._recording_error
            logger.info("Web 操作录制已停止: %s, events=%d", self._serial, len(events))
            return {"recording": False, "events": events, "error": error}

    def get_recording_state(self) -> Dict[str, Any]:
        """返回 Web 操作录制状态。"""
        with self._lock:
            return {
                "recording": self._recording,
                "events": list(self._recording_events),
                "error": self._recording_error,
            }

    def delete_recording_event(self, event_id: int) -> Dict[str, Any]:
        """按稳定事件 ID 删除录制脚本；不存在时拒绝静默错删。"""
        with self._lock:
            for index, event in enumerate(self._recording_events):
                if event.get("event_id") == event_id:
                    deleted = self._recording_events.pop(index)
                    return {
                        "deleted": True,
                        "event": deleted,
                        "events": list(self._recording_events),
                    }
            raise RuntimeError("录制事件不存在: %s" % event_id)

    def clear_recording_events(self) -> Dict[str, Any]:
        """清空当前会话的录制脚本，保留录制开关状态。"""
        with self._lock:
            deleted_count = len(self._recording_events)
            self._recording_events = []
            return {
                "cleared": True,
                "deleted_count": deleted_count,
                "events": [],
            }

    def record_web_action(self, action: str, params: Dict[str, Any]) -> Dict[str, Any]:
        """记录一条 Viewer 操作，并基于对应 hierarchy 生成脚本。"""
        with self._lock:
            if not self._recording:
                return {"recorded": False, "reason": "录制未启动"}
            try:
                if action not in {"click", "long_click", "double_click", "swipe", "input", "key"}:
                    raise RuntimeError("不支持的录制动作: %s" % action)
                normalized_params = _normalize_recording_params(action, params)
                event = self._build_recording_event_locked(action, normalized_params)
            except Exception as exc:
                # 状态接口保留最近一次生成错误，使异步前端轮询仍能展示失败原因。
                self._recording_error = str(exc)
                raise
            self._recording_events.append(event)
            self._recording_error = None
            return {"recorded": True, "event": event}

    def _build_recording_event_locked(self, action: str, params: Dict[str, Any]) -> Dict[str, Any]:
        """在持有会话锁时绑定事件 ID、快照和最终脚本。"""
        self._recording_event_counter += 1
        event: Dict[str, Any] = {
            "event_id": self._recording_event_counter,
            "action": action,
            "timestamp_ms": int(time.time() * 1000),
            "params": dict(params),
        }
        if action == "key":
            # 导航键本身具备稳定语义，不绑定页面快照或控件节点。
            key = str(params.get("key", ""))
            event["code"] = generate_key_code(key)
            return event
        x = int(params.get("x", 0))
        y = int(params.get("y", 0))
        snapshot_id = params.get("snapshot_id")
        snapshot = next((item for item in reversed(self._hierarchy_history)
                         if item.snapshot_id == snapshot_id), None)
        if snapshot is None:
            # 快照缺失时禁止使用后续页面反推控件，直接保留操作时坐标。
            event["code"] = generate_action_code(None, action, params, x, y)
            event["selector_confidence"] = "coordinate"
            return event
        event["snapshot_id"] = snapshot.snapshot_id
        if action == "swipe":
            event["node_id"] = None
            event["selector_confidence"] = "coordinate"
            event["code"] = generate_action_code(None, action, params, x, y)
            return event

        selector, target = generate_selector(snapshot.root, x, y, action=action)
        event["node_id"] = target.node_id if target else None
        event["selector_confidence"] = "selector" if selector else "coordinate"
        event["code"] = generate_action_code(selector, action, params, x, y)
        return event

    def _stop_recording_locked(self) -> None:
        """会话关闭时终止录制并释放仅属于该会话的脚本状态。"""
        self._recording = False
        self._recording_events = []
        self._recording_error = None

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
                    try:
                        self._driver.screen_on()
                    except Exception as e:
                        logger.warning("切换至实时模式触发设备亮屏异常: %s", e)
                    self._warmup_stream_locked()
                else:
                    self._stop_stream_locked()
            if self._mode == CaptureMode.LIVE:
                # 离开 LIVE：录制依赖实时模式（start_recording 强制校验），
                # 必须同步终止，否则 record_web_action 在 snapshot 下仍会
                # 追加事件；已生成事件保留，供前端通过录制状态接口回收
                if self._recording:
                    self._recording = False
                    logger.info("离开实时模式，Web 操作录制已自动停止: %s",
                                self._serial)
                # hierarchy 历史绑定实时页面，模式切换后即失效，清空防止
                # 后续录制按 snapshot_id 误绑到过期快照
                self._hierarchy_history.clear()
            self._mode = mode
            self._last_jpeg_bytes = None
            self._last_frame_meta = None
            self._last_hierarchy = None

    def set_cleanup_policy(self, policy: CleanupPolicy) -> None:
        """更新会话关闭时是否停止设备端实时能力的策略。"""
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

    def wait_stream_frame_seq(self, last_seq: int,
                              timeout: float) -> Tuple[int, Optional[bytes]]:
        """阻塞等待比 last_seq 更新的截图流帧，返回 (帧序号, 当前帧 bytes)。

        MJPEG 高频消费路径不持有会话锁，底层 ScreenshotStream 使用条件变量
        保护帧缓存；并发 stop() 或模式切换最多返回 (0, None)，属于可重试降级。
        """
        # 原子快照避免读取期间 stop() 将会话 driver 置空。
        driver = self._driver
        if driver is None or self._mode != CaptureMode.LIVE:
            return 0, None
        self._used_live_capability = True
        return driver.wait_screenshot_stream_frame_bytes_seq(last_seq, timeout)

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
            self._hierarchy_history.append(snapshot)
            return snapshot

    def get_cached_hierarchy(self) -> Optional[HierarchySnapshot]:
        """读取最近一次控件树快照，不触发设备重新 dump。"""
        with self._lock:
            return self._last_hierarchy

    # ============================================================
    # 触控
    # ============================================================

    def touch(self, events: list) -> None:
        """执行触控事件序列。

        仅 live 模式可用；snapshot 模式调用会抛异常。
        前端需按 down/move/up 顺序串行提交，本方法不做跨调用排序保证。
        """
        with self._lock:
            if self._driver is None:
                raise RuntimeError("会话未启动")
            if self._mode != CaptureMode.LIVE:
                raise RuntimeError("snapshot 模式不支持触控操作")
            self._used_live_capability = True

            # 第一阶段：整批校验与归一化。任一事件非法则整批拒绝，
            # 避免执行到一半才校验失败，在设备上残留 down 无 up 的悬挂触点
            normalized = []
            for event in events:
                try:
                    event_type = TouchEventType(event.get("type", ""))
                except ValueError:
                    raise RuntimeError("未知 touch 事件类型: %s" % event.get("type"))
                x, y = self._normalize_touch_point(event)
                event["x"], event["y"] = x, y
                normalized.append((event_type, x, y))

            # 第二阶段：顺序执行。设备调用中途异常时，若已发 down 且未发
            # 对应 up，在最后成功坐标补发 touch_up 兜底，恢复设备触点状态
            pending_down = False
            last_x, last_y = 0, 0
            try:
                for event_type, x, y in normalized:
                    if event_type == TouchEventType.DOWN:
                        self._driver.touch_down(x, y)
                        pending_down = True
                    elif event_type == TouchEventType.MOVE:
                        self._driver.touch_move(x, y)
                    elif event_type == TouchEventType.UP:
                        self._driver.touch_up(x, y)
                        pending_down = False
                    last_x, last_y = x, y
            except Exception:
                if pending_down:
                    try:
                        self._driver.touch_up(last_x, last_y)
                    except Exception as up_exc:
                        logger.warning("touch 兜底 touch_up 失败: %s", up_exc)
                raise

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
                "recording": self._recording,
                "display_size": list(self._display_size) if self._display_size else None,
            }
            if self._last_frame_meta is not None:
                state["last_frame"] = self._last_frame_meta.to_dict()
            if self._last_hierarchy is not None:
                state["last_hierarchy"] = self._last_hierarchy.to_dict()
            return state
