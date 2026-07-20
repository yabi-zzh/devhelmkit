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
from dataclasses import replace
from typing import Any, Dict, List, Optional, Tuple, TYPE_CHECKING

from devhelmkit.core.selector_spec import SelectorSpec, build_selector
from devhelmkit.exceptions import ComponentNotFoundError, DevhelmError, RpcError
from devhelmkit.harmony.finder.selector_adapter import (
    RELATION_API,
    selector_to_by_chain,
)
from devhelmkit.harmony.finder.xpath_query import (
    extract_node_attributes,
    is_valid_xpath,
    query_xpath,
)
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

# 可无损下推为设备端 On.type 的纯类型 XPath。
_SIMPLE_TYPE_XPATH_RE = re.compile(r'^\s*//([A-Za-z_][\w.\-]*)\s*$')


def _simple_type_xpath_selector(xpath: Optional[str]) -> Optional[SelectorSpec]:
    """把纯类型 XPath 转为设备端选择器，复杂表达式返回 None。"""
    if not xpath:
        return None
    match = _SIMPLE_TYPE_XPATH_RE.fullmatch(xpath)
    if match is None:
        return None
    return build_selector(type=match.group(1))


class ComponentFinder:
    """鸿蒙控件查找门面，统一对接设备端 uitest 服务。"""

    def __init__(self, rpc: 'RpcClient', config: 'HarmonyDriverConfig'):
        """初始化 RPC 客户端、运行配置和弹窗处理器。"""
        self._rpc = rpc
        self._config = config
        self._popup_handler = PopupHandler(
            self.find_components, rpc, config
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
        # 纯类型 xpath 可无损下推到设备端，跳过 captureLayout 与 bounds 锚定。
        if selector.xpath is not None:
            direct_selector = _simple_type_xpath_selector(selector.xpath)
            if direct_selector is not None:
                if selector.instance is not None:
                    direct_selector = replace(
                        direct_selector, instance=selector.instance
                    )
                try:
                    return self.find_component(direct_selector, timeout)
                except ComponentNotFoundError as e:
                    raise ComponentNotFoundError(
                        "xpath 未匹配控件: %s" % selector.xpath
                    ) from e
            return self._find_by_xpath(selector, timeout)
        # instance 选择第 N 个匹配：设备端 On 链无对应能力，客户端轮询实现
        if selector.instance is not None:
            return self._find_by_instance(selector, timeout)
        by_ref = self._build_by_ref(selector)
        timeout_ms = int(timeout * 1000)
        try:
            result = self._rpc.call(
                "Driver.waitForComponent", DRIVER_REF, [by_ref, timeout_ms]
            )
        except RpcError as e:
            # RPC 异常路径：设备端查找过程报错时尝试消除弹窗后重试一次。
            if not self._should_dismiss_popup():
                raise
            logger.debug("控件查找 RPC 异常，尝试消除弹窗后重试: %s",
                         _format_selector(selector))
            if not self._popup_handler.dismiss_popups():
                raise ComponentNotFoundError(
                    "控件未找到: %s" % _format_selector(selector)
                ) from e
            result = self._retry_find_after_dismiss(by_ref)
        else:
            # 未命中路径：waitForComponent 未找到时可能返回空而非抛错，此路径
            # 同样尝试消除弹窗后重试一次，避免弹窗遮挡导致的稳定性失败。
            if not result and self._should_dismiss_popup():
                logger.debug("控件未命中，尝试消除弹窗后重试: %s",
                             _format_selector(selector))
                if self._popup_handler.dismiss_popups():
                    result = self._retry_find_after_dismiss(by_ref)
        if not result:
            raise ComponentNotFoundError(
                "控件未找到: %s" % _format_selector(selector)
            )
        return result

    def _find_by_instance(self, selector: SelectorSpec,
                          timeout: float) -> str:
        """等待第 instance 个（0 起）匹配控件出现并返回其引用。

        设备端 findComponents 为即时查询，这里以渐进退避轮询直到
        匹配数量足够或超时，对齐 waitForComponent 的等待语义。
        """
        instance = selector.instance or 0
        if instance < 0:
            raise DevhelmError("instance 不能为负数: %d" % instance)
        base = replace(selector, instance=None)
        deadline = time.monotonic() + max(timeout, 0.0)
        interval = 0.1
        first_attempt = True
        while first_attempt or time.monotonic() < deadline:
            first_attempt = False
            refs = self.find_components(base)
            if len(refs) > instance:
                return refs[instance]
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                break
            time.sleep(min(interval, remaining))
            interval = min(interval * 2, 0.5)
        raise ComponentNotFoundError(
            "控件未找到: %s (instance=%d)"
            % (_format_selector(selector), instance)
        )

    def _retry_find_after_dismiss(self, by_ref: str) -> Any:
        """弹窗消除成功后，按配置等待并以重试超时重新查找一次。

        wait_time_after_pop_window_dismiss 给弹窗关闭动画留时间，避免动画未完
        就重试仍被遮挡；pop_window_retry_find_timeout 控制这次补偿查找的超时，
        与首次查找超时解耦（重试通常无需再等满首次超时）。
        """
        wait_after = self._config.wait_time_after_pop_window_dismiss
        if wait_after and wait_after > 0:
            time.sleep(wait_after)
        retry_timeout_ms = int(
            self._config.pop_window_retry_find_timeout * 1000
        )
        return self._rpc.call(
            "Driver.waitForComponent", DRIVER_REF, [by_ref, retry_timeout_ms]
        )

    def find_components(self, selector: SelectorSpec) -> list:
        """查找所有匹配控件，返回 Component 引用列表。

        不等待，立即返回当前匹配结果。

        Args:
            selector: 控件定位条件

        Returns:
            Component 对象引用列表（可能为空）
        """
        if selector.xpath is not None:
            direct_selector = _simple_type_xpath_selector(selector.xpath)
            if direct_selector is not None:
                if selector.instance is not None:
                    direct_selector = replace(
                        direct_selector, instance=selector.instance
                    )
                return self.find_components(direct_selector)
            return self._pick_instance(
                self._find_components_by_xpath(selector), selector.instance
            )
        by_ref = self._build_by_ref(selector)
        result = self._rpc.call("Driver.findComponents", DRIVER_REF, [by_ref])
        refs = result if isinstance(result, list) else []
        return self._pick_instance(refs, selector.instance)

    @staticmethod
    def _pick_instance(refs: list, instance: Optional[int]) -> list:
        """instance 非空时收窄为第 N 个匹配（0 起），越界返回空列表。"""
        if instance is None:
            return refs
        if 0 <= instance < len(refs):
            return [refs[instance]]
        return []

    def component_exists(self, selector: SelectorSpec) -> bool:
        """检查控件是否存在。

        纯类型 xpath 下推设备端查询，复杂 xpath 在控件树上即时查询。
        """
        if selector.xpath is not None:
            direct_selector = _simple_type_xpath_selector(selector.xpath)
            if direct_selector is not None:
                return bool(self.find_components(direct_selector))
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
        # xpath selector 走 xpath 查询取命中节点；否则按属性匹配。
        # 不能对 xpath selector 走 _match_node_in_tree：其非 xpath 字段全为
        # None，会命中根节点造成误匹配。
        instance = selector.instance or 0
        if selector.xpath is not None:
            nodes = query_xpath(tree, selector.xpath)
            node = nodes[instance] if len(nodes) > instance else None
        else:
            node = _match_node_in_tree(tree, selector, instance=instance)
        if node is None:
            return None
        attrs = extract_node_attributes(node)
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
    # JSON 响应在客户端执行标准 XPath，再将命中节点用
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

        先用节点的 type 与可用身份属性缩小设备端候选集，再以 bounds 作
        最终唯一键。若控件树属性与设备端瞬时状态不一致，则回退到仅按
        type 查询，避免优化影响 XPath 位置语义和兼容性。
        """
        attrs = extract_node_attributes(node)
        target_bounds = _parse_bounds_quad(attrs.get("bounds"))
        node_type = attrs.get("type")
        if target_bounds is None or not node_type:
            logger.debug("节点缺少 bounds 或 type，无法锚定: %r", attrs)
            return None

        selectors = [_build_anchor_selector(attrs)]
        type_selector = build_selector(type=node_type)
        if selectors[0] != type_selector:
            selectors.append(type_selector)

        checked_refs = set()
        checked_count = 0
        for anchor_selector in selectors:
            try:
                by_ref = self._build_by_ref(anchor_selector)
                candidates = self._rpc.call(
                    "Driver.findComponents", DRIVER_REF, [by_ref]
                )
            except RpcError:
                if anchor_selector == type_selector:
                    raise
                logger.debug("XPath 属性预筛失败，回退 type 查询",
                             exc_info=True)
                continue
            if not isinstance(candidates, list):
                continue
            for ref in candidates:
                if ref in checked_refs:
                    continue
                checked_count += 1
                try:
                    bounds_data = self._rpc.call(
                        "Component.getBounds", ref, []
                    )
                except RpcError:
                    continue
                checked_refs.add(ref)
                if _bounds_data_to_quad(bounds_data) == target_bounds:
                    return ref

        logger.debug("bounds 锚定未命中 (type=%s bounds=%s 已检查候选数=%d)",
                     node_type, target_bounds, checked_count)
        return None

    def _anchor_nodes_to_refs(self,
                              nodes: List[Dict[str, Any]]) -> List[str]:
        """批量按 type 查询候选，并按 bounds 映射回 XPath 顺序。"""
        targets: Dict[
            str, Dict[Tuple[int, int, int, int], List[int]]
        ] = {}
        resolved: List[Optional[str]] = [None] * len(nodes)

        for index, node in enumerate(nodes):
            attrs = extract_node_attributes(node)
            node_type = attrs.get("type")
            bounds = _parse_bounds_quad(attrs.get("bounds"))
            if not node_type or bounds is None:
                continue
            targets.setdefault(str(node_type), {}).setdefault(
                bounds, []
            ).append(index)

        for node_type, bounds_indexes in targets.items():
            by_ref = self._build_by_ref(build_selector(type=node_type))
            candidates = self._rpc.call(
                "Driver.findComponents", DRIVER_REF, [by_ref]
            )
            if not isinstance(candidates, list):
                continue
            remaining_bounds = set(bounds_indexes)
            for ref in candidates:
                try:
                    bounds_data = self._rpc.call(
                        "Component.getBounds", ref, []
                    )
                except RpcError:
                    continue
                bounds = _bounds_data_to_quad(bounds_data)
                if bounds not in remaining_bounds:
                    continue
                for index in bounds_indexes[bounds]:
                    resolved[index] = ref
                remaining_bounds.remove(bounds)
                if not remaining_bounds:
                    break

        return [ref for ref in resolved if ref is not None]

    def _find_by_xpath(self, selector: SelectorSpec,
                       timeout: float) -> str:
        """等待 xpath 节点出现，并通过 bounds 锚定回 Component ref。

        每轮重新采集控件树，覆盖异步渲染以及节点命中后页面更新导致的
        bounds 锚定竞态。timeout <= 0 时仍执行一次即时查询，对齐
        waitForComponent 的立即检查语义。
        """
        xpath = selector.xpath or ""
        if not is_valid_xpath(xpath):
            raise ComponentNotFoundError(
                "xpath 表达式无效: %s" % selector.xpath
            )

        instance = selector.instance or 0
        deadline = time.monotonic() + max(timeout, 0.0)
        interval = 0.1
        xpath_matched = False
        first_attempt = True

        while first_attempt or time.monotonic() < deadline:
            first_attempt = False
            nodes = self._query_xpath_nodes(selector)
            if len(nodes) > instance:
                xpath_matched = True
                ref = self._anchor_node_to_ref(nodes[instance])
                if ref is not None:
                    return ref

            remaining = deadline - time.monotonic()
            if remaining <= 0:
                break
            time.sleep(min(interval, remaining))
            interval = min(interval * 2, 0.5)

        if xpath_matched:
            raise ComponentNotFoundError(
                "xpath 命中节点但无法锚定到设备端控件: %s" % selector.xpath
            )
        raise ComponentNotFoundError(
            "xpath 未匹配控件: %s" % selector.xpath
        )

    def _find_components_by_xpath(self, selector: SelectorSpec) -> list:
        """xpath 选择器查找所有匹配控件。

        对每个命中节点做 bounds 锚定，收集锚定成功的 Component ref。
        bounds 唯一，天然去重，无需按降级条件合并。
        """
        nodes = self._query_xpath_nodes(selector)
        return self._anchor_nodes_to_refs(nodes)

    # ============================================================
    # 弹窗处理
    # ============================================================

    def _should_dismiss_popup(self) -> bool:
        """判断是否启用弹窗自动消除。"""
        return self._config.pop_window_dismiss == "enable"


_BOUNDS_STR_RE = re.compile(r'\[(-?\d+),(-?\d+)\]\[(-?\d+),(-?\d+)\]')

BoundsQuad = Tuple[int, int, int, int]  # (left, top, right, bottom)


def _build_anchor_selector(attrs: Dict[str, Any]) -> SelectorSpec:
    """用控件树中的稳定属性构造候选预筛选器。"""
    kwargs: Dict[str, str] = {"type": str(attrs.get("type"))}

    text = _nonempty_attr(attrs, "text")
    if text is not None:
        kwargs["text"] = text

    description = _nonempty_attr(attrs, "description")
    if description is not None:
        kwargs["desc"] = description

    key = _nonempty_attr(attrs, "key")
    resource_id = (
        _nonempty_attr(attrs, "id")
        or _nonempty_attr(attrs, "resourceId")
        or _nonempty_attr(attrs, "resource-id")
    )
    if key is not None:
        kwargs["key"] = key
    elif resource_id is not None:
        kwargs["resource_id"] = resource_id

    return build_selector(**kwargs)


def _nonempty_attr(attrs: Dict[str, Any], name: str) -> Optional[str]:
    """读取可用于设备端精确匹配的非空字符串属性。"""
    value = attrs.get(name)
    if value is None:
        return None
    text = str(value)
    return text if text else None


def _parse_bounds_quad(raw: Any) -> Optional[BoundsQuad]:
    """解析控件树里的 bounds 为四元组。"""
    if isinstance(raw, str):
        m = _BOUNDS_STR_RE.search(raw)
        if not m:
            return None
        return (int(m.group(1)), int(m.group(2)),
                int(m.group(3)), int(m.group(4)))
    if isinstance(raw, dict):
        try:
            return (int(raw["left"]), int(raw["top"]),
                    int(raw["right"]), int(raw["bottom"]))
        except (KeyError, TypeError, ValueError):
            return None
    if isinstance(raw, (list, tuple)) and len(raw) >= 4:
        try:
            return (int(raw[0]), int(raw[1]),
                    int(raw[2]), int(raw[3]))
        except (TypeError, ValueError):
            return None
    return None


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


def _match_node_in_tree(tree: Dict[str, Any], selector: SelectorSpec,
                        instance: int = 0) -> Optional[Dict[str, Any]]:
    """在控件树中按 SelectorSpec 条件匹配第 instance 个（0 起）节点。

    支持全部文本/描述匹配字段（含正则）与 resource_id/key/type/class_name，
    不支持关系选择器和 xpath（那些走原有路径）。
    """
    results: List[Dict[str, Any]] = []
    _traverse_match(tree, selector, results)
    return results[instance] if len(results) > instance else None


def _traverse_match(node: Dict[str, Any], selector: SelectorSpec,
                    results: List[Dict[str, Any]]) -> None:
    """深度优先前序遍历，收集全部匹配 selector 的节点。

    命中节点的子树继续下探，对齐设备端 findComponents 的匹配顺序，
    保证 instance 语义一致。
    """
    attrs = extract_node_attributes(node)
    if _node_matches_selector(attrs, selector):
        results.append(node)
    for child in node.get("children") or []:
        _traverse_match(child, selector, results)


def _regex_search(pattern: str, value: str) -> bool:
    """正则匹配，对齐设备端 MatchPattern.REGEXP 的 RegExp.test 搜索语义。

    非法正则视为不匹配，不让脏输入炸掉整棵树的遍历。
    """
    try:
        return re.search(pattern, value) is not None
    except re.error:
        logger.warning("正则表达式无效: %r", pattern)
        return False


def _node_matches_selector(attrs: Dict[str, Any], selector: SelectorSpec) -> bool:
    """检查节点属性是否满足 selector 全部非空条件。

    必须覆盖 SelectorSpec 的全部匹配字段：任何被遗漏的字段都会让
    仅含该字段的选择器在树上退化为"匹配一切"，静默命中根节点。
    """
    text = attrs.get("text") or ""
    desc = attrs.get("description") or ""
    if selector.text is not None:
        if attrs.get("text") != selector.text:
            return False
    if selector.text_contains is not None:
        if selector.text_contains not in text:
            return False
    if selector.text_starts_with is not None:
        if not text.startswith(selector.text_starts_with):
            return False
    if selector.text_ends_with is not None:
        if not text.endswith(selector.text_ends_with):
            return False
    if selector.text_matches is not None:
        if not _regex_search(selector.text_matches, text):
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
        if selector.desc_contains not in desc:
            return False
    if selector.desc_starts_with is not None:
        if not desc.startswith(selector.desc_starts_with):
            return False
    if selector.desc_ends_with is not None:
        if not desc.endswith(selector.desc_ends_with):
            return False
    if selector.desc_matches is not None:
        if not _regex_search(selector.desc_matches, desc):
            return False
    return True


def _extract_properties_from_attrs(attrs: Dict[str, Any]) -> Dict[str, Any]:
    """从控件树节点的 attributes 中提取全部属性，对齐 RPC 逐个获取的结果。"""
    def _bool(val: str) -> bool:
        """将设备端布尔文本转换为 Python bool。"""
        return str(val).lower() == "true"

    def _bounds(val: Any) -> Dict[str, int]:
        """解析控件树 bounds 为统一字典。"""
        quad = _parse_bounds_quad(val)
        if quad is None:
            return {"left": 0, "top": 0, "right": 0, "bottom": 0}
        left, top, right, bottom = quad
        return {"left": left, "top": top, "right": right, "bottom": bottom}

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
