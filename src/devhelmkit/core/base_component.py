# !/usr/bin/env python
# -*- coding: utf-8 -*-
"""BaseComponent：跨平台控件对象契约。

对齐 U2 单对象模型：所有操作和关系方法统一在此定义。
内部持有 SelectorSpec（纯数据），不依赖任何可操作选择器抽象。
命名原则：U2 风格 snake_case 为基准，语义化方法为补充。
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any, Callable, Dict, List, Optional, Tuple, Union, TYPE_CHECKING

if TYPE_CHECKING:
    from PIL.Image import Image
    from devhelmkit.core.selector_spec import SelectorSpec
    from devhelmkit.core.base_driver import BaseDriver


class BaseComponent(ABC):
    """控件契约（查找到的控件对象）。"""

    def __init__(self, driver: 'BaseDriver', selector: 'SelectorSpec'):
        """
        Args:
            driver: 驱动实例
            selector: 定位条件（纯数据）
        """
        self._driver = driver
        self._selector = selector

    # ============================================================
    # 点击类
    # ============================================================

    @abstractmethod
    def click(self, timeout: Optional[float] = None) -> None:
        """点击。

        Args:
            timeout: 查找超时秒数，None 取驱动隐式等待默认值。
        """

    @abstractmethod
    def long_click(self, duration: float = 0.5,
                   timeout: Optional[float] = None) -> None:
        """长按。

        Args:
            duration: 长按时长秒数。
            timeout: 查找超时秒数，None 取驱动隐式等待默认值。
        """

    @abstractmethod
    def double_click(self, timeout: Optional[float] = None) -> None:
        """双击。

        Args:
            timeout: 查找超时秒数，None 取驱动隐式等待默认值。
        """

    @abstractmethod
    def click_if_exists(self, timeout: float = 0) -> bool:
        """存在则点击，未找到时返回 False。"""

    @property
    @abstractmethod
    def count(self) -> int:
        """返回当前匹配控件数量。"""

    @abstractmethod
    def all(self) -> List['BaseComponent']:
        """返回当前匹配的全部控件对象。"""

    @abstractmethod
    def first(self) -> 'BaseComponent':
        """返回第一个匹配控件对象。"""

    @abstractmethod
    def last(self) -> 'BaseComponent':
        """返回最后一个匹配控件对象。"""

    # ============================================================
    # 文本类
    # ============================================================

    @abstractmethod
    def set_text(self, text: str,
                 timeout: Optional[float] = None) -> None:
        """输入文本。

        Args:
            text: 待输入文本。
            timeout: 查找超时秒数，None 取驱动隐式等待默认值。
        """

    @abstractmethod
    def get_text(self, timeout: Optional[float] = None) -> str:
        """获取文本。

        Args:
            timeout: 查找超时秒数，None 取驱动隐式等待默认值。
        """

    @abstractmethod
    def clear_text(self, timeout: Optional[float] = None) -> None:
        """清空文本。

        Args:
            timeout: 查找超时秒数，None 取驱动隐式等待默认值。
        """

    @abstractmethod
    def input_text(self, text: str,
                   timeout: Optional[float] = None) -> None:
        """输入文本（set_text 别名）。

        Args:
            text: 待输入文本。
            timeout: 查找超时秒数，None 取驱动隐式等待默认值。
        """

    # ============================================================
    # 状态类
    # ============================================================

    @abstractmethod
    def exists(self) -> bool:
        """是否存在。"""

    @abstractmethod
    def wait(self, timeout: float) -> bool:
        """等待出现。"""

    @abstractmethod
    def wait_gone(self, timeout: float) -> bool:
        """等待消失。"""

    @abstractmethod
    def wait_enabled(self, timeout: float) -> bool:
        """等待控件变为可用。"""

    @abstractmethod
    def wait_disabled(self, timeout: float) -> bool:
        """等待控件变为禁用。"""

    @abstractmethod
    def wait_clickable(self, timeout: float) -> bool:
        """等待控件变为可点击。"""

    @abstractmethod
    def wait_until(self, condition: Callable[[Dict[str, Any]], bool],
                   timeout: float) -> bool:
        """等待控件信息满足条件。"""

    # ============================================================
    # 信息类
    # ============================================================

    @property
    @abstractmethod
    def info(self) -> Dict[str, Any]:
        """控件信息（text/id/class/bounds/clickable/enabled/visible）。"""

    @property
    @abstractmethod
    def bounds(self) -> Any:
        """控件坐标 Rect(left, top, right, bottom)。"""

    @abstractmethod
    def center(self) -> Tuple[int, int]:
        """控件中心点 (x, y)。"""

    @abstractmethod
    def get_attribute(self, name: str,
                      timeout: Optional[float] = None) -> Any:
        """获取控件属性。

        Args:
            name: 属性名。
            timeout: 查找超时秒数，None 取驱动隐式等待默认值。
        """

    @abstractmethod
    def screenshot(self, filename: Optional[str] = None
                   ) -> Union['Image', str, None]:
        """控件截图。

        Args:
            filename: 保存路径，None 返回 PIL Image。
        """

    @property
    @abstractmethod
    def description(self) -> str:
        """description 属性。"""

    @abstractmethod
    def get_hint(self, timeout: Optional[float] = None) -> str:
        """获取 hint 属性。

        Args:
            timeout: 查找超时秒数，None 取驱动隐式等待默认值。
        """

    @abstractmethod
    def get_all_properties(self,
                           timeout: Optional[float] = None) -> dict:
        """获取所有属性。

        Args:
            timeout: 查找超时秒数，None 取驱动隐式等待默认值。
        """

    @abstractmethod
    def get_original_text(self,
                          timeout: Optional[float] = None) -> str:
        """获取原始文本。

        Args:
            timeout: 查找超时秒数，None 取驱动隐式等待默认值。
        """

    # ============================================================
    # 布尔属性
    # ============================================================

    @property
    @abstractmethod
    def is_long_clickable(self) -> bool:
        """是否可长按。"""

    @property
    @abstractmethod
    def is_checked(self) -> bool:
        """是否已选中。"""

    @property
    @abstractmethod
    def is_checkable(self) -> bool:
        """是否可选中。"""

    @property
    @abstractmethod
    def is_selected(self) -> bool:
        """是否处于选中态。"""

    # ============================================================
    # 拖拽类
    # ============================================================

    @abstractmethod
    def drag_to(self, x: int, y: int,
                timeout: Optional[float] = None) -> None:
        """拖拽到坐标。

        Args:
            x: 目标 x 坐标。
            y: 目标 y 坐标。
            timeout: 查找超时秒数，None 取驱动隐式等待默认值。
        """

    @abstractmethod
    def drag_to_component(self, other: 'BaseComponent',
                          timeout: Optional[float] = None) -> None:
        """拖拽到另一控件。

        Args:
            other: 目标控件。
            timeout: 查找超时秒数，None 取驱动隐式等待默认值。
        """

    # ============================================================
    # 缩放类
    # ============================================================

    @abstractmethod
    def pinch_in(self, scale: float = 0.5,
                 timeout: Optional[float] = None) -> None:
        """控件上捏合缩小。

        Args:
            scale: 缩放比例。
            timeout: 查找超时秒数，None 取驱动隐式等待默认值。
        """

    @abstractmethod
    def pinch_out(self, scale: float = 1.5,
                  timeout: Optional[float] = None) -> None:
        """控件上捏合放大。

        Args:
            scale: 缩放比例。
            timeout: 查找超时秒数，None 取驱动隐式等待默认值。
        """

    # ============================================================
    # 滚动类
    # ============================================================

    @abstractmethod
    def scroll_search(self, target, vertical: bool = True,
                      offset: Optional[int] = None) -> Optional['BaseComponent']:
        """滚动查找子控件。"""

    @abstractmethod
    def scroll_to_top(self, speed: int = 600,
                      timeout: Optional[float] = None) -> None:
        """滚动到顶部。

        Args:
            speed: 滚动速度。
            timeout: 查找超时秒数，None 取驱动隐式等待默认值。
        """

    @abstractmethod
    def scroll_to_bottom(self, speed: int = 600,
                         timeout: Optional[float] = None) -> None:
        """滚动到底部。

        Args:
            speed: 滚动速度。
            timeout: 查找超时秒数，None 取驱动隐式等待默认值。
        """

    # ============================================================
    # 关系选择器（返回新的 BaseComponent，持有衍生 SelectorSpec）
    # ============================================================

    @abstractmethod
    def child(self, **kwargs) -> 'BaseComponent':
        """子控件。"""

    @abstractmethod
    def sibling(self, **kwargs) -> 'BaseComponent':
        """兄弟控件。"""

    @abstractmethod
    def after(self, **kwargs) -> 'BaseComponent':
        """之后控件。"""

    @abstractmethod
    def before(self, **kwargs) -> 'BaseComponent':
        """之前控件。"""
