# !/usr/bin/env python
# -*- coding: utf-8 -*-
"""应用与窗口状态类型：AppState / WindowMode / ResizeDirection /
WindowState / OSType。"""
from dataclasses import dataclass
from enum import IntEnum
from typing import Optional, Tuple


class AppState(IntEnum):
    """应用状态。"""
    FOREGROUND = 0
    BACKGROUND = 1


class WindowMode(IntEnum):
    """窗口模式。"""
    FULLSCREEN = 0
    PRIMARY = 1
    SECONDARY = 2
    FLOATING = 3


class ResizeDirection(IntEnum):
    """窗口调整大小方向。"""
    LEFT = 0
    RIGHT = 1
    TOP = 2
    BOTTOM = 3
    TOP_LEFT = 4
    TOP_RIGHT = 5
    BOTTOM_LEFT = 6
    BOTTOM_RIGHT = 7


@dataclass
class WindowState:
    """窗口状态。"""
    window_id: str
    mode: WindowMode
    bounds: Optional[Tuple[int, int, int, int]] = None

    def is_fullscreen(self) -> bool:
        return self.mode == WindowMode.FULLSCREEN


class OSType:
    """操作系统类型（类常量风格）。"""
    OHOS = "OHOS"
    HMOS = "HMOS"
