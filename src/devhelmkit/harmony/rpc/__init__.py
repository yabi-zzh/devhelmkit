# !/usr/bin/env python
# -*- coding: utf-8 -*-
"""鸿蒙 RPC 协议与远程对象管理。

子模块：
- proxy_v2：bin 模式 RPC 传输
- remote_object：远程对象生命周期管理
- client：RPC 客户端，设备端 API 调用与返回值处理

仅支持 HarmonyOS 5.0.0+（API 12+），设备端 uitest 服务统一使用
api9+ 命名（Driver/Component/On），不再兼容 api8 旧命名。
"""
