# !/usr/bin/env python
# -*- coding: utf-8 -*-
"""操作类型与上下文：ActionType / ActionTrackGroup / ActionContext / ActionContextStack。

ActionContextStack 持有 driver 的 weakref.proxy，避免循环引用。
"""
import weakref
from typing import List, Optional, Tuple

from devhelmkit.exceptions import DevhelmError


class ActionType:
    """操作类型常量。"""
    CLICK = "click"
    DOUBLE_CLICK = "double_click"
    LONG_CLICK = "long_click"
    SWIPE = "swipe"
    DRAG = "drag"
    PINCH_IN = "pinch_in"
    PINCH_OUT = "pinch_out"
    INPUT_TEXT = "input_text"
    PRESS_KEY = "press_key"
    MOUSE_SCROLL = "mouse_scroll"


class ActionTrackGroup:
    """操作路径信息。

    使用 __init__ 接收可变参数 *points_group，每个参数是 list[(x, y)]。
    """

    def __init__(self, *points_group):
        if len(points_group) <= 0:
            raise DevhelmError("No data for ActionTrackGroup")
        for points in points_group:
            if not isinstance(points, list):
                raise TypeError("Invalid point_list: %s" % points)
            for point in points:
                x, y = point  # 解包校验
        self._trace_group: List[List[Tuple[int, int]]] = list(points_group)

    def __getitem__(self, item):
        return self._trace_group[item]

    @property
    def first_track(self):
        if len(self._trace_group) < 1:
            raise DevhelmError("No data in this ActionTraceGroup")
        return self[0]


class ActionContext:
    """单次操作上下文。"""

    def __init__(self, level: int = 0):
        self.level = level
        self.reset()

    def reset(self):
        self.action_desc: Optional[str] = None
        self.action_type: Optional[str] = None
        self.pre_page = None
        self.next_page = None
        self.target_selector = None
        self.target_component = None
        self.target_recognize_page = None
        self.action_runnable = None
        self.allow_skip = False
        self.metrics = None

    def __repr__(self):
        return str(self.action_desc)


class ActionContextStack:
    """操作上下文栈。

    用于嵌套操作时管理上下文层级，向栈底传递页面/控件信息。
    持有 driver 的 weakref.proxy 避免循环引用，支持 with 语法，
    仅最顶层 action 通知 HookExtensionManager。
    """

    def __init__(self, driver):
        self.stack: List[ActionContext] = []
        self.default_context = ActionContext()
        self.driver = weakref.proxy(driver)
        self.last_action: Optional[ActionContext] = None

    def push(self) -> ActionContext:
        new_context = ActionContext(len(self.stack))
        self.stack.append(new_context)
        return new_context

    def pop(self, success: bool = True) -> Optional[ActionContext]:
        if len(self.stack) <= 0:
            return None
        current_action_ctx = self.stack.pop()
        self._set_upper_level_info()
        if len(self.stack) <= 0 and success and (not current_action_ctx.allow_skip):
            self.last_action = current_action_ctx
        return current_action_ctx

    def _set_upper_level_info(self):
        """向栈底传递页面/控件信息。"""
        if len(self.stack) < 1:
            return
        top_item = self.top_item
        for item in reversed(self.stack[:-1]):
            if item.pre_page is None:
                item.pre_page = top_item.pre_page
            if item.next_page is None:
                item.next_page = top_item.next_page
            item.target_recognize_page = top_item.target_recognize_page
            item.target_component = top_item.target_component
            item.target_selector = top_item.target_selector

    def __len__(self):
        return len(self.stack)

    @property
    def top_item(self) -> ActionContext:
        if len(self.stack) == 0:
            return self.default_context
        return self.stack[-1]

    @property
    def bottom_item(self) -> ActionContext:
        if len(self.stack) == 0:
            return self.default_context
        return self.stack[0]

    def enter_new_context(self, action_type: str, action_desc: str,
                          action_runnable=None, metrics=None):
        ctx = self.push()
        ctx.action_type = action_type
        ctx.action_desc = action_desc
        ctx.action_runnable = action_runnable
        ctx.metrics = metrics
        return self

    def __enter__(self) -> ActionContext:
        return self.top_item

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.pop(exc_val is None)
        return False
