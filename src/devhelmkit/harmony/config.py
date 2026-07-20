# !/usr/bin/env python
# -*- coding: utf-8 -*-
"""HarmonyDriverConfig：鸿蒙驱动配置。"""
from dataclasses import dataclass, replace
from typing import Optional

from devhelmkit.exceptions import DevhelmError


class ClearTextMode:
    """清空文本模式。"""
    ONCE = "once"
    # 聚焦后全选（Ctrl+A）再按删除键清空，兜底部分 clearText 不生效的输入框
    SELECT_ALL = "select_all"


class ScreenshotMode:
    """截图模式（类常量风格）。

    HDC: 走 hdc shell snapshot_display + base64 读取（默认，兼容性好）
    STREAM: 走 startCaptureScreen 推流，独立端口+socket 接收 JPEG 帧（低延迟）
    """
    HDC = "hdc"
    STREAM = "stream"


@dataclass
class HarmonyDriverConfig:
    """鸿蒙驱动配置，共 13 个配置项。

    控制鸿蒙驱动行为：控件查找、弹窗处理、文本输入、截图、
    资源清理、hdc 路径。
    """

    # 控件查找默认超时（秒），驱动隐式等待初值。非零以容忍异步渲染，
    # 需即时判断时在具体调用传 timeout=0；运行时也可用 implicitly_wait() 覆盖。
    implicit_wait: float = 10.0

    # 弹窗消除
    pop_window_dismiss: str = "disable"
    # 弹窗消除后重试查找的超时（秒），仅在 pop_window_dismiss=enable 时生效
    pop_window_retry_find_timeout: int = 2
    # 弹窗消除后、重试查找前的等待秒数，给页面留出关闭动画时间；0 表示不等待
    wait_time_after_pop_window_dismiss: int = 1
    # 单次查找失败时最多尝试消除的弹窗个数
    pop_window_handle_times: int = 4

    # 文本输入
    clear_text_mode: str = ClearTextMode.ONCE
    clear_text_before_input: bool = True

    # 截图
    # HDC 截图失败重试次数
    screenshot_retry_times: int = 3
    screenshot_mode: str = ScreenshotMode.HDC
    screenshot_stream_scale: float = 0.99

    # 资源清理
    # close() 时是否停止设备端 uitest 守护进程，默认 False 复用进程
    stop_daemon_on_close: bool = False
    # setup 时是否先清理设备端残留 uitest 守护进程再重新启动，默认 False 复用进程。
    # True 时绕过复用优先策略，规避残留 daemon 版本不匹配或状态损坏导致的连接异常。
    restart_daemon_on_setup: bool = False

    # hdc 可执行文件路径，默认 "hdc"（从 PATH 查找）
    # 指定后 connect 时通过 HdcDevice.set_hdc_path 设置全局路径
    hdc_path: str = "hdc"

    def update_from_dict(self, data: dict) -> None:
        """从字典更新配置，未知字段抛 DevhelmError。"""
        for key, value in data.items():
            if not hasattr(self, key):
                raise DevhelmError("未知配置字段: %s" % key)
            setattr(self, key, value)

    @classmethod
    def from_dict(cls, data: dict) -> 'HarmonyDriverConfig':
        """从字典创建配置。"""
        config = cls()
        config.update_from_dict(data)
        return config

    @classmethod
    def from_input(cls, config: Optional['HarmonyDriverConfig'],
                   kwargs: dict) -> 'HarmonyDriverConfig':
        """合并显式配置对象和 connect 透传参数。

        先复制 config，再用 kwargs 覆盖同名字段，原配置对象不被原地修改。
        """
        merged = replace(config) if config is not None else cls()
        if kwargs:
            merged.update_from_dict(kwargs)
        return merged
