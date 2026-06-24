# !/usr/bin/env python
# -*- coding: utf-8 -*-
"""XPath 查询引擎：在控件树 JSON 上执行 xpath 查询。

设备端 uitest 不支持 xpath，通过 dumpLayout 获取控件树后，
在客户端实现 xpath 查询。

支持的 xpath 语法（子集）：
    //TagName               查找所有指定类型的后代节点
    //*                     查找所有节点
    //TagName[@attr="val"]  属性等于
    //TagName[contains(@attr, "val")]  属性包含
    //TagName[@a="v1" and @b="v2"]     多属性 AND 匹配

控件树节点结构：
    {
        "attributes": {"type": "Text", "text": "设置", ...},
        "children": [...]
    }
"""
import re
from typing import Any, Dict, List, Optional

# xpath 主模式：//Tag[predicate?]
_XPATH_RE = re.compile(r'^//(\w+|\*)(?:\[(.+)\])?$')

# 属性等于：@attr="value"
_ATTR_EQ_RE = re.compile(r'@(\w+)\s*=\s*"([^"]*)"')

# 属性包含：contains(@attr, "value")
_ATTR_CONTAINS_RE = re.compile(r'contains\s*\(\s*@(\w+)\s*,\s*"([^"]*)"\s*\)')


def parse_xpath(xpath: str) -> Optional[Dict[str, Any]]:
    """解析 xpath 表达式，返回查询计划。

    Returns:
        {"tag": str, "conditions": [{"attr": str, "op": str, "value": str}]}
        解析失败返回 None。
    """
    match = _XPATH_RE.match(xpath.strip())
    if not match:
        return None
    tag = match.group(1)
    predicate = match.group(2)
    conditions = []
    if predicate:
        # 按 " and " 分割多条件
        parts = re.split(r'\s+and\s+', predicate)
        for part in parts:
            part = part.strip()
            m = _ATTR_CONTAINS_RE.match(part)
            if m:
                conditions.append({
                    "attr": m.group(1), "op": "contains", "value": m.group(2)
                })
                continue
            m = _ATTR_EQ_RE.match(part)
            if m:
                conditions.append({
                    "attr": m.group(1), "op": "equals", "value": m.group(2)
                })
                continue
            return None
    return {"tag": tag, "conditions": conditions}


def query_xpath(tree: Dict[str, Any], xpath: str) -> List[Dict[str, Any]]:
    """在控件树上执行 xpath 查询，返回匹配的节点列表。"""
    plan = parse_xpath(xpath)
    if plan is None:
        return []
    results: List[Dict[str, Any]] = []
    _traverse(tree, plan, results)
    return results


def _traverse(node: Dict[str, Any], plan: Dict[str, Any],
              results: List[Dict[str, Any]]) -> None:
    """深度优先遍历控件树，收集匹配节点。"""
    attrs = node.get("attributes") or {}
    tag = plan["tag"]
    node_type = attrs.get("type", "")

    # tag 匹配（* 匹配任意）
    tag_matched = (tag == "*" or node_type == tag)
    if tag_matched and _match_conditions(attrs, plan["conditions"]):
        results.append(node)

    for child in node.get("children") or []:
        _traverse(child, plan, results)


def _match_conditions(attrs: Dict[str, Any],
                      conditions: List[Dict[str, Any]]) -> bool:
    """检查节点属性是否满足全部条件。"""
    for cond in conditions:
        attr_name = cond["attr"]
        expected = cond["value"]
        actual = attrs.get(attr_name)
        if actual is None:
            return False
        actual_str = str(actual) if not isinstance(actual, bool) else str(actual).lower()
        if cond["op"] == "equals":
            if actual_str != expected:
                return False
        elif cond["op"] == "contains":
            if expected not in actual_str:
                return False
    return True
