# !/usr/bin/env python
# -*- coding: utf-8 -*-
"""设备连接入口：平台识别、设备发现与平台分发。

平台实现延迟导入，避免导入包时触发设备环境探测。
"""
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
    log_level: Optional[int] = None,
    **kwargs
) -> BaseDriver:
    """连接设备。

    Args:
        serial: 设备序列号，None 时自动发现。
        platform: 平台，"auto" | "harmony"。"android" 暂未实现，
            显式传入会抛 PlatformNotSupportedError。
        config: 平台专用配置对象（如 HarmonyDriverConfig）。
        log_level: 日志级别。None 时不覆盖已有配置（首次默认 INFO）；
            传入 logging.DEBUG 可开启调试日志。
        **kwargs: 平台特定参数，覆盖 config 同名字段。

    Returns:
        BaseDriver: 设备驱动实例（具体平台子类）。

    Raises:
        DeviceNotFoundError: 未检测到可连接设备。
        DeviceConnectError: 设备连接失败。
        PlatformNotSupportedError: 平台不支持。
    """
    setup_logger(log_level)

    if platform == "auto":
        # 自动识别当前仅支持鸿蒙：发现设备与序列号校验一次 hdc 查询完成
        serial = _resolve_harmony_serial(serial)
        selected_platform = "harmony"
    else:
        selected_platform = platform
        if serial is None and selected_platform == "harmony":
            serial = _resolve_harmony_serial(None)

    if selected_platform == "harmony":
        from devhelmkit.harmony.driver import HarmonyDriver
        return HarmonyDriver(serial, config=config, **kwargs)

    if selected_platform == "android":
        raise PlatformNotSupportedError("Android 平台暂未支持")

    raise PlatformNotSupportedError("不支持的平台: %s" % selected_platform)


def _resolve_harmony_serial(serial: Optional[str]) -> str:
    """发现鸿蒙设备并解析序列号，单次 hdc 查询完成发现与校验。

    当前平台自动识别仅支持鸿蒙：serial 为 None 取首个设备；
    显式指定 serial 时校验其确实在线。
    """
    try:
        from devhelmkit.harmony.device.hdc import HdcDevice
        targets = HdcDevice.list_targets()
    except Exception as exc:
        raise DeviceConnectError("鸿蒙设备发现失败: %s" % exc) from exc

    if serial is None:
        if not targets:
            raise DeviceNotFoundError(
                "未检测到可连接设备，请手动指定 serial 或 platform"
            )
        return targets[0]
    if serial in targets:
        return serial
    raise DeviceNotFoundError(
        "设备 %s 不在线（在线设备: %s），请检查连接或指定 platform"
        % (serial, targets or "无")
    )
