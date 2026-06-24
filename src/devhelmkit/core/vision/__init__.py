# !/usr/bin/env python
# -*- coding: utf-8 -*-
"""core.vision 子模块：平台无关的图像识别与 OCR 能力。

按需安装依赖：
    pip install devhelmkit[cv]      # 图像识别
    pip install devhelmkit[ocr]     # 图像识别 + OCR
    pip install devhelmkit[all]     # 全部能力
"""
from devhelmkit.core.vision.image_matcher import ImageMatcher, MatchResult
from devhelmkit.core.vision.ocr_engine import OcrEngine
from devhelmkit.core.vision.vision_extension import VisionExtension

__all__ = ["ImageMatcher", "MatchResult", "OcrEngine", "VisionExtension"]