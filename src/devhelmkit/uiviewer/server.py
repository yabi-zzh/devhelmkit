# !/usr/bin/env python
# -*- coding: utf-8 -*-
"""ControlServer：control_port 页面/API/配置/touch 服务。

基于标准库 http.server，不引入 FastAPI/uvicorn。
"""
from __future__ import annotations

import json
import logging
import os
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlparse, parse_qs

from devhelmkit.uiviewer.protocol import CaptureMode, CleanupPolicy
from devhelmkit.uiviewer.registry import DeviceSessionRegistry

logger = logging.getLogger(__name__)

_STATIC_DIR = os.path.realpath(os.path.join(os.path.dirname(__file__), "static"))

_MIME_MAP = {
    ".html": "text/html; charset=utf-8",
    ".css": "text/css; charset=utf-8",
    ".js": "application/javascript; charset=utf-8",
    ".svg": "image/svg+xml",
    ".png": "image/png",
    ".ico": "image/x-icon",
}


class ControlRequestHandler(BaseHTTPRequestHandler):
    """control_port 请求处理器。"""

    registry: DeviceSessionRegistry = None  # type: ignore
    jpeg_port: int = 0
    control_port: int = 0
    # 启用 HTTP/1.1 keep-alive，复用 TCP 连接，消除高频 touch 请求的建连开销
    protocol_version = "HTTP/1.1"

    def log_message(self, format, *args):
        # 访问日志降到 debug，避免高频 touch 刷屏；业务关键事件仍用 info 单独打点
        logger.debug("control_server %s - %s", self.address_string(), format % args)

    # ============================================================
    # GET
    # ============================================================

    def do_GET(self):
        parsed = urlparse(self.path)
        path = parsed.path

        if path == "/" or path == "/index.html":
            self._serve_static("index.html")
        elif path.startswith("/static/"):
            self._serve_static(path[len("/static/"):])
        elif path == "/api/devices":
            self._api_devices()
        elif path == "/api/runtime":
            self._api_runtime()
        elif path == "/api/session":
            self._api_session(parsed)
        elif path == "/api/hierarchy":
            self._api_hierarchy(parsed)
        else:
            self.send_error(404, "Not Found")

    # ============================================================
    # POST
    # ============================================================

    def do_POST(self):
        parsed = urlparse(self.path)
        path = parsed.path

        body = self._read_json_body()
        if body is None:
            return

        if path == "/api/session/select":
            self._api_session_select(body)
        elif path == "/api/session/mode":
            self._api_session_mode(body)
        elif path == "/api/session/cleanup":
            self._api_session_cleanup(body)
        elif path == "/api/session/close":
            self._api_session_close(body)
        elif path == "/api/refresh":
            self._api_refresh(body)
        elif path == "/api/touch":
            self._api_touch(body)
        elif path == "/api/key":
            self._api_key(body)
        elif path == "/api/live/refresh":
            self._api_live_refresh(body)
        else:
            self.send_error(404, "Not Found")

    # ============================================================
    # API 实现
    # ============================================================

    def _api_devices(self):
        devices = self.registry.list_devices()
        logger.info("设备列表: %s", devices)
        self._json_response({"devices": devices})

    def _api_runtime(self):
        self._json_response({
            "control_port": self.control_port,
            "jpeg_port": self.jpeg_port,
        })

    def _api_session(self, parsed):
        params = parse_qs(parsed.query)
        serial = params.get("serial", [None])[0]
        if not serial:
            self._json_response({"sessions": self.registry.get_all_states()})
            return
        session = self.registry.get_session(serial)
        if session is None:
            self.send_error(404, "session not found")
            return
        self._json_response(session.get_state())

    def _api_hierarchy(self, parsed):
        params = parse_qs(parsed.query)
        serial = params.get("serial", [None])[0]
        if not serial:
            self._json_error(400, "missing serial")
            return
        session = self.registry.get_session(serial)
        if session is None or not session.active:
            self._json_error(404, "session not active")
            return
        logger.info("获取控件树: %s (mode=%s)", serial, session.mode.value)
        try:
            snapshot = session.dump_hierarchy()
            logger.info("控件树完成: %s, nodes=%d", serial, len(snapshot.nodes))
            self._json_response(snapshot.to_dict())
        except Exception as e:
            logger.warning("控件树获取失败: %s - %s", serial, e)
            self._json_error(500, str(e))

    def _api_session_select(self, body: dict):
        serial = body.get("serial")
        if not serial:
            self._json_error(400, "missing serial")
            return
        logger.info("选择设备: %s", serial)
        session = self.registry.get_or_create_session(serial)
        if not session.active:
            session.start()
        self._json_response(session.get_state())

    def _api_session_mode(self, body: dict):
        serial = body.get("serial")
        mode_str = body.get("mode")
        if not serial or not mode_str:
            self._json_error(400, "missing serial or mode")
            return
        try:
            mode = CaptureMode(mode_str)
        except ValueError:
            self._json_error(400, "invalid mode: %s" % mode_str)
            return
        session = self.registry.get_session(serial)
        if session is None or not session.active:
            self._json_error(404, "session not active")
            return
        logger.info("切换模式: %s -> %s", serial, mode_str)
        session.set_mode(mode)
        self._json_response(session.get_state())

    def _api_session_cleanup(self, body: dict):
        serial = body.get("serial")
        policy_str = body.get("cleanup")
        if not serial or not policy_str:
            self._json_error(400, "missing serial or cleanup")
            return
        try:
            policy = CleanupPolicy(policy_str)
        except ValueError:
            self._json_error(400, "invalid cleanup: %s" % policy_str)
            return
        session = self.registry.get_session(serial)
        if session is None:
            self._json_error(404, "session not found")
            return
        session.set_cleanup_policy(policy)
        self._json_response(session.get_state())

    def _api_session_close(self, body: dict):
        serial = body.get("serial")
        if not serial:
            self._json_error(400, "missing serial")
            return
        logger.info("断开设备: %s", serial)
        self.registry.close_session(serial)
        self._json_response({"status": "closed", "serial": serial})

    def _api_refresh(self, body: dict):
        serial = body.get("serial")
        if not serial:
            self._json_error(400, "missing serial")
            return
        session = self.registry.get_session(serial)
        if session is None or not session.active:
            self._json_error(404, "session not active")
            return
        logger.info("获取页面: %s (mode=%s)", serial, session.mode.value)
        try:
            jpeg_bytes, meta = session.capture_jpeg()
            hierarchy = session.dump_hierarchy()
            logger.info("获取页面完成: %s, frame_id=%d, nodes=%d", serial, meta.frame_id, len(hierarchy.nodes))
            self._json_response({
                "frame": meta.to_dict(),
                "hierarchy": hierarchy.to_dict(),
            })
        except Exception as e:
            logger.warning("获取页面失败: %s - %s", serial, e)
            self._json_error(500, str(e))

    def _api_touch(self, body: dict):
        serial = body.get("serial")
        events = body.get("events", [])
        if not serial:
            self._json_error(400, "missing serial")
            return
        session = self.registry.get_session(serial)
        if session is None or not session.active:
            self._json_error(404, "session not active")
            return
        logger.debug("触控事件: %s, %d events", serial, len(events))
        try:
            session.touch(events)
            self._json_response({"status": "ok"})
        except Exception as e:
            logger.warning("touch 失败: %s", e)
            self._json_error(500, str(e))

    def _api_key(self, body: dict):
        serial = body.get("serial")
        key = body.get("key")
        if not serial or not key:
            self._json_error(400, "missing serial or key")
            return
        session = self.registry.get_session(serial)
        if session is None or not session.active:
            self._json_error(404, "session not active")
            return
        logger.info("设备按键: %s, key=%s", serial, key)
        try:
            session.press_key(key)
            self._json_response({"status": "ok"})
        except Exception as e:
            logger.warning("按键失败: %s", e)
            self._json_error(500, str(e))

    def _api_live_refresh(self, body: dict):
        serial = body.get("serial")
        if not serial:
            self._json_error(400, "missing serial")
            return
        session = self.registry.get_session(serial)
        if session is None or not session.active:
            self._json_error(404, "session not active")
            return
        logger.info("刷新实时画面: %s", serial)
        try:
            ok = session.refresh_live_frame()
            self._json_response({"ok": ok, "status": "ok" if ok else "no_stream"})
        except Exception as e:
            logger.warning("刷新实时画面失败: %s", e)
            self._json_error(500, str(e))

    # ============================================================
    # 辅助
    # ============================================================

    def _serve_static(self, filename: str):
        filepath = os.path.realpath(os.path.join(_STATIC_DIR, filename))
        try:
            if os.path.commonpath([filepath, _STATIC_DIR]) != _STATIC_DIR:
                self._json_error(403, "Forbidden")
                return
        except ValueError:
            self._json_error(403, "Forbidden")
            return
        if not os.path.isfile(filepath):
            self._json_error(404, "Not Found")
            return
        ext = os.path.splitext(filepath)[1].lower()
        content_type = _MIME_MAP.get(ext, "application/octet-stream")
        with open(filepath, "rb") as f:
            data = f.read()
        self.send_response(200)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def _read_json_body(self):
        content_length = int(self.headers.get("Content-Length", 0))
        if content_length == 0:
            self._json_error(400, "empty body")
            return None
        raw = self.rfile.read(content_length)
        try:
            return json.loads(raw.decode("utf-8"))
        except (json.JSONDecodeError, UnicodeDecodeError) as e:
            self._json_error(400, "invalid JSON: %s" % e)
            return None

    def _json_response(self, data, status=200):
        body = json.dumps(data, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _json_error(self, status: int, message: str) -> None:
        """统一错误响应：JSON body 承载消息，避免非 ASCII 进入 status line。"""
        self._json_response({"error": message}, status=status)


def create_control_server(host, port, registry, jpeg_port):
    server = ThreadingHTTPServer((host, port), ControlRequestHandler)
    ControlRequestHandler.registry = registry
    ControlRequestHandler.jpeg_port = jpeg_port
    ControlRequestHandler.control_port = int(server.server_address[1])
    server.daemon_threads = True
    return server
