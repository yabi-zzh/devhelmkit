# !/usr/bin/env python
# -*- coding: utf-8 -*-
"""WebViewDriver：webview 自动化驱动。

连接设备端 webview，通过 selenium webdriver 提供页面级自动化能力。

完整流程：
  1. 探测 devtools 端口（domain socket 或 tcp）
  2. 建立 hdc 端口转发（本地端口 -> 设备端 devtools）
  3. 查询 webview 内核版本
  4. 启动匹配版本的 chromedriver
  5. 通过 selenium Remote 连接
  6. 资源释放：移除端口转发 + quit webdriver + 停止 chromedriver

使用方式：
    from devhelmkit.harmony.webview import WebViewDriver

    wv = WebViewDriver(device)
    wv.connect("com.huawei.hmos.browser")
    wv.driver.get("https://www.baidu.com")
    wv.close()

或通过 HarmonyDriver 入口：
    d.webview("com.huawei.hmos.browser")
"""
import json
import logging
import re
import socket
import urllib.request
from typing import Optional, TYPE_CHECKING

from devhelmkit.exceptions import DevhelmError
from devhelmkit.harmony.webview.chromedriver_manager import ChromedriverManager
from devhelmkit.harmony.webview.devtools_finder import DevtoolsFinder

logger = logging.getLogger(__name__)

if TYPE_CHECKING:
    from selenium.webdriver.remote.webdriver import WebDriver
    from devhelmkit.harmony.device.hdc import HdcDevice

# 默认本地 devtools 端口（自动分配空闲端口）
DEFAULT_DEVTOOL_PORT = 9222

# 默认连接超时（秒）
DEFAULT_CONNECTION_TIMEOUT = 60

# 页面加载超时（秒）
DEFAULT_PAGE_LOAD_TIMEOUT = 50

# 脚本执行超时（秒）
DEFAULT_SCRIPT_TIMEOUT = 50

# 隐式等待（秒）
IMPLICIT_WAIT_TIMEOUT = 20


class WebViewDriver:
    """webview 自动化驱动，封装 selenium webdriver 连接与资源管理。"""

    def __init__(self, device: "HdcDevice",
                 chromedriver_search_path: str = "",
                 chromedriver_exe_path: str = "",
                 chromedriver_port: int = 9515):
        """
        Args:
            device: HdcDevice 实例
            chromedriver_search_path: chromedriver 存放目录（多版本结构）
            chromedriver_exe_path: 直接指定 chromedriver 路径（优先）
            chromedriver_port: chromedriver 监听端口
        """
        self._device = device
        self._bundle_name: Optional[str] = None
        self._driver: Optional["WebDriver"] = None
        self._devtool_port = DEFAULT_DEVTOOL_PORT
        self._remote_devtool_port = DEFAULT_DEVTOOL_PORT
        self._fport_established = False

        self._finder = DevtoolsFinder(device)
        self._chromedriver = ChromedriverManager(
            search_path=chromedriver_search_path,
            exe_path=chromedriver_exe_path,
            port=chromedriver_port,
        )

    @property
    def driver(self) -> "WebDriver":
        """selenium webdriver 实例。

        未连接时抛异常，确保调用前已 connect。
        """
        if self._driver is None:
            raise DevhelmError("webview 未连接，请先调用 connect()")
        return self._driver

    @property
    def devtools_url(self) -> str:
        """本地 devtools 访问地址。"""
        return "http://127.0.0.1:%d" % self._devtool_port

    def connect(self, bundle_name: str,
                remote_devtools_port: Optional[int] = None,
                connection_timeout: int = DEFAULT_CONNECTION_TIMEOUT,
                options=None) -> "WebDriver":
        """连接指定应用的 webview。

        Args:
            bundle_name: 目标应用包名
            remote_devtools_port: 自定义 webview 内核的 devtools 端口；
                                  系统 web 内核无需指定，自动探测
            connection_timeout: 连接超时（秒）
            options: 传递给 selenium webdriver 的 options

        Returns:
            selenium WebDriver 实例

        Raises:
            DevhelmError: 连接失败
        """
        self._bundle_name = bundle_name
        self.close()
        self._setup_port_forward(bundle_name, remote_devtools_port)
        webview_version = self._get_webview_version()
        self._chromedriver.start(webview_version)
        self._driver = self._connect_selenium(options, connection_timeout)
        return self._driver

    def close(self) -> None:
        """释放资源：移除端口转发 + quit webdriver + 停止 chromedriver。"""
        if self._driver is not None:
            try:
                self._driver.quit()
            except Exception as e:
                logger.warning("quit webdriver 异常: %s", e)
            finally:
                self._driver = None

        self._remove_port_forward()

        if self._chromedriver is not None:
            self._chromedriver.stop()

    def switch_to_visible_window(self, index: int = 0) -> None:
        """切换到 visible 状态的窗口。

        Args:
            index: 第几个可见窗口（0 表示第一个）
        """
        driver = self.driver
        handles = driver.window_handles
        if index < 0:
            handles = list(reversed(handles))
            index = abs(index) - 1
        if index >= len(handles):
            raise ValueError("窗口索引越界: %d (共 %d 个)" % (index, len(handles)))

        count = index
        for handle in handles:
            driver.switch_to.window(handle)
            visible = driver.execute_script("return document.visibilityState")
            if visible == "visible":
                if count == 0:
                    return
                count -= 1

    def get_all_windows(self, with_url: bool = False) -> list:
        """获取所有窗口信息。

        Args:
            with_url: True 返回包含 url/title/visible 的字典列表
        """
        if not with_url:
            return self.driver.window_handles

        driver = self.driver
        current = driver.current_window_handle
        result = []
        for handle in driver.window_handles:
            driver.switch_to.window(handle)
            result.append({
                "handle": handle,
                "url": driver.current_url,
                "title": driver.title,
                "visible": driver.execute_script("return document.visibilityState"),
            })
        driver.switch_to.window(current)
        return result

    def __getattr__(self, name):
        """代理未找到的属性到 selenium webdriver。"""
        return getattr(self._driver, name)

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.close()

    # ============================================================
    # 内部实现
    # ============================================================

    def _setup_port_forward(self, bundle_name: str,
                            remote_devtools_port: Optional[int]) -> None:
        """建立 hdc 端口转发。"""
        self._devtool_port = _get_unused_port()

        if remote_devtools_port is not None:
            # 自定义 webview 内核，指定 tcp 端口
            self._remote_devtool_port = remote_devtools_port
            if not self._finder.check_tcp_port(remote_devtools_port):
                raise DevhelmError(
                    "设备端 devtools 端口 %d 未开放，请检查应用是否已开启 web 调试"
                    % remote_devtools_port
                )
            self._device.shell(
                "hdc fport tcp:%d tcp:%d" % (self._devtool_port, remote_devtools_port)
            )
        elif self._finder.is_using_domain_socket():
            # 系统 web 内核，通过 domain socket 探测
            socket_name = self._finder.find_devtools_socket(bundle_name)
            if socket_name is None:
                raise DevhelmError(
                    "未找到 %s 的 devtools socket，请检查应用是否已开启 web 调试"
                    % bundle_name
                )
            self._device.shell(
                "hdc fport tcp:%d localabstract:%s"
                % (self._devtool_port, socket_name)
            )
        else:
            # 未指定端口且非 domain socket，尝试默认 tcp 端口
            if not self._finder.check_tcp_port(self._remote_devtool_port):
                raise DevhelmError(
                    "设备端 devtools 端口 %d 未开放" % self._remote_devtool_port
                )
            self._device.shell(
                "hdc fport tcp:%d tcp:%d"
                % (self._devtool_port, self._remote_devtool_port)
            )

        self._fport_established = True
        logger.debug(
            "devtools 端口转发已建立: tcp:%d -> 设备 (bundle=%s)",
            self._devtool_port, bundle_name
        )

    def _remove_port_forward(self) -> None:
        """移除 hdc 端口转发。"""
        if not self._fport_established:
            return
        try:
            self._device.shell("hdc fport rm tcp:%d" % self._devtool_port)
        except Exception as e:
            logger.warning("移除端口转发异常: %s", e)
        finally:
            self._fport_established = False

    def _get_webview_version(self, retry: int = 3) -> int:
        """查询设备端 webview 内核版本。

        通过 devtools /json/version 接口获取。
        """
        for _ in range(retry):
            try:
                resp = urllib.request.urlopen(
                    self.devtools_url + "/json/version", timeout=5
                ).read().decode("utf-8", errors="ignore")
                info = json.loads(resp)
                browser = info.get("Browser", "")
                match = re.search(r"/(\d+)\.", browser)
                if match:
                    version = int(match.group(1))
                    logger.debug("webview 内核版本: %d", version)
                    return version
                logger.warning("未知 webview 版本信息: %s", resp)
            except Exception as e:
                logger.warning("查询 webview 版本失败: %s", e)
        logger.warning("无法获取 webview 版本，回退到 114")
        return 114

    def _connect_selenium(self, options, timeout: int) -> "WebDriver":
        """通过 selenium Remote 连接 chromedriver。"""
        try:
            from selenium import webdriver
            from selenium.webdriver.remote.remote_connection import RemoteConnection
        except ImportError as e:
            raise DevhelmError(
                "selenium 未安装，请执行 pip install selenium 或 pip install devhelmkit[webview]"
            ) from e

        RemoteConnection.set_timeout(timeout)

        if options is None:
            options = webdriver.ChromeOptions()
        options.add_experimental_option(
            "debuggerAddress", "127.0.0.1:%d" % self._devtool_port
        )

        try:
            driver = webdriver.Remote(
                command_executor=self._chromedriver.host,
                options=options
            )
        except Exception as e:
            logger.error("连接 chromedriver 失败: %s", e)
            self._chromedriver.stop()
            raise DevhelmError("selenium webdriver 连接失败: %s" % e) from e

        driver.set_page_load_timeout(DEFAULT_PAGE_LOAD_TIMEOUT)
        driver.set_script_timeout(DEFAULT_SCRIPT_TIMEOUT)
        driver.implicitly_wait(IMPLICIT_WAIT_TIMEOUT)

        logger.debug("webview 已连接, 窗口数: %d", len(driver.window_handles))
        logger.debug("当前页面: %s", driver.current_url)
        return driver


def _get_unused_port() -> int:
    """获取一个本地空闲端口。"""
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    try:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]
    finally:
        sock.close()
