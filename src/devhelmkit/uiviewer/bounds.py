# !/usr/bin/env python
# -*- coding: utf-8 -*-
"""bounds 解析底层工具。

protocol 与 node_model 共享的唯一 bounds 解析实现，避免两套解析
行为漂移（负坐标支持、非法输入防御）。本模块不依赖 uiviewer 内
其他模块，protocol / node_model 均可安全导入而不产生循环。
"""
from __future__ import annotations

import re
from typing import Any, Dict, Optional

Bounds = Dict[str, int]

# 支持负坐标：折叠屏 / 多屏场景下控件 bounds 可能为负
_BOUNDS_RE = re.compile(r"\[(-?\d+),(-?\d+)\]\[(-?\d+),(-?\d+)\]")


def parse_bounds(raw: Any) -> Optional[Bounds]:
    """解析多种 bounds 形态为统一矩形，无法解析时返回 None。"""
    if isinstance(raw, str):
        match = _BOUNDS_RE.search(raw)
        if match:
            return {
                "left": int(match.group(1)),
                "top": int(match.group(2)),
                "right": int(match.group(3)),
                "bottom": int(match.group(4)),
            }
    if isinstance(raw, (list, tuple)) and len(raw) >= 4:
        try:
            return {
                "left": int(raw[0]),
                "top": int(raw[1]),
                "right": int(raw[2]),
                "bottom": int(raw[3]),
            }
        except (TypeError, ValueError):
            return None
    if isinstance(raw, dict):
        try:
            return {
                "left": int(raw.get("left", 0)),
                "top": int(raw.get("top", 0)),
                "right": int(raw.get("right", 0)),
                "bottom": int(raw.get("bottom", 0)),
            }
        except (TypeError, ValueError):
            return None
    return None
