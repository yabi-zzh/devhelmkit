# !/usr/bin/env python
# -*- coding: utf-8 -*-
"""FormatString：带变量的模板字符串。

通过 __getattr__ 转发 template 字符串的方法，使其可像 str 一样使用。
"""


class FormatString:
    """格式化字符串（带变量的模板字符串）。"""

    def __init__(self, template: str, **kwargs):
        self.template = template
        self.variables = kwargs

    def __getattr__(self, item):
        # 转发 template 字符串的方法
        return getattr(self.template, item)

    def __str__(self):
        return self.template

    def __repr__(self):
        return self.template
