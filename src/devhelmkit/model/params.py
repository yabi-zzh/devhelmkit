# !/usr/bin/env python
# -*- coding: utf-8 -*-
"""UI 操作参数类型：WindowFilter / UiParam / DeviceType / InputTextMode。"""
from dataclasses import dataclass
from enum import IntEnum
from typing import Optional


class InputTextMode(IntEnum):
    """输入文本模式。"""
    DEFAULT = 0
    CLEAR_FIRST = 1
    APPEND = 2


class DeviceType(IntEnum):
    """设备类型。"""
    PHONE = 0
    TABLET = 1
    TV = 2
    WATCH = 3
    CAR = 4


@dataclass
class WindowFilter:
    """窗口过滤条件。"""
    bundle: Optional[str] = None
    title: Optional[str] = None
    display_id: Optional[int] = None


class UiParam:
    """UI 操作控制相关常量（类常量风格）。"""

    NORMAL = "normal"
    LONG = "long"
    DOUBLE = "double"
    LEFT = "LEFT"
    RIGHT = "RIGHT"
    UP = "UP"
    DOWN = "DOWN"
