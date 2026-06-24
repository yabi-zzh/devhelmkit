# !/usr/bin/env python
# -*- coding: utf-8 -*-
"""AndroidDriver：Android 平台占位实现。

当前不引入 AndroidUiObject、AdbDevice、uiautomator2 适配层。
connect(platform="android") 由 entry.py 统一抛 PlatformNotSupportedError，
不会到达本类。

支持 Android 时，在此实现 BaseDriver 契约，并解除 entry.py 中的平台拦截。
"""
from devhelmkit.core.base_driver import BaseDriver


class AndroidDriver(BaseDriver):
    """Android 平台占位驱动，未实现任何契约方法。"""

    pass
