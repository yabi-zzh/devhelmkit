# !/usr/bin/env python
# -*- coding: utf-8 -*-
"""显示器相关类型：DisplayRotation / DisplayInfo。"""
from dataclasses import dataclass
from enum import IntEnum
from typing import Tuple


class DisplayRotation(IntEnum):
    """屏幕旋转状态。"""
    PORTRAIT = 0
    LANDSCAPE = 1
    REVERSE_PORTRAIT = 2
    REVERSE_LANDSCAPE = 3


@dataclass
class DisplayInfo:
    """显示器信息。"""
    display_id: int
    width: int
    height: int
    density: int
    rotation: DisplayRotation = DisplayRotation.PORTRAIT

    @property
    def size(self) -> Tuple[int, int]:
        return (self.width, self.height)

    def is_portrait(self) -> bool:
        return self.rotation in (DisplayRotation.PORTRAIT,
                                 DisplayRotation.REVERSE_PORTRAIT)
