# !/usr/bin/env python
# -*- coding: utf-8 -*-
"""输入设备与手势类型：InputDevice / MouseButton / GestureStep /
TouchPadSwipeOptions / GestureAction。"""
from dataclasses import dataclass, field
from enum import IntEnum
from typing import List, Optional


class InputDevice(IntEnum):
    """输入设备类型。"""
    TOUCH = 0
    MOUSE = 1
    PEN = 2
    KNUCKLE = 3
    TOUCHPAD = 4


class MouseButton(IntEnum):
    """鼠标按键。"""
    LEFT = 0
    RIGHT = 1
    MIDDLE = 2


@dataclass
class GestureStep:
    """手势步骤。"""
    action: str
    x: int
    y: int
    duration: float = 0.0


@dataclass
class TouchPadSwipeOptions:
    """触控板滑动选项。"""
    speed: Optional[int] = None
    step_length: Optional[int] = None


@dataclass
class GestureAction:
    """手势动作。"""
    steps: List[GestureStep] = field(default_factory=list)
    input_device: InputDevice = InputDevice.TOUCH

    def add_step(self, action: str, x: int, y: int, duration: float = 0.0):
        """添加手势步骤。"""
        self.steps.append(GestureStep(action=action, x=x, y=y, duration=duration))
