# !/usr/bin/env python
# -*- coding: utf-8 -*-
"""BaseWindow：跨平台窗口对象契约。"""
from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any, Dict, List, Tuple


class BaseWindow(ABC):
    """窗口契约，平台实现需继承并实现全部抽象方法。"""

    @property
    @abstractmethod
    def size(self) -> Tuple[int, int]:
        """窗口大小 (width, height)。"""

    @property
    @abstractmethod
    def info(self) -> Dict[str, Any]:
        """窗口信息。"""

    @abstractmethod
    def get_windows(self) -> List['BaseWindow']:
        """所有窗口对象列表。"""
