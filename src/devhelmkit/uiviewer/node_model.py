# !/usr/bin/env python
# -*- coding: utf-8 -*-
"""UIView 层级节点模型与 XPath 生成。

该模块把 Harmony 控件树收敛为统一 UiNode：属性归一化、bounds 解析、
坐标命中、树路径和 XPath 候选都从这里产出，避免录制、属性面板、
后续调试能力各自重复解析页面结构。
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any, Dict, Iterable, List, Optional, Tuple

from devhelmkit.uiviewer.protocol import extract_hierarchy_attributes

_VALID_XML_NAME_RE = re.compile(r"^[A-Za-z_][\w.\-]*$")
_BOUNDS_RE = re.compile(r"\[(-?\d+),(-?\d+)\]\[(-?\d+),(-?\d+)\]")
_FALLBACK_TAG = "orgRoot"
_INTERACTIVE_TYPE_VALUES = {
    "Button",
    "Checkbox",
    "Radio",
    "SearchField",
    "Slider",
    "Switch",
    "TextArea",
    "TextInput",
    "Toggle",
}

Bounds = Dict[str, int]
XPathCandidate = Dict[str, Any]


@dataclass
class UiNode:
    """统一后的 UI 节点。

    字段分两类：
    - 原始结构：node_id、parent_id、children_ids、attributes、bounds；
    - 录制定位视图：id/text/type/description 及其对应脚本选择器字段。
    """

    node_id: str
    attributes: Dict[str, Any]
    bounds: Optional[Bounds]
    depth: int
    parent_id: Optional[str] = None
    children_ids: List[str] = field(default_factory=list)
    sibling_index: int = 0

    id_selector_name: str = "id"
    id_val: str = ""
    text_val: str = ""
    text_attr_name: str = ""
    type_selector_name: str = "type"
    type_val: str = ""
    desc_val: str = ""
    id_and_text: str = ""
    type_and_text: str = ""

    def __post_init__(self) -> None:
        """从原始 attributes 建立录制定位所需的归一化属性视图。"""
        attrs = self.attributes

        self.id_selector_name = "id"
        self.id_val = ""
        for attr_name, selector_name in (
            ("key", "key"),
            ("id", "id"),
            ("resourceId", "resourceId"),
            ("resource-id", "resourceId"),
        ):
            raw_value = attrs.get(attr_name)
            if raw_value:
                self.id_selector_name = selector_name
                self.id_val = str(raw_value).strip()
                break

        self.text_attr_name, self.text_val = _first_text_value(
            attrs,
            (
                "text",
                "value",
                "content",
                "label",
                "originalText",
                "hint",
                "placeholder",
            ),
        )

        self.type_selector_name = "type"
        self.type_val = ""
        for attr_name, selector_name in (
            ("className", "className"),
            ("class", "className"),
            ("type", "type"),
        ):
            raw_value = attrs.get(attr_name)
            if raw_value:
                self.type_selector_name = selector_name
                self.type_val = str(raw_value).strip()
                break

        self.desc_val = str(
            attrs.get("description")
            or attrs.get("desc")
            or ""
        ).strip()

        self.id_and_text = (
            f"{self.id_val}//{self.text_val}"
            if self.id_val and self.text_val else ""
        )
        self.type_and_text = (
            f"{self.type_val}//{self.text_val}"
            if self.type_val and self.text_val else ""
        )

    @property
    def xpath_tag(self) -> str:
        """返回与 harmony.finder.xpath_query 一致的 XPath element tag。"""
        raw_type = self.attributes.get("type")
        if isinstance(raw_type, str) and _VALID_XML_NAME_RE.match(raw_type):
            return raw_type
        return _FALLBACK_TAG


def _first_text_value(attrs: Dict[str, Any], names: Iterable[str]) -> Tuple[str, str]:
    """按设备字段优先级提取可用于文字定位的展示文本。"""
    for name in names:
        value = attrs.get(name)
        if value is None:
            continue
        text = str(value).strip()
        if text:
            return name, text
    return "", ""


def parse_nodes_dfs(root: Dict[str, Any], depth: int = 0) -> List[UiNode]:
    """深度优先解析控件树，node_id 与 protocol.flatten_hierarchy 保持一致。"""
    nodes: List[UiNode] = []
    if not isinstance(root, dict) or not root:
        return nodes
    _walk(root, None, "", depth, nodes)
    return nodes


def find_node_by_id(root: Dict[str, Any], node_id: str) -> Optional[UiNode]:
    """按 node_id 查找统一节点。"""
    for node in parse_nodes_dfs(root):
        if node.node_id == node_id:
            return node
    return None


def find_target_node(dfs_nodes: List[UiNode], x: int, y: int) -> Optional[UiNode]:
    """在 DFS 列表中查找最适合作为录制目标的节点。"""
    containing = [
        node for node in dfs_nodes
        if node.bounds and is_point_inside(node.bounds, x, y)
    ]
    if not containing:
        return None

    best_semantic = _pick_semantic_hit_node(containing)
    if best_semantic is not None:
        return _promote_to_interactive_ancestor(best_semantic, dfs_nodes)

    deepest = max(containing, key=lambda node: (node.depth, -_bounds_area(node.bounds)))
    return _promote_to_interactive_ancestor(deepest, dfs_nodes)


def _promote_to_interactive_ancestor(
    node: UiNode,
    nodes: List[UiNode],
) -> UiNode:
    """将图标、文字等命中叶子提升到最近的真实交互祖先。"""
    if _node_interactive_score(node) > 0:
        return node
    by_id = {item.node_id: item for item in nodes}
    current = by_id.get(node.parent_id) if node.parent_id else None
    while current is not None:
        if _node_interactive_score(current) > 0:
            return current
        current = by_id.get(current.parent_id) if current.parent_id else None
    return node


def _pick_semantic_hit_node(nodes: List[UiNode]) -> Optional[UiNode]:
    """从坐标命中节点中选择语义明确且范围不过大的最优目标。"""
    screen_area = max(
        max((_bounds_area(node.bounds) for node in nodes), default=0),
        1,
    )
    candidates = []
    for node in nodes:
        area = _bounds_area(node.bounds)
        if area / screen_area >= 0.7:
            continue
        semantic_score = _node_semantic_score(node)
        if semantic_score <= 0:
            continue
        interactive_score = _node_interactive_score(node)
        candidates.append((interactive_score, node.depth, -area, semantic_score, node))
    if not candidates:
        return None
    return max(candidates, key=lambda item: item[:4])[4]


def _node_interactive_score(node: UiNode) -> int:
    """按可交互属性和原生控件类型评估节点是否承载真实操作。"""
    attrs = node.attributes
    if _bool_attribute(attrs, "enabled") is False:
        return -20
    if _bool_attribute(attrs, "clickable") is True:
        return 100
    if _bool_attribute(attrs, "longClickable", "long_clickable") is True:
        return 90
    if _bool_attribute(attrs, "checkable") is True:
        return 80
    short_type = str(node.type_val or "").rsplit(".", 1)[-1]
    if short_type in _INTERACTIVE_TYPE_VALUES:
        return 70
    return 0


def _bool_attribute(attrs: Dict[str, Any], *names: str) -> Optional[bool]:
    """读取设备布尔属性，并用 None 区分缺失值与显式 false。"""
    for name in names:
        if name not in attrs:
            continue
        value = attrs.get(name)
        if isinstance(value, bool):
            return value
        normalized = str(value).strip().lower()
        if normalized in {"true", "1", "yes"}:
            return True
        if normalized in {"false", "0", "no"}:
            return False
    return None


def _node_semantic_score(node: UiNode) -> int:
    """按文本、描述、身份和交互类型评估节点定位语义质量。"""
    if node.text_val:
        return 80
    if node.desc_val:
        return 70
    if node.id_val:
        return 55
    if node.type_val and node.type_val.rsplit(".", 1)[-1] in _INTERACTIVE_TYPE_VALUES:
        return 45
    return 0


def _bounds_area(bounds: Optional[Bounds]) -> int:
    """计算有效矩形面积，缺失或反向 bounds 按零面积处理。"""
    if not bounds:
        return 0
    return max(0, bounds["right"] - bounds["left"]) * max(
        0, bounds["bottom"] - bounds["top"]
    )


def is_point_inside(bounds: Bounds, x: int, y: int) -> bool:
    """判断坐标是否落入节点 bounds。"""
    return (
        bounds["left"] <= x < bounds["right"]
        and bounds["top"] <= y < bounds["bottom"]
    )


def generate_xpath_candidates(root: Dict[str, Any], node_id: str) -> List[XPathCandidate]:
    """基于当前控件树和 node_id 生成 XPath 候选。"""
    nodes = parse_nodes_dfs(root)
    target = next((node for node in nodes if node.node_id == node_id), None)
    if target is None:
        return []
    return generate_xpath_candidates_for_node(target, nodes)


def generate_xpath_candidates_for_node(
    target: UiNode,
    nodes: List[UiNode],
) -> List[XPathCandidate]:
    """为目标节点生成多种 XPath 表达式。"""
    candidates: List[XPathCandidate] = []

    class_xpath = _build_tag_xpath(target, nodes)
    if class_xpath:
        candidates.append(class_xpath)

    for by, attr_name, label in (
        ("key", "key", "key"),
        ("id", "id", "id"),
        ("resourceId", "resourceId", "resourceId"),
        ("text", "text", "text"),
        ("value", "value", "value"),
        ("content", "content", "content"),
        ("label", "label", "label"),
        ("originalText", "originalText", "originalText"),
        ("hint", "hint", "hint"),
        ("placeholder", "placeholder", "placeholder"),
        ("description", "description", "description"),
        ("desc", "desc", "description"),
        ("className", "className", "className"),
        ("bounds", "bounds", "bounds"),
    ):
        candidate = _build_attr_xpath(target, nodes, by, attr_name, label)
        if candidate:
            candidates.append(candidate)

    path_xpath = _build_path_xpath(target, nodes)
    if path_xpath:
        candidates.append(path_xpath)

    return _dedupe_candidates(candidates)


def select_xpath_candidate(
    candidates: List[XPathCandidate],
    preferred_by: Optional[str] = None,
) -> Optional[XPathCandidate]:
    """按偏好选择 XPath 候选。"""
    if not candidates:
        return None
    aliases = {
        "type": "class",
        "className": "className",
        "class": "class",
        "path": "path",
    }
    preferred = aliases.get(preferred_by or "", preferred_by)
    if preferred:
        for candidate in candidates:
            if candidate.get("by") == preferred:
                return candidate
    return candidates[0]


def _walk(
    raw_node: Dict[str, Any],
    parent_id: Optional[str],
    prefix: str,
    depth: int,
    nodes: List[UiNode],
) -> str:
    """递归构建稳定 node_id，并同步维护父子关系和同级序号。"""
    sibling_index = 0
    if parent_id is not None:
        parent = next((node for node in reversed(nodes) if node.node_id == parent_id), None)
        sibling_index = len(parent.children_ids) if parent else 0
    node_id = "%s%d" % (prefix, sibling_index) if prefix else "root"

    attrs = extract_hierarchy_attributes(raw_node)
    bounds = parse_bounds(raw_node.get("bounds") if "bounds" in raw_node else attrs.get("bounds"))

    node = UiNode(
        node_id=node_id,
        parent_id=parent_id,
        attributes=attrs,
        bounds=bounds,
        depth=depth,
        sibling_index=sibling_index,
    )
    nodes.append(node)

    children = raw_node.get("children") or []
    if isinstance(children, list):
        for index, child in enumerate(children):
            if not isinstance(child, dict):
                continue
            child_prefix = "%s%d_" % (prefix, index) if prefix else "%d_" % index
            child_id = _walk(child, node_id, child_prefix, depth + 1, nodes)
            node.children_ids.append(child_id)

    return node_id


def parse_bounds(raw: Any) -> Optional[Bounds]:
    """解析多种 bounds 形态为统一矩形。"""
    if isinstance(raw, str):
        match = _BOUNDS_RE.search(raw)
        if match:
            return {
                "left": int(match.group(1)),
                "top": int(match.group(2)),
                "right": int(match.group(3)),
                "bottom": int(match.group(4)),
            }
    if isinstance(raw, (list, tuple)) and len(raw) >= 4:
        try:
            return {
                "left": int(raw[0]),
                "top": int(raw[1]),
                "right": int(raw[2]),
                "bottom": int(raw[3]),
            }
        except (TypeError, ValueError):
            return None
    if isinstance(raw, dict):
        try:
            return {
                "left": int(raw.get("left", 0)),
                "top": int(raw.get("top", 0)),
                "right": int(raw.get("right", 0)),
                "bottom": int(raw.get("bottom", 0)),
            }
        except (TypeError, ValueError):
            return None
    return None


def _build_tag_xpath(target: UiNode, nodes: List[UiNode]) -> Optional[XPathCandidate]:
    """生成按节点类型定位的 XPath，并用全树序号消除重复类型歧义。"""
    tag = target.xpath_tag
    if not tag:
        return None
    same_tag_nodes = [node for node in nodes if node.xpath_tag == tag]
    index = _one_based_index(same_tag_nodes, target)
    if index is None:
        return None
    xpath = f"//{tag}" if len(same_tag_nodes) == 1 else f"(//{tag})[{index}]"
    return _candidate("class", "class", xpath, len(same_tag_nodes), index)


def _build_attr_xpath(
    target: UiNode,
    nodes: List[UiNode],
    by: str,
    attr_name: str,
    label: str,
) -> Optional[XPathCandidate]:
    """生成精确属性 XPath，并记录该属性值在全树中的匹配数量。"""
    value = target.attributes.get(attr_name)
    if value is None or value == "":
        return None
    if not _VALID_XML_NAME_RE.match(attr_name):
        return None
    same_value_nodes = [
        node for node in nodes
        if str(node.attributes.get(attr_name, "")) == str(value)
    ]
    index = _one_based_index(same_value_nodes, target)
    if index is None:
        return None
    predicate = f"//*[@{attr_name}={xpath_literal(value)}]"
    xpath = predicate if len(same_value_nodes) == 1 else f"({predicate})[{index}]"
    return _candidate(by, label, xpath, len(same_value_nodes), index)


def _build_path_xpath(target: UiNode, nodes: List[UiNode]) -> Optional[XPathCandidate]:
    """生成包含每层同类型序号的绝对路径 XPath 作为结构兜底。"""
    by_id = {node.node_id: node for node in nodes}
    chain: List[UiNode] = []
    current: Optional[UiNode] = target
    while current is not None:
        chain.append(current)
        current = by_id.get(current.parent_id) if current.parent_id else None
    chain.reverse()
    if not chain:
        return None

    segments = []
    for node in chain:
        siblings = _siblings_with_same_tag(node, by_id)
        index = _one_based_index(siblings, node) or 1
        segments.append(f"{node.xpath_tag}[{index}]")
    return _candidate("path", "path", "/" + "/".join(segments), 1, 1)


def xpath_literal(value: Any) -> str:
    """生成 XPath 1.0 字符串字面量。"""
    text = str(value)
    if "'" not in text:
        return "'%s'" % text
    if '"' not in text:
        return '"%s"' % text
    parts = text.split("'")
    quoted = []
    for index, part in enumerate(parts):
        if index > 0:
            quoted.append('"\'"')
        if part:
            quoted.append("'%s'" % part)
    return "concat(%s)" % ", ".join(quoted)


def _siblings_with_same_tag(node: UiNode, by_id: Dict[str, UiNode]) -> List[UiNode]:
    """返回同一父节点下 XPath tag 相同的兄弟节点。"""
    if node.parent_id is None:
        return [node]
    parent = by_id.get(node.parent_id)
    if parent is None:
        return [node]
    return [
        by_id[child_id]
        for child_id in parent.children_ids
        if child_id in by_id and by_id[child_id].xpath_tag == node.xpath_tag
    ]


def _one_based_index(items: Iterable[UiNode], target: UiNode) -> Optional[int]:
    """按对象身份返回目标节点的一基序号，未找到时返回 None。"""
    for index, item in enumerate(items, start=1):
        if item is target:
            return index
    return None


def _candidate(
    by: str,
    label: str,
    xpath: str,
    matches: int,
    index: int,
) -> XPathCandidate:
    """构建前后端共享的 XPath 候选数据结构。"""
    return {
        "by": by,
        "label": label,
        "xpath": xpath,
        "matches": matches,
        "index": index,
        "unique": matches == 1,
    }


def _dedupe_candidates(candidates: List[XPathCandidate]) -> List[XPathCandidate]:
    """按 XPath 表达式去重，同时保留候选生成优先级。"""
    seen = set()
    result: List[XPathCandidate] = []
    for candidate in candidates:
        xpath = candidate.get("xpath")
        if not xpath or xpath in seen:
            continue
        seen.add(xpath)
        result.append(candidate)
    return result