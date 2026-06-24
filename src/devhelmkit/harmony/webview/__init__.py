# !/usr/bin/env python
# -*- coding: utf-8 -*-
"""webview 自动化子模块。

提供 webview 页面级自动化能力，基于 selenium webdriver。

使用方式：
    from devhelmkit.harmony.webview import WebViewDriver

    wv = WebViewDriver(device)
    wv.connect("com.huawei.hmos.browser")
    wv.driver.get("https://www.baidu.com")
    wv.close()
"""
from devhelmkit.harmony.webview.webview_driver import WebViewDriver

__all__ = ["WebViewDriver"]
