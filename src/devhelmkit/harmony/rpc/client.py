# !/usr/bin/env python
# -*- coding: utf-8 -*-
"""RpcClient：设备端 API 调用与返回值处理。

统一使用 bin 模式（proxy_v2），废弃 hap 模式。
负责：
- 构造 RPC 消息（api/this/args/message_type）
- 调用 proxy_v2 发送
- 处理返回值（解析 JSON、错误检测、异常分类）
- 远程对象生命周期管理

仅支持 HarmonyOS 5.0.0+（API 12+），设备端 uitest 服务统一使用
api9+ 命名（Driver/Component/On），不再兼容 api8 旧命名。
"""
import json
import logging
from typing import Any, TYPE_CHECKING

from devhelmkit.exceptions import (
    AgentError,
    BackendObjectDroppedError,
    RpcError,
)
from devhelmkit.harmony.rpc.proxy_v2 import rpc as rpc_send
from devhelmkit.harmony.rpc.remote_object import RemoteObjectManager

logger = logging.getLogger(__name__)

if TYPE_CHECKING:
    from devhelmkit.harmony.device.hdc import HdcDevice


class RpcClient:
    """RPC 客户端，统一使用 bin 模式。"""

    def __init__(self, device: 'HdcDevice'):
        self._device = device
        self._remote_objects = RemoteObjectManager()

    def call(self, api_name: str, this_ref: str, args: list) -> Any:
        """调用设备端 API。

        Args:
            api_name: API 名称（api9+ 风格，如 "Driver.click"、"On.text"）
            this_ref: 对象引用（如 'Driver#0'、'Component#3'）
            args: 参数列表（递归处理 FrontEndClass → ref, JsonBase → dict, Enum → value）

        Returns:
            设备端返回结果

        Raises:
            RpcError: RPC 调用失败
            BackendObjectDroppedError: 后端对象引用已失效
            AgentError: 设备端 Agent 异常
        """
        msg = {
            'api': api_name,
            'this': this_ref,
            'args': args,
            'message_type': 'hypium'
        }
        logger.trace("RPC -> %s this=%s args=%r", api_name, this_ref, args)
        reply = rpc_send(self._device, msg)
        result = self._handle_reply(reply, api_name)
        logger.trace("RPC <- %s result=%r", api_name, result)
        return result

    def _handle_reply(self, reply: str, api_name: str) -> Any:
        """处理设备端返回值，解析 JSON 并检测错误。"""
        try:
            result = json.loads(reply)
        except json.JSONDecodeError as e:
            logger.error("RPC 返回值解析失败 [%s]: %s", api_name, reply[:200])
            raise RpcError(
                "RPC 返回值解析失败: %s" % e,
                api=api_name, reply=reply
            ) from e

        error = result.get('error')
        if error:
            logger.warning("RPC 调用失败 [%s]: %s", api_name, error)
            return self._raise_for_error(error, api_name, reply)

        # 设备端异常时可能返回 {"exception":{"code":...,"message":...}}
        exception = result.get('exception')
        if exception:
            msg = exception.get('message', str(exception))
            logger.warning("RPC 调用异常 [%s]: %s", api_name, msg)
            raise RpcError(
                "RPC 调用异常: %s" % msg,
                api=api_name, reply=reply
            )

        return result.get('result')

    @staticmethod
    def _raise_for_error(error: str, api_name: str, reply: str) -> None:
        """根据错误信息抛出对应异常。"""
        error_lower = str(error).lower()

        # 后端对象引用失效
        if 'object' in error_lower and ('dropped' in error_lower or
                                         'released' in error_lower or
                                         'invalid' in error_lower):
            raise BackendObjectDroppedError(
                "后端对象引用已失效: %s" % error,
                api=api_name, reply=reply
            )

        # Agent 进程异常
        if 'agent' in error_lower or 'uitest' in error_lower or \
           'crash' in error_lower:
            raise AgentError("Agent 异常: %s" % error)

        raise RpcError(
            "RPC 调用失败 [%s]: %s" % (api_name, error),
            api=api_name, reply=reply
        )

    @property
    def device(self) -> 'HdcDevice':
        """底层设备通道，供 Captures/Gestures 等非 callHypiumApi 模块复用。"""
        return self._device

    @property
    def remote_objects(self) -> RemoteObjectManager:
        """远程对象管理器。"""
        return self._remote_objects
