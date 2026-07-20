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
import threading
import time
from collections import deque
from contextlib import contextmanager
from datetime import datetime
from typing import Deque, Dict, Iterator, List, Optional, Tuple

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

# 单次请求允许越过的异步推送帧数量上限，防止通道错位时无限循环
MAX_INTERLEAVED_FRAMES = 8

# 暂存的越过帧总量上限，超限丢弃最老帧防止内存膨胀
PENDING_FRAMES_MAXLEN = 32

# wait_push 等待分片（秒）：短分片轮询以便 close() 能及时唤醒等待者
WAIT_PUSH_SLICE = 0.2

# hdc 管理类子进程命令（fport / list targets 等）超时（秒）
HDC_CMD_TIMEOUT = 20

# 状态机
STATE_CLOSED = "CLOSED"
STATE_CONNECTING = "CONNECTING"
STATE_READY = "READY"
STATE_BROKEN = "BROKEN"


class HdcDevice:
    """hdc 命令封装，提供 shell、文件传输、RPC 通道能力。

    线程模型：
    - rpc_call / wait_push 的 socket 读写由 _rpc_lock 串行化，多线程安全；
    - operation() 提供脚本/观察者两级准入：脚本（blocking=True）排队等待，
      观察者（blocking=False）在通道忙或有脚本排队时直接放弃，保证脚本优先；
    - close() 为终态操作，置 _closed 并唤醒等待中的 wait_push。
    """

    # hdc 可执行文件路径，默认从 PATH 查找；可通过 set_hdc_path 覆盖
    _hdc_path: str = "hdc"

    # 设备端是否回显请求 session_id。默认信任回显（现网 uitest 均回显），
    # 连接探活时按实测校准为实例属性；不回显的旧设备退回"下一帧即响应"。
    _sid_echo: bool = True

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
        # RPC 通道串行锁：socket 读写、状态迁移、暂存帧均在其保护下
        self._rpc_lock = threading.RLock()
        # 准入状态锁（细粒度，仅保护 _script_waiters 计数）
        self._operation_state_lock = threading.Lock()
        # 正在排队等待通道的脚本调用数，观察者据此让路
        self._script_waiters = 0
        self._closed = False
        self._close_event = threading.Event()
        # 越过的帧按 session_id 分区暂存：响应帧按 sid 定向取回，
        # 推送帧（无归属 sid）按到达顺序由 wait_push 消费
        self._pending_frames: Dict[int, str] = {}
        self._pending_order: Deque[Tuple[Optional[int], str]] = deque()
        self._agent = AgentManager(
            self, restart_daemon_on_setup=restart_daemon_on_setup
        )

    # ============================================================
    # hdc 命令封装
    # ============================================================

    def _hdc_cmd(self, *args: str) -> List[str]:
        """构造 hdc 命令列表，统一使用 _hdc_path 与设备序列号。"""
        return [self._hdc_path, "-t", self.serial, *args]

    @staticmethod
    def _run_checked(cmd: List[str], desc: str, timeout: float) -> str:
        """执行 hdc 子进程命令，统一超时与失败异常契约。

        hdc 部分子命令失败时退出码仍为 0、仅在 stdout 打印 [Fail]，
        故除退出码外还需检查输出文本。所有异常统一收口为
        DeviceConnectError，保证下游 except 契约稳定。
        """
        try:
            result = subprocess.run(
                cmd, capture_output=True, text=True,
                encoding="utf-8", errors="replace", timeout=timeout
            )
        except subprocess.TimeoutExpired as e:
            raise DeviceConnectError(
                "hdc 命令超时 [%s]（%ss）" % (desc, timeout)) from e
        except OSError as e:
            raise DeviceConnectError(
                "hdc 命令执行失败 [%s]: %s" % (desc, e)) from e
        output = (result.stdout or "") + (result.stderr or "")
        if result.returncode != 0 or "[fail]" in output.lower():
            raise DeviceConnectError(
                "hdc 命令失败 [%s]: %s" % (desc, output.strip()))
        return result.stdout or ""

    def shell(self, cmd: str, timeout: float = 60) -> str:
        """执行 shell 命令，返回回显。"""
        try:
            result = subprocess.run(
                self._hdc_cmd("shell", cmd),
                capture_output=True, text=True,
                encoding="utf-8", errors="replace",
                timeout=timeout
            )
        except subprocess.TimeoutExpired as e:
            raise DeviceConnectError(
                "shell 命令超时 [%s]（%ss）" % (cmd, timeout)) from e
        except OSError as e:
            raise DeviceConnectError(
                "shell 命令执行失败 [%s]: %s" % (cmd, e)) from e
        if result.returncode != 0:
            raise DeviceConnectError(
                "shell 命令失败 [%s]: %s" % (cmd, result.stderr)
            )
        return result.stdout

    def push(self, local_path: str, remote_path: str, timeout: int = 60) -> None:
        """推送文件到设备。"""
        self._run_checked(
            self._hdc_cmd("file", "send", local_path, remote_path),
            "file send %s -> %s" % (local_path, remote_path), timeout)

    def pull(self, remote_path: str, local_path: str, timeout: int = 60) -> None:
        """从设备拉取文件。"""
        self._run_checked(
            self._hdc_cmd("file", "recv", remote_path, local_path),
            "file recv %s -> %s" % (remote_path, local_path), timeout)

    def install(self, hap_path: str, options: str = "", timeout: int = 120) -> None:
        """安装应用。"""
        cmd = self._hdc_cmd("install")
        if options:
            cmd.extend(options.split())
        cmd.append(hap_path)
        self._run_checked(cmd, "install %s" % hap_path, timeout)

    def uninstall(self, package: str, timeout: int = 60) -> None:
        """卸载应用。"""
        self._run_checked(
            self._hdc_cmd("uninstall", package),
            "uninstall %s" % package, timeout)

    @classmethod
    def list_targets(cls) -> List[str]:
        """列出所有连接的设备序列号。"""
        output = cls._run_checked(
            [cls._hdc_path, "list", "targets"],
            "list targets", HDC_CMD_TIMEOUT)
        targets = []
        for line in output.splitlines():
            line = line.strip()
            if line and line != "[Empty]":
                targets.append(line)
        return targets

    @property
    def agent(self) -> AgentManager:
        """设备端 uitest Agent 管理器（daemon 启停、pid 探测）。

        供 screenshot_stream 等模块复用，避免跨模块访问私有成员。
        """
        return self._agent

    # ============================================================
    # 端口转发（公开 API，webview / 截图推流复用）
    # ============================================================

    def fport(self, local_port: int, remote_target: str) -> None:
        """建立主机侧端口转发 tcp:local_port → 设备端 remote_target。

        Args:
            local_port: 主机本地端口
            remote_target: 设备端目标，如 "tcp:9222" 或 "localabstract:xxx"

        Raises:
            DeviceConnectError: 转发建立失败
        """
        self._run_checked(
            self._hdc_cmd("fport", "tcp:%d" % local_port, remote_target),
            "fport tcp:%d %s" % (local_port, remote_target),
            HDC_CMD_TIMEOUT)

    def fport_rm(self, local_port: int, remote_target: str) -> None:
        """移除端口转发。清理路径失败仅记录日志，不向上抛出。"""
        try:
            subprocess.run(
                self._hdc_cmd("fport", "rm",
                              "tcp:%d" % local_port, remote_target),
                capture_output=True, text=True,
                encoding="utf-8", errors="replace",
                timeout=HDC_CMD_TIMEOUT, check=False
            )
        except Exception as e:
            logger.debug("移除端口转发异常（忽略）: %s", e)

    # ============================================================
    # RPC 通道（bin 模式，端口 8012）
    # ============================================================

    @contextmanager
    def operation(self, blocking: bool = True) -> Iterator[bool]:
        """设备通道准入控制，返回是否获得通道。

        - 脚本操作（blocking=True，默认）：排队等待通道，必得（yield True）。
        - 观察者操作（blocking=False）：通道忙或已有脚本在排队时直接放弃
          （yield False），保证用户脚本优先，观察者只利用空闲窗口。
        """
        if blocking:
            with self._operation_state_lock:
                self._script_waiters += 1
            try:
                self._rpc_lock.acquire()
            finally:
                with self._operation_state_lock:
                    self._script_waiters -= 1
            try:
                yield True
            finally:
                self._rpc_lock.release()
            return
        with self._operation_state_lock:
            script_pending = self._script_waiters > 0
        if script_pending:
            yield False
            return
        acquired = self._rpc_lock.acquire(blocking=False)
        try:
            yield acquired
        finally:
            if acquired:
                self._rpc_lock.release()

    def rpc_call(self, msg: str) -> str:
        """RPC 通信入口（线程安全，按设备串行）。

        首次调用懒建立 hdc fport + socket 通道；
        READY 状态复用长连接；BROKEN 状态重建。

        连接阶段失败按指数退避重试；通信阶段失败直接抛异常，
        避免对有副作用操作（点击、输入等）重复执行。
        """
        with self.operation():
            if self._closed:
                raise DeviceConnectError("设备通道已关闭")
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

        优先消费 rpc_call 期间越过并暂存的推送帧；无暂存时以短分片
        select 等待新帧，等待期间不持通道锁，close() 可及时唤醒。

        Args:
            timeout: 等待超时（秒）

        Returns:
            推送帧 body JSON 字符串；超时无数据返回 None

        Raises:
            DeviceConnectError: 通道已关闭
        """
        deadline = time.monotonic() + timeout
        while True:
            if self._closed:
                raise DeviceConnectError("设备通道已关闭")
            with self._rpc_lock:
                body = self._pop_oldest_pending_frame()
                if body is not None:
                    return body
                if self._state != STATE_READY:
                    self._connect_with_retry()
                    body = self._pop_oldest_pending_frame()
                    if body is not None:
                        return body
                sock = self._socket
            if sock is None:
                raise DeviceConnectError("socket 未建立")
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                return None
            # 锁外短分片等待：既不阻塞并发 rpc_call，也让 close() 能打断
            try:
                rlist, _, _ = select.select(
                    [sock], [], [], min(WAIT_PUSH_SLICE, remaining))
            except (OSError, ValueError):
                # close() 关闭 socket 会使 select 失败
                if self._closed:
                    raise DeviceConnectError("设备通道已关闭")
                raise
            if not rlist:
                continue
            with self._rpc_lock:
                if self._closed:
                    raise DeviceConnectError("设备通道已关闭")
                # 可读信号对应的帧可能已被并发 rpc_call 消费并暂存
                body = self._pop_oldest_pending_frame()
                if body is not None:
                    return body
                if self._socket is None:
                    raise DeviceConnectError("socket 未建立")
                ready, _, _ = select.select([self._socket], [], [], 0)
                if not ready:
                    continue
                old_timeout = self._socket.gettimeout()
                self._socket.settimeout(5.0)
                try:
                    _, body = self._recv_frame()
                    return body
                except (socket.timeout, OSError, DeviceConnectError) as e:
                    logger.warning("wait_push 接收异常，转入 BROKEN: %s", e)
                    self._set_broken()
                    return None
                finally:
                    if self._socket is not None:
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
        设备端回显 session_id 时（真机实测 uitest 均回显，探活校准），
        按其关联请求-响应：session_id 不匹配的帧（事件推送等）暂存，
        供 wait_push 消费，避免被误读为本次调用的返回值。
        """
        if self._socket is None:
            raise DeviceConnectError("socket 未建立")
        session_id = random.randint(0, 0xFFFFFFFF)
        self._socket.sendall(self._build_frame(msg, session_id))
        return self._recv_response(session_id)

    def _recv_response(self, expected_sid: int) -> str:
        """接收 expected_sid 对应的响应帧，越过的帧暂存。"""
        pending = self._pending_frames.pop(expected_sid, None)
        if pending is not None:
            return pending
        for _ in range(MAX_INTERLEAVED_FRAMES):
            recv_sid, body = self._recv_frame()
            if not self._sid_echo or recv_sid is None \
                    or recv_sid == expected_sid:
                return body
            logger.debug("收到非本次请求的帧（sid=%s），暂存", recv_sid)
            self._enqueue_pending_frame(recv_sid, body)
        raise DeviceConnectError(
            "连续收到 %d 个非本次请求的帧，RPC 通道疑似错位"
            % MAX_INTERLEAVED_FRAMES)

    def _enqueue_pending_frame(self, sid: Optional[int], body: str) -> None:
        """暂存越过的帧：按 sid 建索引供响应定向取回，按序供推送消费。"""
        if len(self._pending_order) >= PENDING_FRAMES_MAXLEN:
            dropped = self._pop_oldest_pending_frame()
            if dropped is not None:
                logger.warning("暂存帧超限（%d），丢弃最老帧",
                               PENDING_FRAMES_MAXLEN)
        if sid is not None:
            self._pending_frames[sid] = body
        self._pending_order.append((sid, body))

    def _pop_oldest_pending_frame(self) -> Optional[str]:
        """按到达顺序取出最老的未被认领帧；已被响应定向取走的跳过。"""
        while self._pending_order:
            sid, body = self._pending_order.popleft()
            if sid is None:
                return body
            if self._pending_frames.pop(sid, None) is not None:
                return body
        return None

    @staticmethod
    def _build_frame(msg: str, session_id: int) -> bytes:
        """构造 UITest RPC 协议帧。

        格式: HEAD + sessionId(4字节大端) + length(4字节大端) + body + TAIL
        """
        body = msg.encode("utf-8")
        return RPC_HEAD + struct.pack(">II", session_id, len(body)) + body + RPC_TAIL

    def _recv_frame(self) -> Tuple[Optional[int], str]:
        """接收并解析 UITest RPC 协议帧，返回 (session_id, body)。

        设备端异常时可能返回裸 JSON（无协议帧包装），
        此时尝试读取完整 JSON 交给上层处理，session_id 为 None。
        """
        if self._socket is None:
            raise DeviceConnectError("socket 未建立")
        head = self._recv_exact(len(RPC_HEAD))
        if head != RPC_HEAD:
            # HEAD 不匹配，可能是设备端返回了裸 JSON 异常
            if head[:1] == b'{':
                return None, self._recv_raw_json(head)
            raise DeviceConnectError("协议帧 HEAD 不匹配: %r" % head[:32])
        header = self._recv_exact(8)
        session_id, length = struct.unpack(">II", header)
        if length > RECV_BUFFER_LIMIT:
            raise DeviceConnectError("协议帧 body 过大: %d 字节" % length)
        body = self._recv_exact(length)
        tail = self._recv_exact(len(RPC_TAIL))
        if tail != RPC_TAIL:
            raise DeviceConnectError("协议帧 TAIL 不匹配")
        return session_id, body.decode("utf-8")

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

        使用无副作用的 getDeviceInfo 作为探活消息。同时判定设备端是否
        回显请求 session_id：回显可用时后续按 session_id 关联请求-响应，
        不可用时保持"下一帧即响应"的兼容行为。
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
        session_id = random.randint(0, 0xFFFFFFFF)
        frame = self._build_frame(msg, session_id)
        if self._socket is None:
            raise DeviceConnectError("socket 未建立")
        self._socket.sendall(frame)
        recv_sid, _ = self._recv_frame()
        self._sid_echo = (recv_sid == session_id)
        logger.debug("session_id 回显判定: %s", self._sid_echo)

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
        self.fport(self._local_port, target)
        self._fport_established = True

    def _cleanup_fport(self) -> None:
        """清理 hdc 端口转发。"""
        if not self._fport_established or self._local_port is None:
            return
        if self._agent.protocol_version and self._agent.protocol_version >= 2:
            target = "localabstract:%s" % UITEST_SOCKET_NAME
        else:
            target = "tcp:%d" % RPC_PORT
        self.fport_rm(self._local_port, target)
        self._fport_established = False
        self._local_port = None

    # ============================================================
    # 状态机
    # ============================================================

    def reset_connection(self) -> None:
        """主动使 RPC 通道失效，下一次 rpc_call 自动重建连接。

        供显式重启设备端守护进程（如推流启动失败清理 daemon）后调用，
        避免下一次 RPC 在已死的旧连接上白白失败一次。
        """
        with self._rpc_lock:
            if self._state == STATE_READY:
                logger.debug("RPC 通道被主动重置（daemon 已重启）")
                self._set_broken()

    def _set_broken(self) -> None:
        """转入 BROKEN 状态，丢弃暂存帧（连接级状态已失效）。"""
        self._state = STATE_BROKEN
        self._pending_frames.clear()
        self._pending_order.clear()
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
        """关闭通道，释放 socket 与端口转发。终态操作，不可再复用。

        先置关闭标记再收资源：等待中的 wait_push 会被唤醒并抛
        DeviceConnectError，避免消费者卡满超时。

        Args:
            stop_daemon: 是否停止设备端 uitest 守护进程。
                默认 False，守护进程可复用，避免频繁启停开销。
                True 时调用 AgentManager.stop_daemon() 清理设备端进程。
        """
        self._closed = True
        self._close_event.set()
        with self._rpc_lock:
            self._close_socket()
            self._cleanup_fport()
            self._pending_frames.clear()
            self._pending_order.clear()
            self._state = STATE_CLOSED
        if stop_daemon:
            self._agent.stop_daemon()

    def __enter__(self) -> 'HdcDevice':
        return self

    def __exit__(self, exc_type, exc_val, exc_tb) -> bool:
        self.close()
        return False
