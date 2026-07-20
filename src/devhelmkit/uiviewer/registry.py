# !/usr/bin/env python
# -*- coding: utf-8 -*-
"""DeviceSessionRegistry：多设备会话管理。

按 serial 创建/缓存/释放 UiViewerSession，
支持设备枚举、选择、切换和按 serial 隔离清理状态。
"""
from __future__ import annotations

import logging
import threading
from typing import Dict, List, Optional

from devhelmkit.uiviewer.protocol import CaptureMode, CleanupPolicy
from devhelmkit.uiviewer.session import UiViewerSession

logger = logging.getLogger(__name__)


class DeviceSessionRegistry:
    """多设备会话注册表。

    线程安全：内部 _lock 保护 sessions 字典操作。
    """

    def __init__(self):
        self._sessions: Dict[str, UiViewerSession] = {}
        self._lock = threading.Lock()

    def list_devices(self) -> List[str]:
        """枚举当前 hdc 连接的所有设备序列号。"""
        from devhelmkit.harmony.device.hdc import HdcDevice
        try:
            return HdcDevice.list_targets()
        except Exception as e:
            logger.warning("设备枚举失败: %s", e)
            return []

    def get_session(self, serial: str) -> Optional[UiViewerSession]:
        """获取已有会话，不存在返回 None。"""
        with self._lock:
            return self._sessions.get(serial)

    def get_or_create_session(self, serial: str) -> UiViewerSession:
        """获取或创建指定设备的会话。

        新会话默认 snapshot 模式，不自动 start。
        调用方需显式调用 session.start() 才会创建 driver。
        """
        with self._lock:
            session = self._sessions.get(serial)
            if session is None:
                session = UiViewerSession(serial)
                self._sessions[serial] = session
            return session

    def get_or_create_started_session(self, serial: str) -> UiViewerSession:
        """获取或创建会话并保证其已启动，防止产生无人管理的孤儿 driver。

        start() 是慢设备 I/O，放在 registry 锁外执行（锁内只做查表/建表），
        依赖 session 自身锁保证幂等。start 完成后回查 registry：若期间
        会话已被 close_session 移除，则刚创建的 driver 无人管理，立即
        stop 释放并向调用方报错。

        Raises:
            RuntimeError: 启动期间会话被并发关闭。
        """
        with self._lock:
            session = self._sessions.get(serial)
            if session is None:
                session = UiViewerSession(serial)
                self._sessions[serial] = session
        session.start()
        with self._lock:
            still_registered = self._sessions.get(serial) is session
        if not still_registered:
            session.stop()
            raise RuntimeError("会话在启动期间被关闭: %s" % serial)
        return session

    def close_session(self, serial: str) -> None:
        """关闭并移除指定设备的会话。"""
        with self._lock:
            session = self._sessions.pop(serial, None)
        if session is not None:
            session.stop()

    def close_all(self) -> None:
        """关闭所有会话，释放全部资源。"""
        with self._lock:
            sessions = list(self._sessions.values())
            self._sessions.clear()
        for session in sessions:
            session.stop()

    def get_active_sessions(self) -> List[UiViewerSession]:
        """获取所有已启动的会话。"""
        with self._lock:
            return [s for s in self._sessions.values() if s.active]

    def set_mode(self, serial: str, mode: CaptureMode) -> None:
        """切换指定设备的采集模式。"""
        session = self.get_or_create_session(serial)
        session.set_mode(mode)

    def set_cleanup_policy(self, serial: str,
                           policy: CleanupPolicy) -> None:
        """设置指定设备的清理策略。"""
        session = self.get_or_create_session(serial)
        session.set_cleanup_policy(policy)

    def get_all_states(self) -> List[dict]:
        """获取所有会话的状态摘要。

        registry 锁内只拷贝会话列表，锁外逐个取状态（get_state 需各
        session 锁，可能被慢 I/O 长期占用；与 close_all 的写法一致），
        避免单设备阻塞卡死所有依赖 registry 锁的请求路由。
        """
        with self._lock:
            sessions = list(self._sessions.values())
        return [s.get_state() for s in sessions]
