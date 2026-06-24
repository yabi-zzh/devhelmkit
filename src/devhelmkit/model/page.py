# !/usr/bin/env python
# -*- coding: utf-8 -*-
"""页面信息类型。"""
from dataclasses import dataclass
from typing import Optional


@dataclass
class BasicPage:
    """页面信息。"""
    screenshot_path: Optional[str] = None
    layout_path: Optional[str] = None
    display_id: int = 0
