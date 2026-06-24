# !/usr/bin/env python
# -*- coding: utf-8 -*-
"""OcrResult：OCR 识别结果数据结构。"""
from __future__ import annotations

from dataclasses import dataclass
from typing import List

from devhelmkit.model.rect import Rect


@dataclass
class OcrResult:
    """单条 OCR 识别结果。

    Attributes:
        text: 识别出的文本。
        bounds: 文本在屏幕中的坐标矩形。
        confidence: 置信度 0-1，越高越可信。
    """
    text: str
    bounds: Rect
    confidence: float

    @property
    def center(self):
        """返回文本中心点。"""
        return self.bounds.center


def filter_by_text(results: List[OcrResult], text: str,
                   fuzzy: bool = False) -> List[OcrResult]:
    """从 OCR 结果中筛选匹配文本。

    Args:
        results: OCR 结果列表。
        text: 目标文本。
        fuzzy: True 时子串匹配（忽略大小写），False 时精确匹配。
    """
    if fuzzy:
        target = text.lower()
        return [r for r in results if target in r.text.lower()]
    return [r for r in results if r.text == text]
