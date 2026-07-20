# !/usr/bin/env python
# -*- coding: utf-8 -*-
"""VisionExtension：平台无关的图像识别与 OCR 命名空间。

只依赖 BaseDriver 公开接口（screenshot / click / get_component_bound），
所有平台（HarmonyOS / Android / iOS）均可直接复用。

调用方式：d.vision.find_image(...) / d.vision.ocr(...) / d.vision.click_text(...)
"""
from __future__ import annotations

import logging
import time
from typing import List, Optional, Tuple, Union, TYPE_CHECKING

from devhelmkit.core.vision.image_matcher import ImageMatcher
from devhelmkit.exceptions import DevhelmError
from devhelmkit.model.ocr_result import filter_by_text
from devhelmkit.model.rect import Rect

logger = logging.getLogger(__name__)

if TYPE_CHECKING:
    from PIL.Image import Image
    from devhelmkit.core.base_driver import BaseDriver
    from devhelmkit.model.ocr_result import OcrResult


class VisionExtension:
    """图像识别与 OCR 命名空间，挂在 driver.vision 上。

    通过持有 BaseDriver 引用调用底层截图、点击等能力，
    不依赖任何平台特有 API。
    """

    def __init__(self, driver: 'BaseDriver'):
        self._driver = driver

    # ============================================================
    # region 解析（平台无关，只依赖 BaseDriver 公开接口）
    # ============================================================

    def _resolve_region(self, region) -> Optional[Rect]:
        """将多种 region 类型统一解析为 Rect。

        支持：Rect / dict / (left,top,right,bottom) / 控件对象 / None
        控件对象通过 BaseDriver.get_component_bound() 获取边界。
        """
        if region is None:
            return None
        if isinstance(region, Rect):
            return region
        if isinstance(region, dict):
            return Rect(
                left=int(region.get('left', 0)),
                top=int(region.get('top', 0)),
                right=int(region.get('right', 0)),
                bottom=int(region.get('bottom', 0)),
            )
        if isinstance(region, (list, tuple)) and len(region) >= 4:
            return Rect(
                left=int(region[0]), top=int(region[1]),
                right=int(region[2]), bottom=int(region[3]),
            )
        # 控件对象：通过 BaseDriver 公开接口获取 bounds
        try:
            bounds = self._driver.get_component_bound(region)
            if bounds is not None:
                if isinstance(bounds, Rect):
                    return bounds
                if isinstance(bounds, (list, tuple)) and len(bounds) >= 4:
                    return Rect(
                        left=int(bounds[0]), top=int(bounds[1]),
                        right=int(bounds[2]), bottom=int(bounds[3]),
                    )
                if isinstance(bounds, dict):
                    return Rect(
                        left=int(bounds.get('left', 0)),
                        top=int(bounds.get('top', 0)),
                        right=int(bounds.get('right', 0)),
                        bottom=int(bounds.get('bottom', 0)),
                    )
        except Exception as e:
            logger.debug("解析控件 bounds 失败，返回 None: %s", e)
        return None

    def _get_timeout(self, timeout: Optional[float]) -> float:
        """获取有效超时：显式传入优先，否则取 driver 默认隐式等待。"""
        if timeout is not None:
            return timeout
        # BaseDriver 子类应维护 _implicit_wait 属性
        return getattr(self._driver, '_implicit_wait', 10.0)

    # ============================================================
    # 低延迟截图通道（轮询查找加速）
    # ============================================================

    def _try_begin_fast_capture(self) -> bool:
        """首轮未命中后启用低延迟截图通道，返回是否由本次启用。

        平台不支持或启用失败时返回 False，继续使用默认截图，不影响功能。
        """
        try:
            return bool(self._driver.begin_fast_capture())
        except Exception as e:
            logger.debug("启用快速截图通道异常，回退默认截图: %s", e)
            return False

    def _end_fast_capture(self, started: bool) -> None:
        """关闭本次启用的低延迟截图通道；未启用则不处理。"""
        if not started:
            return
        try:
            self._driver.end_fast_capture()
        except Exception as e:
            logger.debug("关闭快速截图通道异常（忽略）: %s", e)

    # ============================================================
    # 图像识别
    # ============================================================

    def find_image(self, template: Union[str, 'Image', bytes],
                   region=None, threshold: float = 0.8,
                   timeout: Optional[float] = None,
                   mode: str = "template",
                   min_match_count: int = 8,
                   scale_range: Optional[Tuple[float, float]] = None
                   ) -> Optional[Rect]:
        """查找图像位置。

        Args:
            template: 模板图片路径、PIL.Image 或 bytes
            region: 限定查找区域，None 为全屏
            threshold: 匹配阈值（0-1），低于此值视为未匹配
            timeout: 超时秒，None 走全局 implicitly_wait
            mode: template 或 feature
            min_match_count: feature 模式下的最少有效特征点数
            scale_range: 多尺度搜索缩放区间 (lo, hi)，None 用默认 3 档

        Returns:
            匹配位置 Rect，未找到返回 None
        """
        rect_region = self._resolve_region(region)
        deadline = time.monotonic() + self._get_timeout(timeout)
        interval = 0.1
        fast_started = False
        try:
            while True:
                source_img = self._driver.screenshot()
                result = ImageMatcher.match(
                    template=template, source=source_img,
                    threshold=threshold, region=rect_region,
                    mode=mode, min_match_count=min_match_count,
                    scale_range=scale_range,
                )
                if result is not None:
                    return result.rect
                if time.monotonic() >= deadline:
                    return None
                # 首轮未命中且仍需轮询时才启用快通道：立即命中的场景不付
                # 推流启动成本，需反复截图的等待场景享受低延迟帧。
                if not fast_started:
                    fast_started = self._try_begin_fast_capture()
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    return None
                time.sleep(min(interval, remaining))
                interval = min(interval * 2, 0.5)
        finally:
            self._end_fast_capture(fast_started)

    def touch_image(self, template: Union[str, 'Image', bytes],
                    region=None, threshold: float = 0.8,
                    timeout: Optional[float] = None,
                    mode: str = "template",
                    min_match_count: int = 8,
                    scale_range: Optional[Tuple[float, float]] = None) -> bool:
        """查找并点击图像。"""
        rect = self.find_image(
            template, region=region, threshold=threshold, timeout=timeout,
            mode=mode, min_match_count=min_match_count,
            scale_range=scale_range,
        )
        if rect is None:
            return False
        self._driver.click(rect.center.x, rect.center.y)
        return True

    def exists_image(self, template: Union[str, 'Image', bytes],
                     region=None, threshold: float = 0.8,
                     mode: str = "template",
                     min_match_count: int = 8,
                     scale_range: Optional[Tuple[float, float]] = None) -> bool:
        """检查图像是否存在（单次检测，不等待）。"""
        rect_region = self._resolve_region(region)
        source_img = self._driver.screenshot()
        result = ImageMatcher.match(
            template=template, source=source_img,
            threshold=threshold, region=rect_region,
            mode=mode, min_match_count=min_match_count,
            scale_range=scale_range,
        )
        return result is not None

    def wait_image(self, template: Union[str, 'Image', bytes],
                   region=None, threshold: float = 0.8,
                   timeout: float = 10,
                   mode: str = "template",
                   min_match_count: int = 8,
                   scale_range: Optional[Tuple[float, float]] = None) -> bool:
        """等待图像出现。"""
        rect = self.find_image(
            template, region=region, threshold=threshold, timeout=timeout,
            mode=mode, min_match_count=min_match_count,
            scale_range=scale_range,
        )
        return rect is not None

    # ============================================================
    # OCR
    # ============================================================

    def ocr(self, region=None,
            timeout: Optional[float] = None) -> List['OcrResult']:
        """识别屏幕文本。

        region 限定识别区域以提升速度（全屏 800ms+ -> 区域 100ms）。
        """
        from devhelmkit.core.vision.ocr_engine import OcrEngine

        rect_region = self._resolve_region(region)
        deadline = time.monotonic() + self._get_timeout(timeout)
        attempts = 0
        interval = 0.1
        fast_started = False
        try:
            while True:
                if attempts > 0 and time.monotonic() >= deadline:
                    return []
                attempts += 1
                try:
                    source_img = self._driver.screenshot()
                    return OcrEngine.recognize(source_img, region=rect_region)
                except DevhelmError:
                    raise
                except Exception as e:
                    logger.warning("OCR 调用异常: %s", e)
                    if not fast_started:
                        fast_started = self._try_begin_fast_capture()
                    remaining = deadline - time.monotonic()
                    if remaining <= 0:
                        return []
                    time.sleep(min(interval, remaining))
                    interval = min(interval * 2, 0.5)
        finally:
            self._end_fast_capture(fast_started)

    def find_text(self, text: str, region=None, fuzzy: bool = False,
                  index: int = 1,
                  timeout: Optional[float] = None) -> Optional['OcrResult']:
        """通过 OCR 查找屏幕文本位置。

        Args:
            text: 目标文本
            region: 限定查找区域
            fuzzy: True 子串匹配（忽略大小写），False 精确匹配
            index: 匹配到多个结果时选择第几个，1-based（默认 1=第一个）
            timeout: 超时秒，None 走全局 implicitly_wait
        """
        target_idx = index - 1
        if target_idx < 0:
            raise DevhelmError("index 必须 >= 1，当前: %d" % index)

        deadline = time.monotonic() + self._get_timeout(timeout)
        attempts = 0
        interval = 0.1
        fast_started = False
        try:
            while True:
                if attempts > 0 and time.monotonic() >= deadline:
                    return None
                attempts += 1
                remaining = max(0.0, deadline - time.monotonic())
                results = self.ocr(region=region, timeout=remaining)
                matched = filter_by_text(results, text, fuzzy=fuzzy)
                if matched and len(matched) > target_idx:
                    return matched[target_idx]
                if not fast_started:
                    fast_started = self._try_begin_fast_capture()
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    return None
                time.sleep(min(interval, remaining))
                interval = min(interval * 2, 0.5)
        finally:
            self._end_fast_capture(fast_started)

    def click_text(self, text: str, region=None, fuzzy: bool = False,
                   index: int = 1,
                   timeout: Optional[float] = None) -> bool:
        """通过 OCR 查找并点击文本。

        Args:
            text: 目标文本
            region: 限定查找区域
            fuzzy: True 子串匹配（忽略大小写），False 精确匹配
            index: 匹配到多个结果时点击第几个，1-based（默认 1=第一个）
            timeout: 超时秒，None 走全局 implicitly_wait
        """
        result = self.find_text(text, region=region, fuzzy=fuzzy,
                                index=index, timeout=timeout)
        if result is None:
            return False
        self._driver.click(result.center.x, result.center.y)
        return True