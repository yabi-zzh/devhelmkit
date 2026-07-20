# !/usr/bin/env python
# -*- coding: utf-8 -*-
"""chromedriver 进程管理：启动、停止、版本匹配。

chromedriver 是 selenium webdriver 与 webview 之间的桥梁。
本模块负责：
  1. 按平台选择正确的二进制文件名（chromedriver.exe / chromedriver / chromedriver.mac）
  2. 按设备 webview 版本匹配 chromedriver 版本
  3. 启动 chromedriver 进程并监听指定端口
  4. 版本不匹配时停止旧进程并重启
  5. 资源释放时停止 chromedriver 进程

chromedriver 二进制需用户自行下载放置于 search_path 目录下：
    search_path/
    ├── chromedriver_114/
    │   ├── chromedriver.exe      # Windows
    │   ├── chromedriver          # Linux
    │   └── chromedriver.mac      # macOS
    └── chromedriver_132/
        ├── chromedriver.exe
        ├── chromedriver
        └── chromedriver.mac
"""
import json
import logging
import os
import platform
import socket
import stat
import subprocess
import tempfile
import time
import urllib.request
from typing import Optional

from devhelmkit.exceptions import DevhelmError

logger = logging.getLogger(__name__)

# chromedriver 日志级别环境变量名
CHROME_DRIVER_LOG_LEVEL_ENV = "CHROME_DRIVER_LOG_LEVEL"

# 停止旧进程后到重启之间的等待时间（秒），留出端口释放窗口
KILL_WAIT = 1.0


class ChromedriverManager:
    """chromedriver 进程生命周期管理。"""

    def __init__(self, search_path: str = "",
                 exe_path: str = "",
                 port: int = 0):
        """
        Args:
            search_path: chromedriver 存放目录（多版本目录结构）
            exe_path: 直接指定 chromedriver 可执行文件路径（优先于 search_path）
            port: chromedriver 监听端口，0 表示启动时动态分配空闲端口，
                避免固定端口造成全机只能跑一个实例
        """
        self._search_path = search_path
        self._exe_path = exe_path
        self._fixed_port = port
        self._port = port
        self._process: Optional[subprocess.Popen] = None
        self._log_path = ""

    @property
    def host(self) -> str:
        """chromedriver 访问地址。"""
        return "http://localhost:%d" % self._port

    @property
    def port(self) -> int:
        return self._port

    def set_exe_path(self, path: str) -> None:
        """直接指定 chromedriver 可执行文件路径。"""
        self._exe_path = path

    def set_search_path(self, path: str) -> None:
        """设置 chromedriver 存放目录。"""
        self._search_path = path

    def start(self, webview_version: int) -> None:
        """启动与 webview 版本匹配的 chromedriver。

        chromedriver 主版本必须与 webview 内核一致：已运行实例的主版本
        与目标不相等时（无论更高还是更低）都停止后重启；相等才复用。

        Args:
            webview_version: 设备端 webview 内核版本号（如 114）

        Raises:
            DevhelmError: chromedriver 未找到或启动失败
        """
        chrome_path = self._resolve_path(webview_version)
        if self._is_running():
            current_version = self._get_version()
            if current_version != webview_version:
                logger.debug(
                    "chromedriver 版本 %d 与 webview 版本 %d 不一致，重启",
                    current_version, webview_version
                )
                self.stop()
                time.sleep(KILL_WAIT)
                self._start_process(chrome_path)
            else:
                logger.debug("chromedriver 已运行，版本 %d，复用", current_version)
        else:
            self._start_process(chrome_path)

    def stop(self) -> None:
        """停止本实例启动的 chromedriver 进程。

        只管理自己启动的 _process，不按进程名清理"残留"，
        避免误杀其他项目或用户的 chromedriver / selenium 会话。
        """
        if self._process is None:
            return
        try:
            self._process.terminate()
            self._process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            self._process.kill()
            self._process.wait(timeout=3)
        except Exception as e:
            logger.warning("停止 chromedriver 进程异常: %s", e)
        finally:
            self._process = None

    def _resolve_path(self, version: int) -> str:
        """解析 chromedriver 可执行文件路径。

        优先级：exe_path > search_path/chromedriver_{version}/{name}；
        无内置回退，两者均未配置或文件不存在时直接报错。
        """
        proc_name = self._get_process_name()
        if self._exe_path:
            path = self._exe_path
        elif self._search_path:
            path = os.path.join(
                self._search_path, "chromedriver_%d" % version, proc_name
            )
        else:
            raise DevhelmError(
                "未配置 chromedriver 路径，请通过 set_exe_path 或 set_search_path 设置"
            )

        if not os.path.isfile(path):
            raise DevhelmError("chromedriver 不存在: %s" % path)
        return path

    def _start_process(self, chrome_path: str) -> None:
        """启动 chromedriver 子进程。"""
        if not _is_windows():
            os.chmod(chrome_path, stat.S_IRWXU)

        # 未指定固定端口时动态分配，支持多实例并行
        if self._fixed_port <= 0:
            self._port = _get_unused_port()

        log_path = os.path.join(
            tempfile.gettempdir(), "chromedriver.log"
        )
        log_level = os.getenv(CHROME_DRIVER_LOG_LEVEL_ENV, "info")
        cmd = [
            chrome_path,
            "--log-level=%s" % log_level,
            "--log-path=%s" % log_path,
            "--port=%d" % self._port,
        ]
        self._log_path = log_path
        logger.debug("启动 chromedriver: %s", " ".join(cmd))
        self._process = subprocess.Popen(cmd)

    def _is_running(self) -> bool:
        """检查 chromedriver 是否在运行（通过 HTTP /status）。"""
        if self._port <= 0:
            return False
        try:
            with urllib.request.urlopen(
                self.host + "/status", timeout=2
            ) as response:
                response.read()
            return True
        except Exception:
            return False

    def _get_version(self) -> int:
        """查询运行中 chromedriver 的主版本号，失败返回 0。

        /status 返回结构: {"value": {"build": {"version": "114.0.x.y (...)"}}}
        """
        for _ in range(3):
            try:
                with urllib.request.urlopen(
                    self.host + "/status", timeout=5
                ) as response:
                    resp = response.read().decode("utf-8", errors="ignore")
                info = json.loads(resp)
                version_str = (
                    info.get("value", {}).get("build", {}).get("version", "")
                )
                major = version_str.split(".", 1)[0]
                if major.isdigit():
                    return int(major)
            except Exception as e:
                logger.debug("查询 chromedriver 版本失败: %s", e)
        return 0

    @staticmethod
    def _get_process_name() -> str:
        """获取当前平台的 chromedriver 进程名。"""
        if _is_windows():
            return "chromedriver.exe"
        elif _is_mac():
            return "chromedriver.mac"
        else:
            return "chromedriver"


def _is_windows() -> bool:
    return platform.system() == "Windows"


def _is_mac() -> bool:
    return platform.system() == "Darwin"


def _get_unused_port() -> int:
    """获取一个本地空闲端口。"""
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    try:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]
    finally:
        sock.close()
