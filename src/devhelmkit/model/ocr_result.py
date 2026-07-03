# !/usr/bin/env python
# -*- coding: utf-8 -*-
"""OcrResult：OCR 识别结果数据结构。"""
from __future__ import annotations

from dataclasses import dataclass
from difflib import SequenceMatcher
import re
from typing import List
import unicodedata

from devhelmkit.model.rect import Rect


_OCR_IGNORED_TEXT_PATTERN = re.compile(r"[\s\u200b\u200c\u200d\ufeff]+")


def _normalize_ocr_text(text: str) -> str:
    return _OCR_IGNORED_TEXT_PATTERN.sub(
        "", unicodedata.normalize("NFKC", text)
    ).casefold()


def _is_fuzzy_text_match(candidate: str, target: str) -> bool:
    candidate_text = _normalize_ocr_text(candidate)
    target_text = _normalize_ocr_text(target)
    if not candidate_text or not target_text:
        return False
    if target_text in candidate_text:
        return True
    if len(candidate_text) < 3 or len(target_text) < 3:
        return False

    max_length = max(len(candidate_text), len(target_text))
    threshold = 0.75 if max_length <= 8 else 0.72
    return SequenceMatcher(None, candidate_text, target_text).ratio() >= threshold


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
        fuzzy: True 时先做归一化子串匹配，再用相似度兜底；False 时精确匹配。
    """
    if fuzzy:
        return [r for r in results if _is_fuzzy_text_match(r.text, text)]
    return [r for r in results if r.text == text]
