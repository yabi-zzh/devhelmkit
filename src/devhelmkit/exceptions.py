# !/usr/bin/env python
# -*- coding: utf-8 -*-
"""统一异常体系。

异常类型单文件定义，避免各平台重复定义。命名约束：
- DevhelmTimeoutError 不与 Python 内建 TimeoutError 同名冲突；
- DeviceConnectError 作为设备连接失败的唯一命名；
- ComponentNotFoundError 作为控件未找到的唯一命名。
"""
from typing import Optional


class DevhelmError(Exception):
    """框架基础异常，所有 devhelmkit 异常的根。"""


class DeviceNotFoundError(DevhelmError):
    """未检测到可连接设备。"""


class DeviceConnectError(DevhelmError):
    """设备连接失败（hdc 连接、RPC socket 建立失败等）。"""


class PlatformNotSupportedError(DevhelmError):
    """平台不支持（如阶段一调用 connect(platform="android")）。"""


class DevhelmTimeoutError(DevhelmError):
    """框架操作超时，刻意不与 Python 内建 TimeoutError 同名。"""


class RpcError(DevhelmError):
    """RPC 通信异常，携带 api 与原始 reply 上下文便于诊断。"""

    def __init__(self, message: str, api: Optional[str] = None,
                 reply: Optional[str] = None):
        super().__init__(message)
        self.api = api
        self.reply = reply


class BackendObjectDroppedError(RpcError):
    """设备端远程对象引用已失效，需恢复后重试。"""


class ComponentNotFoundError(DevhelmError):
    """控件未找到。"""


class ComponentDisappearedError(ComponentNotFoundError):
    """控件查找到后又消失。"""


class AgentError(DevhelmError):
    """设备端 uitest / Agent 异常（进程崩溃、版本不支持等）。"""
