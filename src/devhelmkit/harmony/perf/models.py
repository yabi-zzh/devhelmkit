# !/usr/bin/env python
# -*- coding: utf-8 -*-
"""性能监控数据类型。"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import List, Optional


@dataclass
class CpuCoreSample:
    """单核 CPU 采样。"""

    index: int
    usage: Optional[float]
    frequency: Optional[float]


@dataclass
class FpsSample:
    """FPS / 卡顿采样。"""

    fps: Optional[float]
    refresh_rate: Optional[float]
    jank_count: Optional[int]


@dataclass
class CpuSample:
    """CPU 采样。"""

    proc_usage: Optional[float]
    total_usage: Optional[float]
    cores: List[CpuCoreSample] = field(default_factory=list)


@dataclass
class GpuSample:
    """GPU 采样。"""

    load: Optional[float]


@dataclass
class MemorySample:
    """内存采样（单位 MB）。"""

    pss: Optional[float]
    heap_size: Optional[float]
    heap_alloc: Optional[float]
    mem_available: Optional[float]
    mem_total: Optional[float]


@dataclass
class NetworkSample:
    """网络采样（单位 KB/s）。"""

    down: Optional[float]
    up: Optional[float]


@dataclass
class PerfDataPoint:
    """单次性能采样点。"""

    timestamp: float
    time_label: str
    fps: FpsSample
    cpu: CpuSample
    gpu: GpuSample
    memory: MemorySample
    network: NetworkSample
