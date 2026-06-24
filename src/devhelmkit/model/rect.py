# !/usr/bin/env python
# -*- coding: utf-8 -*-
"""Rect 与 Point：坐标矩形与坐标点。"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Tuple


@dataclass
class Point:
    """坐标点。"""
    x: int
    y: int

    def as_tuple(self) -> Tuple[int, int]:
        return (self.x, self.y)


@dataclass
class Rect:
    """矩形坐标。"""

    left: int
    top: int
    right: int
    bottom: int

    @property
    def width(self) -> int:
        return self.right - self.left

    @property
    def height(self) -> int:
        return self.bottom - self.top

    @property
    def center(self) -> Point:
        return Point(
            x=(self.left + self.right) // 2,
            y=(self.top + self.bottom) // 2
        )

    @property
    def top_left(self) -> Point:
        return Point(x=self.left, y=self.top)

    @property
    def bottom_right(self) -> Point:
        return Point(x=self.right, y=self.bottom)

    def contains(self, point: Point) -> bool:
        """判断点是否在矩形内。"""
        return (self.left <= point.x <= self.right and
                self.top <= point.y <= self.bottom)

    def as_tuple(self) -> Tuple[int, int, int, int]:
        return (self.left, self.top, self.right, self.bottom)
