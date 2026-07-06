# !/usr/bin/env python
# -*- coding: utf-8 -*-
"""ComponentFinder：鸿蒙控件查找统一门面。

职责：
- 将 SelectorSpec 转为设备端 By/On 链（通过 selector_adapter + RPC）
- 调用 Driver.findComponent / Driver.waitForComponent 获取 Component 引用
- 在 Component 引用上执行操作方法
- 弹窗自动消除（配置开启时，查找失败自动尝试消除弹窗后重试）

By/On 链构造流程：
    On#seed (静态根)
      → On.text("xx", pattern) → By#1
      → On.id("yy")           → By#2 (this=By#1)
      → On.within(parent_ref) → By#3 (this=By#2, args=[parent_ref])

关系选择器递归处理：先构造 parent By 链，再在 child By 链末尾
调用 On.within / On.isAfter / On.isBefore。
"""
import json
import logging
import re
import time
from typing import Any, Dict, List, Optional, Tuple, TYPE_CHECKING

from devhelmkit.core.selector_spec import SelectorSpec, build_selector
from devhelmkit.exceptions import ComponentNotFoundError, DevhelmError, RpcError
from devhelmkit.harmony.finder.selector_adapter import (
    RELATION_API,
    selector_to_by_chain,
)
from devhelmkit.harmony.finder.xpath_query import query_xpath
from devhelmkit.harmony.finder.popup_handler import PopupHandler
from devhelmkit.harmony.rpc.proxy_v2 import rpc_captures

logger = logging.getLogger(__name__)

if TYPE_CHECKING:
    from devhelmkit.harmony.config import HarmonyDriverConfig
    from devhelmkit.harmony.rpc.client import RpcClient

# 设备端静态对象引用
DRIVER_REF = "Driver#0"
ON_SEED_REF = "On#seed"

# 默认查找超时（秒）
DEFAULT_FIND_TIMEOUT = 10.0


class ComponentFinder:
    """鸿蒙控件查找门面，统一对接设备端 uitest 服务。"""

    def __init__(self, rpc: 'RpcClient', config: 'HarmonyDriverConfig'):
        self._rpc = rpc
        self._config = config
        self._popup_handler = PopupHandler(
            self.find_component, rpc, config
        )

    # ============================================================
    # 控件查找
    # ============================================================

    def find_component(self, selector: SelectorSpec,
                       timeout: float = DEFAULT_FIND_TIMEOUT) -> str:
        """查找单个控件，返回 Component 对象引用。

        Args:
            selector: 控件定位条件
            timeout: 查找超时（秒）

        Returns:
            设备端 Component 对象引用（如 "Component#3"）

        Raises:
            ComponentNotFoundError: 控件未找到
            RpcError: RPC 通信异常
        """
        # xpath 选择器走客户端查询：dump 控件树 → 查询节点 → 降级 SelectorSpec → By 链
        if selector.xpath is not None:
            return self._find_by_xpath(selector, timeout)
        by_ref = self._build_by_ref(selector)
        timeout_ms = int(timeout * 1000)
        try:
            result = self._rpc.call(
                "Driver.waitForComponent", DRIVER_REF, [by_ref, timeout_ms]
            )
        except RpcError as e:
            if self._should_dismiss_popup():
                logger.debug("控件查找失败，尝试消除弹窗后重试: %s",
                             _format_selector(selector))
                if self._popup_handler.dismiss_popups():
                    result = self._rpc.call(
                        "Driver.waitForComponent", DRIVER_REF,
                        [by_ref, timeout_ms]
                    )
                else:
                    raise ComponentNotFoundError(
                        "控件未找到: %s" % _format_selector(selector)
                    ) from e
            else:
                raise
        if not result:
            raise ComponentNotFoundError(
                "控件未找到: %s" % _format_selector(selector)
            )
        return result

    def find_components(self, selector: SelectorSpec) -> list:
        """查找所有匹配控件，返回 Component 引用列表。

        不等待，立即返回当前匹配结果。

        Args:
            selector: 控件定位条件

        Returns:
            Component 对象引用列表（可能为空）
        """
        if selector.xpath is not None:
            return self._find_components_by_xpath(selector)
        by_ref = self._build_by_ref(selector)
        result = self._rpc.call("Driver.findComponents", DRIVER_REF, [by_ref])
        return result if isinstance(result, list) else []

    def component_exists(self, selector: SelectorSpec) -> bool:
        """检查控件是否存在。

        xpath 选择器直接在控件树上查询，无需构造 By 链。
        """
        if selector.xpath is not None:
            return bool(self._query_xpath_nodes(selector))
        return bool(self.find_components(selector))

    def wait_component(self, selector: SelectorSpec,
                       timeout: float) -> bool:
        """等待控件出现，返回是否出现。"""
        try:
            self.find_component(selector, timeout)
            return True
        except ComponentNotFoundError:
            return False

    def wait_component_gone(self, selector: SelectorSpec,
                            timeout: float) -> bool:
        """等待控件消失，返回是否消失。

        渐进轮询：首次 0.1s → 0.2s → 0.5s 递增，避免固定 0.5s 导致
        消失场景响应慢。
        """
        deadline = time.monotonic() + timeout
        interval = 0.1
        while time.monotonic() < deadline:
            if not self.component_exists(selector):
                return True
            remaining = deadline - time.monotonic()
            time.sleep(min(interval, remaining))
            interval = min(interval * 2, 0.5)
        return not self.component_exists(selector)

    # ============================================================
    # 控件操作
    # ============================================================

    def call_component(self, selector: SelectorSpec, method: str,
                       args: Optional[list] = None,
                       timeout: float = DEFAULT_FIND_TIMEOUT) -> Any:
        """查找控件并调用其方法。

        Args:
            selector: 控件定位条件
            method: Component 方法名（如 "click"、"getText"）
            args: 方法参数列表
            timeout: 查找超时

        Returns:
            方法返回值
        """
        component_ref = self.find_component(selector, timeout)
        return self._rpc.call("Component." + method, component_ref, args or [])

    def call_component_by_ref(self, component_ref: str, method: str,
                              args: Optional[list] = None) -> Any:
        """直接在 Component 引用上调用方法（跳过查找）。

        用于已持有 Component 引用的场景，避免重复查找。
        """
        return self._rpc.call("Component." + method, component_ref, args or [])

    def find_component_ref(self, selector: SelectorSpec,
                           timeout: float = DEFAULT_FIND_TIMEOUT) -> str:
        """查找控件并返回 Component 引用，语义等同于 find_component。"""
        return self.find_component(selector, timeout)

    def get_properties_from_tree(self, selector: SelectorSpec,
                                 timeout: float = DEFAULT_FIND_TIMEOUT) -> Optional[Dict[str, Any]]:
        """通过控件树一次性获取目标控件的全部属性。

        Args:
            selector: 控件定位条件
            timeout: 查找超时（秒）

        Returns:
            属性字典（含 text/id/type/enabled/focused/selected/clickable/
            long_clickable/scrollable/checkable/checked/description/bounds），
            未找到返回 None。
        """
        tree = self._dump_layout()
        if tree is None:
            return None
        # xpath selector 走 xpath 查询取首个命中节点；否则按属性匹配。
        # 不能对 xpath selector 走 _match_node_in_tree：其非 xpath 字段全为
        # None，会命中根节点造成误匹配。
        if selector.xpath is not None:
            nodes = query_xpath(tree, selector.xpath)
            node = nodes[0] if nodes else None
        else:
            node = _match_node_in_tree(tree, selector)
        if node is None:
            return None
        attrs = node.get("attributes") or {}
        return _extract_properties_from_attrs(attrs)

    # ============================================================
    # By/On 链构造
    # ============================================================

    def _build_by_ref(self, selector: SelectorSpec) -> str:
        """通过 RPC 顺序调用构造 By/On 链，返回 By 对象引用。

        递归处理关系选择器：先构造 parent By 链，再在 child By 链
        末尾调用 On.within / On.isAfter / On.isBefore。
        """
        chain = selector_to_by_chain(selector)
        by_ref = ON_SEED_REF
        for api_name, args in chain:
            by_ref = self._rpc.call(api_name, by_ref, args)

        # 关系选择器：在 child By 链末尾追加关系调用
        if selector.parent is not None and selector.relation:
            parent_ref = self._build_by_ref(selector.parent)
            relation_api = RELATION_API.get(selector.relation)
            if relation_api is not None:
                by_ref = self._rpc.call(relation_api, by_ref, [parent_ref])
            elif selector.relation == 'sibling':
                # OpenHarmony On API 仅提供 within/isAfter/isBefore，无 sibling
                # 对应能力。静默忽略会返回错误控件，故显式报错，引导改用
                # child()/after()/before() 组合表达兄弟关系。
                raise DevhelmError(
                    "sibling 关系选择器在 HarmonyOS 平台不受支持，"
                    "请改用 after()/before() 或 parent().child() 表达"
                )

        return by_ref

    # ============================================================
    # xpath 客户端查询
    # 设备端 uitest 不支持 xpath，通过 Captures.captureLayout 获取控件树
    # JSON 后，在客户端执行标准 XPath（见 xpath_query），再将命中节点用
    # bounds 精确锚定回设备端 Component ref，复用 Component 引用机制。
    # ============================================================

    def _dump_layout(self) -> Optional[Dict[str, Any]]:
        """通过 uitest RPC (Captures.captureLayout) 获取控件树。

        比 hdc shell dumpLayout 快，无需文件中转。
        """
        reply = rpc_captures(self._rpc.device, "captureLayout", {})
        try:
            data = json.loads(reply)
        except json.JSONDecodeError as e:
            logger.error("控件树响应解析失败: %s", e)
            return None
        if isinstance(data, dict):
            if data.get('error'):
                logger.warning("captureLayout 调用失败: %s", data['error'])
                return None
            if data.get('exception'):
                msg = data['exception'].get('message', str(data['exception']))
                logger.warning("captureLayout 调用异常: %s", msg)
                return None
            if 'result' in data:
                data = data['result']
        return data if isinstance(data, dict) else None

    def _query_xpath_nodes(self, selector: SelectorSpec) -> List[Dict[str, Any]]:
        """执行 xpath 查询，返回匹配节点列表。"""
        if not selector.xpath:
            return []
        tree = self._dump_layout()
        if tree is None:
            return []
        return query_xpath(tree, selector.xpath)

    def _anchor_node_to_ref(self, node: Dict[str, Any]) -> Optional[str]:
        """把 xpath 命中的控件树节点锚定回设备端 Component ref。

        锚定原理（已真机验证）：captureLayout 树里的 bounds 与设备端
        Component.getBounds 逐值相等，故用 bounds 作几何唯一键。

        流程：
            findComponents(On.type(节点.type))  → 同 type 候选 refs
              → 逐个 getBounds 与目标 bounds 精确比对
              → 命中即锚定；无命中返回 None

        为何不走属性降级：text/id 在重复控件场景无法唯一区分，位置语义
        （如 (//Button)[2]）在降级时丢失。bounds 是屏上唯一的几何锚点。

        Returns:
            锚定到的 Component ref；无法锚定返回 None。
        """
        attrs = node.get("attributes") or {}
        target_bounds = _parse_bounds_quad(attrs.get("bounds"))
        node_type = attrs.get("type")
        if target_bounds is None or not node_type:
            logger.debug("节点缺少 bounds 或 type，无法锚定: %r", attrs)
            return None

        by_ref = self._build_by_ref(build_selector(type=node_type))
        candidates = self._rpc.call(
            "Driver.findComponents", DRIVER_REF, [by_ref]
        )
        if not isinstance(candidates, list):
            return None
        for ref in candidates:
            try:
                bounds_data = self._rpc.call("Component.getBounds", ref, [])
            except RpcError:
                continue
            if _bounds_data_to_quad(bounds_data) == target_bounds:
                return ref
        logger.debug("bounds 锚定未命中 (type=%s bounds=%s 候选数=%d)",
                     node_type, target_bounds, len(candidates))
        return None

    def _find_by_xpath(self, selector: SelectorSpec,
                       timeout: float) -> str:
        """xpath 选择器查找单个控件。

        dump 控件树 → 标准 XPath 查询 → 取首个命中节点 → bounds 锚定回 ref。
        """
        nodes = self._query_xpath_nodes(selector)
        if not nodes:
            raise ComponentNotFoundError(
                "xpath 未匹配控件: %s" % selector.xpath
            )
        ref = self._anchor_node_to_ref(nodes[0])
        if ref is None:
            raise ComponentNotFoundError(
                "xpath 命中节点但无法锚定到设备端控件: %s" % selector.xpath
            )
        return ref

    def _find_components_by_xpath(self, selector: SelectorSpec) -> list:
        """xpath 选择器查找所有匹配控件。

        对每个命中节点做 bounds 锚定，收集锚定成功的 Component ref。
        bounds 唯一，天然去重，无需按降级条件合并。
        """
        nodes = self._query_xpath_nodes(selector)
        refs: list = []
        for node in nodes:
            ref = self._anchor_node_to_ref(node)
            if ref is not None:
                refs.append(ref)
        return refs

    # ============================================================
    # 弹窗处理
    # ============================================================

    def _should_dismiss_popup(self) -> bool:
        """判断是否启用弹窗自动消除。"""
        return self._config.pop_window_dismiss == "enable"


_BOUNDS_STR_RE = re.compile(r'\[(-?\d+),(-?\d+)\]\[(-?\d+),(-?\d+)\]')

BoundsQuad = Tuple[int, int, int, int]  # (left, top, right, bottom)


def _parse_bounds_quad(raw: Any) -> Optional[BoundsQuad]:
    """解析控件树里的 bounds 字符串 "[l,t][r,b]" 为四元组。"""
    if not isinstance(raw, str):
        return None
    m = _BOUNDS_STR_RE.search(raw)
    if not m:
        return None
    return (int(m.group(1)), int(m.group(2)),
            int(m.group(3)), int(m.group(4)))


def _bounds_data_to_quad(data: Any) -> Optional[BoundsQuad]:
    """把 Component.getBounds 返回值归一化为四元组。

    设备端可能返回 dict {left,top,right,bottom} 或 list [l,t,r,b]。
    """
    if isinstance(data, dict):
        try:
            return (int(data["left"]), int(data["top"]),
                    int(data["right"]), int(data["bottom"]))
        except (KeyError, TypeError, ValueError):
            return None
    if isinstance(data, (list, tuple)) and len(data) >= 4:
        try:
            return (int(data[0]), int(data[1]),
                    int(data[2]), int(data[3]))
        except (TypeError, ValueError):
            return None
    return None


def _format_selector(selector: SelectorSpec) -> str:
    """格式化选择器为可读字符串，用于异常信息。"""
    parts = []
    if selector.text is not None:
        parts.append("text=%r" % selector.text)
    if selector.text_contains is not None:
        parts.append("textContains=%r" % selector.text_contains)
    if selector.resource_id is not None:
        parts.append("resourceId=%r" % selector.resource_id)
    if selector.key is not None:
        parts.append("key=%r" % selector.key)
    if selector.class_name is not None:
        parts.append("className=%r" % selector.class_name)
    if selector.xpath is not None:
        parts.append("xpath=%r" % selector.xpath)
    return ", ".join(parts) if parts else str(selector)


def _match_node_in_tree(tree: Dict[str, Any],
                        selector: SelectorSpec) -> Optional[Dict[str, Any]]:
    """在控件树中按 SelectorSpec 条件匹配第一个节点。

    支持 text/text_contains/resource_id/key/type/class_name 匹配，
    不支持关系选择器和 xpath（那些走原有路径）。
    """
    results: List[Dict[str, Any]] = []
    _traverse_match(tree, selector, results)
    return results[0] if results else None


def _traverse_match(node: Dict[str, Any], selector: SelectorSpec,
                    results: List[Dict[str, Any]]) -> None:
    """深度优先遍历，收集匹配 selector 的节点。"""
    attrs = node.get("attributes") or {}
    if _node_matches_selector(attrs, selector):
        results.append(node)
        return
    for child in node.get("children") or []:
        _traverse_match(child, selector, results)


def _node_matches_selector(attrs: Dict[str, Any], selector: SelectorSpec) -> bool:
    """检查节点属性是否满足 selector 全部非空条件。"""
    if selector.text is not None:
        if attrs.get("text") != selector.text:
            return False
    if selector.text_contains is not None:
        if selector.text_contains not in (attrs.get("text") or ""):
            return False
    if selector.text_starts_with is not None:
        if not (attrs.get("text") or "").startswith(selector.text_starts_with):
            return False
    if selector.text_ends_with is not None:
        if not (attrs.get("text") or "").endswith(selector.text_ends_with):
            return False
    if selector.resource_id is not None:
        if attrs.get("id") != selector.resource_id:
            return False
    if selector.key is not None:
        if attrs.get("key") != selector.key:
            return False
    if selector.class_name is not None:
        if attrs.get("type") != selector.class_name:
            return False
    if selector.type is not None:
        if attrs.get("type") != selector.type:
            return False
    if selector.desc is not None:
        if attrs.get("description") != selector.desc:
            return False
    if selector.desc_contains is not None:
        if selector.desc_contains not in (attrs.get("description") or ""):
            return False
    return True


def _extract_properties_from_attrs(attrs: Dict[str, Any]) -> Dict[str, Any]:
    """从控件树节点的 attributes 中提取全部属性，对齐 RPC 逐个获取的结果。"""
    def _bool(val: str) -> bool:
        return str(val).lower() == "true"

    def _bounds(val: str) -> Dict[str, int]:
        """解析 "[left,top][right,bottom]" 格式。"""
        m = re.match(r'\[(\d+),(\d+)\]\[(\d+),(\d+)\]', val or "")
        if m:
            return {
                "left": int(m.group(1)), "top": int(m.group(2)),
                "right": int(m.group(3)), "bottom": int(m.group(4)),
            }
        return {"left": 0, "top": 0, "right": 0, "bottom": 0}

    return {
        "text": attrs.get("text", ""),
        "id": attrs.get("id", ""),
        "type": attrs.get("type", ""),
        "enabled": _bool(attrs.get("enabled", "false")),
        "focused": _bool(attrs.get("focused", "false")),
        "selected": _bool(attrs.get("selected", "false")),
        "clickable": _bool(attrs.get("clickable", "false")),
        "long_clickable": _bool(attrs.get("longClickable", "false")),
        "scrollable": _bool(attrs.get("scrollable", "false")),
        "checkable": _bool(attrs.get("checkable", "false")),
        "checked": _bool(attrs.get("checked", "false")),
        "description": attrs.get("description", ""),
        "bounds": _bounds(attrs.get("bounds", "")),
    }
