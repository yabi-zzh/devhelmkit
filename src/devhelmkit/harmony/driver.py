# !/usr/bin/env python
# -*- coding: utf-8 -*-
"""HarmonyDriver：鸿蒙平台驱动门面。

编排 HdcDevice（设备通道）、RpcClient（RPC 通信）、ComponentFinder
（控件查找）三层能力，对用户暴露 U2 风格 API。

仅支持 HarmonyOS 5.0.0+（API 12+），设备端 uitest 服务统一使用
api9+ 命名（Driver/Component/On）。
"""
from __future__ import annotations

import base64
import io
import json
import os
import re
import shlex
import tempfile
import time
import logging
from typing import Any, Dict, List, Optional, Tuple, Union, TYPE_CHECKING

from PIL import Image

from devhelmkit.core.base_driver import BaseDriver
from devhelmkit.core.selector_spec import SelectorSpec, build_selector
from devhelmkit.exceptions import DeviceConnectError, DevhelmError, DevhelmTimeoutError
from devhelmkit.harmony.config import HarmonyDriverConfig, ScreenshotMode
from devhelmkit.harmony.device.hdc import HdcDevice
from devhelmkit.harmony.finder.component_finder import ComponentFinder, DRIVER_REF
from devhelmkit.harmony.rpc.client import RpcClient
from devhelmkit.harmony.rpc.proxy_v2 import rpc_captures, rpc_gestures
from devhelmkit.harmony.screenshot_stream import ScreenshotStream
from devhelmkit.harmony.uiobject import UiObject, _to_rect
from devhelmkit.harmony.uiwindow import UiWindow
from devhelmkit.model.input import GestureAction, InputDevice
from devhelmkit.model.keys import KeyCode
from devhelmkit.model.rect import Rect

logger = logging.getLogger(__name__)

if TYPE_CHECKING:
    from devhelmkit.core.base_component import BaseComponent
    from devhelmkit.harmony.vision.vision_extension import VisionExtension

# 语义按键 → KeyCode 映射
_KEY_MAP = {
    'back': KeyCode.BACK,
    'home': KeyCode.HOME,
    'power': KeyCode.POWER,
    'volume_up': KeyCode.VOLUME_UP,
    'volume_down': KeyCode.VOLUME_DOWN,
    'recent': KeyCode.VIRTUAL_MULTITASK,
    'menu': KeyCode.MENU,
    'enter': KeyCode.ENTER,
    'escape': KeyCode.ESCAPE,
    'delete': KeyCode.DEL,
    'tab': KeyCode.TAB,
    'space': KeyCode.SPACE,
}

# 不支持的 uitest 版本
_UNSUPPORTED_UITEST_VERSIONS = {"4.1.3.2"}

# 控件属性名 → 设备端 RPC 方法名映射
_PROPERTY_METHOD_MAP = {
    "id": "getId",
    "text": "getText",
    "key": "getKey",
    "type": "getType",
    "enabled": "isEnabled",
    "focused": "isFocused",
    "clickable": "isClickable",
    "scrollable": "isScrollable",
    "checked": "isChecked",
    "checkable": "isCheckable",
    "description": "getDescription",
    "selected": "isSelected",
    "bounds": "getBounds",
}


class HarmonyDriver(BaseDriver):
    """鸿蒙平台驱动门面。"""

    def __init__(self, serial: str,
                 config: Optional[HarmonyDriverConfig] = None,
                 **config_kwargs):
        self._config = HarmonyDriverConfig.from_input(config, config_kwargs)
        # 应用 hdc 路径配置（全局生效，影响所有后续 HdcDevice 实例）
        if self._config.hdc_path and self._config.hdc_path != "hdc":
            HdcDevice.set_hdc_path(self._config.hdc_path)
        self._device = HdcDevice(serial)
        self._setup_device()
        self._rpc = RpcClient(self._device)
        self._finder = ComponentFinder(self._rpc, self._config)
        self._implicit_wait: float = 10.0
        self._closed = False
        self._toast_observer: Optional[str] = None
        self._toast_listening: bool = False
        self._ui_event_observer: Optional[str] = None
        self._ui_event_listening: bool = False
        self._vision: Optional['VisionExtension'] = None
        self._screenshot_stream: Optional['ScreenshotStream'] = None
        # 设备属性不随屏幕变化，长期缓存
        self._device_props: Optional[Dict[str, str]] = None
        # main ability 探测缓存（per-driver 实例，多设备隔离）
        self._main_ability_cache: Optional[Dict[str, str]] = None

    # ============================================================
    # 生命周期
    # ============================================================

    def close(self, stop_daemon: Optional[bool] = None) -> None:
        """关闭驱动，释放 RPC 对象、socket 与端口转发。

        Args:
            stop_daemon: 是否停止设备端 uitest 守护进程。
                None 时取 config.stop_daemon_on_close（默认 False）。
                True 强制停止；False 强制保留。
        """
        if self._closed:
            return
        self._closed = True
        try:
            self._stop_screenshot_stream()
        except Exception as e:
            logger.debug("关闭截图推流异常（忽略）: %s", e)
        try:
            self._rpc.remote_objects.release_all()
        except Exception as e:
            logger.debug("释放远程对象异常（忽略）: %s", e)
        if stop_daemon is None:
            stop_daemon = self._config.stop_daemon_on_close
        self._device.close(stop_daemon=stop_daemon)

    @property
    def device_sn(self) -> str:
        return self._device.serial

    @property
    def platform(self) -> str:
        return "harmony"

    # ============================================================
    # 设备信息
    # ============================================================

    @property
    def info(self) -> Dict[str, Any]:
        """设备基本信息（品牌、型号、系统版本等）。"""
        return {
            "serial": self.device_sn,
            "platform": self.platform,
            "device_type": self.get_device_type(),
            "device_model": self.get_device_model(),
            "brand": self.get_brand(),
            "abi": self.get_abi(),
            "os_type": self.get_os_type(),
            "os_version": self.get_system_version(),
            "api_level": self.get_api_level(),
            "display_size": self.get_display_size(),
            "display_rotation": self.get_display_rotation(),
        }

    def get_display_size(self) -> Tuple[int, int]:
        w, h, _ = self._query_display_info()
        return (w, h)

    def get_display_rotation(self) -> int:
        _, _, rot = self._query_display_info()
        return rot

    def _query_display_info(self) -> Tuple[int, int, int]:
        """实时获取屏幕尺寸与旋转角度，不缓存。"""
        output = self.shell('hidumper -s DisplayManagerService -a "-a"')
        return _parse_display_info(output)

    def set_display_rotation(self, rotation: int) -> None:
        self._rpc.call("Driver.setDisplayRotation", DRIVER_REF, [rotation])

    def set_display_rotation_enabled(self, enabled: bool) -> None:
        self._rpc.call(
            "Driver.setDisplayRotationEnabled", DRIVER_REF, [enabled]
        )

    def get_device_type(self) -> str:
        return self._get_device_prop('devtype')

    def get_device_model(self) -> str:
        return self._get_device_prop('model')

    def get_brand(self) -> str:
        return self._get_device_prop('brand')

    def get_abi(self) -> str:
        raw = self._get_device_prop('abi')
        return raw.split(",")[0].strip() if raw else ""

    def get_os_type(self) -> str:
        return "harmony"

    def get_system_version(self) -> str:
        return self._get_device_prop('swver')

    def get_api_level(self) -> str:
        return self._get_device_prop('apiver')

    # 设备属性 key → marker 映射
    _PARAM_KEYS = [
        ('const.product.devicetype', 'devtype'),
        ('const.product.model', 'model'),
        ('const.product.brand', 'brand'),
        ('const.product.cpu.abilist', 'abi'),
        ('const.product.software.version', 'swver'),
        ('const.ohos.apiversion', 'apiver'),
    ]

    def _get_device_prop(self, marker: str) -> str:
        """从缓存的设备属性中取值，首次访问时批量 shell 获取全部属性。"""
        if self._device_props is None:
            self._refresh_device_props()
        return (self._device_props or {}).get(marker, '').strip()

    def _refresh_device_props(self) -> None:
        """批量获取全部设备属性并缓存。"""
        parts = []
        for key, marker in self._PARAM_KEYS:
            parts.append('echo __%s__; param get %s' % (marker, key))
        cmd = '; '.join(parts)
        output = self.shell(cmd)
        props: Dict[str, str] = {}
        current_marker = None
        for line in output.splitlines():
            line = line.strip()
            if not line:
                continue
            if line.startswith('__') and line.endswith('__'):
                current_marker = line[2:-2]
                continue
            if current_marker and current_marker not in props:
                lower = line.lower()
                if 'not found' in lower or 'fail' in lower or 'error' in lower:
                    continue
                if lower.startswith('param get ') or lower.startswith('echo '):
                    continue
                props[current_marker] = line
        self._device_props = props

    def refresh_device_props(self) -> None:
        """手动刷新设备属性缓存。"""
        self._device_props = None
        self._refresh_device_props()

    # ============================================================
    # 屏幕操作
    # ============================================================

    def screen_on(self) -> None:
        logger.debug("亮屏 (serial=%s)", self.device_sn)
        self.shell("power-shell wakeup")

    def screen_off(self) -> None:
        logger.debug("熄屏 (serial=%s)", self.device_sn)
        self.shell("power-shell suspend")

    def is_screen_on(self) -> bool:
        output = self.shell("hidumper -s PowerManagerService -a '-a'")
        return "Current State: AWAKE" in output

    def is_screen_locked(self) -> bool:
        output = self.shell("hidumper -s ScreenlockService -a -all")
        for line in output.splitlines():
            if "screenLocked" in line:
                return "false" not in line
        return not self.is_screen_on()

    def unlock(self) -> None:
        logger.debug("解锁设备 (serial=%s)", self.device_sn)
        w, h = self.get_display_size()
        self.screen_on()
        self.wait(1)
        if not self.is_screen_locked():
            return
        if self.get_device_type() == "2in1":
            self.press("enter")
        else:
            self.swipe(
                int(0.5 * w), int(0.99 * h),
                int(0.5 * w), int(0.7 * h),
                duration=0.1,
            )

    def set_sleep_time(self, seconds: float) -> None:
        if not self.is_screen_on():
            self.screen_on()
        self.shell("power-shell timeout -o %d" % int(seconds * 1000))

    def restore_sleep_time(self) -> None:
        self.shell("power-shell timeout -r")

    def wake_up_display(self) -> None:
        """唤醒屏幕（语义化别名，等价于 screen_on）。"""
        self.screen_on()

    def close_display(self) -> None:
        """关闭屏幕（语义化别名，等价于 screen_off）。"""
        self.screen_off()

    # ============================================================
    # 选择器入口（U2 风格）
    # ============================================================

    def __call__(self, **kwargs) -> 'UiObject':
        selector = build_selector(**kwargs)
        return UiObject(self, selector)

    def xpath(self, xpath: str) -> 'UiObject':
        selector = build_selector(xpath=xpath)
        return UiObject(self, selector)

    # ============================================================
    # 应用管理
    # ============================================================

    def app_start(self, package: str, activity: Optional[str] = None,
                  params: str = "", wait_time: float = 1,
                  *, module: Optional[str] = None) -> None:
        """启动应用。

        activity 为 None 时从设备侧 bm dump 自动探测主 Ability。
        `aa start -a` 使用设备声明的 Ability 名；Stage 模型下常见为短名
        `EntryAbility`，不能强行拼成 `package.EntryAbility`。
        module 为可选入参；仅显式传入时拼接 `-m`。
        """
        if activity is None:
            ability = self._resolve_main_ability(package)
        else:
            ability = activity
        cmd = "aa start -a %s -b %s" % (ability, package)
        if module:
            cmd += " -m %s" % module
        if params:
            cmd += " " + params
        logger.debug("启动应用 %s/%s (serial=%s)", package, ability, self.device_sn)
        try:
            output = self.shell(cmd)
        except DeviceConnectError as e:
            raise DevhelmError("启动应用失败 [%s]: %s" % (cmd, e)) from e
        if "error:" in output.lower() or "failed to start ability" in output.lower():
            raise DevhelmError("启动应用失败 [%s]: %s" % (cmd, output.strip()))
        if wait_time:
            self.wait(wait_time)

    def force_start_app(self, package: str, activity: Optional[str] = None,
                        clear_data: bool = False,
                        wait_time: float = 1) -> None:
        """强制重启应用：回桌面 → 停止 → 可选清数据 → 启动。

        Args:
            package: 包名
            activity: Ability 名，None 时自动探测
            clear_data: 是否清除应用数据（含缓存）
            wait_time: 启动后等待时间
        """
        self.go_home()
        self.app_stop(package, wait_time=0.3)
        if clear_data:
            self.clear_app_data(package)
        self.app_start(package, activity=activity, wait_time=wait_time)

    def open_url(self, url: str, system_browser: Optional[bool] = None) -> None:
        """通过 schema / URI 打开页面（深链）。

        自动判断 URL scheme：
        - http/https：默认用系统浏览器打开
        - 其他 scheme（如 kwai://、settings://）：默认由系统选择处理方

        Args:
            url: 目标 URL，如 "https://www.example.com" 或 "kwai://myprofile"
            system_browser: 是否强制使用系统浏览器。
                None 表示按 scheme 自动判断；
                True 强制系统浏览器；
                False 由系统选择处理方（应用深链）。
        """
        if system_browser is None:
            system_browser = url.lower().startswith(("http://", "https://"))
        if system_browser:
            cmd = "aa start -A ohos.want.action.viewData -e entity.system.browsable -U %s" % shlex.quote(url)
        else:
            cmd = "aa start -U %s" % shlex.quote(url)
        logger.debug("打开 URL %s (serial=%s)", url, self.device_sn)
        self.shell(cmd)

    def app_stop(self, package: str, wait_time: float = 0.5) -> None:
        logger.debug("停止应用 %s (serial=%s)", package, self.device_sn)
        self.shell("aa force-stop %s" % package)
        if wait_time:
            self.wait(wait_time)

    def app_current(self) -> Tuple[Optional[str], Optional[str]]:
        """获取当前前台应用包名与 Ability 名。

        位于桌面或读取失败时返回 (None, None)。

        Returns:
            (package_name, ability_name)
        """
        cmd = "hidumper -s WindowManagerService -a '-a'; echo __SEP__; hidumper -s AbilityManagerService -a -l"
        output = self.shell(cmd)

        # 分割两段输出
        parts = output.split("__SEP__", 1)
        win_echo = parts[0] if len(parts) > 0 else ""
        mission_echo = parts[1] if len(parts) > 1 else ""

        focus_match = re.search(r"Focus window: (\d+)", win_echo)
        if not focus_match:
            return (None, None)
        focus_window = focus_match.group(1)

        # mission 列表
        missions = re.findall(
            r"Mission ID #(\d+)\s+mission name #\[(.*?)\]", mission_echo
        )
        for mission_id, mission_name in missions:
            if mission_id == focus_window:
                pkg = mission_name.split(":")[0].replace("#", "")
                ability = mission_name.split(":")[-1]
                return (pkg, ability)

        # 焦点窗口未命中 mission，回退在窗口回显中查找
        missions = re.findall(
            r"Mission ID #(\d+)\s+mission name #\[(.*?)\]", win_echo
        )
        for mission_id, mission_name in missions:
            if mission_id == focus_window:
                pkg = mission_name.split(":")[0].replace("#", "")
                ability = mission_name.split(":")[-1]
                return (pkg, ability)

        return (None, None)

    def app_list(self) -> List[str]:
        output = self.shell("bm dump -a")
        packages = []
        for line in output.splitlines():
            line = line.strip()
            if line and not line.startswith("ID") and "." in line:
                packages.append(line)
        return packages

    def has_app(self, package: str) -> bool:
        output = self.shell("bm dump -n %s" % shlex.quote(package))
        return package in output

    def clear_app_data(self, package: str) -> None:
        self.shell("bm clean -n %s -d" % shlex.quote(package))

    def app_install(self, path: str, options: str = "") -> None:
        """安装应用。

        Args:
            path: 安装包在设备端的路径（hap/hsp 包）
            options: bm install 额外参数（如 "-r" 覆盖安装）
        """
        cmd = "bm install -p %s" % shlex.quote(path)
        if options:
            cmd += " " + options
        logger.debug("安装应用 %s (serial=%s)", path, self.device_sn)
        self.shell(cmd)

    def app_uninstall(self, package: str) -> None:
        """卸载应用。"""
        logger.debug("卸载应用 %s (serial=%s)", package, self.device_sn)
        self.shell("bm uninstall -n %s" % shlex.quote(package))

    def get_app_info(self, package: str) -> dict:
        """获取应用详细信息（bm dump -n 解析结果）。"""
        output = self.shell("bm dump -n %s" % shlex.quote(package))
        try:
            json_start = output.find("{")
            json_end = output.rfind("}") + 1
            if json_start >= 0 and json_end > json_start:
                return json.loads(output[json_start:json_end])
        except (json.JSONDecodeError, ValueError) as e:
            logger.warning("应用信息解析失败: %s", e)
        return {}

    def _resolve_entry(self, package: str) -> Optional[str]:
        """探测 aa start 可用主 Ability 名。

        数据来源：bm dump -n {package} 中的 mainAbility。
        部分包会输出多个 mainAbility，其中多数为空；入口解析只取第一个非空值。
        """
        output = self.shell("bm dump -n %s" % shlex.quote(package))
        pattern = r'"mainAbility"\s*:\s*"([^"]*)"'
        for value in re.findall(pattern, output):
            ability = value.strip()
            if ability:
                return ability
        return None

    def get_app_main_ability(self, package: str) -> Optional[str]:
        """自动探测 aa start 可用主 Ability 名。"""
        return self._resolve_entry(package)

    def _resolve_main_ability(self, package: str) -> str:
        """解析主 Ability，带缓存。

        探测失败时不在框架层提前中断，回退到 HarmonyOS 默认入口，
        让设备侧 aa start 返回真实执行错误，便于定位实际失败原因。
        """
        if self._main_ability_cache is None:
            self._main_ability_cache = {}
        if package in self._main_ability_cache:
            return self._main_ability_cache[package]
        ability = self._resolve_entry(package) or "EntryAbility"
        self._main_ability_cache[package] = ability
        return ability

    # ============================================================
    # 坐标操作
    # ============================================================

    def click(self, x: int, y: int) -> None:
        self._rpc.call("Driver.click", DRIVER_REF, [x, y])

    def long_click(self, x: int, y: int, duration: float = 0.5) -> None:
        # 设备端 longClickAt 要求 duration >= 1500ms，低于阈值用 longClick（设备端固定时长）
        duration_ms = int(duration * 1000)
        if duration_ms >= 1500:
            self._rpc.call(
                "Driver.longClickAt", DRIVER_REF, [{"x": x, "y": y}, duration_ms]
            )
        else:
            self._rpc.call("Driver.longClick", DRIVER_REF, [x, y])

    def double_click(self, x: int, y: int) -> None:
        self._rpc.call("Driver.doubleClick", DRIVER_REF, [x, y])

    def swipe(self, x1: int, y1: int, x2: int, y2: int,
              duration: float = 0.5) -> None:
        distance = max(abs(x2 - x1), abs(y2 - y1), 1)
        speed = int(distance / duration) if duration > 0 else 600
        self._rpc.call(
            "Driver.swipe", DRIVER_REF, [x1, y1, x2, y2, speed]
        )

    def swipe_dir(self, direction: str, distance: int = 60,
                  area=None, speed=None) -> None:
        w, h = self.get_display_size()
        cx, cy = w // 2, h // 2
        direction = direction.upper()
        if direction == 'UP':
            x1, y1, x2, y2 = cx, cy + distance, cx, cy - distance
        elif direction == 'DOWN':
            x1, y1, x2, y2 = cx, cy - distance, cx, cy + distance
        elif direction == 'LEFT':
            x1, y1, x2, y2 = cx + distance, cy, cx - distance, cy
        elif direction == 'RIGHT':
            x1, y1, x2, y2 = cx - distance, cy, cx + distance, cy
        else:
            raise DevhelmError("未知滑动方向: %s" % direction)
        self.swipe(x1, y1, x2, y2)

    def drag(self, x1: int, y1: int, x2: int, y2: int,
             duration: float = 0.5) -> None:
        distance = max(abs(x2 - x1), abs(y2 - y1), 1)
        speed = int(distance / duration) if duration > 0 else 600
        self._rpc.call(
            "Driver.drag", DRIVER_REF, [x1, y1, x2, y2, speed]
        )

    def fling(self, direction: str, distance: int = 50,
              area=None, speed: str = "fast") -> None:
        speed_map = {"fast": 1000, "normal": 600, "slow": 300}
        swipe_speed = speed_map.get(speed, 600)
        w, h = self.get_display_size()
        cx, cy = w // 2, h // 2
        direction = direction.upper()
        if direction == 'UP':
            x1, y1, x2, y2 = cx, cy + distance, cx, cy - distance
        elif direction == 'DOWN':
            x1, y1, x2, y2 = cx, cy - distance, cx, cy + distance
        elif direction == 'LEFT':
            x1, y1, x2, y2 = cx + distance, cy, cx - distance, cy
        elif direction == 'RIGHT':
            x1, y1, x2, y2 = cx - distance, cy, cx + distance, cy
        else:
            raise DevhelmError("未知滑动方向: %s" % direction)
        self._rpc.call(
            "Driver.swipe", DRIVER_REF, [x1, y1, x2, y2, swipe_speed]
        )

    def uinput_mouse_move(self, x1: int, y1: int, x2: int, y2: int,
                          duration_ms: int = 300) -> None:
        """设备级 uinput 鼠标移动，命令 `uinput -M -m x1 y1 x2 y2 duration`。

        直接注入鼠标移动事件，不经过 uitest RPC，用于以极小位移触发画面变化。
        """
        self.shell("uinput -M -m %d %d %d %d %d" % (x1, y1, x2, y2, duration_ms))

    # ============================================================
    # 实时触控（Gestures 模块，支持 down/move/up 序列）
    # ============================================================

    def touch_down(self, x: int, y: int) -> None:
        """按下触控点。"""
        logger.trace("Gestures -> touchDown (%d, %d)", x, y)
        rpc_gestures(self._device, "touchDown", {"x": x, "y": y})

    def touch_move(self, x: int, y: int) -> None:
        """移动触控点（需先 touch_down）。"""
        logger.trace("Gestures -> touchMove (%d, %d)", x, y)
        rpc_gestures(self._device, "touchMove", {"x": x, "y": y})

    def touch_up(self, x: int, y: int) -> None:
        """抬起触控点（结束触控序列）。"""
        logger.trace("Gestures -> touchUp (%d, %d)", x, y)
        rpc_gestures(self._device, "touchUp", {"x": x, "y": y})

    # ============================================================
    # 按键
    # ============================================================

    def press(self, key: str) -> None:
        keycode = _KEY_MAP.get(key.lower())
        if keycode is None:
            raise DevhelmError("未知按键: %s" % key)
        self.press_keycode(int(keycode))

    def press_keycode(self, keycode: int) -> None:
        if isinstance(keycode, KeyCode):
            keycode = int(keycode)
        # Driver.pressKey 设备端不存在，改用 Driver.triggerKey
        self._rpc.call("Driver.triggerKey", DRIVER_REF, [keycode])

    def go_home(self) -> None:
        # 专用 API，比 pressKey 更稳定
        self._rpc.call("Driver.pressHome", DRIVER_REF, [])

    def go_back(self) -> None:
        # 专用 API，比 pressKey 更稳定
        self._rpc.call("Driver.pressBack", DRIVER_REF, [])

    def go_recent_task(self) -> None:
        """进入多任务界面（META_LEFT + TAB 组合键，比手势滑动更稳定）。"""
        self.press_combination_key(int(KeyCode.META_LEFT), int(KeyCode.TAB))

    def press_power(self) -> None:
        self.press_keycode(int(KeyCode.POWER))

    def press_combination_key(self, key1: int, key2: int,
                              key3: Optional[int] = None) -> None:
        keys = []
        for item in (key1, key2, key3):
            if item is None:
                continue
            if isinstance(item, KeyCode):
                item = int(item)
            keys.append(item)
        self._rpc.call("Driver.triggerCombineKeys", DRIVER_REF, keys)

    # ============================================================
    # Shell
    # ============================================================

    def shell(self, cmd: str, timeout: float = 60) -> str:
        return self._device.shell(cmd, timeout=timeout)

    # ============================================================
    # 截图
    # ============================================================

    def screenshot(self, filename: Optional[str] = None,
                   area=None) -> Union['Image', str, None]:
        """截图。

        - area=None：全屏截图
        - area 指定：全屏截图后用 PIL 裁剪
            - SelectorSpec / UiObject / dict / str：先解析控件 getBounds 拿 Rect
            - Rect / (left,top,right,bottom)：直接作为区域
        - filename 为 None：返回 PIL.Image.Image
        - filename 指定：保存到文件，返回文件路径 str

        截图模式由 config.screenshot_mode 决定：
        - HDC（默认）：走 hdc shell snapshot_display + base64 读取
        - STREAM：走 startCaptureScreen 推流，从独立端口获取最新 JPEG 帧
        """
        img_data = self._capture_full_bytes()
        img = Image.open(io.BytesIO(img_data))
        img.load()

        if area is not None:
            rect = self._resolve_area_rect(area)
            if rect is not None:
                img = img.crop((rect.left, rect.top, rect.right, rect.bottom))

        if filename:
            img.save(filename)
            return filename
        return img

    def capture_hdc_jpeg_bytes(self) -> bytes:
        """通过 HDC 获取单帧 JPEG bytes，不复用或启动截图推流。"""
        return self._capture_hdc_bytes()

    def get_screenshot_stream_frame(self) -> Optional['Image']:
        """获取截图推流当前帧；未启动时自动启动，暂无线帧返回 None。"""
        stream = self._get_or_start_screenshot_stream()
        return stream.get_frame()

    def get_screenshot_stream_frame_bytes(self) -> Optional[bytes]:
        """获取截图推流当前帧的原始 JPEG bytes，未启动或暂无帧返回 None。

        不自动启动推流：仅在通道已活跃时返回缓存帧，跳过 PIL 解码+重编码，
        供 MJPEG 直推等低延迟轮询使用。无锁调用：先原子快照 stream 引用，
        避免检查后被 _stop_screenshot_stream 置 None 引发空引用。
        """
        stream = self._screenshot_stream
        if stream is None:
            return None
        return stream.get_frame_bytes()

    def get_screenshot_stream_frame_bytes_seq(self) -> Tuple[int, Optional[bytes]]:
        """获取截图推流 (帧序号, 当前帧 bytes)，未启动返回 (0, None)。

        序号单调递增，供 MJPEG 直推按帧变化去重，避免重复推送同一帧。
        无锁调用：先原子快照 stream 引用，避免检查后被置 None 的竞态。
        """
        stream = self._screenshot_stream
        if stream is None:
            return 0, None
        return stream.get_frame_bytes_seq()

    def stop_screenshot_stream(self) -> None:
        """停止截图推流通道。"""
        self._stop_screenshot_stream()

    def is_screenshot_stream_active(self) -> bool:
        """推流通道是否已启动且正在推流。"""
        stream = self._screenshot_stream
        return stream is not None and stream._streaming

    def _capture_full_bytes(self) -> bytes:
        """全屏截图，返回 JPEG bytes。

        通道选择优先级：
        1. 推流通道已启动（录屏中或已开启 stream）：直接复用最新帧，零延迟
        2. screenshot_mode=STREAM：自动启动推流通道
        3. screenshot_mode=HDC（默认）：走 hdc shell snapshot_display
        """
        # 推流通道已存在且活跃时，直接复用最新帧
        if self._screenshot_stream is not None and \
                self._screenshot_stream._streaming:
            return self._capture_stream_bytes()
        if self._config.screenshot_mode == ScreenshotMode.STREAM:
            return self._capture_stream_bytes()
        return self._capture_hdc_bytes()

    def _capture_stream_bytes(self) -> bytes:
        """从推流通道获取最新帧 bytes。

        首次调用时自动启动推流，后续复用已建立的通道。
        """
        stream = self._get_or_start_screenshot_stream()
        img = stream.get_frame()
        if img is None:
            raise DevhelmError("推流截图未获取到帧数据")
        buf = io.BytesIO()
        img.save(buf, format='JPEG')
        return buf.getvalue()

    def _capture_hdc_bytes(self) -> bytes:
        """全屏截图，走 hdc shell snapshot_display + base64 读取。"""
        remote_path = "/data/local/tmp/devhelm_screenshot.jpeg"
        cmd = "rm -f %s && snapshot_display -f %s > /dev/null 2>&1 && base64 %s" % (
            remote_path, remote_path, remote_path
        )
        b64_text = self.shell(cmd)
        return base64.b64decode(b64_text.replace("\n", "").replace("\r", ""))

    def _get_or_start_screenshot_stream(self) -> 'ScreenshotStream':
        """获取或启动截图推流通道。"""
        if self._screenshot_stream is not None and \
                self._screenshot_stream._streaming:
            return self._screenshot_stream

        self._screenshot_stream = ScreenshotStream(
            self._device,
            scale=self._config.screenshot_stream_scale
        )
        if not self._screenshot_stream.start():
            raise DevhelmError("截图推流通道启动失败")
        return self._screenshot_stream

    def _stop_screenshot_stream(self) -> None:
        """停止截图推流通道。"""
        if self._screenshot_stream is not None:
            self._screenshot_stream.stop()
            self._screenshot_stream = None

    # ============================================================
    # 录屏
    # ============================================================

    def start_recording(self, output_dir: str) -> None:
        """开始录屏，捕获设备屏幕帧序列。

        自动启动推流通道（如未已启动），然后开始录制。
        JPEG 帧存放在 output_dir/frames/，mp4 存放在 output_dir/。
        录屏期间不影响 screenshot() 正常获取最新帧。

        Args:
            output_dir: 录屏输出目录
        """
        stream = self._get_or_start_screenshot_stream()
        stream.start_recording(output_dir)

    def stop_recording(self, output_path: str) -> str:
        """停止录屏并合成为视频文件。

        Args:
            output_path: 输出视频路径（.mp4 推荐）

        Returns:
            实际保存的视频文件路径
        """
        if self._screenshot_stream is None:
            raise DevhelmError("未在录屏状态")
        return self._screenshot_stream.stop_recording(output_path)

    def record(self, output_path: str) -> 'RecordingContext':
        """创建录屏上下文管理器，保证异常路径下自动停止录屏。

        使用方式::

            with d.record("/tmp/output.mp4"):
                d(text="登录").click()
            # 退出 with 块时自动合成视频，即使中间抛异常

        Args:
            output_path: 输出视频路径（.mp4 推荐）

        Returns:
            RecordingContext 上下文管理器
        """
        return RecordingContext(self, output_path)

    def _resolve_area_rect(self, area) -> Optional['Rect']:
        """将 area 参数解析为 Rect。

        支持：
        - Rect：原样返回
        - dict：构造 Rect
        - (left, top, right, bottom)：构造 Rect
        - SelectorSpec / UiObject / str：走控件查找 getBounds
        查找失败返回 None。
        """
        if isinstance(area, Rect):
            return area
        if isinstance(area, dict):
            return Rect(
                left=int(area.get('left', 0)),
                top=int(area.get('top', 0)),
                right=int(area.get('right', 0)),
                bottom=int(area.get('bottom', 0)),
            )
        if isinstance(area, (list, tuple)) and len(area) >= 4:
            return Rect(
                left=int(area[0]), top=int(area[1]),
                right=int(area[2]), bottom=int(area[3]),
            )
        # 控件选择器：走查找拿 bounds
        # UiObject 透传其内部 SelectorSpec
        if hasattr(area, '_selector'):
            selector = area._selector
        else:
            selector = _to_selector(area)
        if selector is None:
            return None
        try:
            bounds_data = self.call_component(selector, "getBounds")
            return _to_rect(bounds_data)
        except Exception as e:
            logger.debug("获取控件边界失败，返回 None: %s", e)
            return None

    def dump_hierarchy(self, source: str = "rpc",
                       filename: Optional[str] = None) -> Union[dict, str, None]:
        """导出控件树。

        - source="rpc": 走 uitest RPC（Captures.captureLayout），直接返回控件树 JSON，无需文件中转
        - source="hdc": 走 hdc shell（uitest dumpLayout -p），独立于 RPC 守护进程状态
        - filename 为 None：返回解析后的 dict
        - filename 指定：保存 JSON 到文件，返回文件路径 str
        """
        if source not in ("rpc", "hdc"):
            raise ValueError("source 仅支持 'rpc' 或 'hdc'，当前: %s" % source)

        if source == "rpc":
            # 走 RPC 通道：Captures.captureLayout 直接返回控件树 JSON
            logger.trace("RPC(Captures) -> captureLayout")
            reply = rpc_captures(self._device, "captureLayout", {})
            try:
                data = json.loads(reply)
            except json.JSONDecodeError as e:
                logger.error("控件树响应解析失败: %s", e)
                return None
            # 检测错误
            if isinstance(data, dict):
                if data.get('error'):
                    logger.warning("captureLayout 调用失败: %s", data['error'])
                    return None
                if data.get('exception'):
                    msg = data['exception'].get('message', str(data['exception']))
                    logger.warning("captureLayout 调用异常: %s", msg)
                    return None
                # 响应可能是 {"result": {...}} 或直接是控件树
                if 'result' in data:
                    data = data['result']
            logger.trace("RPC(Captures) <- captureLayout ok")
        else:
            # 走 hdc shell：uitest dumpLayout -p 命令独立于 RPC 守护进程
            remote_path = "/data/local/tmp/devhelm_layout.json"
            self.shell("uitest dumpLayout -p %s" % remote_path)
            tmp = tempfile.NamedTemporaryFile(suffix=".json", delete=False)
            tmp_path = tmp.name
            tmp.close()
            try:
                self._device.pull(remote_path, tmp_path)
                with open(tmp_path, "r", encoding="utf-8") as f:
                    data = json.load(f)
            except Exception as e:
                logger.error("控件树解析失败 (source=hdc): %s", e)
                return None
            finally:
                if os.path.exists(tmp_path):
                    os.remove(tmp_path)

        if not isinstance(data, dict):
            logger.error("控件树数据格式异常: %s", type(data))
            return None

        if filename:
            with open(filename, "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
            return filename
        return data

    # ============================================================
    # 等待
    # ============================================================

    def wait(self, seconds: float) -> None:
        time.sleep(seconds)

    def wait_for_idle(self, idle_time: float = 0.7,
                      timeout: float = 10) -> None:
        """等待 UI 稳定。

        当前设备端未提供空闲状态轮询接口，采用固定延时近似：静默等待
        idle_time 秒，并以 timeout 作为上限封顶（取两者较小值）。
        """
        self.wait(min(idle_time, timeout))

    def implicitly_wait(self, seconds: float) -> None:
        self._implicit_wait = seconds

    # ============================================================
    # 窗口
    # ============================================================

    @property
    def window(self) -> 'UiWindow':
        return UiWindow(self, self._rpc)

    def get_windows(self) -> List['UiWindow']:
        """获取所有窗口（当前不支持，返回空列表）。"""
        return []

    # ============================================================
    # webview 自动化
    # ============================================================

    def webview(self, bundle_name: str,
                chromedriver_search_path: str = "",
                chromedriver_exe_path: str = "",
                remote_devtools_port: Optional[int] = None,
                connection_timeout: int = 60,
                options=None) -> "WebViewDriver":
        """连接指定应用的 webview，返回 selenium webdriver 封装。

        Args:
            bundle_name: 目标应用包名
            chromedriver_search_path: chromedriver 存放目录（多版本结构）
            chromedriver_exe_path: 直接指定 chromedriver 路径（优先）
            remote_devtools_port: 自定义 webview 内核的 devtools 端口；
                                  系统 web 内核无需指定
            connection_timeout: 连接超时（秒）
            options: 传递给 selenium webdriver 的 options

        Returns:
            WebViewDriver 实例，可通过 .driver 访问 selenium webdriver

        Example:
            wv = d.webview("com.huawei.hmos.browser")
            wv.driver.get("https://www.baidu.com")
            wv.close()
        """
        from devhelmkit.harmony.webview import WebViewDriver
        wv = WebViewDriver(
            self._device,
            chromedriver_search_path=chromedriver_search_path,
            chromedriver_exe_path=chromedriver_exe_path,
        )
        wv.connect(
            bundle_name,
            remote_devtools_port=remote_devtools_port,
            connection_timeout=connection_timeout,
            options=options,
        )
        return wv

    # ============================================================
    # 文件操作
    # ============================================================

    def push_file(self, local_path: str, remote_path: str,
                  timeout: int = 60) -> None:
        self._device.push(local_path, remote_path, timeout=timeout)

    def pull_file(self, remote_path: str,
                  local_path: Optional[str] = None,
                  timeout: int = 60) -> None:
        if local_path is None:
            tmp = tempfile.NamedTemporaryFile(delete=False)
            local_path = tmp.name
            tmp.close()
        self._device.pull(remote_path, local_path, timeout=timeout)

    def has_file(self, path: str) -> bool:
        output = self.shell("test -f %s && echo yes || echo no" % shlex.quote(path))
        return "yes" in output

    # ============================================================
    # 控件查找（UiObject 门面方法）
    # ============================================================

    def call_component(self, selector: SelectorSpec, method: str,
                       args: Optional[list] = None,
                       timeout: Optional[float] = None) -> Any:
        return self._finder.call_component(
            selector, method, args or [],
            timeout if timeout is not None else self._implicit_wait
        )

    def get_properties_from_tree(self, selector: SelectorSpec,
                                 timeout: Optional[float] = None) -> Optional[Dict[str, Any]]:
        """通过控件树一次性获取目标控件的全部属性。"""
        return self._finder.get_properties_from_tree(
            selector, timeout if timeout is not None else self._implicit_wait
        )

    def component_exists(self, selector: SelectorSpec) -> bool:
        selector = _to_selector(selector)
        if selector is None:
            return False
        return self._finder.component_exists(selector)

    def wait_component(self, selector: SelectorSpec,
                       timeout: float) -> bool:
        selector = _to_selector(selector)
        if selector is None:
            return False
        return self._finder.wait_component(selector, timeout)

    def wait_component_gone(self, selector: SelectorSpec,
                            timeout: float) -> bool:
        selector = _to_selector(selector)
        if selector is None:
            return True
        return self._finder.wait_component_gone(selector, timeout)

    def scroll_search(self, selector: SelectorSpec, target,
                      vertical: bool = True,
                      offset: Optional[int] = None) -> Optional['UiObject']:
        """在可滚动容器内滚动查找目标控件。

        当前 HarmonyOS 实现未接入设备端滚动查找能力，调用即抛
        NotImplementedError。需要滚动定位时，可用 scroll_to_top /
        scroll_to_bottom 配合 find_component 手动实现。
        """
        raise NotImplementedError(
            "scroll_search 在 HarmonyOS 平台暂未实现，"
            "请用 scroll_to_top/scroll_to_bottom 配合 find_component 替代"
        )

    # ============================================================
    # 控件查找（BaseDriver 契约）
    # ============================================================

    def find_component(self, target,
                       scroll_target=None) -> Optional['BaseComponent']:
        selector = _to_selector(target)
        if selector is None:
            return None
        return UiObject(self, selector)

    def find_all_components(self, target) -> List['BaseComponent']:
        selector = _to_selector(target)
        if selector is None:
            return []
        refs = self._finder.find_components(selector)
        # 为每个匹配 ref 各建一个 UiObject 并预绑定其 Component 引用，
        # 使后续操作命中对应控件，而非都落到首个匹配。
        result: List['BaseComponent'] = []
        for ref in refs:
            obj = UiObject(self, selector)
            obj._component_ref = ref
            result.append(obj)
        return result

    def get_component_bound(self, target) -> Optional[Any]:
        selector = _to_selector(target)
        if selector is None:
            return None
        try:
            return UiObject(self, selector).bounds
        except DevhelmError:
            return None

    def get_component_property(self, target, name: str) -> Any:
        selector = _to_selector(target)
        if selector is None:
            raise DevhelmError("无效的控件目标: %r" % (target,))
        method = _PROPERTY_METHOD_MAP.get(name)
        if method is None:
            raise DevhelmError(
                "不支持的属性: %s，支持: %s" % (name, list(_PROPERTY_METHOD_MAP.keys()))
            )
        return self.call_component(selector, method)

    def switch_component_status(self, target, checked: bool) -> None:
        """切换控件状态（如 Checkbox/RadioButton）。

        读取控件当前 isChecked，仅当与目标状态不一致时点击切换，
        避免重复点击导致状态回退。

        Args:
            target: 控件目标（SelectorSpec / UiObject / 选择器 kwargs）
            checked: 目标状态 True=选中 / False=取消选中
        """
        selector = _to_selector(target)
        if selector is None:
            raise DevhelmError("无效的控件目标: %r" % (target,))
        current = self.call_component(selector, "isChecked")
        if bool(current) != bool(checked):
            self.call_component(selector, "click")

    # ============================================================
    # 文本输入辅助
    # ============================================================

    def hide_keyboard(self) -> None:
        self.press("back")

    def input_text_on_cursor(self, text: str) -> None:
        self.shell("uitest uiInput text %s" % shlex.quote(text))

    def clear_text_on_cursor(self) -> None:
        """清空当前获焦输入框文本。

        通过 uitest uiInput clear 命令清空当前光标所在输入框，
        不依赖控件定位。
        """
        self.shell("uitest uiInput clear")

    def move_cursor(self, direction: str, times: int = 1) -> None:
        key_map = {
            "LEFT": KeyCode.DPAD_LEFT,
            "RIGHT": KeyCode.DPAD_RIGHT,
            "UP": KeyCode.DPAD_UP,
            "DOWN": KeyCode.DPAD_DOWN,
            "BEGIN": KeyCode.MOVE_HOME,
            "END": KeyCode.MOVE_END,
        }
        keycode = key_map.get(direction.upper())
        if keycode is None:
            raise DevhelmError("未知光标方向: %s" % direction)
        for _ in range(times):
            self.press_keycode(int(keycode))

    # ============================================================
    # 手势扩展
    # ============================================================

    def _build_pointer_matrix(self,
                              gestures: List[GestureAction]) -> str:
        """将 GestureAction 列表转为设备端 PointerMatrix 远程对象。

        每个 GestureAction 代表一指的轨迹，步骤数取最大值，
        不足的用末尾坐标填充以保持位置静止。

        Returns:
            PointerMatrix 对象引用（如 "PointerMatrix#0"）
        """
        fingers = len(gestures)
        if fingers == 0:
            raise DevhelmError("gestures 不能为空")
        max_steps = max(len(g.steps) for g in gestures)
        if max_steps == 0:
            raise DevhelmError("GestureAction 无步骤")
        ref = self._rpc.call(
            "PointerMatrix.create", "PointerMatrix#seed", [fingers, max_steps]
        )
        if not isinstance(ref, str):
            raise DevhelmError("PointerMatrix 创建失败: %r" % (ref,))
        for finger_idx, gesture in enumerate(gestures):
            steps = gesture.steps
            if not steps:
                continue
            last = steps[-1]
            for step_idx in range(max_steps):
                step = steps[step_idx] if step_idx < len(steps) else last
                self._rpc.call(
                    "PointerMatrix.setPoint", ref,
                    [finger_idx, step_idx, {"x": step.x, "y": step.y}]
                )
        return ref

    def inject_gesture(self, gesture: GestureAction,
                       speed: int = 2000) -> None:
        """单指自定义手势。"""
        ref = self._build_pointer_matrix([gesture])
        self._rpc.call("Driver.injectMultiPointerAction", DRIVER_REF, [ref, speed])

    def inject_multi_finger_gesture(self, gestures: List[GestureAction],
                                    speed: int = 2000) -> None:
        """多指手势，每个 GestureAction 代表一指轨迹。"""
        ref = self._build_pointer_matrix(gestures)
        self._rpc.call("Driver.injectMultiPointerAction", DRIVER_REF, [ref, speed])

    def two_finger_swipe(self, s1: tuple, e1: tuple,
                         s2: tuple, e2: tuple,
                         duration: float = 0.5) -> None:
        """双指滑动。

        Args:
            s1/e1: 第一指起止坐标
            s2/e2: 第二指起止坐标
            duration: 滑动时长（秒），用于计算速度
        """
        g1 = GestureAction()
        g1.add_step("move", s1[0], s1[1])
        g1.add_step("move", e1[0], e1[1])
        g2 = GestureAction()
        g2.add_step("move", s2[0], s2[1])
        g2.add_step("move", e2[0], e2[1])
        dist = max(abs(e1[0] - s1[0]), abs(e1[1] - s1[1]), 1)
        speed = int(dist / duration) if duration > 0 else 600
        self.inject_multi_finger_gesture([g1, g2], speed)

    def multi_finger_touch(self, points: List[tuple],
                           duration: float = 0.1) -> None:
        """多指同时点击。

        Args:
            points: 各指按下坐标 [(x, y), ...]
            duration: 按住时长（秒），用于计算速度
        """
        gestures = []
        for pt in points:
            g = GestureAction()
            g.add_step("down", pt[0], pt[1])
            g.add_step("up", pt[0], pt[1])
            gestures.append(g)
        speed = int(100 / duration) if duration > 0 else 1000
        self.inject_multi_finger_gesture(gestures, speed)

    # ============================================================
    # 鼠标操作
    # ============================================================

    def mouse_click(self, pos, button_id: int = 0,
                    key1: Optional[int] = None,
                    key2: Optional[int] = None) -> None:
        """鼠标点击。

        Args:
            pos: 点击位置 (x, y) 或 {x, y}
            button_id: 0=左键 1=右键 2=中键
            key1: 组合键1（如 Ctrl=2072）
            key2: 组合键2
        """
        args = [_to_point(pos), button_id]
        if key1 is not None:
            args.append(key1)
            if key2 is not None:
                args.append(key2)
        self._rpc.call("Driver.mouseClick", DRIVER_REF, args)

    def mouse_double_click(self, pos, button_id: int = 0) -> None:
        """鼠标双击。"""
        self._rpc.call(
            "Driver.mouseDoubleClick", DRIVER_REF,
            [_to_point(pos), button_id]
        )

    def mouse_long_click(self, pos, button_id: int = 0,
                         press_time: float = 1.5) -> None:
        """鼠标长按。

        Args:
            press_time: 按住时长（秒），转为毫秒传入设备端
        """
        duration_ms = int(press_time * 1000)
        self._rpc.call(
            "Driver.mouseLongClick", DRIVER_REF,
            [_to_point(pos), button_id, 0, 0, duration_ms]
        )

    def mouse_scroll(self, pos, direction: str, steps: int,
                     key1: Optional[int] = None,
                     key2: Optional[int] = None) -> None:
        """鼠标滚轮滚动。

        Args:
            direction: 'up' 向上 / 'down' 向下
            steps: 滚动步数
        """
        down = direction.lower() == "down"
        args = [_to_point(pos), down, steps]
        if key1 is not None:
            args.append(key1)
            if key2 is not None:
                args.append(key2)
        self._rpc.call("Driver.mouseScroll", DRIVER_REF, args)

    def mouse_move_to(self, pos) -> None:
        """鼠标光标瞬移到指定位置。"""
        self._rpc.call("Driver.mouseMoveTo", DRIVER_REF, [_to_point(pos)])

    def mouse_move(self, start, end, speed: int = 3000) -> None:
        """鼠标沿轨迹从起点移动到终点。"""
        self._rpc.call(
            "Driver.mouseMoveWithTrack", DRIVER_REF,
            [_to_point(start), _to_point(end), speed]
        )

    def mouse_drag(self, start, end, speed: int = 3000) -> None:
        """鼠标拖拽。"""
        self._rpc.call(
            "Driver.mouseDrag", DRIVER_REF,
            [_to_point(start), _to_point(end), speed]
        )

    # ============================================================
    # 触控笔操作
    # ============================================================

    def pen_click(self, target, offset=None) -> None:
        """触控笔点击。

        Args:
            target: 坐标 (x, y) 或 UiObject（取 center）
            offset: 相对偏移 (dx, dy)
        """
        point = self._resolve_target_point(target, offset)
        self._rpc.call("Driver.penClick", DRIVER_REF, [point])

    def pen_double_click(self, target, offset=None) -> None:
        """触控笔双击。"""
        point = self._resolve_target_point(target, offset)
        self._rpc.call("Driver.penDoubleClick", DRIVER_REF, [point])

    def pen_long_click(self, target, offset=None,
                       pressure: Optional[float] = None) -> None:
        """触控笔长按。

        Args:
            pressure: 笔压力值 0.0-1.0
        """
        point = self._resolve_target_point(target, offset)
        args = [point]
        if pressure is not None:
            args.append(pressure)
        self._rpc.call("Driver.penLongClick", DRIVER_REF, args)

    def pen_swipe(self, direction: str, distance: int = 60,
                  area=None, pressure: Optional[float] = None,
                  duration: float = 0.3) -> None:
        """触控笔方向滑动。

        Args:
            direction: 'UP'/'DOWN'/'LEFT'/'RIGHT'
            distance: 滑动距离（像素）
            duration: 滑动时长（秒），用于计算速度
        """
        w, h = self.get_display_size()
        cx, cy = w // 2, h // 2
        direction = direction.upper()
        if direction == 'UP':
            start, end = (cx, cy + distance), (cx, cy - distance)
        elif direction == 'DOWN':
            start, end = (cx, cy - distance), (cx, cy + distance)
        elif direction == 'LEFT':
            start, end = (cx + distance, cy), (cx - distance, cy)
        elif direction == 'RIGHT':
            start, end = (cx - distance, cy), (cx + distance, cy)
        else:
            raise DevhelmError("未知滑动方向: %s" % direction)
        self.pen_slide(start, end, area, pressure, duration)

    def pen_slide(self, start, end, area=None,
                  pressure: Optional[float] = None,
                  duration: float = 0.3) -> None:
        """触控笔精确滑动。

        Args:
            start: 起点 (x, y)
            end: 终点 (x, y)
            pressure: 笔压力值
            duration: 滑动时长（秒），用于计算速度
        """
        start_pt = _to_point(start)
        end_pt = _to_point(end)
        dist = max(abs(end_pt['x'] - start_pt['x']),
                   abs(end_pt['y'] - start_pt['y']), 1)
        speed = int(dist / duration) if duration > 0 else 600
        args = [start_pt, end_pt, speed]
        if pressure is not None:
            args.append(pressure)
        self._rpc.call("Driver.penSwipe", DRIVER_REF, args)

    def pen_drag(self, start, end, area=None,
                 pressure: Optional[float] = None,
                 press_time: float = 1.5,
                 duration: float = 0.5) -> None:
        """触控笔拖拽（按住后移动）。

        Args:
            start: 起点 (x, y)
            end: 终点 (x, y)
            press_time: 起点按住时长（秒）
            duration: 移动到终点的时长（秒）
            pressure: 笔压力值
        """
        g = GestureAction(input_device=InputDevice.PEN)
        g.add_step("down", start[0], start[1], press_time)
        g.add_step("move", end[0], end[1], duration)
        ref = self._build_pointer_matrix([g])
        dist = max(abs(end[0] - start[0]), abs(end[1] - start[1]), 1)
        speed = int(dist / duration) if duration > 0 else 600
        args = [ref, speed]
        if pressure is not None:
            args.append(pressure)
        self._rpc.call("Driver.injectPenPointerAction", DRIVER_REF, args)

    def pen_inject_gesture(self, gesture: GestureAction,
                          pressure: Optional[float] = None,
                          speed: int = 2000) -> None:
        """触控笔自定义手势。"""
        ref = self._build_pointer_matrix([gesture])
        args = [ref, speed]
        if pressure is not None:
            args.append(pressure)
        self._rpc.call("Driver.injectPenPointerAction", DRIVER_REF, args)

    # ============================================================
    # 指关节操作
    # ============================================================

    def knuckle_knock(self, targets: list, times: int = 2) -> None:
        """指关节敲击（常用于截屏等快捷操作）。

        Args:
            targets: 敲击位置列表，1-2 个点 [(x, y), ...]
            times: 敲击次数
        """
        points = [_to_point(t) for t in targets]
        # 设备端底层参数非数组：单点 [point, times]，双点 [p0, p1, times]
        args = points + [times]
        self._rpc.call("Driver.knuckleKnock", DRIVER_REF, args)

    def inject_knuckle_gesture(self, gesture: GestureAction,
                               speed: int = 2000) -> None:
        """指关节自定义手势。"""
        ref = self._build_pointer_matrix([gesture])
        self._rpc.call(
            "Driver.injectKnucklePointerAction", DRIVER_REF, [ref, speed]
        )

    # ============================================================
    # 手势导航
    # ============================================================

    def swipe_to_home(self, times: int = 1) -> None:
        logger.debug("上滑回桌面 times=%d (serial=%s)", times, self.device_sn)
        w, h = self.get_display_size()
        start_x = w // 2
        start_y = h - 10
        end_y = h - h // 3
        end_x = int(start_x * 1.2)
        for i in range(times):
            self.swipe(start_x, start_y, end_x, end_y, duration=0.3)
            if i < times - 1:
                self.wait(0.5)
        self.wait(1)

    def swipe_to_back(self, side: str = "right", times: int = 1,
                      height: float = 0.5) -> None:
        """侧滑返回：side='LEFT'/'RIGHT'，height 为屏幕高度比例。"""
        logger.debug("侧滑返回 side=%s times=%d (serial=%s)",
                     side, times, self.device_sn)
        side = side.upper()
        if side == "RIGHT":
            start = self.to_abs_pos(0.99, height)
            end = self.to_abs_pos(0.6, height * 1.2)
        elif side == "LEFT":
            start = self.to_abs_pos(0.01, height)
            end = self.to_abs_pos(0.4, height * 1.2)
        else:
            raise DevhelmError("未知侧滑方向: %s" % side)
        cmd = "uinput -T -m %d %d %d %d %d" % (
            start[0], start[1], end[0], end[1], 200
        )
        for i in range(times):
            self.shell(cmd)
            if i < times - 1:
                self.wait(0.5)

    def swipe_to_recent_task(self) -> None:
        logger.debug("上滑进入多任务 (serial=%s)", self.device_sn)
        w, h = self.get_display_size()
        start_x = w // 2
        start_y = h - 10
        end_y = h - h // 4
        end_x = int(start_x * 1.2)
        self.swipe(start_x, start_y, end_x, end_y, duration=0.3)
        self.wait(1)

    # ============================================================
    # 坐标转换
    # ============================================================

    def to_abs_pos(self, x: float, y: float) -> Tuple[int, int]:
        # 每轴独立判断：[-1,1] 按比例转换，否则按绝对值
        w, h = self.get_display_size()
        abs_x = int(x * w) if -1.0 <= x <= 1.0 else int(x)
        abs_y = int(y * h) if -1.0 <= y <= 1.0 else int(y)
        return (abs_x, abs_y)

    # ============================================================
    # 设备初始化
    # ============================================================

    def _setup_device(self) -> None:
        """设备初始化：检查 uitest 版本。"""
        uitest_version = self._get_uitest_version()
        if uitest_version in _UNSUPPORTED_UITEST_VERSIONS:
            raise DevhelmError(
                "不支持的 uitest 版本: %s" % uitest_version
            )

    def _get_uitest_version(self) -> str:
        """获取 uitest 版本。"""
        output = self._device.shell("uitest --version")
        return output.strip()

    # ============================================================
    # 穿戴设备扩展
    # ============================================================

    def rotate_crown(self, steps: int,
                     speed: Optional[int] = None) -> None:
        """旋转表冠（穿戴设备专用）。

        Args:
            steps: 旋转角度（正数顺时针，负数逆时针）
            speed: 旋转速度（可选）
        """
        args = [steps]
        if speed is not None:
            args.append(speed)
        self._rpc.call("Driver.crownRotate", DRIVER_REF, args)

    # ============================================================
    # 触控板操作
    # ============================================================

    def touchpad_swipe(self, direction: str, fingers: int = 3,
                       speed: Optional[int] = None) -> None:
        """触控板多指滑动。

        Args:
            direction: 'UP'/'DOWN'/'LEFT'/'RIGHT'
            fingers: 手指数（2-4）
            speed: 滑动速度（可选）
        """
        direction_code = _UIDIRECTION_MAP.get(direction.upper())
        if direction_code is None:
            raise DevhelmError("未知滑动方向: %s" % direction)
        args = [fingers, direction_code]
        if speed is not None:
            args.append({"speed": speed})
        self._rpc.call("Driver.touchPadMultiFingerSwipe", DRIVER_REF, args)

    def touchpad_swipe_and_hold(self, direction: str, fingers: int = 3,
                                speed: Optional[int] = None) -> None:
        """触控板多指滑动后停顿（stay=true）。

        Args:
            direction: 'UP'/'DOWN'/'LEFT'/'RIGHT'
            fingers: 手指数（2-4）
            speed: 滑动速度（可选）
        """
        direction_code = _UIDIRECTION_MAP.get(direction.upper())
        if direction_code is None:
            raise DevhelmError("未知滑动方向: %s" % direction)
        options: Dict[str, Any] = {"stay": True}
        if speed is not None:
            options["speed"] = speed
        self._rpc.call(
            "Driver.touchPadMultiFingerSwipe", DRIVER_REF,
            [fingers, direction_code, options]
        )

    # ============================================================
    # 事件监听
    # ============================================================

    def start_listen_toast(self) -> None:
        """开始 Toast 监听（once 模式，触发一次后自动移除）。"""
        if self._toast_observer is None:
            self._toast_observer = self._rpc.call(
                "Driver.createUIEventObserver", DRIVER_REF, []
            )
        self._rpc.call(
            "UIEventObserver.once", self._toast_observer,
            ["toastShow", "callback#0"]
        )
        self._toast_listening = True

    def get_latest_toast(self, timeout: float = 3.0) -> str:
        """获取最新 Toast 文本。

        阻塞等待设备端 Toast 事件回调推送，超时抛 DevhelmTimeoutError。
        需先调用 start_listen_toast。
        """
        if not self._toast_listening:
            raise DevhelmError("未启动 toast 监听，请先 start_listen_toast")
        push = self._device.wait_push(timeout)
        self._toast_listening = False
        if push is None:
            raise DevhelmTimeoutError("等待 toast 超时（%ss）" % timeout)
        return self._parse_event_text(push)

    def check_toast(self, text: str, fuzzy: str = "equal",
                    timeout: float = 3.0) -> bool:
        """检查 Toast 是否包含指定文本。

        Args:
            text: 期望文本
            fuzzy: 匹配方式 'equal'/'contains'/'startswith'
            timeout: 等待超时（秒）
        """
        try:
            actual = self.get_latest_toast(timeout)
        except DevhelmTimeoutError:
            return False
        if fuzzy == "contains":
            return text in actual
        if fuzzy == "startswith":
            return actual.startswith(text)
        return actual == text

    def start_listen_ui_event(self, event_type: str) -> None:
        """开始 UI 事件监听（once 模式）。

        Args:
            event_type: 'dialogShow' / 'windowChange' / 'componentEventOccur'
        """
        if self._ui_event_observer is None:
            self._ui_event_observer = self._rpc.call(
                "Driver.createUIEventObserver", DRIVER_REF, []
            )
        if event_type in ("windowChange", "componentEventOccur"):
            args = [event_type, 1, {"timeout": 5000}, "callback#0"]
        else:
            args = [event_type, "callback#0"]
        self._rpc.call(
            "UIEventObserver.once", self._ui_event_observer, args
        )
        self._ui_event_listening = True

    def get_latest_ui_event(self, timeout: float = 3.0) -> Optional[dict]:
        """获取最新 UI 事件数据。

        阻塞等待设备端事件回调推送，超时返回 None。
        需先调用 start_listen_ui_event。
        """
        if not self._ui_event_listening:
            raise DevhelmError("未启动 ui_event 监听，请先 start_listen_ui_event")
        push = self._device.wait_push(timeout)
        self._ui_event_listening = False
        if push is None:
            return None
        return self._parse_event_dict(push)

    @staticmethod
    def _parse_event_text(push: str) -> str:
        """从回调推送帧中提取文本字段（容错解析）。"""
        try:
            data = json.loads(push)
        except (json.JSONDecodeError, TypeError):
            return push
        if not isinstance(data, dict):
            return str(data)
        for key in ('args', 'params'):
            val = data.get(key)
            if isinstance(val, list) and val:
                info = val[0]
                if isinstance(info, dict):
                    return info.get('text') or info.get('message') or ''
        info = data.get('result') or data.get('info') or data
        if isinstance(info, dict):
            return info.get('text') or info.get('message') or ''
        return str(info)

    @staticmethod
    def _parse_event_dict(push: str) -> Optional[dict]:
        """从回调推送帧中提取事件数据字典（容错解析）。"""
        try:
            data = json.loads(push)
        except (json.JSONDecodeError, TypeError):
            return None
        if not isinstance(data, dict):
            return None
        for key in ('args', 'params'):
            val = data.get(key)
            if isinstance(val, list) and val and isinstance(val[0], dict):
                return val[0]
        info = data.get('result') or data.get('info')
        if isinstance(info, dict):
            return info
        return data

    # ============================================================
    # 图像识别与 OCR（独立命名空间）
    # ============================================================

    @property
    def vision(self) -> 'VisionExtension':
        """图像识别与 OCR 能力命名空间，懒加载。"""
        if self._vision is None:
            from devhelmkit.core.vision.vision_extension import VisionExtension
            self._vision = VisionExtension(self)
        return self._vision

    # ============================================================
    # 配置访问
    # ============================================================

    @property
    def config(self) -> HarmonyDriverConfig:
        return self._config

    def update_config(self, **kwargs) -> None:
        self._config.update_from_dict(kwargs)

    def _resolve_target_point(self, target, offset=None) -> dict:
        """将 target 解析为 {x, y} 坐标点。

        Args:
            target: 坐标 (x, y) / {x, y} / UiObject（取 center）
            offset: 相对偏移 (dx, dy)
        """
        if hasattr(target, 'center'):
            x, y = target.center()
        else:
            pt = _to_point(target)
            x, y = pt['x'], pt['y']
        if offset:
            x += int(offset[0])
            y += int(offset[1])
        return {"x": x, "y": y}


def _to_point(pos) -> dict:
    """将坐标转为 {x, y} 字典。

    支持 (x, y) tuple/list 和 {x, y} dict。
    """
    if isinstance(pos, dict):
        return {"x": int(pos['x']), "y": int(pos['y'])}
    if isinstance(pos, (list, tuple)) and len(pos) >= 2:
        return {"x": int(pos[0]), "y": int(pos[1])}
    raise DevhelmError("无效的坐标: %r" % (pos,))


def _parse_display_info(output: str) -> Tuple[int, int, int]:
    """从 DisplayManagerService hidumper 输出中解析屏幕宽高与旋转。

    优先从 [DISPLAY INFO] 段提取 Width/Height/Rotation，
    回退到 Bounds<L,T,W,H> 与 ScreenRotation 字段。

    Returns:
        (width, height, rotation)
    """
    w, h, rot = 0, 0, 0
    # 优先 [DISPLAY INFO] 段
    display_info_idx = output.find('[DISPLAY INFO]')
    if display_info_idx != -1:
        section = output[display_info_idx:]
        wm = re.search(r'^Width:\s*(\d+)', section, re.MULTILINE)
        hm = re.search(r'^Height:\s*(\d+)', section, re.MULTILINE)
        rm = re.search(r'^Rotation:\s*(\d+)', section, re.MULTILINE)
        if wm:
            w = int(wm.group(1))
        if hm:
            h = int(hm.group(1))
        if rm:
            rot = int(rm.group(1))
    # 回退到 Bounds
    if w == 0 or h == 0:
        bm = re.search(r'Bounds<L,T,W,H>:\s*\d+,\s*\d+,\s*(\d+),\s*(\d+)', output)
        if bm:
            w = int(bm.group(1))
            h = int(bm.group(2))
    # 回退旋转
    if rot == 0:
        rm = re.search(r'ScreenRotation:\s*(\d+)', output)
        if rm:
            rot = int(rm.group(1))
    return (w, h, rot)


# UiDirection 枚举值（设备端数字编码）
_UIDIRECTION_MAP = {"LEFT": 0, "RIGHT": 1, "UP": 2, "DOWN": 3}


def _to_selector(target) -> Optional[SelectorSpec]:
    """将 target 转为 SelectorSpec。"""
    if isinstance(target, SelectorSpec):
        return target
    if isinstance(target, dict):
        return build_selector(**target)
    if isinstance(target, str):
        return build_selector(text=target)
    return None


class RecordingContext:
    """录屏上下文管理器，保证异常路径下自动停止并合成视频。

    由 HarmonyDriver.record() 创建，不直接实例化。
    """

    def __init__(self, driver: 'HarmonyDriver', output_path: str):
        self._driver = driver
        self._output_path = output_path
        self._output_dir: Optional[str] = None
        self._video_path: Optional[str] = None

    def __enter__(self) -> 'RecordingContext':
        self._output_dir = os.path.dirname(self._output_path) or "."
        self._driver.start_recording(self._output_dir)
        return self

    def __exit__(self, exc_type, exc_val, exc_tb) -> bool:
        try:
            self._video_path = self._driver.stop_recording(self._output_path)
        except Exception as e:
            logger.warning("录屏自动停止失败: %s", e)
        return False

    @property
    def video_path(self) -> Optional[str]:
        """合成后的视频文件路径，退出 with 块后可用。"""
        return self._video_path
