# !/usr/bin/env python
# -*- coding: utf-8 -*-
"""OcrEngine：基于 RapidOCR 的 OCR 识别封装（平台无关）。

依赖：rapidocr-onnxruntime（含 onnxruntime + 模型）
模型随包分发，离线可用。

速度优化：
- region 限定识别区域，避免全屏 OCR（全屏 800ms+ → 区域 100ms）
- 引擎单例缓存，避免重复加载模型（模型加载 ~2s）
"""
from __future__ import annotations

import io
from typing import List, Optional, Union, TYPE_CHECKING

from devhelmkit.exceptions import DevhelmError
from devhelmkit.model.ocr_result import OcrResult
from devhelmkit.model.rect import Rect

if TYPE_CHECKING:
    from PIL.Image import Image


class OcrEngine:
    """RapidOCR 封装，单例缓存引擎实例。"""

    _engine = None  # RapidOCR 单例，避免重复加载模型

    @classmethod
    def _get_engine(cls):
        """懒加载 RapidOCR 引擎，未安装抛友好错误。"""
        if cls._engine is None:
            try:
                from rapidocr_onnxruntime import RapidOCR
            except ImportError as e:
                raise DevhelmError(
                    "OCR 依赖未安装，请执行 pip install devhelmkit[ocr]"
                ) from e
            cls._engine = RapidOCR(use_angle_cls=False)
        return cls._engine

    @classmethod
    def recognize(cls, image: Union[str, "Image", bytes],
                  region: Optional[Rect] = None) -> List[OcrResult]:
        """识别图片中的文本。

        Args:
            image: 图片（路径 / PIL.Image / bytes）
            region: 限定识别区域，在 PIL.Image 上裁剪后再送 OCR

        Returns:
            OcrResult 列表，每个元素含 text / bounds / confidence
        """
        engine = cls._get_engine()

        # region 裁剪
        if region is not None:
            image = cls._crop_region(image, region)

        img_array = cls._to_ndarray(image)
        result, _elapse = engine(img_array)

        if not result:
            return []

        return cls._parse_result(result, region)

    @classmethod
    def _crop_region(cls, image: Union[str, "Image", bytes],
                     region: Rect) -> "Image":
        """在 PIL.Image 上裁剪区域。"""
        pil_img = cls._to_pil(image)
        return pil_img.crop((region.left, region.top, region.right, region.bottom))

    @classmethod
    def _to_pil(cls, image: Union[str, "Image", bytes]) -> "Image":
        """统一转为 PIL.Image。"""
        from PIL import Image as PILImage

        if isinstance(image, str):
            return PILImage.open(image)
        if isinstance(image, bytes):
            return PILImage.open(io.BytesIO(image))
        if hasattr(image, "save"):
            return image
        raise DevhelmError("不支持的图片类型: %s" % type(image).__name__)

    @classmethod
    def _to_ndarray(cls, image: Union[str, "Image", bytes]):
        """PIL.Image / 路径 / bytes 转 numpy ndarray（RGB）。"""
        import numpy as np

        pil_img = cls._to_pil(image)
        if pil_img.mode != "RGB":
            pil_img = pil_img.convert("RGB")
        return np.array(pil_img)

    @classmethod
    def _parse_result(cls, result, region: Optional[Rect]) -> List[OcrResult]:
        """解析 RapidOCR 返回结果，兼容新旧版本格式。

        旧版（v1.x）：[[dt_boxes, txt, score], ...]
            dt_boxes: [[x1,y1], [x2,y2], [x3,y3], [x4,y4]]  # 左上→右上→右下→左下
        新版（v3.x dict）：[{dt_boxes, rec_txt, score}, ...]
        """
        ocr_results = []
        for item in result:
            if isinstance(item, dict):
                # 新版 dict 格式
                dt_boxes = item.get("dt_boxes") or item.get("boxes")
                text = item.get("rec_txt") or item.get("text") or ""
                score = item.get("score") or item.get("rec_score") or 0.0
            elif isinstance(item, (list, tuple)) and len(item) >= 3:
                # 旧版 list 格式
                dt_boxes = item[0]
                text = item[1]
                score = item[2]
            else:
                continue

            if not dt_boxes or len(dt_boxes) < 4:
                continue

            bounds = cls._boxes_to_rect(dt_boxes)

            # region 偏移还原
            if region is not None:
                bounds = Rect(
                    left=bounds.left + region.left,
                    top=bounds.top + region.top,
                    right=bounds.right + region.left,
                    bottom=bounds.bottom + region.top,
                )

            try:
                confidence = float(score)
            except (TypeError, ValueError):
                confidence = 0.0

            ocr_results.append(OcrResult(
                text=text,
                bounds=bounds,
                confidence=confidence,
            ))
        return ocr_results

    @staticmethod
    def _boxes_to_rect(dt_boxes) -> Rect:
        """4 点框转 Rect（取外接矩形）。"""
        xs = [p[0] for p in dt_boxes]
        ys = [p[1] for p in dt_boxes]
        return Rect(
            left=int(min(xs)),
            top=int(min(ys)),
            right=int(max(xs)),
            bottom=int(max(ys)),
        )