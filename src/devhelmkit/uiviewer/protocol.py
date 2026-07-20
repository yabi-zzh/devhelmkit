# !/usr/bin/env python
# -*- coding: utf-8 -*-
"""UIViewer 数据契约：模式、帧、控件树、触控、清理策略。"""
from __future__ import annotations

import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional, Tuple

from devhelmkit.uiviewer.bounds import parse_bounds


class CaptureMode(str, Enum):
    """采集模式。

    SNAPSHOT: HDC 单次截图 + dumpLayout 文件导出，不启动 RPC 或截图推流
    LIVE: uitest 实时模式，启动截图流和触控
    """
    SNAPSHOT = "snapshot"
    LIVE = "live"


class TouchEventType(str, Enum):
    """触控事件类型。"""
    DOWN = "down"
    MOVE = "move"
    UP = "up"


class CleanupPolicy(str, Enum):
    """关闭时清理策略。"""
    KEEP = "keep"
    STOP = "stop"


@dataclass
class FrameMeta:
    """截图帧元信息。"""
    frame_id: int
    timestamp_ms: int
    display_size: Tuple[int, int]
    image_size: Tuple[int, int]
    mode: CaptureMode

    def to_dict(self) -> Dict[str, Any]:
        return {
            "frame_id": self.frame_id,
            "timestamp_ms": self.timestamp_ms,
            "display_size": list(self.display_size),
            "image_size": list(self.image_size),
            "mode": self.mode.value,
        }


@dataclass
class HierarchySnapshot:
    """控件树快照。"""
    snapshot_id: int
    timestamp_ms: int
    source: str
    root: Dict[str, Any]
    nodes: Dict[str, Dict[str, Any]] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "snapshot_id": self.snapshot_id,
            "timestamp_ms": self.timestamp_ms,
            "source": self.source,
            "root": self.root,
            "nodes": self.nodes,
        }


@dataclass
class TouchEvent:
    """单个触控事件。"""
    type: TouchEventType
    x: int
    y: int
    pointer_id: int = 1
    timestamp_ms: int = field(default_factory=lambda: int(time.time() * 1000))

    def to_dict(self) -> Dict[str, Any]:
        return {
            "type": self.type.value,
            "x": self.x,
            "y": self.y,
            "pointer_id": self.pointer_id,
            "timestamp_ms": self.timestamp_ms,
        }


@dataclass
class TouchBatch:
    """触控事件批次。"""
    serial: str
    events: List[TouchEvent] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "serial": self.serial,
            "events": [e.to_dict() for e in self.events],
        }


@dataclass
class SessionState:
    """单设备会话状态。"""
    serial: str
    mode: CaptureMode = CaptureMode.SNAPSHOT
    cleanup_policy: CleanupPolicy = CleanupPolicy.KEEP
    active: bool = False
    display_size: Optional[Tuple[int, int]] = None
    last_frame_meta: Optional[FrameMeta] = None
    last_hierarchy: Optional[HierarchySnapshot] = None

    def to_dict(self) -> Dict[str, Any]:
        result: Dict[str, Any] = {
            "serial": self.serial,
            "mode": self.mode.value,
            "cleanup_policy": self.cleanup_policy.value,
            "active": self.active,
        }
        if self.display_size is not None:
            result["display_size"] = list(self.display_size)
        if self.last_frame_meta is not None:
            result["last_frame"] = self.last_frame_meta.to_dict()
        if self.last_hierarchy is not None:
            result["last_hierarchy"] = self.last_hierarchy.to_dict()
        return result


def extract_hierarchy_attributes(node: Dict[str, Any]) -> Dict[str, Any]:
    """提取节点属性，并从顶层属性结构中排除树结构字段。"""
    wrapped = node.get("attributes")
    if isinstance(wrapped, dict):
        return wrapped
    return {
        key: value
        for key, value in node.items()
        if key != "children"
    }


def flatten_hierarchy(root: Dict[str, Any],
                      parent_id: Optional[str] = None,
                      path_prefix: str = "") -> Dict[str, Dict[str, Any]]:
    """将控件树扁平化为 node_id -> node 映射。

    node_id 基于树路径生成，在同一快照内稳定。
    """
    nodes: Dict[str, Dict[str, Any]] = {}

    def _walk(node: Dict[str, Any], parent: Optional[str], prefix: str) -> str:
        idx = 0
        if parent is not None:
            siblings = nodes.get(parent, {}).get("children_ids", [])
            idx = len(siblings)
        node_id = "%s%d" % (prefix, idx) if prefix else "root"

        attrs = extract_hierarchy_attributes(node)
        children_raw = node.get("children", [])

        flat_node: Dict[str, Any] = {
            "node_id": node_id,
            "parent_id": parent,
            "attributes": attrs if isinstance(attrs, dict) else {},
            "children_ids": [],
        }

        # 复用 bounds 模块的统一解析：支持负坐标且对非法输入有防御
        source_attrs = attrs if isinstance(attrs, dict) else node
        bounds = parse_bounds(source_attrs.get("bounds"))
        if bounds is not None:
            flat_node["bounds"] = bounds

        nodes[node_id] = flat_node

        for i, child in enumerate(children_raw):
            child_id = _walk(child, node_id, "%s%d_" % (prefix, i) if prefix else "%d_" % i)
            flat_node["children_ids"].append(child_id)

        return node_id

    _walk(root, parent_id, path_prefix)
    return nodes
