# !/usr/bin/env python
# -*- coding: utf-8 -*-
"""UiWindow：HarmonyOS 平台窗口对象。

窗口操作能力较控件操作少，当前阶段保留基础结构，
后续按需补充基于 Driver.findWindow 的实现。
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional, Tuple, TYPE_CHECKING

from devhelmkit.core.base_window import BaseWindow

if TYPE_CHECKING:
    from devhelmkit.harmony.driver import HarmonyDriver
    from devhelmkit.harmony.rpc.client import RpcClient


class UiWindow(BaseWindow):
    """HarmonyOS 平台窗口对象。

    持有驱动引用，通过 RPC 调用设备端窗口 API。
    """

    def __init__(self, driver: 'HarmonyDriver',
                 rpc: 'RpcClient', window_id: Optional[int] = None):
        self._driver = driver
        self._rpc = rpc
        self._window_id = window_id

    @property
    def size(self) -> Tuple[int, int]:
        """窗口大小，设备端暂无窗口级尺寸 API，回退为屏幕尺寸。"""
        return self._driver.get_display_size()

    @property
    def info(self) -> Dict[str, Any]:
        """窗口信息，设备端暂无窗口信息 API，返回空字典占位。"""
        return {}

    def get_windows(self) -> List['UiWindow']:
        """获取所有窗口，设备端暂无枚举窗口 API，返回空列表占位。"""
        return []
