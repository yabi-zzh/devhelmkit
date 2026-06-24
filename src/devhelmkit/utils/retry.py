# !/usr/bin/env python
# -*- coding: utf-8 -*-
"""可控重试工具：仅用于连接阶段与无副作用流程。

RPC 运行时（控件查找、点击、输入等）默认不重试，避免副作用操作被重复执行。
"""
import logging
import time
from typing import Callable, Optional, Tuple, Type

logger = logging.getLogger(__name__)


def retry(func: Callable, retries: int = 3, delay: float = 1.0,
          backoff: float = 2.0,
          exceptions: Tuple[Type[BaseException], ...] = (Exception,),
          sleep: Optional[Callable[[float], None]] = None) -> object:
    """指数退避重试。

    Args:
        func: 待重试的可调用对象。
        retries: 最大重试次数（不含首次）。
        delay: 首次失败后等待秒数。
        backoff: 退避倍率，每次等待 = delay * backoff ** attempt。
        exceptions: 触发重试的异常类型。
        sleep: 自定义 sleep 函数，便于测试注入。

    Returns:
        func 的返回值。

    Raises:
        最后一次失败的异常。
    """
    _sleep = sleep or time.sleep
    attempt = 0
    while True:
        try:
            return func()
        except exceptions as exc:
            attempt += 1
            if attempt > retries:
                raise
            wait = delay * (backoff ** (attempt - 1))
            logger.debug("第 %d 次重试，等待 %.2fs：%s", attempt, wait, exc)
            _sleep(wait)
