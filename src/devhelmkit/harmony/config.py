# !/usr/bin/env python
# -*- coding: utf-8 -*-
"""HarmonyDriverConfig：鸿蒙驱动配置。"""
from dataclasses import dataclass, replace
from typing import Optional, Tuple

from devhelmkit.exceptions import DevhelmError


class ComponentFindMode:
    """控件查找模式（类常量风格）。"""
    UITEST = "uitest"
    UITREE = "uitree"


class ClearTextMode:
    """清空文本模式。"""
    ONCE = "once"
    ONE_BY_ONE = "one_by_one"


class InputTextModeConstant:
    """输入文本模式（PASTE 模式需设备端 uitest 支持，API level > 20）。"""
    DEFAULT = "default"
    PASTE = "paste"


class StepLogMode:
    """步骤日志模式。"""
    AUTO = "auto"
    ENABLE = "enable"
    DISABLE = "disable"


class PopWindowHandlerConfig:
    """弹窗消除开关（pop_window_dismiss 字段取值）。"""
    ENABLE = "enable"
    DISABLE = "disable"


class ScreenshotMode:
    """截图模式（类常量风格）。

    HDC: 走 hdc shell snapshot_display + base64 读取（默认，兼容性好）
    STREAM: 走 startCaptureScreen 推流，独立端口+socket 接收 JPEG 帧（低延迟）
    """
    HDC = "hdc"
    STREAM = "stream"


@dataclass
class HarmonyDriverConfig:
    """鸿蒙驱动配置，共 27 个配置项。

    控制鸿蒙驱动行为：控件查找策略、弹窗处理、操作等待、文本输入、
    截图、日志、显示、调试、模板匹配、扩展能力、资源清理、hdc 路径。
    """

    # 控件查找
    component_find_backend: str = "uitest"

    # 弹窗消除
    pop_window_dismiss: str = "disable"
    enable_pop_window_dismiss_in_check: bool = True
    pop_window_retry_find_timeout: int = 2
    wait_time_after_pop_window_dismiss: int = 1
    preprocess_pop_window: bool = False
    pop_window_handle_times: int = 4
    pop_window_preprocess_times: int = 4
    pop_window_service_restart_times: int = 3
    enable_pop_window_screenshot: bool = True

    # 操作等待
    after_action_wait_time: int = 1

    # 文本输入
    clear_text_mode: str = ClearTextMode.ONCE
    clear_text_before_input: bool = True
    input_text_mode: str = InputTextModeConstant.DEFAULT
    _out_of_screen_coord_for_input_text: Tuple[int, int] = (10000, 10000)

    # 截图
    enable_component_found_screenshot: bool = False
    enable_action_screenshot: bool = False
    screenshot_retry_times: int = 3
    screenshot_mode: str = ScreenshotMode.HDC
    screenshot_stream_scale: float = 0.99

    # 日志
    save_step_log: str = StepLogMode.AUTO

    # 显示
    default_display_id: int = 0

    # 调试
    debug_page_info: bool = True

    # 模板匹配
    template_scale_range: Tuple[float, float] = (0.2, 1.2)

    # 扩展
    enable_extension: bool = True

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
