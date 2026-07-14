# !/usr/bin/env python
# -*- coding: utf-8 -*-
"""操作录制定位计算与脚本生成模块。

通过对 UI 树进行 DFS 扁平化，分析控件属性的全局唯一性及邻近锚点相对位置，
自动生成符合 devhelmkit 规范的 python 自动化代码。
"""
import math
import re
from dataclasses import dataclass
from typing import Dict, Any, List, Optional, Tuple
from collections import Counter

from devhelmkit.uiviewer.node_model import (
    UiNode,
    find_target_node,
    generate_xpath_candidates_for_node,
    parse_nodes_dfs,
)

WidgetNode = UiNode


@dataclass(frozen=True)
class _SelectorArgsCandidate:
    """可放入 d(...) 或关系选择器参数区的选择器片段。"""

    args: str
    score: int
    kind: str


@dataclass(frozen=True)
class _SelectorCandidate:
    """完整可执行定位表达式候选。"""

    expr: str
    score: int
    priority: int
    kind: str


_GENERIC_TYPE_VALUES = {
    "Blank",
    "Canvas",
    "Column",
    "Component",
    "Divider",
    "Flex",
    "Grid",
    "GridItem",
    "Image",
    "List",
    "ListItem",
    "Navigation",
    "NavigationBar",
    "Panel",
    "Path",
    "Rect",
    "RelativeContainer",
    "Row",
    "Scroll",
    "Shape",
    "Stack",
    "SymbolGlyph",
    "Text",
    "TitleBar",
    "Toolbar",
    "View",
    "XComponent",
}

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

_EDITABLE_TYPE_VALUES = {
    "SearchField",
    "TextArea",
    "TextInput",
}

_SUPPORTED_ACTIONS = frozenset({
    "click",
    "double_click",
    "input",
    "long_click",
    "swipe",
})

_KIND_PRIORITY = {
    "direct:id": 100,
    "direct:text": 90,
    "direct:desc": 85,
    "direct:id_text": 78,
    "direct:id_desc": 76,
    "direct:text_desc": 74,
    "direct:type_text": 72,
    "direct:type_desc": 70,
    "direct:id_type": 68,
    "direct:type": 60,
    "relative": 50,
    "xpath": 40,
}

def _py_literal(value: Any) -> str:
    """生成可直接嵌入录制脚本的 Python 字面量。"""
    return repr(str(value))


def _selector_kw(name: str, value: Any) -> str:
    """生成单个选择器关键字参数。"""
    return f"{name}={_py_literal(value)}"


def _selector_args(*items: Tuple[str, Any]) -> str:
    """按候选顺序拼接稳定可读的选择器参数。"""
    return ", ".join(_selector_kw(name, value) for name, value in items)


def _py_int(value: Any) -> str:
    """生成坐标使用的 Python 整数字面量。"""
    return str(int(value))


def _py_float(value: Any, default: float = 0.5) -> str:
    """生成时长使用的 Python 浮点字面量，无效值回退默认时长。"""
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return repr(default)
    if not math.isfinite(parsed) or parsed <= 0:
        return repr(default)
    return repr(parsed)


def generate_key_code(key: Any) -> str:
    """生成设备导航按键的录制脚本。"""
    if key == "back":
        return "d.go_back()"
    if key == "home":
        return "d.go_home()"
    if key == "recent":
        return "d.go_recent_task()"
    return f"d.press({_py_literal(key)})"


def analyze_uniqueness(dfs_nodes: List[WidgetNode]) -> Dict[str, Counter]:
    """统计属性值在全树中出现的次数，辅助唯一性检索。"""
    counters = {
        name: Counter()
        for name in (
            "identity",
            "identity_text",
            "identity_desc",
            "identity_type",
            "id",
            "text",
            "type",
            "desc",
            "id_text",
            "id_desc",
            "id_type",
            "text_desc",
            "type_text",
            "type_desc",
        )
    }

    for node in dfs_nodes:
        identities = {identity[1] for identity in _identity_values(node)}
        has_text = bool(node.text_val and node.text_attr_name == "text")
        has_desc = bool(node.desc_val)
        has_type = bool(node.type_val)

        for identity in identities:
            counters["identity"][identity] += 1
            if has_text:
                counters["identity_text"][(identity, node.text_val)] += 1
            if has_desc:
                counters["identity_desc"][(identity, node.desc_val)] += 1
            if has_type:
                counters["identity_type"][(identity, node.type_val)] += 1

        if node.id_val:
            counters["id"][node.id_val] += 1
        if has_text:
            counters["text"][node.text_val] += 1
        if has_type:
            counters["type"][node.type_val] += 1
        if has_desc:
            counters["desc"][node.desc_val] += 1

        if node.id_val and has_text:
            counters["id_text"][(node.id_val, node.text_val)] += 1
        if node.id_val and has_desc:
            counters["id_desc"][(node.id_val, node.desc_val)] += 1
        if node.id_val and has_type:
            counters["id_type"][(node.id_val, node.type_val)] += 1
        if has_text and has_desc:
            counters["text_desc"][(node.text_val, node.desc_val)] += 1
        if has_type and has_text:
            counters["type_text"][(node.type_val, node.text_val)] += 1
        if has_type and has_desc:
            counters["type_desc"][(node.type_val, node.desc_val)] += 1

    return counters


def get_unique_selector(node: WidgetNode, counters: Dict[str, Counter]) -> Optional[str]:
    """计算单个控件的唯一选择器配置串，若不唯一返回 None。"""
    choice = _best_args_candidate(_direct_selector_args_candidates(node, counters))
    return choice.args if choice else None


def generate_relative_selector(
    target_idx: int, target_node: WidgetNode,
    dfs_nodes: List[WidgetNode], counters: Dict[str, Counter]
) -> Optional[str]:
    """生成高质量相对定位表达式；低质量 after(...) 直接放弃。"""
    if not 0 <= target_idx < len(dfs_nodes) or dfs_nodes[target_idx] is not target_node:
        return None
    candidate = _best_selector_candidate(
        _relative_selector_candidates(target_node, dfs_nodes, counters)
    )
    return candidate.expr if candidate else None


def generate_selector(
    root: Dict[str, Any],
    x: int,
    y: int,
    action: Optional[str] = None,
) -> Tuple[Optional[str], Optional[WidgetNode]]:
    """整合坐标命中、唯一性分析和定位器生成，返回脚本选择器与目标节点。"""
    dfs_nodes = parse_nodes_dfs(root)
    target_node = find_target_node(dfs_nodes, x, y)
    if not target_node:
        return None, None

    if action == "input" and not _is_editable_node(target_node):
        raise ValueError(
            f"输入动作目标不是可编辑控件: {target_node.type_val or 'unknown'}"
        )

    if _is_container_type(target_node.type_val) and not _is_interactive_node(target_node):
        return None, target_node

    counters = analyze_uniqueness(dfs_nodes)
    candidates = _direct_selector_candidates(target_node, counters)
    best = _best_selector_candidate(candidates, min_score=70)
    if best and best.score >= 97:
        return best.expr, target_node

    if action != "input":
        candidates.extend(
            _semantic_descendant_selector_candidates(target_node, dfs_nodes, counters)
        )
        best = _best_selector_candidate(candidates, min_score=70)
        if best and best.score >= 87:
            return best.expr, target_node

    candidates.extend(_xpath_selector_candidates(target_node, dfs_nodes))
    candidates.extend(
        _relative_selector_candidates(target_node, dfs_nodes, counters)
    )

    best = _best_selector_candidate(candidates, min_score=70)
    return (best.expr if best else None), target_node


def _direct_selector_candidates(
    node: WidgetNode,
    counters: Dict[str, Counter],
) -> List[_SelectorCandidate]:
    """把参数候选包装为可直接执行的 d(...) 定位表达式。"""
    return [
        _selector_candidate(
            expr=f"d({candidate.args})",
            score=candidate.score,
            kind=candidate.kind,
        )
        for candidate in _direct_selector_args_candidates(node, counters)
    ]


def _direct_selector_args_candidates(
    node: WidgetNode,
    counters: Dict[str, Counter],
) -> List[_SelectorArgsCandidate]:
    """按单字段优先、必要时组合字段的规则生成唯一参数候选。"""
    candidates: List[_SelectorArgsCandidate] = []
    identities = _identity_values(node)
    text_score = _text_score(node.text_val)
    desc_score = _description_score(node.desc_val)
    type_score = _type_score(node.type_val)
    if _is_container_type(node.type_val):
        text_score = min(text_score, 55)
        desc_score = min(desc_score, 55)

    def add_unique(
        counter_name: str,
        counter_key: Any,
        kind: str,
        score: int,
        *items: Tuple[str, Any],
    ) -> None:
        """仅接纳在指定统计维度中可证明唯一的参数组合。"""
        if items and counters[counter_name][counter_key] == 1:
            candidates.append(_selector_args_candidate(items, score, kind))

    stable_unique_identities = []
    for identity in identities:
        identity_score = _identity_score(identity[1])
        if counters["identity"][identity[1]] == 1 and identity_score >= 70:
            stable_unique_identities.append((identity, identity_score))
            identity_bonus = {"key": 2, "id": 1, "resourceId": 0}.get(
                identity[0], 0
            )
            add_unique(
                "identity", identity[1], "direct:id",
                min(100, identity_score + 8 + identity_bonus), identity,
            )

    text_is_unique = bool(
        node.text_val
        and node.text_attr_name == "text"
        and counters["text"][node.text_val] == 1
    )
    desc_is_unique = bool(
        node.desc_val and counters["desc"][node.desc_val] == 1
    )
    if text_is_unique:
        add_unique(
            "text", node.text_val, "direct:text",
            min(96, text_score + 6), ("text", node.text_val),
        )
    if desc_is_unique:
        add_unique(
            "desc", node.desc_val, "direct:desc",
            min(94, desc_score + 5), ("description", node.desc_val),
        )
    if node.type_val:
        add_unique(
            "type", node.type_val, "direct:type",
            min(76, type_score + 3), (node.type_selector_name, node.type_val),
        )

    # 组合只用于解决单字段重复；单字段已稳定唯一时保持脚本最简。
    for identity in identities:
        identity_score = _identity_score(identity[1])
        if identity_score < 70:
            continue
        if (
            node.text_val
            and node.text_attr_name == "text"
            and not stable_unique_identities
        ):
            add_unique(
                "identity_text", (identity[1], node.text_val), "direct:id_text",
                _combine_score(identity_score, text_score, bonus=14, limit=94),
                identity, ("text", node.text_val),
            )
        if node.desc_val and not stable_unique_identities:
            add_unique(
                "identity_desc", (identity[1], node.desc_val), "direct:id_desc",
                _combine_score(identity_score, desc_score, bonus=13, limit=93),
                identity, ("description", node.desc_val),
            )
        if node.type_val and not stable_unique_identities:
            add_unique(
                "identity_type", (identity[1], node.type_val), "direct:id_type",
                _combine_score(identity_score, type_score, bonus=7, limit=86),
                identity, (node.type_selector_name, node.type_val),
            )

    if (
        node.text_val and node.desc_val and node.text_attr_name == "text"
        and not text_is_unique and not desc_is_unique
    ):
        add_unique(
            "text_desc", (node.text_val, node.desc_val), "direct:text_desc",
            _combine_score(text_score, desc_score, bonus=10, limit=92),
            ("text", node.text_val), ("description", node.desc_val),
        )
    if (
        node.type_val and node.text_val and node.text_attr_name == "text"
        and not text_is_unique
    ):
        add_unique(
            "type_text", (node.type_val, node.text_val), "direct:type_text",
            _combine_score(type_score, text_score, bonus=12, limit=90),
            (node.type_selector_name, node.type_val), ("text", node.text_val),
        )
    if node.type_val and node.desc_val and not desc_is_unique:
        add_unique(
            "type_desc", (node.type_val, node.desc_val), "direct:type_desc",
            _combine_score(type_score, desc_score, bonus=11, limit=88),
            (node.type_selector_name, node.type_val),
            ("description", node.desc_val),
        )

    return candidates


def _semantic_descendant_selector_candidates(
    target_node: WidgetNode,
    dfs_nodes: List[WidgetNode],
    counters: Dict[str, Counter],
) -> List[_SelectorCandidate]:
    """用可点击容器内部的唯一语义节点定位同一用户目标。"""
    if not _is_interactive_node(target_node):
        return []

    descendants = _descendants_of(target_node, dfs_nodes)
    text_candidates: List[_SelectorCandidate] = []
    desc_candidates: List[_SelectorCandidate] = []
    for node in descendants:
        if node.text_val and node.text_attr_name == "text":
            score = min(96, _text_score(node.text_val) + 6)
            if score >= 70 and counters["text"][node.text_val] == 1:
                text_candidates.append(
                    _selector_candidate(
                        expr=f"d(text={_py_literal(node.text_val)})",
                        score=score,
                        kind="direct:text",
                    )
                )
        if node.desc_val:
            score = min(94, _description_score(node.desc_val) + 5)
            if score >= 70 and counters["desc"][node.desc_val] == 1:
                desc_candidates.append(
                    _selector_candidate(
                        expr=f"d(description={_py_literal(node.desc_val)})",
                        score=score,
                        kind="direct:desc",
                    )
                )

    unique_text_candidates = _dedupe_selector_candidates(text_candidates)
    if len(unique_text_candidates) == 1:
        return unique_text_candidates
    unique_desc_candidates = _dedupe_selector_candidates(desc_candidates)
    if not unique_text_candidates and len(unique_desc_candidates) == 1:
        return unique_desc_candidates
    return []


def _dedupe_selector_candidates(
    candidates: List[_SelectorCandidate],
) -> List[_SelectorCandidate]:
    """按最终表达式去重，避免同一语义后代重复提高候选数量。"""
    return list({candidate.expr: candidate for candidate in candidates}.values())


def _descendants_of(
    target_node: WidgetNode,
    dfs_nodes: List[WidgetNode],
) -> List[WidgetNode]:
    """按父子关系收集目标容器的全部语义后代。"""
    by_parent: Dict[Optional[str], List[WidgetNode]] = {}
    for node in dfs_nodes:
        by_parent.setdefault(node.parent_id, []).append(node)

    descendants: List[WidgetNode] = []
    pending = list(by_parent.get(target_node.node_id, []))
    pending_index = 0
    while pending_index < len(pending):
        node = pending[pending_index]
        pending_index += 1
        if _is_interactive_node(node):
            continue
        descendants.append(node)
        pending.extend(by_parent.get(node.node_id, []))
    return descendants


def _is_interactive_node(node: WidgetNode) -> bool:
    """识别能代表真实用户操作的原生控件或显式可交互节点。"""
    short_type = str(node.type_val or "").rsplit(".", 1)[-1]
    if short_type in _INTERACTIVE_TYPE_VALUES:
        return True
    attrs = node.attributes
    return any(
        str(attrs.get(name, "")).strip().lower() in {"true", "1", "yes"}
        for name in ("clickable", "longClickable", "long_clickable", "checkable")
    )


def _is_editable_node(node: WidgetNode) -> bool:
    """识别可安全承接 input_text 的输入控件。"""
    short_type = str(node.type_val or "").rsplit(".", 1)[-1]
    if short_type in _EDITABLE_TYPE_VALUES:
        return True
    return str(node.attributes.get("editable", "")).strip().lower() in {
        "true",
        "1",
        "yes",
    }


def _relative_selector_candidates(
    target_node: WidgetNode,
    dfs_nodes: List[WidgetNode],
    counters: Dict[str, Counter],
) -> List[_SelectorCandidate]:
    """仅用同父兄弟语义锚点生成方向可验证的 before/after 候选。"""
    candidates: List[_SelectorCandidate] = []
    siblings_by_parent: Dict[Optional[str], List[WidgetNode]] = {}
    for node in dfs_nodes:
        siblings_by_parent.setdefault(node.parent_id, []).append(node)
    sibling_nodes = siblings_by_parent.get(target_node.parent_id, [])
    sibling_positions = {
        node.node_id: position
        for position, node in enumerate(sibling_nodes)
    }
    target_position = sibling_positions.get(target_node.node_id)
    if target_position is None:
        return candidates
    anchor_ranges = (
        ("after", range(target_position - 1, -1, -1)),
        ("before", range(target_position + 1, len(sibling_nodes))),
    )

    for relation, anchor_positions in anchor_ranges:
        for anchor_position in anchor_positions:
            anchor_node = sibling_nodes[anchor_position]
            anchor_choice = _best_args_candidate(
                _direct_selector_args_candidates(anchor_node, counters),
                min_score=78,
            )
            if not anchor_choice or anchor_choice.kind == "direct:type":
                continue

            if relation == "after":
                sub_nodes = sibling_nodes[anchor_position + 1:]
            else:
                sub_nodes = sibling_nodes[:anchor_position]
            target_choices = _relative_target_args_candidates(target_node, sub_nodes)
            for target_choice in target_choices:
                distance = abs(target_position - anchor_position)
                distance_penalty = min(18, max(0, distance - 1) // 2)
                score = min(
                    86,
                    int((anchor_choice.score + target_choice.score) / 2)
                    + 6
                    - distance_penalty,
                )
                if score < 70:
                    continue
                candidates.append(
                    _selector_candidate(
                        expr=(
                            f"d({anchor_choice.args})"
                            f".{relation}({target_choice.args})"
                        ),
                        score=score,
                        kind="relative",
                    )
                )

    return candidates


def _relative_target_args_candidates(
    target_node: WidgetNode,
    sub_nodes: List[WidgetNode],
) -> List[_SelectorArgsCandidate]:
    """在锚点对应方向的同级节点中生成可证明唯一的目标参数。"""
    candidates: List[_SelectorArgsCandidate] = []
    id_score = _identity_score(target_node.id_val)
    text_score = _text_score(target_node.text_val)
    desc_score = _description_score(target_node.desc_val)
    type_score = _type_score(target_node.type_val)

    def add_if_unique(
        kind: str,
        score: int,
        *items: Tuple[str, Any],
        min_score: int = 70,
    ) -> None:
        """过滤低可信候选，并确认目标在关系方向内只命中一次。"""
        if score < min_score:
            return
        if _count_matching_items(sub_nodes, items) == 1:
            candidates.append(_selector_args_candidate(items, score, kind))

    if target_node.text_val and target_node.text_attr_name == "text":
        add_if_unique("relative:text", text_score, ("text", target_node.text_val))
    if target_node.desc_val:
        add_if_unique(
            "relative:desc", desc_score, ("description", target_node.desc_val)
        )
    if target_node.id_val:
        add_if_unique(
            "relative:id", id_score,
            (target_node.id_selector_name, target_node.id_val),
        )
    if target_node.type_val and not _is_generic_type(target_node.type_val):
        short_type = target_node.type_val.rsplit(".", 1)[-1]
        add_if_unique(
            "relative:type", type_score,
            (target_node.type_selector_name, target_node.type_val),
            min_score=60 if short_type in _INTERACTIVE_TYPE_VALUES else 70,
        )
    if target_node.id_val and target_node.text_val and target_node.text_attr_name == "text":
        add_if_unique(
            "relative:id_text",
            _combine_score(id_score, text_score, bonus=12, limit=94),
            (target_node.id_selector_name, target_node.id_val),
            ("text", target_node.text_val),
        )
    if target_node.type_val and target_node.text_val and target_node.text_attr_name == "text":
        add_if_unique(
            "relative:type_text",
            _combine_score(type_score, text_score, bonus=10, limit=90),
            (target_node.type_selector_name, target_node.type_val),
            ("text", target_node.text_val),
        )
    if target_node.type_val and target_node.desc_val:
        add_if_unique(
            "relative:type_desc",
            _combine_score(type_score, desc_score, bonus=10, limit=88),
            (target_node.type_selector_name, target_node.type_val),
            ("description", target_node.desc_val),
        )

    return candidates


def _xpath_selector_candidates(
    target_node: WidgetNode,
    dfs_nodes: List[WidgetNode],
) -> List[_SelectorCandidate]:
    """把唯一且不依赖 bounds、类型序号或绝对路径的 XPath 纳入候选。"""
    candidates: List[_SelectorCandidate] = []
    for xpath_candidate in generate_xpath_candidates_for_node(target_node, dfs_nodes):
        xpath = xpath_candidate.get("xpath")
        by = xpath_candidate.get("by")
        if (
            not xpath
            or not xpath_candidate.get("unique")
            or by in {"bounds", "class", "path"}
        ):
            continue
        candidates.append(
            _selector_candidate(
                expr=f"d.xpath({_py_literal(xpath)})",
                score=_xpath_score(target_node, xpath_candidate),
                kind="xpath",
            )
        )
    return candidates


def _selector_args_candidate(
    items: Tuple[Tuple[str, Any], ...],
    score: int,
    kind: str,
) -> _SelectorArgsCandidate:
    """构建已归一化分数的选择器参数候选。"""
    return _SelectorArgsCandidate(
        args=_selector_args(*items),
        score=_clip_score(score),
        kind=kind,
    )


def _selector_candidate(expr: str, score: int, kind: str) -> _SelectorCandidate:
    """构建完整表达式候选并绑定同分时使用的类型优先级。"""
    base_kind = kind if kind in _KIND_PRIORITY else kind.split(":", 1)[0]
    return _SelectorCandidate(
        expr=expr,
        score=_clip_score(score),
        priority=_KIND_PRIORITY.get(base_kind, 0),
        kind=kind,
    )


def _best_args_candidate(
    candidates: List[_SelectorArgsCandidate],
    min_score: int = 0,
) -> Optional[_SelectorArgsCandidate]:
    """选择分数最高、类型更稳定且表达更短的参数候选。"""
    return max(
        (candidate for candidate in candidates if candidate.score >= min_score),
        key=lambda candidate: (
            candidate.score,
            _KIND_PRIORITY.get(candidate.kind, 0),
            -len(candidate.args),
        ),
        default=None,
    )


def _best_selector_candidate(
    candidates: List[_SelectorCandidate],
    min_score: int = 0,
) -> Optional[_SelectorCandidate]:
    """选择满足可信阈值且最稳定、最简洁的完整定位表达式。"""
    return max(
        (candidate for candidate in candidates if candidate.score >= min_score),
        key=lambda candidate: (
            candidate.score,
            candidate.priority,
            -len(candidate.expr),
        ),
        default=None,
    )


def _count_matching_items(
    nodes: List[WidgetNode],
    items: Tuple[Tuple[str, Any], ...],
) -> int:
    """统计参数组合在指定节点范围内的精确匹配数。"""
    return sum(1 for node in nodes if _node_matches_items(node, items))


def _node_matches_items(
    node: WidgetNode,
    items: Tuple[Tuple[str, Any], ...],
) -> bool:
    """判断节点是否满足选择器参数中的全部精确条件。"""
    return all(
        str(_selector_item_value(node, name)) == str(value)
        for name, value in items
    )


def _selector_item_value(node: WidgetNode, name: str) -> Any:
    """按 devhelmkit 选择器字段语义读取节点原始值。"""
    attrs = node.attributes
    if name == "text":
        return node.text_val
    if name == "description":
        return node.desc_val
    if name == "key":
        return attrs.get("key", "")
    if name == "id":
        return attrs.get("id", "")
    if name == "resourceId":
        return attrs.get("resourceId") or attrs.get("resource-id") or ""
    if name == "className":
        return attrs.get("className") or attrs.get("class") or ""
    if name == "type":
        return attrs.get("type", "")
    return attrs.get(name, "")


def _xpath_score(target_node: WidgetNode, candidate: Dict[str, Any]) -> int:
    """结合属性稳定性、唯一性和类型语义评估 XPath 可信度。"""
    by = str(candidate.get("by") or "")
    matches = _safe_int(candidate.get("matches"), 1)
    unique = bool(candidate.get("unique"))
    class_score = 52 if _is_generic_type(target_node.xpath_tag) else 70
    base_scores = {
        "key": _identity_score(str(target_node.attributes.get("key") or "")) + 6,
        "id": _identity_score(str(target_node.attributes.get("id") or "")) + 6,
        "resourceId": _identity_score(
            str(
                target_node.attributes.get("resourceId")
                or target_node.attributes.get("resource-id")
                or ""
            )
        ) + 6,
        "text": _text_score(target_node.text_val) + 4,
        "value": _text_like_xpath_score(target_node, "value"),
        "content": _text_like_xpath_score(target_node, "content"),
        "label": _text_like_xpath_score(target_node, "label"),
        "originalText": _text_like_xpath_score(target_node, "originalText"),
        "hint": _text_like_xpath_score(target_node, "hint"),
        "placeholder": _text_like_xpath_score(target_node, "placeholder"),
        "description": _description_score(target_node.desc_val) + 4,
        "desc": _description_score(target_node.desc_val) + 4,
        "className": _type_score(target_node.type_val) + 2,
        "class": class_score,
        "bounds": 42,
        "path": 56,
    }
    score = base_scores.get(by, 50)
    if unique:
        score += 8
    elif by == "class":
        score -= min(6, max(0, matches - 1) // 10)
    else:
        score -= min(14, max(0, matches - 1) // 3)
    return _clip_score(min(score, 84))


def _text_like_xpath_score(target_node: WidgetNode, attr_name: str) -> int:
    """评估 value、hint 等类文本属性的 XPath 稳定性。"""
    value = target_node.attributes.get(attr_name)
    if value is None:
        return 0
    return min(82, _text_score(value) + 2)


def _combine_score(
    first: int,
    second: int,
    bonus: int,
    limit: int,
) -> int:
    """合并两个属性分数，并限制组合定位不能超过其可信上限。"""
    return min(limit, int((first + second) / 2) + bonus)


def _identity_values(node: WidgetNode) -> List[Tuple[str, str]]:
    """返回节点所有可执行身份属性，避免动态 key 遮蔽稳定 id。"""
    attrs = node.attributes
    identities: List[Tuple[str, str]] = []
    for attr_name, selector_name in (
        ("key", "key"),
        ("id", "id"),
        ("resourceId", "resourceId"),
        ("resource-id", "resourceId"),
    ):
        value = str(attrs.get(attr_name) or "").strip()
        identity = (selector_name, value)
        if value and identity not in identities:
            identities.append(identity)
    return identities


def _identity_score(value: Any) -> int:
    """降低 UUID、时间戳、长哈希和无意义身份值的定位可信度。"""
    text = str(value or "").strip()
    if not text:
        return 0
    lowered = text.lower()
    if any(marker in lowered for marker in ("undefined", "[object object]", "null_")):
        return 20
    if re.fullmatch(
        r"[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[1-5][0-9a-fA-F]{3}-[89abAB][0-9a-fA-F]{3}-[0-9a-fA-F]{12}",
        text,
    ):
        return 24
    if re.search(r"(?:^|[_-])\d{10,}(?:[_-]|$)", text):
        return 30
    if text.isdigit():
        return 28
    if len(text) > 96:
        return 32
    if re.fullmatch(r"[0-9a-fA-F]{12,}", text):
        return 36
    if re.search(r"[A-Za-z_]{6,}\d{2,}$", text):
        return 42
    if re.search(r"\d{5,}", text):
        return 40
    if text.count(".") >= 4 or text.count("/") >= 4:
        return 48
    if len(text) > 64:
        return 50
    return 90


def _text_score(value: Any) -> int:
    """降低长文本、多行文本和纯数字文本的定位可信度。"""
    text = str(value or "").strip()
    if not text:
        return 0
    if "\n" in text or "\r" in text or len(text) > 120:
        return 20
    if len(text) > 60:
        return 58
    if text.isdigit():
        return 58
    return 90


def _description_score(value: Any) -> int:
    """按长度评估无障碍描述作为定位语义的稳定性。"""
    text = str(value or "").strip()
    if not text:
        return 0
    if len(text) > 120:
        return 42
    if len(text) > 60:
        return 64
    return 88


def _type_score(value: Any) -> int:
    """优先原生交互类型，降低通用容器类型的定位可信度。"""
    text = str(value or "").strip()
    if not text:
        return 0
    short_type = text.rsplit(".", 1)[-1]
    if _is_generic_type(text):
        return 38
    if short_type in _INTERACTIVE_TYPE_VALUES:
        return 72
    return 62


def _is_container_type(value: Any) -> bool:
    """识别不应仅凭当前唯一性直接生成定位器的通用容器。"""
    text = str(value or "").strip().rsplit(".", 1)[-1]
    return text.endswith(("Dialog", "Panel", "TitleBar", "Toolbar"))


def _is_generic_type(value: Any) -> bool:
    """判断类型是否缺少足以独立定位用户目标的业务语义。"""
    text = str(value or "").strip()
    short_name = text.rsplit(".", 1)[-1]
    return short_name in _GENERIC_TYPE_VALUES or _is_container_type(short_name)


def _clip_score(score: int) -> int:
    """把候选可信度限制在统一的 0 到 100 区间。"""
    return max(0, min(100, int(score)))


def _safe_int(value: Any, default: int) -> int:
    """解析候选元数据整数，无效值使用调用方默认值。"""
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def generate_action_code(
    selector: Optional[str], action: str, params: Dict[str, Any], x: int, y: int
) -> str:
    """根据动作类型和选择器拼接 python 自动化代码语句。"""
    if action not in _SUPPORTED_ACTIONS:
        raise ValueError(f"不支持的录制动作: {action}")

    x_arg = _py_int(x)
    y_arg = _py_int(y)

    if action == "swipe":
        ex = _py_int(params.get("ex", x))
        ey = _py_int(params.get("ey", y))
        duration = _py_float(params.get("duration", 0.5))
        return f"d.swipe({x_arg}, {y_arg}, {ex}, {ey}, duration={duration})"

    if selector:
        if action == "click":
            return f"{selector}.click()"
        if action == "long_click":
            duration = _py_float(params.get("duration", 0.5))
            return f"{selector}.long_click(duration={duration})"
        if action == "double_click":
            return f"{selector}.double_click()"
        text = params.get("text", "")
        return f"{selector}.input_text({_py_literal(text)})"

    if action == "click":
        return f"d.click({x_arg}, {y_arg})"
    if action == "long_click":
        duration = _py_float(params.get("duration", 0.5))
        return f"d.long_click({x_arg}, {y_arg}, duration={duration})"
    if action == "double_click":
        return f"d.double_click({x_arg}, {y_arg})"
    text = params.get("text", "")
    return f"d.click({x_arg}, {y_arg})\nd.input_text_on_cursor({_py_literal(text)})"
