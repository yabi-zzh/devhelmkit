# !/usr/bin/env python
# -*- coding: utf-8 -*-
"""轻量日志：Error / Warning / Info / Debug / Trace。

仅控制台输出，无轮转、无脱敏。

级别语义：
- ERROR   设备连接失败、RPC 协议异常等不可恢复错误
- WARNING 可恢复异常、降级回退、版本不匹配等需关注的情况
- INFO    默认级别，框架保持静默，仅用户脚本自身的输出可见
- DEBUG   框架内部状态变更（守护进程启停、通道建立、推流、录屏、webview 连接等）
- TRACE   高频请求/响应明细（RPC 帧文、触控坐标、控件树请求等）

使用方式：
    import logging
    logger = logging.getLogger(__name__)
    logger.debug("...")
    logger.trace("...")
"""
import logging
import sys

_LOGGER_NAME = "devhelmkit"

# Trace 级别注册到 logging 模块（数值低于 DEBUG=10）
TRACE = 5
logging.addLevelName(TRACE, "TRACE")


def _trace(self, message, *args, **kwargs):
    if self.isEnabledFor(TRACE):
        self._log(TRACE, message, args, **kwargs)


logging.Logger.trace = _trace  # type: ignore[attr-defined]


class _MillisFormatter(logging.Formatter):
    """时间精确到毫秒，级别用单字母缩写（E/W/I/D/T）。"""

    _LEVEL_SHORT = {
        logging.ERROR: "E",
        logging.WARNING: "W",
        logging.INFO: "I",
        logging.DEBUG: "D",
        TRACE: "T",
    }

    def formatTime(self, record, datefmt=None):
        timestamp = super().formatTime(record, "%H:%M:%S")
        return "%s.%03d" % (timestamp, record.msecs)

    def format(self, record):
        record.levelname = self._LEVEL_SHORT.get(record.levelno, record.levelname)
        return super().format(record)


def setup_logger(level: int = logging.INFO) -> logging.Logger:
    """配置 devhelmkit 根 logger，附加控制台 handler。

    所有以 _LOGGER_NAME 为前缀的子 logger（如 devhelmkit.harmony.driver）
    均继承此 handler 与级别配置。
    """
    root = logging.getLogger(_LOGGER_NAME)
    root.setLevel(level)
    if not any(isinstance(h, logging.StreamHandler) and h.stream is sys.stderr
               for h in root.handlers):
        handler = logging.StreamHandler(sys.stderr)
        handler.setFormatter(
            _MillisFormatter("[%(asctime)s] [%(levelname)s] [%(name)s] %(message)s")
        )
        root.addHandler(handler)
    return root


def get_logger(name: str = _LOGGER_NAME) -> logging.Logger:
    """获取 devhelmkit 命名空间下的 logger。

    Args:
        name: logger 名称，通常传 __name__（如 devhelmkit.harmony.driver）。
    """
    return logging.getLogger(name)