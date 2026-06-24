# !/usr/bin/env python
# -*- coding: utf-8 -*-
"""bin 模式 RPC 传输，保留设备端协议。

proxy_v2 不读取 device 内部代理字段，只调用统一传输入口 device.rpc_call()。
设备端协议消息格式：
{
    "module": "com.ohos.devicetest.hypiumApiHelper",
    "method": "callHypiumApi",
    "params": <内层消息字典>,
    "request_id": "<时间戳>"
}
"""
import json
from datetime import datetime
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from devhelmkit.harmony.device.hdc import HdcDevice


def _generate_request_id() -> str:
    """生成基于时间戳的请求 ID。"""
    return datetime.now().strftime("%Y%m%d%H%M%S%f")


def _send(device: 'HdcDevice', method: str, params: dict) -> str:
    """构造 bin 模式 RPC 消息并发送至设备端。

    统一负责 request_id 生成、full_msg 组装、JSON 序列化与设备调用，
    对外函数仅构造 params 后委托本函数。

    Args:
        device: HdcDevice 实例，提供 rpc_call 传输入口
        method: 设备端协议 method 字段（如 callHypiumApi/Captures/Gestures）
        params: 内层 params 消息字典

    Returns:
        设备端回显的 JSON 字符串
    """
    full_msg = {
        "module": "com.ohos.devicetest.hypiumApiHelper",
        "method": method,
        "params": params,
        "request_id": _generate_request_id()
    }
    full_msg_str = json.dumps(full_msg, ensure_ascii=False,
                              separators=(',', ':'))
    return device.rpc_call(full_msg_str)


def rpc(device: 'HdcDevice', msg: dict) -> str:
    """发送 bin 模式 RPC，返回设备端回显字符串。

    Args:
        device: HdcDevice 实例，提供 rpc_call 传输入口
        msg: 内层消息字典（含 api/this/args/message_type）

    Returns:
        设备端回显的 JSON 字符串
    """
    return _send(device, "callHypiumApi", msg)


def rpc_captures(device: 'HdcDevice', api: str, args: dict) -> str:
    """发送 Captures 模块 RPC（如 captureLayout）。

    Captures 模块协议与 callHypiumApi 不同：
    - method 为 "Captures"
    - params 中无 this/message_type，args 为对象而非数组

    Args:
        device: HdcDevice 实例
        api: API 名称（如 "captureLayout"）
        args: 参数对象

    Returns:
        设备端回显的 JSON 字符串
    """
    params = {
        "api": api,
        "args": args
    }
    return _send(device, "Captures", params)


def rpc_gestures(device: 'HdcDevice', api: str, args: dict) -> str:
    """发送 Gestures 模块 RPC（如 touchDown/touchMove/touchUp）。

    Gestures 模块协议与 callHypiumApi 不同：
    - method 为 "Gestures"
    - params 中无 this/message_type，args 为对象（如 {x, y}）而非数组

    Args:
        device: HdcDevice 实例
        api: API 名称（如 "touchDown"）
        args: 参数对象

    Returns:
        设备端回显的 JSON 字符串
    """
    params = {
        "api": api,
        "args": args
    }
    return _send(device, "Gestures", params)
