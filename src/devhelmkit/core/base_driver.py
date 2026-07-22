# !/usr/bin/env python
# -*- coding: utf-8 -*-
"""BaseDriver：跨平台设备驱动契约。

命名原则：U2 风格 snake_case 为基准，语义化方法为补充。
抽象层只定义跨平台通用接口，平台特有能力通过子类扩展提供。
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any, Dict, List, Optional, Tuple, Union, TYPE_CHECKING

if TYPE_CHECKING:
    from PIL.Image import Image
    from devhelmkit.core.base_component import BaseComponent
    from devhelmkit.core.base_window import BaseWindow


class BaseDriver(ABC):
    """跨平台设备驱动契约。"""

    # ============================================================
    # 生命周期
    # ============================================================

    @abstractmethod
    def close(self) -> None:
        """关闭驱动，释放连接资源。"""

    def __enter__(self) -> 'BaseDriver':
        return self

    def __exit__(self, exc_type, exc_val, exc_tb) -> bool:
        self.close()
        return False

    @property
    @abstractmethod
    def device_sn(self) -> str:
        """设备序列号。"""

    @property
    @abstractmethod
    def platform(self) -> str:
        """平台标识：'harmony' / 'android'。"""

    # ============================================================
    # 设备信息
    # ============================================================

    @property
    @abstractmethod
    def info(self) -> Dict[str, Any]:
        """设备基本信息（品牌、型号、系统版本等）。"""

    @abstractmethod
    def get_display_size(self) -> Tuple[int, int]:
        """获取屏幕分辨率 (width, height)。"""

    @abstractmethod
    def get_display_rotation(self) -> int:
        """获取屏幕方向。"""

    @abstractmethod
    def set_display_rotation(self, rotation: int) -> None:
        """设置屏幕方向。"""

    @abstractmethod
    def set_display_rotation_enabled(self, enabled: bool) -> None:
        """自动旋转开关。"""

    @abstractmethod
    def get_device_type(self) -> str:
        """设备类型（phone / tablet / 2in1 / wearable / ...）。"""

    @abstractmethod
    def get_device_model(self) -> str:
        """设备型号。"""

    @abstractmethod
    def get_brand(self) -> str:
        """设备品牌。"""

    @abstractmethod
    def get_abi(self) -> str:
        """CPU ABI（如 arm64-v8a）。"""

    @abstractmethod
    def get_os_type(self) -> str:
        """操作系统类型标识。"""

    @abstractmethod
    def get_system_version(self) -> str:
        """操作系统版本号。"""

    @abstractmethod
    def get_api_level(self) -> str:
        """API 级别。"""

    # ============================================================
    # 屏幕操作
    # ============================================================

    @abstractmethod
    def screen_on(self) -> None:
        """亮屏（唤醒屏幕）。"""

    @abstractmethod
    def screen_off(self) -> None:
        """熄屏。"""

    @abstractmethod
    def is_screen_on(self) -> bool:
        """屏幕是否点亮。"""

    @abstractmethod
    def is_screen_locked(self) -> bool:
        """屏幕是否锁屏。"""

    @abstractmethod
    def unlock(self) -> None:
        """解锁设备（亮屏 + 上滑/回车解除锁屏）。"""

    @abstractmethod
    def set_sleep_time(self, seconds: float) -> None:
        """设置熄屏时间（秒）。"""

    @abstractmethod
    def restore_sleep_time(self) -> None:
        """恢复默认熄屏时间。"""

    # ============================================================
    # 选择器入口（U2 风格）
    # ============================================================

    @abstractmethod
    def __call__(self, **kwargs) -> 'BaseComponent':
        """U2 风格选择器：d(text=, resourceId=, className=)，返回控件对象。

        平台实现返回具体子类（协变），如 HarmonyDriver 返回 UiObject。
        """

    @abstractmethod
    def xpath(self, xpath: str) -> 'BaseComponent':
        """xpath 选择器，返回控件对象。"""

    # ============================================================
    # 应用管理
    # ============================================================

    @abstractmethod
    def app_start(self, package: str, activity: Optional[str] = None,
                  params: str = "", wait_time: float = 1) -> None:
        """启动应用。"""

    @abstractmethod
    def app_stop(self, package: str, wait_time: float = 0.5) -> None:
        """停止应用。"""

    @abstractmethod
    def app_current(self) -> Tuple[Optional[str], Optional[str]]:
        """获取当前前台应用 (package, activity)。

        位于桌面或读取失败时返回 (None, None)。
        """

    @abstractmethod
    def app_list(self) -> List[str]:
        """已安装应用列表。"""

    @abstractmethod
    def has_app(self, package: str) -> bool:
        """查询是否已安装应用。"""

    @abstractmethod
    def clear_app_data(self, package: str) -> None:
        """清除应用数据。"""

    # ============================================================
    # 坐标操作
    # ============================================================

    @abstractmethod
    def click(self, x: Union[int, float], y: Union[int, float]) -> None:
        """坐标点击；``[-1, 1]`` 按屏幕比例，否则按像素。"""

    @abstractmethod
    def long_click(self, x: Union[int, float], y: Union[int, float],
                   duration: float = 0.5) -> None:
        """坐标长按；``[-1, 1]`` 按屏幕比例，否则按像素。"""

    @abstractmethod
    def double_click(self, x: Union[int, float], y: Union[int, float]) -> None:
        """坐标双击；``[-1, 1]`` 按屏幕比例，否则按像素。"""

    @abstractmethod
    def swipe(self, x1: Union[int, float], y1: Union[int, float],
              x2: Union[int, float], y2: Union[int, float],
              duration: float = 0.5) -> None:
        """精确滑动（起止坐标）；``[-1, 1]`` 按屏幕比例，否则按像素。"""

    @abstractmethod
    def swipe_dir(self, direction: str, distance: int = 60,
                  area=None, speed=None) -> None:
        """方向滑动：'UP' / 'DOWN' / 'LEFT' / 'RIGHT'。"""

    @abstractmethod
    def swipe_ext(self, direction: str, scale: float = 0.8,
                  box=None, duration: float = 0.5) -> None:
        """按比例在全屏或 ``box`` 区域内方向滑动。

        Args:
            direction: ``up``/``down``/``left``/``right``（``bottom`` 视为 ``down``）。
            scale: 滑动行程占区域边长的比例，范围 ``(0, 1]``。
            box: 可选 ``(x1, y1, x2, y2)``，支持比例或像素。
            duration: 滑动时长（秒）。
        """

    @abstractmethod
    def drag(self, x1: Union[int, float], y1: Union[int, float],
             x2: Union[int, float], y2: Union[int, float],
             duration: float = 0.5) -> None:
        """拖拽；``[-1, 1]`` 按屏幕比例，否则按像素。"""

    @abstractmethod
    def fling(self, direction: str, distance: int = 50,
              area=None, speed: str = "fast") -> None:
        """抛滑（快速惯性滑动）。"""

    # ============================================================
    # 实时触控（支持 down/move/up 序列，用于实时拖拽等场景）
    # ============================================================

    @abstractmethod
    def touch_down(self, x: int, y: int) -> None:
        """按下触控点。"""

    @abstractmethod
    def touch_move(self, x: int, y: int) -> None:
        """移动触控点（需先 touch_down）。"""

    @abstractmethod
    def touch_up(self, x: int, y: int) -> None:
        """抬起触控点（结束触控序列）。"""

    # ============================================================
    # 按键
    # ============================================================

    @abstractmethod
    def press(self, key: str) -> None:
        """语义按键：'back' / 'home' / 'power' / 'volume_up' / ..."""

    @abstractmethod
    def press_keycode(self, keycode: int) -> None:
        """按键码（平台原始按键码，由平台实现自行解释）。"""

    @abstractmethod
    def go_home(self) -> None:
        """返回桌面（自动选最稳定路径）。"""

    @abstractmethod
    def go_back(self) -> None:
        """返回上一级（自动选最稳定路径）。"""

    @abstractmethod
    def go_recent_task(self) -> None:
        """进入多任务界面（自动选最稳定路径）。"""

    @abstractmethod
    def press_power(self) -> None:
        """按下电源键。"""

    @abstractmethod
    def press_combination_key(self, key1: int, key2: int,
                              key3: Optional[int] = None) -> None:
        """按下组合键（支持 2 键或 3 键）。"""

    # ============================================================
    # Shell
    # ============================================================

    @abstractmethod
    def shell(self, cmd: str, timeout: float = 60) -> str:
        """执行 shell 命令，返回回显内容。"""

    # ============================================================
    # 截图
    # ============================================================

    @abstractmethod
    def screenshot(self, filename: Optional[str] = None,
                   area=None) -> Union['Image', str, None]:
        """截图。

        - filename 为 None：返回 PIL.Image.Image
        - filename 指定：保存到文件，返回文件路径 str
        - area 指定区域截图（Rect / SelectorSpec / None）
        - 失败：返回 None
        """

    @abstractmethod
    def start_recording(self, output_dir: str) -> None:
        """开始录屏，捕获设备屏幕帧序列。

        JPEG 帧存放在 output_dir/frames/，mp4 存放在 output_dir/。

        Args:
            output_dir: 录屏输出目录
        """

    @abstractmethod
    def stop_recording(self, output_path: str) -> str:
        """停止录屏并合成为视频文件。

        Args:
            output_path: 输出视频路径（.mp4 推荐）

        Returns:
            实际保存的视频文件路径
        """

    @abstractmethod
    def dump_hierarchy(self, source: str = "rpc",
                       filename: Optional[str] = None) -> Union[dict, str, None]:
        """导出控件树。

        - source: 获取方式
            - "rpc": 走 uitest RPC（Captures.captureLayout），直接返回控件树 JSON，默认
            - "hdc": 走 hdc shell（uitest dumpLayout -p），独立于 RPC 守护进程状态
        - filename 为 None：返回解析后的 dict
        - filename 指定：保存 JSON 到文件，返回文件路径 str
        - 失败：返回 None
        """

    # ============================================================
    # 低延迟连续截图（可选优化，平台按需实现）
    # ============================================================

    def begin_fast_capture(self) -> bool:
        """为反复截图的轮询场景（图像/OCR 查找）开启低延迟截图通道。

        默认平台无此能力，返回 False（继续使用 screenshot() 默认通道）。
        平台可覆写为启用推流等快通道，并返回本次调用是否由自身开启，供
        end_fast_capture 决定是否关闭，避免误关用户已开启的通道。
        """
        return False

    def end_fast_capture(self) -> None:
        """关闭由 begin_fast_capture 开启的低延迟截图通道，默认无操作。"""

    # ============================================================
    # 等待
    # ============================================================

    @abstractmethod
    def wait(self, seconds: float) -> None:
        """强制等待指定秒数。"""

    @abstractmethod
    def wait_for_idle(self, idle_time: float = 0.7,
                      timeout: float = 10) -> None:
        """等待 UI 进入空闲状态。"""

    @abstractmethod
    def implicitly_wait(self, seconds: float) -> None:
        """设置隐式等待。"""

    # ============================================================
    # 窗口
    # ============================================================

    @property
    @abstractmethod
    def window(self) -> 'BaseWindow':
        """当前窗口对象。"""

    @abstractmethod
    def get_windows(self) -> List['BaseWindow']:
        """获取所有窗口。"""

    # ============================================================
    # webview 自动化（可选实现，不支持时抛 NotImplementedError）
    # ============================================================

    def webview(self, bundle_name: str, **kwargs):
        """连接应用 webview，返回 selenium webdriver 封装。

        平台不支持 webview 测试时抛 NotImplementedError。
        """
        raise NotImplementedError("当前平台不支持 webview 自动化")

    # ============================================================
    # 文件操作
    # ============================================================

    @abstractmethod
    def push_file(self, local_path: str, remote_path: str,
                  timeout: int = 60) -> None:
        """推送文件到设备。"""

    @abstractmethod
    def pull_file(self, remote_path: str,
                  local_path: Optional[str] = None,
                  timeout: int = 60) -> str:
        """从设备拉取文件，返回实际保存的本地路径。

        local_path 为 None 时保存到临时文件，调用方通过返回值获取路径。
        """

    @abstractmethod
    def has_file(self, path: str) -> bool:
        """查询设备端文件是否存在。"""

    # ============================================================
    # 控件查找
    # ============================================================

    @abstractmethod
    def find_component(self, target, scroll_target=None) -> Optional['BaseComponent']:
        """查找控件返回对象。"""

    @abstractmethod
    def find_all_components(self, target) -> List['BaseComponent']:
        """查找所有匹配控件。"""

    @abstractmethod
    def get_component_bound(self, target) -> Optional[Any]:
        """获取控件边界 Rect，未找到返回 None。"""

    @abstractmethod
    def get_component_property(self, target, name: str) -> Any:
        """获取控件指定属性（id/text/key/type/enabled/focused/clickable/scrollable/checked/checkable）。"""

    # ============================================================
    # 图像识别与 OCR（独立命名空间，按需安装依赖）
    # ============================================================

    @property
    @abstractmethod
    def vision(self) -> Any:
        """图像识别与 OCR 能力命名空间。

        返回平台特定的 vision 扩展对象，提供以下方法：
            - find_image(template, region, threshold, timeout) -> Optional[Rect]
            - touch_image(template, region, threshold, timeout) -> bool
            - exists_image(template, region, threshold) -> bool
            - wait_image(template, region, threshold, timeout) -> bool
            - ocr(region, timeout) -> List[OcrResult]
            - find_text(text, region, fuzzy, timeout) -> Optional[OcrResult]
            - click_text(text, region, fuzzy, timeout) -> bool

        依赖未安装时调用方法抛 DevhelmError。
        """

    # ============================================================
    # 文本输入辅助
    # ============================================================

    @abstractmethod
    def hide_keyboard(self) -> None:
        """隐藏软键盘。"""

    @abstractmethod
    def input_text_on_cursor(self, text: str) -> None:
        """在当前光标处输入文本（不依赖控件定位）。"""

    @abstractmethod
    def move_cursor(self, direction: str, times: int = 1) -> None:
        """移动输入框光标：'LEFT' / 'RIGHT' / 'UP' / 'DOWN' / 'BEGIN' / 'END'。"""

    # ============================================================
    # 手势扩展
    # ============================================================

    @abstractmethod
    def inject_gesture(self, gesture, speed: int = 2000) -> None:
        """自定义手势。"""

    # ============================================================
    # 手势导航
    # ============================================================

    @abstractmethod
    def swipe_to_home(self, times: int = 1) -> None:
        """屏幕底端上滑回到桌面（需开启手势导航）。"""

    @abstractmethod
    def swipe_to_back(self, side: str = "LEFT", times: int = 1,
                      height: float = 0.5) -> None:
        """侧滑返回：side='LEFT'/'RIGHT'，height 为屏幕高度比例。"""

    @abstractmethod
    def swipe_to_recent_task(self) -> None:
        """底端上滑停顿进入多任务界面。"""

    # ============================================================
    # 坐标转换
    # ============================================================

    @abstractmethod
    def to_abs_pos(self, x: float, y: float) -> Tuple[int, int]:
        """比例坐标转绝对坐标。"""
