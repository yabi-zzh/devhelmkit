# !/usr/bin/env python
# -*- coding: utf-8 -*-
"""UIViewer CLI 入口：无参数启动，自动打开浏览器。"""
from __future__ import annotations

import argparse
import logging
import threading
import time
import webbrowser

from devhelmkit.uiviewer.registry import DeviceSessionRegistry
from devhelmkit.uiviewer.server import create_control_server
from devhelmkit.uiviewer.jpeg_server import create_jpeg_server
from devhelmkit.uiviewer import perf



def _stop_server(server, thread) -> None:
    """按启动状态关闭 HTTP server，避免半启动或信号中断时阻塞。"""
    if server is None:
        return
    if thread is not None and thread.is_alive():
        try:
            server.shutdown()
        except KeyboardInterrupt:
            pass
        thread.join(timeout=2)
    server.server_close()


def main():
    """启动 UIViewer 双端口服务并自动打开浏览器。"""
    parser = argparse.ArgumentParser(
        prog="devhelmkit-uiviewer",
        description="UIViewer 网页版控件查看器",
    )
    parser.add_argument(
        "--perf", action="store_true",
        help="开启投屏/触摸性能排查日志（采集 fps、推流 fps、触控 RPC 耗时）",
    )
    args = parser.parse_args()

    # 性能日志（perf logger）为 INFO 级别，保持根级别 INFO 即可，
    # 避免 --perf 时把 HTTP 访问日志等 DEBUG 噪声一起放出来刷屏。
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )

    if args.perf:
        # 运行时开启两处性能埋点（uiviewer 侧 + harmony 采集侧）
        perf.set_enabled(True)
        try:
            from devhelmkit.harmony import screenshot_stream
            screenshot_stream.set_perf_enabled(True)
        except Exception:
            pass
        print("性能日志已开启 (--perf)")

    host = "127.0.0.1"
    registry = DeviceSessionRegistry()
    control_srv = None
    jpeg_srv = None
    control_thread = None
    jpeg_thread = None

    try:
        jpeg_srv = create_jpeg_server(host, 0, registry)
        jpeg_port = int(jpeg_srv.server_address[1])
        control_srv = create_control_server(host, 0, registry, jpeg_port)
        control_port = int(control_srv.server_address[1])

        url = "http://%s:%d/?jpegPort=%d" % (host, control_port, jpeg_port)
        print("UIViewer 已启动")
        print("  控制页面: %s" % url)
        print("  Control 端口: %d" % control_port)
        print("  JPEG 端口: %d" % jpeg_port)
        print("  按 Ctrl+C 退出")

        control_thread = threading.Thread(
            target=control_srv.serve_forever, daemon=True
        )
        jpeg_thread = threading.Thread(
            target=jpeg_srv.serve_forever, daemon=True
        )
        control_thread.start()
        jpeg_thread.start()

        try:
            webbrowser.open(url)
        except Exception:
            pass

        # Windows 上 signal.signal(SIGINT) 在主线程阻塞时不可靠，
        # 直接捕获 KeyboardInterrupt 即可退出。
        while True:
            time.sleep(0.5)
    except KeyboardInterrupt:
        pass
    finally:
        print("\n正在关闭...")
        registry.close_all()
        _stop_server(control_srv, control_thread)
        _stop_server(jpeg_srv, jpeg_thread)
        print("已退出")


if __name__ == "__main__":
    main()
