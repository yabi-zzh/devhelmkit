# !/usr/bin/env python
# -*- coding: utf-8 -*-
"""UIViewer 性能排查日志工具。

默认关闭，避免高频 touch/MJPEG 刷屏。通过环境变量开启：
    DEVHELM_UIVIEWER_PERF=1    # 开启性能日志（INFO 级别单独输出）

设计目标：
- 触控链路：每次 touch 请求的事件数、每类 RPC 耗时、总耗时
- MJPEG 推流：周期性统计实际 fps、平均帧大小、平均帧间隔
- 截图采集：设备到帧的端到端延迟
所有埋点在关闭时是接近零开销的早返回。
"""
from __future__ import annotations

import logging
import os
import time
from typing import Optional

logger = logging.getLogger("devhelmkit.uiviewer.perf")

# 运行时读取一次；置 1/true/yes/on 开启。也可通过 set_enabled() 在运行时切换
# （例如 CLI 的 --perf 参数），因此用可变全局而非常量。
_ENABLED = os.environ.get("DEVHELM_UIVIEWER_PERF", "").strip().lower() in (
    "1", "true", "yes", "on"
)


def set_enabled(value: bool) -> None:
    """运行时开启/关闭性能日志（供 CLI --perf 等入口调用）。"""
    global _ENABLED
    _ENABLED = bool(value)


def enabled() -> bool:
    """性能日志是否开启。"""
    return _ENABLED


def log(msg: str, *args) -> None:
    """输出一条性能日志（仅在开启时）。"""
    if _ENABLED:
        logger.info(msg, *args)


def now_ms() -> float:
    """高精度毫秒时间戳（用于耗时测量）。"""
    return time.perf_counter() * 1000.0


class RateMeter:
    """周期性速率/延迟统计器，用于 MJPEG 等高频循环。

    每累计 window 个样本或超过 interval_s 秒输出一次聚合，避免逐帧刷屏。
    线程安全由调用方保证（通常单消费线程）。
    """

    def __init__(self, name: str, window: int = 60,
                 interval_s: float = 2.0):
        self._name = name
        self._window = window
        self._interval_s = interval_s
        self._count = 0
        self._bytes_total = 0
        self._last_ts: Optional[float] = None
        self._gap_total = 0.0
        self._gap_max = 0.0
        self._period_start = time.perf_counter()

    def tick(self, frame_bytes: int = 0) -> None:
        """记录一次事件（如推送一帧）；到达窗口时输出聚合统计。"""
        if not _ENABLED:
            return
        t = time.perf_counter()
        if self._last_ts is not None:
            gap = (t - self._last_ts) * 1000.0
            self._gap_total += gap
            if gap > self._gap_max:
                self._gap_max = gap
        self._last_ts = t
        self._count += 1
        self._bytes_total += frame_bytes

        elapsed = t - self._period_start
        if self._count >= self._window or elapsed >= self._interval_s:
            self._flush(elapsed)

    def _flush(self, elapsed: float) -> None:
        if self._count == 0 or elapsed <= 0:
            self._reset()
            return
        fps = self._count / elapsed
        avg_gap = self._gap_total / max(self._count - 1, 1)
        avg_kb = (self._bytes_total / self._count) / 1024.0
        logger.info(
            "[perf] %s: fps=%.1f frames=%d avg_gap=%.1fms max_gap=%.1fms avg_size=%.1fKB",
            self._name, fps, self._count, avg_gap, self._gap_max, avg_kb,
        )
        self._reset()

    def _reset(self) -> None:
        self._count = 0
        self._bytes_total = 0
        self._gap_total = 0.0
        self._gap_max = 0.0
        self._period_start = time.perf_counter()
        # 保留 _last_ts 以连续测量帧间隔