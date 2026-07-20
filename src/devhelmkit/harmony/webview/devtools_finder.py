# !/usr/bin/env python
# -*- coding: utf-8 -*-
"""devtools 端口探测：定位设备端 webview 调试端口。

HarmonyOS webview 调试端口有两种形态：
  1. domain socket：webview_devtools_remote_{pid}（系统 web 内核，默认）
  2. tcp 端口：9222 等（自定义 web 内核，需应用主动开启）

探测流程：
  1. 读取 /proc/net/unix 判断是否使用 domain socket
  2. 通过 ps -ef | grep {bundle_name} 获取应用 PID
  3. 在 /proc/net/unix 中匹配包含该 PID 的 devtools socket 名
"""
import logging
import re
import shlex
import time
from typing import List, Optional

from devhelmkit.harmony.device.hdc import HdcDevice

logger = logging.getLogger(__name__)

# domain socket 名称前缀
DOMAIN_SOCKET_PREFIX = "webview_devtools_remote_"

# 默认探测超时（秒）
DEFAULT_STARTUP_TIMEOUT = 8

# 轮询间隔（秒）
POLL_INTERVAL = 0.8


class DevtoolsFinder:
    """设备端 webview devtools 端口探测。"""

    def __init__(self, device: HdcDevice):
        self._device = device

    def is_using_domain_socket(self, timeout: float = DEFAULT_STARTUP_TIMEOUT) -> bool:
        """检查设备是否使用 domain socket 形式的 devtools。

        Args:
            timeout: 探测超时（秒），轮询直到发现或超时

        Returns:
            True 表示使用 domain socket，False 表示需用 tcp 端口
        """
        deadline = time.time() + timeout
        while time.time() < deadline:
            result = self._device.shell(
                "cat /proc/net/unix | grep %s" % DOMAIN_SOCKET_PREFIX
            )
            if DOMAIN_SOCKET_PREFIX in result:
                return True
            time.sleep(POLL_INTERVAL)
        return False

    def find_devtools_socket(self, bundle_name: str,
                             timeout: float = DEFAULT_STARTUP_TIMEOUT) -> Optional[str]:
        """查找指定应用的 devtools domain socket 名称。

        通过应用 PID 与 /proc/net/unix 中的 devtools socket 匹配。

        Args:
            bundle_name: 应用包名
            timeout: 探测超时（秒）

        Returns:
            socket 名称（如 webview_devtools_remote_12345），未找到返回 None
        """
        deadline = time.time() + timeout
        while time.time() < deadline:
            devtools_sockets = self._get_devtools_sockets()
            if not devtools_sockets:
                time.sleep(POLL_INTERVAL)
                continue

            process_pids = self._get_bundle_pids(bundle_name)
            if not process_pids:
                time.sleep(POLL_INTERVAL)
                continue

            # socket 名以 "_{pid}" 结尾才算命中，避免子串误匹配
            # （如 pid "123" 误匹配 webview_devtools_remote_12345）
            for socket_name in devtools_sockets:
                for pid in process_pids:
                    if socket_name.endswith("_" + pid):
                        logger.debug(
                            "找到 devtools socket: %s (pid=%s, bundle=%s)",
                            socket_name, pid, bundle_name
                        )
                        return socket_name
            time.sleep(POLL_INTERVAL)
        return None

    def check_tcp_port(self, port: int) -> bool:
        """检查设备端 tcp devtools 端口是否开放。

        Args:
            port: 设备端 tcp 端口号

        Returns:
            True 表示端口已开放
        """
        # grep 仅做粗过滤，边界匹配在主机侧完成，
        # 避免端口号作为子串误命中（如 9222 命中 :92223）
        result = self._device.shell("netstat -tlnp | grep :%d" % port)
        return re.search(r"[:.]%d\b" % port, result) is not None

    def _get_devtools_sockets(self) -> List[str]:
        """读取 /proc/net/unix 中所有 devtools socket 名称。"""
        result = self._device.shell("cat /proc/net/unix | grep devtools")
        sockets = []
        for line in result.split("\n"):
            items = line.split()
            if not items:
                continue
            # 最后一列为 socket 名称，去掉前导 @
            name = items[-1].strip("@")
            if name:
                sockets.append(name)
        return sockets

    def _get_bundle_pids(self, bundle_name: str) -> List[str]:
        """获取指定包名应用的所有进程 PID。"""
        # 包名来自用户输入，quote 后再拼入设备 shell，防止命令注入
        result = self._device.shell("ps -ef | grep %s" % shlex.quote(bundle_name))
        pids = []
        for line in result.split("\n"):
            items = line.split()
            if len(items) < 8:
                continue
            pid = items[1]
            actual_name = items[7]
            if bundle_name in actual_name:
                pids.append(pid)
        return pids
