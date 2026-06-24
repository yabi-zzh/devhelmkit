# !/usr/bin/env python
# -*- coding: utf-8 -*-
"""SelectorSpec：纯数据选择器规格。

对齐 U2 单对象模型：d(**kwargs) 直接返回 UiObject，SelectorSpec 仅作为
内部纯数据类封装控件定位条件，不向用户暴露任何操作接口。所有操作与
关系方法统一在 UiObject / BaseComponent 上。
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, Optional


@dataclass(frozen=True)
class SelectorSpec:
    """控件定位条件的纯数据封装（内部使用，不直接暴露给用户）。

    用户通过 d(text="x", resourceId="y") 构造，由 UiObject 持有。
    frozen=True 保证不可变，关系选择器衍生新实例时安全。
    """

    # 文本匹配
    text: Optional[str] = None
    text_contains: Optional[str] = None
    text_starts_with: Optional[str] = None
    text_ends_with: Optional[str] = None
    text_matches: Optional[str] = None
    text_matches_flags: Optional[int] = None

    # 描述匹配
    desc: Optional[str] = None
    desc_contains: Optional[str] = None
    desc_starts_with: Optional[str] = None
    desc_ends_with: Optional[str] = None
    desc_matches: Optional[str] = None

    # 通用定位
    resource_id: Optional[str] = None       # 对应 U2 resourceId / id
    class_name: Optional[str] = None        # 对应 U2 className / class_
    key: Optional[str] = None              # 鸿蒙 key 选择器
    type: Optional[str] = None             # 鸿蒙 type 选择器
    index: Optional[int] = None
    instance: Optional[int] = None

    # 关系选择器
    parent: Optional['SelectorSpec'] = None
    relation: Optional[str] = None          # 'child' / 'sibling' / 'after' / 'before'

    # xpath
    xpath: Optional[str] = None

    def merge(self, **kwargs) -> 'SelectorSpec':
        """合并新的选择条件，返回新实例（不可变）。"""
        normalized = _normalize_aliases(kwargs)
        merged = {**self.__dict__, **normalized}
        return SelectorSpec(**merged)

    @classmethod
    def with_relation(cls, parent: 'SelectorSpec', relation: str,
                      child: 'SelectorSpec') -> 'SelectorSpec':
        """构造关系选择器，避免 parent/relation 重复传参。"""
        child_data = {
            key: value
            for key, value in child.__dict__.items()
            if key not in ('parent', 'relation')
        }
        return cls(parent=parent, relation=relation, **child_data)


# U2 / 鸿蒙选择器别名 → 内部字段名
_ALIAS_MAPPING = {
    'className': 'class_name',
    'class_': 'class_name',
    'resourceId': 'resource_id',
    'id': 'resource_id',
    'description': 'desc',
    'textContains': 'text_contains',
    'textStartswith': 'text_starts_with',
    'textStartsWith': 'text_starts_with',
    'textEndswith': 'text_ends_with',
    'textEndsWith': 'text_ends_with',
    'textMatches': 'text_matches',
    'flags': 'text_matches_flags',
    'descContains': 'desc_contains',
    'descStartswith': 'desc_starts_with',
    'descStartsWith': 'desc_starts_with',
    'descEndswith': 'desc_ends_with',
    'descEndsWith': 'desc_ends_with',
    'descMatches': 'desc_matches',
}


def _normalize_aliases(kwargs: Dict[str, Any]) -> Dict[str, Any]:
    """U2 / 鸿蒙选择器别名归一化为内部字段。"""
    return {_ALIAS_MAPPING.get(key, key): value for key, value in kwargs.items()}


def build_selector(**kwargs) -> SelectorSpec:
    """从用户 kwargs 构建 SelectorSpec（含别名归一化）。"""
    normalized = _normalize_aliases(kwargs)
    return SelectorSpec(**normalized)
