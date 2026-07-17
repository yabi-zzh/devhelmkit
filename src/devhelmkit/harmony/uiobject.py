# !/usr/bin/env python
# -*- coding: utf-8 -*-
"""UiObject：HarmonyOS 平台控件对象。

UiObject 只持有 SelectorSpec 与驱动引用，不直接拼底层 RPC 消息。
控件查找、选择器转换、远程对象引用和弹窗处理统一交给 HarmonyDriver /
ComponentFinder。每次操作都重新定位控件，对齐 U2 单对象模型。
"""
from __future__ import annotations

import time
from typing import Any, Callable, List, Optional, Tuple, Union, TYPE_CHECKING

from devhelmkit.core.base_component import BaseComponent
from devhelmkit.core.selector_spec import SelectorSpec, build_selector
from devhelmkit.exceptions import (
    BackendObjectDroppedError,
    ComponentNotFoundError,
)
from devhelmkit.model.rect import Rect

if TYPE_CHECKING:
    from PIL.Image import Image
    from devhelmkit.harmony.driver import HarmonyDriver


class UiObject(BaseComponent):
    """HarmonyOS 平台控件对象。

    所有操作通过 HarmonyDriver 门面委托给 ComponentFinder，
    由 ComponentFinder 负责 By/On 链构造、findComponent 和方法调用。

    Component ref 缓存：首次查找后缓存 ref，后续操作直接复用，
    避免连续操作时重复查找。调用 refresh() 手动失效。
    """

    def __init__(self, driver: 'HarmonyDriver', selector: 'SelectorSpec'):
        super().__init__(driver, selector)
        self._component_ref: Optional[str] = None

    def refresh(self) -> None:
        """手动失效缓存的 Component ref，下次操作重新查找。"""
        self._component_ref = None

    # ============================================================
    # 内部：控件操作门面
    # ============================================================

    def _call_component(self, method: str,
                        args: Optional[list] = None,
                        timeout: Optional[float] = None) -> Any:
        """通过驱动门面执行控件操作。

        首次调用时查找控件并缓存引用，后续直接复用。
        引用失效时自动重新查找一次。

        Args:
            method: Component 方法名。
            args: 方法参数列表。
            timeout: 查找超时秒数，None 取驱动隐式等待默认值。
        """
        if self._component_ref is not None:
            try:
                return self._driver._finder.call_component_by_ref(
                    self._component_ref, method, args or []
                )
            except BackendObjectDroppedError:
                self._component_ref = None
        component_ref = self._driver._finder.find_component(
            self._selector,
            timeout if timeout is not None else self._driver._implicit_wait
        )
        self._component_ref = component_ref
        return self._driver._finder.call_component_by_ref(
            component_ref, method, args or []
        )

    # ============================================================
    # 点击类
    # ============================================================

    def click(self, timeout: Optional[float] = None) -> None:
        self._call_component("click", timeout=timeout)

    def long_click(self, duration: float = 0.5,
                   timeout: Optional[float] = None) -> None:
        self._call_component("longClick", [duration], timeout=timeout)

    def double_click(self, timeout: Optional[float] = None) -> None:
        self._call_component("doubleClick", timeout=timeout)

    def click_if_exists(self, timeout: float = 0) -> bool:
        """存在则点击；控件未找到时返回 False。"""
        try:
            self.click(timeout=timeout)
            return True
        except ComponentNotFoundError:
            return False

    @property
    def count(self) -> int:
        """返回当前匹配控件数量。"""
        return len(self._driver._finder.find_components(self._selector))

    def all(self) -> List['UiObject']:
        """批量查找并绑定当前匹配的控件引用。"""
        refs = self._driver._finder.find_components(self._selector)
        return [self._with_component_ref(ref) for ref in refs]

    def first(self) -> 'UiObject':
        """返回第一个匹配控件；实际操作时才使用已绑定引用。"""
        refs = self._driver._finder.find_components(self._selector)
        if not refs:
            raise ComponentNotFoundError(
                "控件未找到: %s" % self._selector
            )
        return self._with_component_ref(refs[0])

    def last(self) -> 'UiObject':
        """返回最后一个匹配控件；实际操作时才使用已绑定引用。"""
        refs = self._driver._finder.find_components(self._selector)
        if not refs:
            raise ComponentNotFoundError(
                "控件未找到: %s" % self._selector
            )
        return self._with_component_ref(refs[-1])

    def _with_component_ref(self, component_ref: str) -> 'UiObject':
        """创建持有短期 Component ref 的控件对象。"""
        obj = UiObject(self._driver, self._selector)
        obj._component_ref = component_ref
        return obj

    # ============================================================
    # 文本类
    # ============================================================

    def set_text(self, text: str,
                 timeout: Optional[float] = None) -> None:
        self._call_component("inputText", [text], timeout=timeout)

    def get_text(self, timeout: Optional[float] = None) -> str:
        return self._call_component("getText", timeout=timeout)

    def clear_text(self, timeout: Optional[float] = None) -> None:
        self._call_component("clearText", timeout=timeout)

    def input_text(self, text: str,
                   timeout: Optional[float] = None) -> None:
        self.set_text(text, timeout=timeout)

    # ============================================================
    # 状态类
    # ============================================================

    def exists(self) -> bool:
        return self._driver.component_exists(self._selector)

    def wait(self, timeout: float) -> bool:
        return self._driver.wait_component(self._selector, timeout)

    def wait_gone(self, timeout: float) -> bool:
        return self._driver.wait_component_gone(self._selector, timeout)

    def wait_enabled(self, timeout: Optional[float] = None) -> bool:
        """等待控件变为可用。"""
        return self.wait_until(
            lambda info: bool(info.get("enabled")), timeout=timeout
        )

    def wait_disabled(self, timeout: Optional[float] = None) -> bool:
        """等待控件变为禁用。"""
        return self.wait_until(
            lambda info: info.get("enabled") is False, timeout=timeout
        )

    def wait_clickable(self, timeout: Optional[float] = None) -> bool:
        """等待控件变为可点击。"""
        return self.wait_until(
            lambda info: bool(info.get("clickable")), timeout=timeout
        )

    def wait_until(self, condition: Callable[[dict], bool],
                   timeout: Optional[float] = None) -> bool:
        """在统一 deadline 内等待控件信息满足条件。"""
        if not callable(condition):
            raise TypeError("condition 必须是可调用对象")
        wait_timeout = self._resolve_wait_timeout(timeout)
        deadline = time.monotonic() + wait_timeout
        interval = 0.1
        first_attempt = True

        while first_attempt or time.monotonic() < deadline:
            first_attempt = False
            try:
                if condition(self.info):
                    return True
            except ComponentNotFoundError:
                pass

            remaining = deadline - time.monotonic()
            if remaining <= 0:
                break
            time.sleep(min(interval, remaining))
            interval = min(interval * 2, 0.5)
        return False

    def _resolve_wait_timeout(self, timeout: Optional[float]) -> float:
        """解析等待超时，统一使用非墙上时钟计算 deadline。"""
        value = (
            timeout
            if timeout is not None
            else getattr(self._driver, "_implicit_wait", 10.0)
        )
        value = float(value)
        if value < 0:
            raise ValueError("timeout 不能为负数")
        return value

    def _collect_properties(self,
                            timeout: Optional[float] = None) -> dict:
        """收集控件共有属性（文本、类型、布尔状态）。

        Args:
            timeout: 查找超时秒数，None 取驱动隐式等待默认值。
        """
        props = self._driver.get_properties_from_tree(
            self._selector, timeout=timeout
        )
        if props is not None:
            return {
                "text": props["text"],
                "id": props["id"],
                "type": props["type"],
                "enabled": props["enabled"],
                "focused": props["focused"],
                "selected": props["selected"],
                "clickable": props["clickable"],
                "long_clickable": props["long_clickable"],
                "scrollable": props["scrollable"],
                "checkable": props["checkable"],
                "checked": props["checked"],
            }
        # 回退：dump_hierarchy 未匹配，走逐个 RPC
        return {
            "text": self._call_component("getText", timeout=timeout),
            "id": self._call_component("getId", timeout=timeout),
            "type": self._call_component("getType", timeout=timeout),
            "enabled": self._call_component("isEnabled", timeout=timeout),
            "focused": self._call_component("isFocused", timeout=timeout),
            "selected": self._call_component("isSelected", timeout=timeout),
            "clickable": self._call_component("isClickable", timeout=timeout),
            "long_clickable": self._call_component("isLongClickable", timeout=timeout),
            "scrollable": self._call_component("isScrollable", timeout=timeout),
            "checkable": self._call_component("isCheckable", timeout=timeout),
            "checked": self._call_component("isChecked", timeout=timeout),
        }

    @property
    def info(self) -> dict:
        """控件综合信息（文本、类型、状态、边界等）。"""
        props = self._driver.get_properties_from_tree(
            self._selector, timeout=self._driver._implicit_wait
        )
        if props is not None:
            return props
        # 回退：逐个 RPC
        result = self._collect_properties()
        result["description"] = self._call_component("getDescription")
        result["bounds"] = self._call_component("getBounds")
        return result

    @property
    def bounds(self) -> Rect:
        props = self._driver.get_properties_from_tree(
            self._selector, timeout=self._driver._implicit_wait
        )
        if props is not None:
            b = props["bounds"]
            return Rect(
                left=int(b["left"]), top=int(b["top"]),
                right=int(b["right"]), bottom=int(b["bottom"]),
            )
        result = self._call_component("getBounds")
        return _to_rect(result)

    def center(self) -> Tuple[int, int]:
        return self.bounds.center.as_tuple()

    def get_attribute(self, name: str,
                      timeout: Optional[float] = None) -> Any:
        return self._call_component("getAttribute", [name], timeout=timeout)

    def screenshot(self, filename: Optional[str] = None
                   ) -> Union['Image', str, None]:
        return self._driver.screenshot(filename=filename, area=self._selector)

    @property
    def description(self) -> str:
        return self._call_component("getDescription")

    def get_hint(self, timeout: Optional[float] = None) -> str:
        return self._call_component("getHint", timeout=timeout)

    def get_all_properties(self,
                           timeout: Optional[float] = None) -> dict:
        """获取控件全部布尔属性与文本。"""
        return self._collect_properties(timeout=timeout)

    def get_original_text(self,
                          timeout: Optional[float] = None) -> str:
        return self._call_component("getOriginalText", timeout=timeout)

    # ============================================================
    # 布尔属性
    # ============================================================

    @property
    def is_long_clickable(self) -> bool:
        return self._call_component("isLongClickable")

    @property
    def is_checked(self) -> bool:
        return self._call_component("isChecked")

    @property
    def is_checkable(self) -> bool:
        return self._call_component("isCheckable")

    @property
    def is_selected(self) -> bool:
        return self._call_component("isSelected")

    # ============================================================
    # 拖拽类
    # ============================================================

    def drag_to(self, x: int, y: int,
                timeout: Optional[float] = None) -> None:
        self._call_component("dragTo", [x, y], timeout=timeout)

    def drag_to_component(self, other: 'UiObject',
                          timeout: Optional[float] = None) -> None:
        self._call_component(
            "dragToComponent", [other._selector], timeout=timeout
        )

    # ============================================================
    # 缩放类
    # ============================================================

    def pinch_in(self, scale: float = 0.5,
                 timeout: Optional[float] = None) -> None:
        self._call_component("pinchIn", [scale], timeout=timeout)

    def pinch_out(self, scale: float = 1.5,
                  timeout: Optional[float] = None) -> None:
        self._call_component("pinchOut", [scale], timeout=timeout)

    # ============================================================
    # 滚动类
    # ============================================================

    def scroll_search(self, target, vertical: bool = True,
                      offset: Optional[int] = None) -> Optional['UiObject']:
        return self._driver.scroll_search(
            self._selector, target, vertical, offset
        )

    def scroll_to_top(self, speed: int = 600,
                      timeout: Optional[float] = None) -> None:
        self._call_component("scrollToTop", [speed], timeout=timeout)

    def scroll_to_bottom(self, speed: int = 600,
                         timeout: Optional[float] = None) -> None:
        self._call_component("scrollToBottom", [speed], timeout=timeout)

    # ============================================================
    # 关系选择器：返回新的 UiObject，持有衍生 SelectorSpec
    # ============================================================

    def child(self, **kwargs) -> 'UiObject':
        child_spec = build_selector(**kwargs)
        new_spec = SelectorSpec.with_relation(self._selector, 'child', child_spec)
        return UiObject(self._driver, new_spec)

    def sibling(self, **kwargs) -> 'UiObject':
        sibling_spec = build_selector(**kwargs)
        new_spec = SelectorSpec.with_relation(
            self._selector, 'sibling', sibling_spec
        )
        return UiObject(self._driver, new_spec)

    def after(self, **kwargs) -> 'UiObject':
        after_spec = build_selector(**kwargs)
        new_spec = SelectorSpec.with_relation(self._selector, 'after', after_spec)
        return UiObject(self._driver, new_spec)

    def before(self, **kwargs) -> 'UiObject':
        before_spec = build_selector(**kwargs)
        new_spec = SelectorSpec.with_relation(self._selector, 'before', before_spec)
        return UiObject(self._driver, new_spec)


def _to_rect(data: Any) -> Rect:
    """将设备端返回的坐标数据转为 Rect。

    设备端 getBounds 可能返回字典或列表，统一转换为 Rect。
    """
    if isinstance(data, dict):
        return Rect(
            left=int(data.get('left', 0)),
            top=int(data.get('top', 0)),
            right=int(data.get('right', 0)),
            bottom=int(data.get('bottom', 0)),
        )
    if isinstance(data, (list, tuple)) and len(data) >= 4:
        return Rect(
            left=int(data[0]), top=int(data[1]),
            right=int(data[2]), bottom=int(data[3]),
        )
    return Rect(left=0, top=0, right=0, bottom=0)
