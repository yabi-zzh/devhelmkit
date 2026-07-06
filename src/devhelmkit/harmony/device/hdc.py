# !/usr/bin/env python
# -*- coding: utf-8 -*-
"""HdcDevice：hdc 命令封装与 bin 模式 RPC 通道。

替代 xdevice DeviceNode，仅依赖 hdc 命令行工具。
RPC 通道统一使用 bin 模式（端口 8012），懒建立并复用长连接。

状态机：CLOSED / CONNECTING / READY / BROKEN
- 懒连接：首次 rpc_call 时建立 hdc fport + socket，不在构造阶段创建
- 长连接复用：READY 状态下 socket 持续复用，降低延迟
- 断线重建：连接阶段失败按指数退避重试；通信阶段失败不重试
"""
import json
import logging
import random
import select
import socket
import struct
import subprocess
import time
from datetime import datetime
from typing import List, Optional

from devhelmkit.exceptions import DeviceConnectError
from devhelmkit.harmony.agent.so_manager import AgentManager

logger = logging.getLogger(__name__)

# bin 模式 RPC 端口（v1 协议设备端监听端口；v2 协议使用 localabstract）
RPC_PORT = 8012

# UITest RPC 协议帧头尾
RPC_HEAD = b"_uitestkit_rpc_message_head_"
RPC_TAIL = b"_uitestkit_rpc_message_tail_"

# v2 协议设备端 localabstract socket 名称
UITEST_SOCKET_NAME = "uitest_socket"

# 连接重试参数
MAX_CONNECT_RETRIES = 3
CONNECT_RETRY_BASE_INTERVAL = 1.0

# socket 通信超时（秒）
SOCKET_TIMEOUT = 30

# 接收缓冲上限（字节），防止异常回显导致内存膨胀
RECV_BUFFER_LIMIT = 16 * 1024 * 1024

# 状态机
STATE_CLOSED = "CLOSED"
STATE_CONNECTING = "CONNECTING"
STATE_READY = "READY"
STATE_BROKEN = "BROKEN"


class HdcDevice:
    """hdc 命令封装，提供 shell、文件传输、RPC 通道能力。"""

    # hdc 可执行文件路径，默认从 PATH 查找；可通过 set_hdc_path 覆盖
    _hdc_path: str = "hdc"

    @classmethod
    def set_hdc_path(cls, path: str) -> None:
        """设置 hdc 可执行文件路径。

        当 hdc 未加入系统 PATH，或需指定特定版本时使用。
        设置后对所有后续创建的 HdcDevice 实例生效。

        Args:
            path: hdc 可执行文件绝对路径
        """
        cls._hdc_path = path

    def __init__(self, serial: str, restart_daemon_on_setup: bool = False):
        self.serial = serial
        self._socket: Optional[socket.socket] = None
        self._state = STATE_CLOSED
        self._fport_established = False
        self._local_port: Optional[int] = None
        self._agent = AgentManager(
            self, restart_daemon_on_setup=restart_daemon_on_setup
        )

    # ============================================================
    # hdc 命令封装
    # ============================================================

    def _hdc_cmd(self, *args: str) -> List[str]:
        """构造 hdc 命令列表，统一使用 _hdc_path 与设备序列号。"""
        return [self._hdc_path, "-t", self.serial, *args]

    def shell(self, cmd: str, timeout: float = 60) -> str:
        """执行 shell 命令，返回回显。"""
        result = subprocess.run(
            self._hdc_cmd("shell", cmd),
            capture_output=True, text=True, encoding="utf-8",
            timeout=timeout
        )
        if result.returncode != 0:
            raise DeviceConnectError(
                "shell 命令失败 [%s]: %s" % (cmd, result.stderr)
            )
        return result.stdout

    def push(self, local_path: str, remote_path: str, timeout: int = 60) -> None:
        """推送文件到设备。"""
        subprocess.run(
            self._hdc_cmd("file", "send", local_path, remote_path),
            check=True, timeout=timeout
        )

    def pull(self, remote_path: str, local_path: str, timeout: int = 60) -> None:
        """从设备拉取文件。"""
        subprocess.run(
            self._hdc_cmd("file", "recv", remote_path, local_path),
            check=True, timeout=timeout
        )

    def install(self, hap_path: str, options: str = "", timeout: int = 120) -> None:
        """安装应用。"""
        cmd = self._hdc_cmd("install")
        if options:
            cmd.extend(options.split())
        cmd.append(hap_path)
        subprocess.run(cmd, check=True, timeout=timeout)

    def uninstall(self, package: str, timeout: int = 60) -> None:
        """卸载应用。"""
        subprocess.run(
            self._hdc_cmd("uninstall", package),
            check=True, timeout=timeout
        )

    @classmethod
    def list_targets(cls) -> List[str]:
        """列出所有连接的设备序列号。"""
        result = subprocess.run(
            [cls._hdc_path, "list", "targets"],
            capture_output=True, text=True, encoding="utf-8"
        )
        targets = []
        for line in result.stdout.splitlines():
            line = line.strip()
            if line and line != "[Empty]":
                targets.append(line)
        return targets

    # ============================================================
    # RPC 通道（bin 模式，端口 8012）
    # ============================================================

    def rpc_call(self, msg: str) -> str:
        """RPC 通信入口。

        首次调用懒建立 hdc fport + socket 通道；
        READY 状态复用长连接；BROKEN 状态重建。

        连接阶段失败按指数退避重试；通信阶段失败直接抛异常，
        避免对有副作用操作（点击、输入等）重复执行。
        """
        if self._state == STATE_READY:
            try:
                return self._send_and_recv(msg)
            except (BrokenPipeError, ConnectionResetError,
                    socket.timeout, OSError, DeviceConnectError) as e:
                logger.warning("RPC 通道异常，转入 BROKEN: %s", e)
                self._set_broken()
                raise DeviceConnectError("RPC 通道断开: %s" % e) from e

        self._connect_with_retry()
        return self._send_and_recv(msg)

    def wait_push(self, timeout: float = 3.0) -> Optional[str]:
        """等待并接收设备端异步推送帧（如事件回调）。

        用 select 检测 socket 可读，可读时读取完整帧；
        不可读（超时）返回 None，不消费任何字节，避免协议错位。

        与 rpc_call 共享同一 socket，不可并发调用（单线程顺序使用）。

        Args:
            timeout: 等待超时（秒）

        Returns:
            推送帧 body JSON 字符串；超时无数据返回 None
        """
        if self._state != STATE_READY:
            self._connect_with_retry()
        if self._socket is None:
            raise DeviceConnectError("socket 未建立")
        rlist, _, _ = select.select([self._socket], [], [], timeout)
        if not rlist:
            return None
        old_timeout = self._socket.gettimeout()
        self._socket.settimeout(5.0)
        try:
            return self._recv_frame()
        except (socket.timeout, OSError, DeviceConnectError) as e:
            logger.warning("wait_push 接收异常，转入 BROKEN: %s", e)
            self._set_broken()
            return None
        finally:
            self._socket.settimeout(old_timeout)

    def _connect_with_retry(self) -> None:
        """建立连接，失败时指数退避重试。"""
        last_error: Optional[Exception] = None
        for attempt in range(MAX_CONNECT_RETRIES):
            try:
                self._connect()
                return
            except DeviceConnectError as e:
                last_error = e
                if attempt < MAX_CONNECT_RETRIES - 1:
                    wait = CONNECT_RETRY_BASE_INTERVAL * (2 ** attempt)
                    logger.debug("连接失败，%.1fs 后重试 (%d/%d)",
                                wait, attempt + 1, MAX_CONNECT_RETRIES)
                    time.sleep(wait)
        if last_error is None:
            raise DeviceConnectError("连接重试未产生异常（不应发生）")
        raise last_error

    def _connect(self) -> None:
        """建立 uitest 守护进程 + hdc fport + socket 连接，并发送探活。"""
        self._state = STATE_CONNECTING
        try:
            self._agent.ensure_daemon_running()
            self._setup_fport()
            sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            sock.settimeout(SOCKET_TIMEOUT)
            sock.connect(("127.0.0.1", self._local_port))
            self._socket = sock
            self._probe_agent()
            self._state = STATE_READY
            logger.debug("RPC 通道已建立 (serial=%s)", self.serial)
        except Exception as e:
            logger.warning("RPC 通道建立失败 (serial=%s): %s", self.serial, e)
            self._close_socket()
            self._cleanup_fport()
            self._state = STATE_CLOSED
            raise DeviceConnectError("无法连接到 Agent: %s" % e) from e

    def _send_and_recv(self, msg: str) -> str:
        """发送 RPC 请求并接收响应。

        使用 UITest 协议帧：HEAD + sessionId(4) + length(4) + body + TAIL。
        """
        if self._socket is None:
            raise DeviceConnectError("socket 未建立")
        frame = self._build_frame(msg)
        self._socket.sendall(frame)
        return self._recv_frame()

    @staticmethod
    def _build_frame(msg: str) -> bytes:
        """构造 UITest RPC 协议帧。

        格式: HEAD + sessionId(4字节大端) + length(4字节大端) + body + TAIL
        """
        body = msg.encode("utf-8")
        session_id = random.randint(0, 0xFFFFFFFF)
        return RPC_HEAD + struct.pack(">II", session_id, len(body)) + body + RPC_TAIL

    def _recv_frame(self) -> str:
        """接收并解析 UITest RPC 协议帧，返回 body JSON 字符串。

        设备端异常时可能返回裸 JSON（无协议帧包装），
        此时尝试读取完整 JSON 交给上层处理。
        """
        if self._socket is None:
            raise DeviceConnectError("socket 未建立")
        head = self._recv_exact(len(RPC_HEAD))
        if head != RPC_HEAD:
            # HEAD 不匹配，可能是设备端返回了裸 JSON 异常
            if head[:1] == b'{':
                return self._recv_raw_json(head)
            raise DeviceConnectError("协议帧 HEAD 不匹配: %r" % head[:32])
        header = self._recv_exact(8)
        _session_id, length = struct.unpack(">II", header)
        if length > RECV_BUFFER_LIMIT:
            raise DeviceConnectError("协议帧 body 过大: %d 字节" % length)
        body = self._recv_exact(length)
        tail = self._recv_exact(len(RPC_TAIL))
        if tail != RPC_TAIL:
            raise DeviceConnectError("协议帧 TAIL 不匹配")
        return body.decode("utf-8")

    def _recv_raw_json(self, first_bytes: bytes) -> str:
        """读取裸 JSON 响应（设备端异常时可能不按协议帧格式返回）。

        以短超时读取剩余数据，尝试解析为完整 JSON。
        """
        buf = bytearray(first_bytes)
        old_timeout = self._socket.gettimeout()
        self._socket.settimeout(2.0)
        try:
            while True:
                try:
                    chunk = self._socket.recv(4096)
                except socket.timeout:
                    break
                if not chunk:
                    break
                buf.extend(chunk)
                # 尝试解析为完整 JSON
                try:
                    text = buf.decode("utf-8")
                    json.loads(text)
                    return text
                except (json.JSONDecodeError, UnicodeDecodeError):
                    continue
        finally:
            self._socket.settimeout(old_timeout)
        raise DeviceConnectError("协议帧 HEAD 不匹配: %r" % bytes(buf[:32]))

    def _recv_exact(self, n: int) -> bytes:
        """精确读取 n 字节。"""
        if self._socket is None:
            raise DeviceConnectError("socket 未建立")
        buf = bytearray()
        while len(buf) < n:
            chunk = self._socket.recv(min(4096, n - len(buf)))
            if not chunk:
                raise ConnectionResetError("socket 对端关闭")
            buf.extend(chunk)
            if len(buf) > RECV_BUFFER_LIMIT:
                raise DeviceConnectError(
                    "回显超过缓冲上限 %d 字节" % RECV_BUFFER_LIMIT)
        return bytes(buf)

    def _probe_agent(self) -> None:
        """发送探活 RPC 确认通道可用。

        使用无副作用的 getDeviceInfo 作为探活消息。
        """
        probe_msg = {
            "module": "com.ohos.devicetest.hypiumApiHelper",
            "method": "callHypiumApi",
            "params": {
                "api": "Driver.getDeviceInfo",
                "this": "Driver#0",
                "args": [],
                "message_type": "hypium"
            },
            "request_id": datetime.now().strftime("%Y%m%d%H%M%S%f")
        }
        msg = json.dumps(probe_msg, ensure_ascii=False, separators=(',', ':'))
        frame = self._build_frame(msg)
        if self._socket is None:
            raise DeviceConnectError("socket 未建立")
        self._socket.sendall(frame)
        self._recv_frame()

    # ============================================================
    # 端口转发
    # ============================================================

    def _setup_fport(self) -> None:
        """建立 hdc 端口转发。

        动态分配本地端口，v2 协议（6.0+）转发到 localabstract:uitest_socket；
        v1 协议（5.0）转发到 tcp:8012。
        """
        if self._fport_established:
            return
        # 动态分配本地空闲端口
        s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        s.bind(("127.0.0.1", 0))
        self._local_port = s.getsockname()[1]
        s.close()

        if self._agent.protocol_version and self._agent.protocol_version >= 2:
            target = "localabstract:%s" % UITEST_SOCKET_NAME
        else:
            target = "tcp:%d" % RPC_PORT
        subprocess.run(
            self._hdc_cmd("fport", "tcp:%d" % self._local_port, target),
            check=True
        )
        self._fport_established = True

    def _cleanup_fport(self) -> None:
        """清理 hdc 端口转发。"""
        if not self._fport_established or self._local_port is None:
            return
        if self._agent.protocol_version and self._agent.protocol_version >= 2:
            target = "localabstract:%s" % UITEST_SOCKET_NAME
        else:
            target = "tcp:%d" % RPC_PORT
        try:
            subprocess.run(
                self._hdc_cmd("fport", "rm",
                              "tcp:%d" % self._local_port, target),
                check=False
            )
        except Exception as e:
            logger.debug("移除端口转发异常（忽略）: %s", e)
        self._fport_established = False
        self._local_port = None

    # ============================================================
    # 状态机
    # ============================================================

    def _set_broken(self) -> None:
        """转入 BROKEN 状态。"""
        self._state = STATE_BROKEN
        self._close_socket()

    def _close_socket(self) -> None:
        """关闭 socket。"""
        if self._socket is not None:
            try:
                self._socket.close()
            except Exception as e:
                logger.debug("关闭 socket 异常（忽略）: %s", e)
            self._socket = None

    # ============================================================
    # 生命周期
    # ============================================================

    def close(self, stop_daemon: bool = False) -> None:
        """关闭通道，释放 socket 与端口转发。

        Args:
            stop_daemon: 是否停止设备端 uitest 守护进程。
                默认 False，守护进程可复用，避免频繁启停开销。
                True 时调用 AgentManager.stop_daemon() 清理设备端进程。
        """
        self._close_socket()
        self._cleanup_fport()
        if stop_daemon:
            self._agent.stop_daemon()
        self._state = STATE_CLOSED

    def __enter__(self) -> 'HdcDevice':
        return self

    def __exit__(self, exc_type, exc_val, exc_tb) -> bool:
        self.close()
        return False
