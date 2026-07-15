# !/usr/bin/env python
# -*- coding: utf-8 -*-
"""devhelmkit：跨平台 UI 自动化框架。

包根只导出稳定入口、公共契约与统一异常，平台实现延迟导入。
"""
from devhelmkit.entry import connect
from devhelmkit.core.base_driver import BaseDriver
from devhelmkit.core.base_component import BaseComponent
from devhelmkit.core.base_window import BaseWindow
from devhelmkit.core.selector_spec import SelectorSpec, build_selector
from devhelmkit.exceptions import (
    DevhelmError,
    DeviceNotFoundError,
    DeviceConnectError,
    PlatformNotSupportedError,
    DevhelmTimeoutError,
    RpcError,
    BackendObjectDroppedError,
    ComponentNotFoundError,
    ComponentDisappearedError,
    AgentError,
)

__all__ = [
    "connect",
    "BaseDriver",
    "BaseComponent",
    "BaseWindow",
    "SelectorSpec",
    "build_selector",
    "DevhelmError",
    "DeviceNotFoundError",
    "DeviceConnectError",
    "PlatformNotSupportedError",
    "DevhelmTimeoutError",
    "RpcError",
    "BackendObjectDroppedError",
    "ComponentNotFoundError",
    "ComponentDisappearedError",
    "AgentError",
]

__version__ = "0.4.1"
