# !/usr/bin/env python
# -*- coding: utf-8 -*-
"""设备连接入口：平台识别、设备发现与平台分发。

平台实现延迟导入，避免导入包时触发设备环境探测。
"""
import logging
from typing import Optional

from devhelmkit.core.base_driver import BaseDriver
from devhelmkit.exceptions import (
    DeviceConnectError,
    DeviceNotFoundError,
    PlatformNotSupportedError,
)
from devhelmkit.utils.logger import setup_logger


def connect(
    serial: Optional[str] = None,
    platform: str = "auto",
    config=None,
    log_level: int = None,
    **kwargs
) -> BaseDriver:
    """连接设备。

    Args:
        serial: 设备序列号，None 时自动发现。
        platform: 平台，"auto" | "harmony" | "android"。
        config: 平台专用配置对象（如 HarmonyDriverConfig）。
        log_level: 日志级别，None 默认 INFO。传入 logging.DEBUG 可开启调试日志。
        **kwargs: 平台特定参数，覆盖 config 同名字段。

    Returns:
        BaseDriver: 设备驱动实例（具体平台子类）。

    Raises:
        DeviceNotFoundError: 未检测到可连接设备。
        DeviceConnectError: 设备连接失败。
        PlatformNotSupportedError: 平台不支持。
    """
    setup_logger(log_level if log_level is not None else logging.INFO)

    if serial is None:
        serial = _discover_serial()

    selected_platform = _detect_platform(serial) if platform == "auto" else platform

    if selected_platform == "harmony":
        from devhelmkit.harmony.driver import HarmonyDriver
        return HarmonyDriver(serial, config=config, **kwargs)

    if selected_platform == "android":
        raise PlatformNotSupportedError("Android 平台暂未支持")

    raise PlatformNotSupportedError("不支持的平台: %s" % selected_platform)


def _discover_serial() -> str:
    """自动发现首个可用设备序列号。"""
    try:
        from devhelmkit.harmony.device.hdc import HdcDevice
        targets = HdcDevice.list_targets()
    except Exception as exc:
        raise DeviceConnectError("鸿蒙设备发现失败: %s" % exc) from exc

    if not targets:
        raise DeviceNotFoundError(
            "未检测到可连接设备，请手动指定 serial 或 platform"
        )
    return targets[0]


def _detect_platform(serial: Optional[str]) -> str:
    """自动识别平台：当前仅识别鸿蒙设备。"""
    try:
        from devhelmkit.harmony.device.hdc import HdcDevice
        targets = HdcDevice.list_targets()
    except Exception as exc:
        raise DeviceConnectError("鸿蒙设备发现失败: %s" % exc) from exc

    if serial is None and targets:
        return "harmony"
    if serial is not None and serial in targets:
        return "harmony"

    raise DeviceNotFoundError(
        "未检测到可连接设备，请手动指定 serial 或 platform"
    )
