# !/usr/bin/env python
# -*- coding: utf-8 -*-
"""鸿蒙控件查找后端。

子模块：
- selector_adapter：SelectorSpec → 设备端 On 查询条件转换
- component_finder：ComponentFinder 统一查找门面
- popup_handler：弹窗自动消除策略

仅支持 HarmonyOS 5.0.0+（API 12+），设备端 uitest 服务统一使用
api9+ 命名（Driver/Component/On）。
"""
