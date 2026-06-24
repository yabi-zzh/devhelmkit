# !/usr/bin/env python
# -*- coding: utf-8 -*-
"""ImageMatcher：基于 OpenCV 的图像匹配（平台无关）。

默认使用模板匹配；feature 模式用于目标存在缩放、旋转或轻微透视变化的场景。

依赖：opencv-python-headless + numpy
"""
from __future__ import annotations

import io
import logging
from typing import Optional, Union, TYPE_CHECKING

from devhelmkit.exceptions import DevhelmError
from devhelmkit.model.rect import Rect

if TYPE_CHECKING:
    from PIL.Image import Image

logger = logging.getLogger(__name__)


class MatchResult:
    """匹配结果。"""

    def __init__(self, rect: Rect, confidence: float, scale: float = 1.0):
        self.rect = rect
        self.confidence = confidence
        self.scale = scale

    def __repr__(self) -> str:
        return "MatchResult(rect=%s, confidence=%.3f, scale=%.2f)" % (
            self.rect.as_tuple(), self.confidence, self.scale
        )


class ImageMatcher:
    """OpenCV 图像匹配器。

    所有方法均为类方法，无状态，调用前自动校验依赖。
    """

    _CV2_AVAILABLE = None  # 依赖缓存，避免重复检查

    @classmethod
    def _ensure_cv2(cls):
        """校验 OpenCV 可用，懒加载。"""
        if cls._CV2_AVAILABLE is None:
            try:
                __import__("cv2")
                __import__("numpy")
                cls._CV2_AVAILABLE = True
            except ImportError as e:
                raise DevhelmError(
                    "图像识别依赖未安装，请执行 pip install devhelmkit[cv]"
                ) from e
        elif not cls._CV2_AVAILABLE:
            raise DevhelmError("图像识别依赖未安装，请执行 pip install devhelmkit[cv]")

    @classmethod
    def _to_cv2(cls, image: Union[str, "Image", bytes]):
        """将多种图片格式转为 OpenCV BGR ndarray。"""
        cls._ensure_cv2()
        import cv2
        import numpy as np

        if isinstance(image, str):
            img = cv2.imdecode(np.fromfile(image, dtype=np.uint8), -1)
            if img is None:
                raise DevhelmError("模板图片读取失败: %s" % image)
        elif isinstance(image, bytes):
            img_arr = np.frombuffer(image, dtype=np.uint8)
            img = cv2.imdecode(img_arr, cv2.IMREAD_UNCHANGED)
            if img is None:
                raise DevhelmError("模板图片解码失败（bytes 无效）")
        elif hasattr(image, "save"):
            buf = io.BytesIO()
            image.convert("RGB").save(buf, format="PNG")
            img_arr = np.frombuffer(buf.getvalue(), dtype=np.uint8)
            img = cv2.imdecode(img_arr, cv2.IMREAD_COLOR)
            if img is None:
                raise DevhelmError("PIL 图片转 OpenCV 失败")
        else:
            raise DevhelmError("不支持的图片类型: %s" % type(image).__name__)
        return cls._normalize_cv2_image(img)

    @classmethod
    def _normalize_cv2_image(cls, image):
        """统一 OpenCV 图片通道，便于后续匹配。"""
        import cv2

        if len(image.shape) == 2:
            return cv2.cvtColor(image, cv2.COLOR_GRAY2BGR)
        if image.shape[2] == 4:
            return cv2.cvtColor(image, cv2.COLOR_BGRA2BGR)
        return image

    @classmethod
    def match(cls, template: Union[str, "Image", bytes],
              source: Union[str, "Image", bytes],
              threshold: float = 0.8,
              region: Optional[Rect] = None,
              multi_scale: bool = True,
              mode: str = "template",
              min_match_count: int = 8) -> Optional[MatchResult]:
        """在 source 中查找 template。

        Args:
            template: 模板图（路径 / PIL.Image / bytes）
            source: 背景图（路径 / PIL.Image / bytes）
            threshold: 匹配阈值 0-1，低于此值视为未匹配
            region: 限定查找区域
            multi_scale: template 模式下启用多尺度兜底
            mode: template 或 feature
            min_match_count: feature 模式下的最少有效特征点数

        Returns:
            MatchResult 或 None
        """
        cls._ensure_cv2()
        src = cls._to_cv2(source)
        tpl = cls._to_cv2(template)

        offset_left = 0
        offset_top = 0
        if region is not None:
            offset_left = region.left
            offset_top = region.top
            src = src[region.top:region.bottom, region.left:region.right]
            if src.size == 0:
                return None

        match_mode = mode.strip().lower()
        if match_mode == "template":
            result = cls._match_template(src, tpl, threshold, multi_scale)
        elif match_mode == "feature":
            result = cls._match_feature(src, tpl, threshold, min_match_count)
        else:
            raise DevhelmError("不支持的图像匹配模式: %s，支持 template / feature" % mode)

        if result is not None and region is not None:
            result.rect = Rect(
                left=result.rect.left + offset_left,
                top=result.rect.top + offset_top,
                right=result.rect.right + offset_left,
                bottom=result.rect.bottom + offset_top,
            )
        return result

    @classmethod
    def _match_template(cls, src, tpl, threshold: float,
                        multi_scale: bool) -> Optional[MatchResult]:
        """模板匹配。"""
        result = cls._match_single_scale(src, tpl, threshold)
        if result is not None and cls._color_check(src, tpl, result.rect):
            return result
        if not multi_scale:
            return None
        result = cls._match_multi_scale(src, tpl, threshold)
        if result is None:
            return None
        if not cls._color_check(src, tpl, result.rect):
            return None
        return result

    @classmethod
    def _match_single_scale(cls, src, tpl, threshold) -> Optional[MatchResult]:
        """单尺度灰度匹配。"""
        import cv2

        src_gray = cv2.cvtColor(src, cv2.COLOR_BGR2GRAY)
        tpl_gray = cv2.cvtColor(tpl, cv2.COLOR_BGR2GRAY)
        res = cv2.matchTemplate(src_gray, tpl_gray, cv2.TM_CCOEFF_NORMED)
        _, max_val, _, max_loc = cv2.minMaxLoc(res)
        if max_val < threshold:
            return None
        h, w = tpl.shape[:2]
        rect = Rect(left=max_loc[0], top=max_loc[1],
                    right=max_loc[0] + w, bottom=max_loc[1] + h)
        return MatchResult(rect=rect, confidence=float(max_val), scale=1.0)

    @classmethod
    def _match_multi_scale(cls, src, tpl, threshold) -> Optional[MatchResult]:
        """多尺度灰度匹配（0.9-1.1，3 级）。"""
        import cv2

        src_gray = cv2.cvtColor(src, cv2.COLOR_BGR2GRAY)
        tpl_gray = cv2.cvtColor(tpl, cv2.COLOR_BGR2GRAY)
        h_tpl, w_tpl = tpl_gray.shape

        best = None
        for scale in (0.9, 1.0, 1.1):
            if scale != 1.0:
                resized = cv2.resize(src_gray, None, fx=scale, fy=scale,
                                     interpolation=cv2.INTER_AREA)
            else:
                resized = src_gray
            h_img, w_img = resized.shape
            if h_tpl > h_img or w_tpl > w_img:
                continue
            res = cv2.matchTemplate(resized, tpl_gray, cv2.TM_CCOEFF_NORMED)
            _, max_val, _, max_loc = cv2.minMaxLoc(res)
            if best is None or max_val > best.confidence:
                x = int(max_loc[0] / scale)
                y = int(max_loc[1] / scale)
                rect = Rect(left=x, top=y, right=x + w_tpl, bottom=y + h_tpl)
                best = MatchResult(rect=rect, confidence=float(max_val), scale=scale)
            if max_val >= threshold:
                break
        if best is None or best.confidence < threshold:
            return None
        return best

    @classmethod
    def _match_feature(cls, src, tpl, threshold: float,
                       min_match_count: int) -> Optional[MatchResult]:
        """特征匹配。"""
        import cv2
        import numpy as np

        src_gray = cv2.cvtColor(src, cv2.COLOR_BGR2GRAY)
        tpl_gray = cv2.cvtColor(tpl, cv2.COLOR_BGR2GRAY)
        detector, matcher, matcher_kind = cls._create_feature_tools(cv2)

        tpl_keypoints, tpl_descriptors = detector.detectAndCompute(tpl_gray, None)
        src_keypoints, src_descriptors = detector.detectAndCompute(src_gray, None)
        if tpl_descriptors is None or src_descriptors is None:
            return None
        if len(tpl_keypoints) < min_match_count or len(src_keypoints) < min_match_count:
            return None

        if matcher_kind == "flann":
            tpl_descriptors = tpl_descriptors.astype(np.float32)
            src_descriptors = src_descriptors.astype(np.float32)

        matches = cls._collect_good_matches(matcher, tpl_descriptors, src_descriptors)
        if len(matches) < min_match_count:
            return None

        tpl_points = np.float32([tpl_keypoints[m.queryIdx].pt for m in matches]).reshape(-1, 1, 2)
        src_points = np.float32([src_keypoints[m.trainIdx].pt for m in matches]).reshape(-1, 1, 2)
        try:
            homography, mask = cv2.findHomography(tpl_points, src_points, cv2.RANSAC, 5.0)
        except cv2.error:
            return None
        if homography is None or mask is None:
            return None

        inliers = int(mask.ravel().sum())
        if inliers < min_match_count:
            return None
        inlier_ratio = inliers / max(len(matches), 1)
        confidence = float(min(1.0, inlier_ratio))
        if confidence < threshold:
            return None

        h_tpl, w_tpl = tpl_gray.shape
        corners = np.float32([[0, 0], [0, h_tpl - 1], [w_tpl - 1, h_tpl - 1], [w_tpl - 1, 0]]).reshape(-1, 1, 2)
        try:
            transformed = cv2.perspectiveTransform(corners, homography)
        except cv2.error:
            return None

        xs = transformed[:, 0, 0]
        ys = transformed[:, 0, 1]
        left = max(0, int(np.floor(xs.min())))
        top = max(0, int(np.floor(ys.min())))
        right = min(src.shape[1], int(np.ceil(xs.max())))
        bottom = min(src.shape[0], int(np.ceil(ys.max())))
        if right <= left or bottom <= top:
            return None

        matched_area = (right - left) * (bottom - top)
        template_area = w_tpl * h_tpl
        if matched_area < template_area * 0.2 or matched_area > template_area * 8:
            return None

        return MatchResult(
            rect=Rect(left=left, top=top, right=right, bottom=bottom),
            confidence=confidence,
            scale=1.0,
        )

    @classmethod
    def _create_feature_tools(cls, cv2):
        """创建特征提取器和匹配器。"""
        if hasattr(cv2, "SIFT_create"):
            detector = cv2.SIFT_create()
            matcher = cv2.FlannBasedMatcher(
                {"algorithm": 1, "trees": 5},
                {"checks": 50},
            )
            return detector, matcher, "flann"

        detector = cv2.ORB_create(nfeatures=1000)
        matcher = cv2.BFMatcher(cv2.NORM_HAMMING, crossCheck=False)
        return detector, matcher, "bf"

    @classmethod
    def _collect_good_matches(cls, matcher, tpl_descriptors, src_descriptors):
        """筛选稳定特征匹配点。"""
        try:
            raw_matches = matcher.knnMatch(tpl_descriptors, src_descriptors, k=2)
        except Exception as e:
            logger.debug("特征匹配 knnMatch 失败，视为无匹配: %s", e)
            return []

        good_matches = []
        for pair in raw_matches:
            if len(pair) < 2:
                continue
            first, second = pair
            if first.distance < 0.75 * second.distance:
                good_matches.append(first)
        return good_matches

    @classmethod
    def _color_check(cls, src, tpl, rect: Rect, threshold: float = 0.7) -> bool:
        """颜色二次校验，防止灰度匹配误判。

        裁剪源图匹配区域与模板缩放对齐后，BGR 三通道分别 matchTemplate 取均值。
        """
        import cv2
        import numpy as np

        h_tpl, w_tpl = tpl.shape[:2]
        if (rect.left < 0 or rect.top < 0 or
                rect.right > src.shape[1] or rect.bottom > src.shape[0]):
            return False
        region = src[rect.top:rect.bottom, rect.left:rect.right]
        if region.shape[0] != h_tpl or region.shape[1] != w_tpl:
            region = cv2.resize(region, (w_tpl, h_tpl),
                                interpolation=cv2.INTER_AREA)
        similarities = []
        for i in range(3):
            res = cv2.matchTemplate(region[:, :, i], tpl[:, :, i],
                                    cv2.TM_CCOEFF_NORMED)
            _, max_val, _, _ = cv2.minMaxLoc(res)
            similarities.append(max_val)
        score = float(np.mean(similarities))
        return score >= threshold