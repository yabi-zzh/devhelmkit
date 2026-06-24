# !/usr/bin/env python
# -*- coding: utf-8 -*-
"""超时与状态轮询工具。"""
import time
from typing import Callable, Optional, Tuple, Type

from devhelmkit.exceptions import DevhelmTimeoutError


def wait_for(predicate: Callable[[], bool], timeout: float = 10.0,
             interval: float = 0.5,
             sleep: Optional[Callable[[float], None]] = None) -> bool:
    """轮询等待条件成立。

    Args:
        predicate: 返回 bool 的可调用对象，True 表示条件满足。
        timeout: 总超时秒数。
        interval: 轮询间隔秒数。
        sleep: 自定义 sleep 函数，便于测试注入。

    Returns:
        True 若在超时内条件成立，否则 False。
    """
    _sleep = sleep or time.sleep
    deadline = time.monotonic() + timeout
    while True:
        if predicate():
            return True
        if time.monotonic() >= deadline:
            return False
        _sleep(min(interval, max(0.0, deadline - time.monotonic())))


def wait_for_raise(predicate: Callable[[], bool], timeout: float = 10.0,
                    interval: float = 0.5,
                    exceptions: Tuple[Type[BaseException], ...] = (Exception,),
                    sleep: Optional[Callable[[float], None]] = None) -> bool:
    """轮询等待条件成立，predicate 抛异常时视为未满足继续轮询。

    超时后返回 False 而非抛异常，调用方可自行决定是否抛 DevhelmTimeoutError。
    """
    _sleep = sleep or time.sleep
    deadline = time.monotonic() + timeout
    while True:
        try:
            if predicate():
                return True
        except exceptions:
            pass
        if time.monotonic() >= deadline:
            return False
        _sleep(min(interval, max(0.0, deadline - time.monotonic())))


def ensure_timeout(timeout: Optional[float], default: float) -> float:
    """规范化超时：None 取默认值，负数视为 0。"""
    if timeout is None:
        return default
    return max(0.0, float(timeout))


def raise_on_timeout(timeout: float, condition_desc: str) -> None:
    """显式抛 DevhelmTimeoutError。"""
    raise DevhelmTimeoutError("等待超时（%.2fs）：%s" % (timeout, condition_desc))
