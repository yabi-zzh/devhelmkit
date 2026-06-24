# !/usr/bin/env python
# -*- coding: utf-8 -*-
"""MatchPattern：匹配模式枚举。"""
from enum import IntEnum


class MatchPattern(IntEnum):
    """匹配模式，用于控件文本/属性的匹配方式。"""

    EQUALS = 0          # 精确匹配（默认）
    CONTAINS = 1        # 包含
    STARTS_WITH = 2     # 开头匹配
    ENDS_WITH = 3       # 结尾匹配
    REGEXP = 4          # 正则匹配
    REGEXP_ICASE = 5    # 正则匹配（忽略大小写）
