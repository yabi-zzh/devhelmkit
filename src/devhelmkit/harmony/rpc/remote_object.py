# !/usr/bin/env python
# -*- coding: utf-8 -*-
"""远程对象生命周期管理。

跟踪设备端远程对象引用（如 Driver#0、Component#3、On#seed）的创建与回收。
活跃对象使用 WeakSet 跟踪，待回收对象累积超过 batch_size 时触发批量清理。
"""
from typing import Any, Set
from weakref import WeakSet


DEFAULT_BATCH_SIZE = 20


class RemoteObjectManager:
    """管理设备端远程对象引用的生命周期。"""

    def __init__(self) -> None:
        self.total_registered_objects = 0
        self.total_removed_objects = 0
        self.batch_size = DEFAULT_BATCH_SIZE
        # 待回收的对象引用集合
        self.pending_release_refs: Set[str] = set()
        # 活跃对象弱引用集合（不阻止 GC）
        self.active_objects = WeakSet()
        # 标记是否已执行 release_all，禁止后续 add_object
        self._released = False

    def add_object(self, obj: Any) -> None:
        """注册远程对象到活跃集合。"""
        if self._released:
            return
        remains = len(self.active_objects)
        self.active_objects.add(obj)
        if len(self.active_objects) > remains:
            self.total_registered_objects += 1

    def remove_object(self, backend_obj_ref: str) -> None:
        """标记远程对象引用为待回收。"""
        self.total_removed_objects += 1
        self.pending_release_refs.add(backend_obj_ref)

    def release_all(self) -> None:
        """释放所有远程对象。"""
        self._released = True
        for item in self.active_objects:
            if hasattr(item, 'release'):
                item.release()
