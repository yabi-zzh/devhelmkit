# !/usr/bin/env python
# -*- coding: utf-8 -*-
"""SelectorSpec → 设备端 On 查询条件转换。

将跨平台纯数据 SelectorSpec 转为设备端 By/On 链构造计划。
本模块只做纯数据转换，不执行 RPC 调用，不依赖 RpcClient。

By/On 链构造顺序：
1. 从静态根 On#seed 开始
2. 按 selector_to_by_chain 返回的 [(api_name, args), ...] 顺序 RPC 调用
3. 每次调用返回新的 By 对象引用，作为下一次调用的 this

关系选择器（parent/relation）不在本模块处理，由 ComponentFinder
在构造 By 链时递归处理 parent 后调用 On.within / On.isAfter / On.isBefore。
"""
from typing import List, Tuple

from devhelmkit.core.selector_spec import SelectorSpec
from devhelmkit.model.match_pattern import MatchPattern


def selector_to_by_chain(selector: SelectorSpec) -> List[Tuple[str, list]]:
    """将叶子选择器转为 By/On 链构造计划。

    不处理关系选择器（parent/relation），仅转换定位条件。

    Args:
        selector: 控件定位条件

    Returns:
        [(api_name, args), ...]，按顺序 RPC 调用构造 By 链。
        api_name 为 api9+ 风格（On.text / On.id / On.type / On.description）。
        空列表表示无定位条件（匹配所有控件）。
    """
    chain: List[Tuple[str, list]] = []

    _append_text_chain(chain, selector)
    _append_desc_chain(chain, selector)
    _append_id_chain(chain, selector)
    _append_type_chain(chain, selector)

    return chain


def _append_text_chain(chain: List[Tuple[str, list]],
                       selector: SelectorSpec) -> None:
    """文本匹配条件，同组互斥，按优先级取第一个非空字段。"""
    if selector.text is not None:
        chain.append(("On.text", [selector.text, int(MatchPattern.EQUALS)]))
    elif selector.text_contains is not None:
        chain.append(("On.text", [selector.text_contains, int(MatchPattern.CONTAINS)]))
    elif selector.text_starts_with is not None:
        chain.append(("On.text", [selector.text_starts_with, int(MatchPattern.STARTS_WITH)]))
    elif selector.text_ends_with is not None:
        chain.append(("On.text", [selector.text_ends_with, int(MatchPattern.ENDS_WITH)]))
    elif selector.text_matches is not None:
        chain.append(("On.text", [selector.text_matches, int(MatchPattern.REGEXP)]))


def _append_desc_chain(chain: List[Tuple[str, list]],
                       selector: SelectorSpec) -> None:
    """描述匹配条件，同组互斥。"""
    if selector.desc is not None:
        chain.append(("On.description", [selector.desc, int(MatchPattern.EQUALS)]))
    elif selector.desc_contains is not None:
        chain.append(("On.description", [selector.desc_contains, int(MatchPattern.CONTAINS)]))
    elif selector.desc_starts_with is not None:
        chain.append(("On.description", [selector.desc_starts_with, int(MatchPattern.STARTS_WITH)]))
    elif selector.desc_ends_with is not None:
        chain.append(("On.description", [selector.desc_ends_with, int(MatchPattern.ENDS_WITH)]))
    elif selector.desc_matches is not None:
        chain.append(("On.description", [selector.desc_matches, int(MatchPattern.REGEXP)]))


def _append_id_chain(chain: List[Tuple[str, list]],
                     selector: SelectorSpec) -> None:
    """ID/Key 定位，key 优先于 resource_id。

    API 12+ 中 By.key 和 By.id 统一映射到 On.id。
    """
    if selector.key is not None:
        chain.append(("On.id", [selector.key]))
    elif selector.resource_id is not None:
        chain.append(("On.id", [selector.resource_id]))


def _append_type_chain(chain: List[Tuple[str, list]],
                       selector: SelectorSpec) -> None:
    """类型定位，class_name 优先于 type。"""
    if selector.class_name is not None:
        chain.append(("On.type", [selector.class_name]))
    elif selector.type is not None:
        chain.append(("On.type", [selector.type]))


# 关系选择器 → 设备端 On API 映射
RELATION_API = {
    'child': 'On.within',
    'after': 'On.isAfter',
    'before': 'On.isBefore',
}
