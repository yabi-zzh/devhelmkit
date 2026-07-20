# !/usr/bin/env python
# -*- coding: utf-8 -*-
"""设备端 uitest 守护进程（agent.so）管理。

职责：
- 探测设备 ABI 与 uitest 协议版本（v1=5.0 / v2=6.0+）
- 按版本选择本地 agent.so（assets/so/{abi}/）
- MD5 校验避免重复推送
- 启动 uitest 守护进程并渐进式等待就绪
- 守护进程加载后清理设备端临时 so，避免残留与版本混淆
"""
import hashlib
import logging
import os
import re
import shlex
import time
from typing import TYPE_CHECKING, Optional, Tuple

from devhelmkit.exceptions import AgentError, DeviceConnectError

logger = logging.getLogger(__name__)

if TYPE_CHECKING:
    from devhelmkit.harmony.device.hdc import HdcDevice

# 设备端 agent.so 路径
DEVICE_AGENT_PATH = "/data/local/tmp/agent.so"

# 守护进程启动命令
DAEMON_COMMAND = "uitest start-daemon singleness"

# 协议版本阈值：uitest 版本 > 该值则为 v2（6.0+），否则 v1（5.0）
PROTOCOL_V2_THRESHOLD = "6.0.2.1"

# 守护进程启动渐进式等待（秒），总计约 410ms
DAEMON_START_DELAYS = (0.030, 0.050, 0.080, 0.100, 0.150)

# 本地 so 资产根目录（相对包根）
SO_ASSET_DIR = "assets/so"

# ABI → 协议版本 → so 文件名
# arm64-v8a 区分 v1/v2，x86_64 不区分（仅模拟器场景）
_AGENT_FILE_MAP = {
    "arm64-v8a": {1: "agent_v1.so", 2: "agent_v2.so"},
    "x86_64": {1: "agent.so", 2: "agent.so"},
}


def _compare_version(a: str, b: str) -> int:
    """语义版本比较，返回 -1/0/1。缺失位按 0 处理。"""
    pa = [int(x) for x in re.findall(r"\d+", a)]
    pb = [int(x) for x in re.findall(r"\d+", b)]
    for x, y in zip(pa, pb):
        if x < y:
            return -1
        if x > y:
            return 1
    if len(pa) < len(pb):
        return -1
    if len(pa) > len(pb):
        return 1
    return 0


def _get_package_root() -> str:
    """获取 devhelmkit 包根目录绝对路径。

    so_manager.py 位于 harmony/agent/so_manager.py，包根为上两级。
    """
    here = os.path.dirname(os.path.abspath(__file__))
    return os.path.dirname(os.path.dirname(here))


class AgentManager:
    """设备端 uitest 守护进程管理器。

    管理流程：探测设备信息 → 检查守护进程 → 推送 agent.so → 启动守护进程 → 删除设备端 so。
    """

    def __init__(self, device: 'HdcDevice',
                 restart_daemon_on_setup: bool = False):
        self._device = device
        self._abi: Optional[str] = None
        self._protocol_version: Optional[int] = None
        # setup 时是否先清理残留 daemon 再启动（绕过复用优先策略）
        self._restart_daemon_on_setup = restart_daemon_on_setup

    def detect_device_info(self) -> Tuple[str, int]:
        """探测设备 ABI 与 uitest 协议版本。

        Returns:
            (abi, protocol_version) 元组，protocol_version 为 1（5.0）或 2（6.0+）。
        """
        abi = self._detect_abi()
        protocol_version = self._detect_protocol_version()
        self._abi = abi
        self._protocol_version = protocol_version
        logger.debug("设备信息 (serial=%s): abi=%s, protocol=v%d",
                    self._device.serial, abi, protocol_version)
        return abi, protocol_version

    @property
    def abi(self) -> Optional[str]:
        return self._abi

    @property
    def protocol_version(self) -> Optional[int]:
        return self._protocol_version

    def ensure_daemon_running(self) -> None:
        """确保 uitest 守护进程已启动。

        优先复用已有进程；未运行则推送 agent.so 并启动。
        无论守护进程是否已运行，都需探测协议版本以正确建立端口转发。
        """
        if self._abi is None or self._protocol_version is None:
            self.detect_device_info()

        # 启动清理开关：先杀残留 daemon 再重启，规避复用到版本不匹配或状态损坏的进程。
        # one-shot 语义：仅首次 setup 生效后立即置位，hdc 通道 BROKEN 重连会
        # 反复调用本方法，若不置位则"setup 时重启"退化为"每次重连都杀 daemon"
        if self._restart_daemon_on_setup:
            self._restart_daemon_on_setup = False
            logger.debug("restart_daemon_on_setup=True，清理残留守护进程 (serial=%s)",
                         self._device.serial)
            self.stop_daemon()
        elif self._is_daemon_running():
            logger.debug("uitest 守护进程已运行，复用 (serial=%s)",
                         self._device.serial)
            return

        logger.debug("uitest 守护进程未运行，准备启动 (serial=%s)",
                    self._device.serial)
        self._deploy_agent_so(self._abi, self._protocol_version)
        self._start_daemon_and_wait()

    def stop_daemon(self) -> None:
        """停止设备端 uitest 守护进程。

        复用 _find_daemon_pids 定位目标 pid 后逐个 kill -9。按 host 侧
        Python 过滤 cmdline，天然排除 scrcpy_server、extension-name 等
        扩展进程与 grep 自身，无需依赖设备端 pgrep 能力。
        """
        pids = self._find_daemon_pids()
        if not pids:
            logger.debug("uitest 守护进程未运行，无需停止 (serial=%s)",
                         self._device.serial)
            return
        for pid in pids:
            try:
                self._device.shell("kill -9 %s" % pid, timeout=5)
            except DeviceConnectError as e:
                logger.warning("kill -9 pid=%s 失败 (serial=%s): %s",
                            pid, self._device.serial, e)
        # 确认进程已退出，避免端口占用影响下次启动
        if self._find_daemon_pids():
            logger.warning("uitest 守护进程仍存活 (serial=%s)", self._device.serial)
        else:
            logger.debug("uitest 守护进程已停止 (serial=%s)",
                        self._device.serial)

    # ============================================================
    # 设备信息探测
    # ============================================================

    def _detect_abi(self) -> str:
        """获取设备 CPU ABI。"""
        try:
            raw = self._device.shell(
                'param get "const.product.cpu.abilist"', timeout=10
            ).strip()
        except DeviceConnectError as e:
            raise AgentError("获取设备 ABI 失败: %s" % e) from e
        # abilist 可能是 "arm64-v8a,armeabi-v7a"，取首个
        abi = raw.split(",")[0].strip() if raw else ""
        if not abi or abi == "default":
            abi = "arm64-v8a"
        return abi

    def _detect_protocol_version(self) -> int:
        """获取 uitest 版本并判定协议版本。"""
        try:
            raw = self._device.shell("uitest --version", timeout=10)
        except DeviceConnectError as e:
            raise AgentError("获取 uitest 版本失败: %s" % e) from e
        match = re.search(r"\d+\.\d+\.\d+\.\d+", raw)
        if not match:
            logger.warning("无法解析 uitest 版本 [%s]，默认 v1", raw.strip())
            return 1
        uitest_version = match.group()
        return (2 if _compare_version(uitest_version, PROTOCOL_V2_THRESHOLD) > 0
                else 1)

    # ============================================================
    # agent.so 选择与推送
    # ============================================================

    def _select_agent_so(self, abi: str, protocol_version: int) -> str:
        """选择本地 agent.so 文件路径。"""
        version_map = _AGENT_FILE_MAP.get(abi)
        if version_map is None:
            raise AgentError("不支持的设备 ABI: %s" % abi)
        filename = version_map.get(protocol_version)
        if filename is None:
            raise AgentError(
                "ABI %s 无 protocol v%d 对应的 agent.so" % (abi, protocol_version))
        path = os.path.join(_get_package_root(), SO_ASSET_DIR, abi, filename)
        if not os.path.isfile(path):
            raise AgentError("本地 agent.so 不存在: %s" % path)
        return path

    def _deploy_agent_so(self, abi: str, protocol_version: int) -> None:
        """推送 agent.so 到设备，MD5 匹配则跳过。"""
        local_path = self._select_agent_so(abi, protocol_version)
        local_md5 = self._calc_file_md5(local_path)

        device_md5 = self._get_device_file_md5(DEVICE_AGENT_PATH)
        if device_md5 == local_md5:
            logger.debug("agent.so MD5 匹配，跳过推送 (serial=%s)",
                         self._device.serial)
            return

        logger.debug("推送 agent.so (abi=%s, v%d, %s -> %s)",
                    abi, protocol_version,
                    (device_md5 or "none")[:8], local_md5[:8])
        # 推送前删除旧文件，避免权限问题导致覆盖失败
        try:
            self._device.shell('rm -f "%s"' % DEVICE_AGENT_PATH, timeout=10)
        except DeviceConnectError:
            pass
        self._device.push(local_path, DEVICE_AGENT_PATH)

    @staticmethod
    def _calc_file_md5(path: str) -> str:
        """计算本地文件 MD5。"""
        h = hashlib.md5()
        with open(path, "rb") as f:
            for chunk in iter(lambda: f.read(64 * 1024), b""):
                h.update(chunk)
        return h.hexdigest()

    def _get_device_file_md5(self, remote_path: str) -> Optional[str]:
        """获取设备端文件 MD5，不存在返回 None。"""
        cmd = 'test -f %s && md5sum %s || echo NOT_EXISTS' % (
            shlex.quote(remote_path), shlex.quote(remote_path))
        try:
            out = self._device.shell(cmd, timeout=15)
        except DeviceConnectError:
            return None
        out = out.strip()
        if not out or out == "NOT_EXISTS":
            return None
        match = re.match(r"^([a-f0-9]{32})", out, re.IGNORECASE)
        return match.group(1).lower() if match else None

    # ============================================================
    # 守护进程管理
    # ============================================================

    def _is_daemon_running(self) -> bool:
        """检查 uitest 守护进程是否运行。"""
        return bool(self._find_daemon_pids())

    def _find_daemon_pids(self) -> list:
        """定位设备端 uitest 守护进程 pid 列表。

        设备端仅执行最通用的 `ps -ef`（toybox 均支持），真正的过滤放在
        host 侧 Python，规避设备端 pgrep -f 匹配不完整/输出格式不一致的问题：

        - cmdline 需同时含 "start-daemon" 与 "singleness"，精确锁定守护进程；
        - 排除 grep/ps 自身进程行；
        - scrcpy_server、extension-name 等扩展进程 cmdline 不含上述组合，
          天然被排除，无需逐个 grep -v 打补丁。

        ps -ef 列布局: UID PID PPID ... CMD，pid 取第 2 列。
        """
        try:
            out = self._device.shell("ps -ef", timeout=10)
        except DeviceConnectError as e:
            logger.warning("查询 uitest 进程失败 (serial=%s): %s",
                           self._device.serial, e)
            return []
        pids = []
        for line in out.splitlines():
            if "start-daemon" not in line or "singleness" not in line:
                continue
            if "grep" in line or "ps -ef" in line:
                continue
            fields = line.split()
            if len(fields) < 2 or not fields[1].isdigit():
                continue
            pids.append(fields[1])
        return pids

    def _start_daemon_and_wait(self) -> None:
        """启动守护进程并渐进式等待就绪。"""
        try:
            self._device.shell(DAEMON_COMMAND, timeout=30)
        except DeviceConnectError as e:
            raise AgentError("启动 uitest 守护进程失败: %s" % e) from e

        for delay in DAEMON_START_DELAYS:
            time.sleep(delay)
            if self._is_daemon_running():
                logger.debug("uitest 守护进程已启动 (serial=%s)",
                            self._device.serial)
                # 进程已加载到内存，清理设备端临时 so 避免残留与版本混淆
                try:
                    self._device.shell('rm -f "%s"' % DEVICE_AGENT_PATH,
                                       timeout=5)
                except DeviceConnectError:
                    pass
                return

        raise AgentError(
            "uitest 守护进程启动超时 (serial=%s)" % self._device.serial)
