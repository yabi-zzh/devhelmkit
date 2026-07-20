# !/usr/bin/env python
# -*- coding: utf-8 -*-
"""弹窗自动消除策略。

在控件查找失败时，自动检测并消除常见系统弹窗（权限请求、更新提示、
广告弹窗等），消除后重试查找。

弹窗消除策略：遍历常见确认类按钮文本，查找并点击存在的弹窗按钮。
仅点击确认类按钮（允许/确定/知道了），不点击取消类按钮。

PopupHandler 不直接依赖 ComponentFinder，通过注入的 find_components
回调查找弹窗按钮，避免循环依赖。回调选用即时查找（不等待）的
find_components，既天然避免与 find_component 形成弹窗消除递归，也消除
逐候选文本各自阻塞查找超时的串行叠加。
"""
import logging
from typing import Callable, List, TYPE_CHECKING

from devhelmkit.core.selector_spec import SelectorSpec, build_selector
from devhelmkit.exceptions import RpcError

logger = logging.getLogger(__name__)

if TYPE_CHECKING:
    from devhelmkit.harmony.config import HarmonyDriverConfig
    from devhelmkit.harmony.rpc.client import RpcClient

# 常见弹窗确认类按钮文本（按优先级排序）
_POPUP_DISMISS_TEXTS = [
    "允许",
    "仅在使用中允许",
    "始终允许",
    "确定",
    "我知道了",
    "知道了",
    "同意",
    "继续",
    "关闭",
    "跳过",
]


class PopupHandler:
    """弹窗自动消除处理器。

    通过注入的 find_components 回调即时查找弹窗按钮，找到后通过 RPC
    调用 Component.click 点击消除。
    """

    def __init__(self,
                 find_components: Callable[[SelectorSpec], List[str]],
                 rpc: 'RpcClient', config: 'HarmonyDriverConfig'):
        self._find_components = find_components
        self._rpc = rpc
        self._config = config

    def dismiss_popups(self) -> bool:
        """检测并消除弹窗，返回是否处理了弹窗。

        遍历常见弹窗按钮文本，查找并点击存在的按钮。
        最多处理 pop_window_handle_times 个弹窗。
        """
        handled = False
        max_times = self._config.pop_window_handle_times
        for _ in range(max_times):
            if not self._dismiss_one_popup():
                break
            handled = True
        return handled

    def _dismiss_one_popup(self) -> bool:
        """消除单个弹窗，返回是否找到并处理了弹窗。

        对每个候选文本用 find_components 即时查询（单次 RPC，不等待超时），
        命中即点击首个匹配控件。不存在时快速跳过，避免逐文本阻塞满查找超时。
        """
        for text in _POPUP_DISMISS_TEXTS:
            try:
                refs = self._find_components(build_selector(text=text))
            except RpcError as e:
                logger.warning("消除弹窗查找 RPC 异常: %s", e)
                continue
            if not refs:
                continue
            try:
                self._rpc.call("Component.click", refs[0], [])
            except RpcError as e:
                logger.warning("消除弹窗点击 RPC 异常: %s", e)
                continue
            logger.debug("已消除弹窗: %s", text)
            return True
        return False
