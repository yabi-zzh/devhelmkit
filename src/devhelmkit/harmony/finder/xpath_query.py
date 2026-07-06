# !/usr/bin/env python
# -*- coding: utf-8 -*-
"""XPath 查询引擎：在控件树 JSON 上执行标准 XPath 1.0 查询。

设备端 uitest 不支持 xpath，故通过 captureLayout 取控件树 JSON 后，在客户端
转成 lxml etree 交由 lxml 执行查询，具体语法支持范围以 lxml XPath 1.0 为准。

两条关键设计决策：

1. 节点到 element 的映射：控件 type 作为 element 的 tag，其余 attributes
   原样挂为 element 属性。由此控件的 text/description 等是 element 属性而非
   文本内容，故按 @text 而非 text() 匹配。

2. element 回指原始节点：查询命中的是 etree element，但下游 bounds 锚定需要
   原始 JSON 节点的 attributes。回指不能用 id(element)——lxml 的 element 是
   对底层 C 节点的按需代理，构建期的 Python 包装被回收后其 id 会被 CPython
   复用，与查询时新生成的包装对象对不上（实测 //Text 全 miss）。改为构建时
   将原始节点按序存入列表，并把列表下标写入 element 的专属属性
   （见 _DHK_IDX_ATTR），命中后据此取回原始节点。
"""
import logging
import re
from typing import Any, Dict, List, Tuple

from lxml import etree

logger = logging.getLogger(__name__)

# 合法 XML tag（NCName）粗校验：字母/下划线开头，后接字母/数字/_/-/.
_VALID_TAG_RE = re.compile(r'^[A-Za-z_][\w.\-]*$')

# tag 非法时的兜底名（对齐无 type 的根节点场景）
_FALLBACK_TAG = "orgRoot"

# XML 不接受的控制字符（\x00-\x1F 除 \t\n\r，以及 \x7F）
_CTRL_CHARS_RE = re.compile(r'[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]')

# element→原始节点的稳定回指属性名（内部专用，不与控件属性冲突）
_DHK_IDX_ATTR = "_dhkNodeIdx"


def query_xpath(tree: Dict[str, Any], xpath: str) -> List[Dict[str, Any]]:
    """在控件树上执行标准 XPath 查询，返回匹配的原始 JSON 节点列表。

    Args:
        tree: 控件树根节点（captureLayout 的 JSON）
        xpath: 标准 XPath 1.0 表达式

    Returns:
        匹配的原始 JSON 节点列表。表达式非法、或结果非节点（如 count()
        返回标量）时返回空列表。
    """
    root, node_list = _json_to_etree(tree)
    try:
        result = root.xpath(xpath)
    except etree.XPathError as e:
        logger.warning("XPath 表达式无效 [%s]: %s", xpath, e)
        return []

    # xpath 可能返回标量（数字/字符串/布尔，如 count()、@attr），只保留 element
    if not isinstance(result, list):
        return []
    nodes: List[Dict[str, Any]] = []
    for el in result:
        if not hasattr(el, "get"):
            continue
        raw_idx = el.get(_DHK_IDX_ATTR)
        if raw_idx is None:
            continue
        idx = int(raw_idx)
        if 0 <= idx < len(node_list):
            nodes.append(node_list[idx])
    return nodes


def _json_to_etree(
    tree: Dict[str, Any]
) -> Tuple[etree._Element, List[Dict[str, Any]]]:
    """把控件树 JSON 递归转为 lxml etree，并建立序号→原始节点列表。

    Returns:
        (etree 根 element, [原始 JSON 节点]，下标即 element 的 _dhkNodeIdx)
    """
    node_list: List[Dict[str, Any]] = []
    root = _build_element(tree, node_list)
    return root, node_list


def _build_element(node: Dict[str, Any],
                   node_list: List[Dict[str, Any]]) -> etree._Element:
    """递归构建单个 element：type 作 tag，其余 attributes 作属性。

    把原始节点追加进 node_list，并把其下标写入 element 的专属回指属性。
    """
    attrs = node.get("attributes") or {}
    tag = _safe_tag(attrs.get("type"))
    clean = _sanitize_attrs(attrs)
    idx = len(node_list)
    node_list.append(node)
    clean[_DHK_IDX_ATTR] = str(idx)
    el = etree.Element(tag, attrib=clean)
    for child in node.get("children") or []:
        el.append(_build_element(child, node_list))
    return el


def _safe_tag(node_type: Any) -> str:
    """把控件 type 归一化为合法 XML tag，非法则兜底。"""
    if isinstance(node_type, str) and _VALID_TAG_RE.match(node_type):
        return node_type
    return _FALLBACK_TAG


def _sanitize_attrs(attrs: Dict[str, Any]) -> Dict[str, str]:
    """把 attributes 归一化为 etree 可接受的 {str: str}。

    - 值统一 str 化（etree 属性值必须是字符串）
    - 剔除 XML 非法控制字符，避免 etree 构建抛错
    - 跳过非法属性名（含空格/冒号等），保留可作 XPath 谓词的正常属性
    """
    clean: Dict[str, str] = {}
    for key, value in attrs.items():
        if not isinstance(key, str) or not _VALID_TAG_RE.match(key):
            continue
        clean[key] = _CTRL_CHARS_RE.sub("", str(value))
    return clean
