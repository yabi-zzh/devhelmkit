# !/usr/bin/env python
# -*- coding: utf-8 -*-
"""Runnable：可执行任务封装。"""


class Runnable:
    """延迟执行任务封装（函数 + 参数）。"""

    def __init__(self, func, args, kwargs):
        self.func = func
        self.args = args
        self.kwargs = kwargs

    def run(self):
        self.func(*self.args, **self.kwargs)

    def __str__(self):
        return "%s%s-%s" % (self.func.__name__, self.args, self.kwargs)
