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
from devhelmkit.uiviewer.node_model import (
    generate_xpath_candidates,
    select_xpath_candidate,
)

logger = logging.getLogger(__name__)

_STATIC_DIR = os.path.realpath(os.path.join(os.path.dirname(__file__), "static"))
_MAX_JSON_BODY_SIZE = 1024 * 1024

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
        """将 HTTP 访问日志降到 debug，避免高频 touch 请求刷屏。"""
        logger.debug("control_server %s - %s", self.address_string(), format % args)

    # ============================================================
    # GET
    # ============================================================

    def do_GET(self):
        """分发静态资源、会话查询、控件树、XPath 和录制状态请求。"""
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
        elif path == "/api/xpath":
            self._api_xpath(parsed)
        elif path == "/api/record/state":
            self._api_record_state(parsed)
        else:
            self.send_error(404, "Not Found")

    # ============================================================
    # POST
    # ============================================================

    def do_POST(self):
        """分发会话控制、触控、导航和录制写操作。"""
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
        elif path == "/api/record/start":
            self._api_record_start(body)
        elif path == "/api/record/stop":
            self._api_record_stop(body)
        elif path == "/api/record/action":
            self._api_record_action(body)
        elif path == "/api/record/delete":
            self._api_record_delete(body)
        elif path == "/api/record/clear":
            self._api_record_clear(body)
        else:
            self.send_error(404, "Not Found")

    # ============================================================
    # API 实现
    # ============================================================

    def _api_devices(self):
        """返回当前可用设备序列号列表。"""
        devices = self.registry.list_devices()
        logger.info("设备列表: %s", devices)
        self._json_response({"devices": devices})

    def _api_runtime(self):
        """返回控制端与 JPEG 流服务端口。"""
        self._json_response({
            "control_port": self.control_port,
            "jpeg_port": self.jpeg_port,
        })

    def _api_session(self, parsed):
        """返回全部会话状态或指定设备的会话状态。"""
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
        """获取指定设备当前模式对应的 hierarchy 快照。"""
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

    def _api_xpath(self, parsed):
        """基于当前缓存 hierarchy 返回目标节点的 XPath 候选。"""
        params = parse_qs(parsed.query)
        serial = params.get("serial", [None])[0]
        node_id = params.get("node_id", [None])[0]
        preferred_by = params.get("by", ["class"])[0]
        if not serial or not node_id:
            self._json_error(400, "missing serial or node_id")
            return
        session = self.registry.get_session(serial)
        if session is None or not session.active:
            self._json_error(404, "session not active")
            return
        snapshot = session.get_cached_hierarchy()
        if snapshot is None:
            self._json_error(409, "hierarchy not ready, refresh first")
            return
        candidates = generate_xpath_candidates(snapshot.root, node_id)
        if not candidates:
            self._json_error(404, "node not found in cached hierarchy")
            return
        selected = select_xpath_candidate(candidates, preferred_by) or candidates[0]
        self._json_response({
            "status": "ok",
            "snapshot_id": snapshot.snapshot_id,
            "node_id": node_id,
            "by": selected.get("by"),
            "xpath": selected.get("xpath"),
            "selected": selected,
            "candidates": candidates,
        })

    def _api_session_select(self, body: dict):
        """创建或激活指定设备的 Viewer 会话。"""
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
        """切换指定设备的 snapshot/live 采集模式。"""
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
        """设置指定设备会话关闭时的资源清理策略。"""
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
        """关闭指定设备会话并释放设备资源。"""
        serial = body.get("serial")
        if not serial:
            self._json_error(400, "missing serial")
            return
        logger.info("断开设备: %s", serial)
        self.registry.close_session(serial)
        self._json_response({"status": "closed", "serial": serial})

    def _api_refresh(self, body: dict):
        """获取 snapshot 模式的一帧图像和对应 hierarchy。"""
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
        """转发 Viewer 的有序 touch 事件批次到当前设备。"""
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
        """转发 Viewer 的设备导航按键。"""
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
        """在实时模式触发一次设备侧画面刷新。"""
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

    def _api_record_start(self, body: dict):
        """启动当前设备的 Web 操作录制并返回初始空状态。"""
        serial = body.get("serial")
        if not serial:
            self._json_error(400, "missing serial")
            return
        session = self.registry.get_session(serial)
        if session is None or not session.active:
            self._json_error(404, "session not active")
            return
        try:
            session.start_recording()
            self._json_response({"status": "recording", **session.get_recording_state()})
        except Exception as exc:
            logger.warning("启动 Web 操作录制失败: %s", exc)
            self._json_error(500, str(exc))

    def _api_record_stop(self, body: dict):
        """停止接收新操作，同时保留并返回当前脚本事件。"""
        serial = body.get("serial")
        if not serial:
            self._json_error(400, "missing serial")
            return
        session = self.registry.get_session(serial)
        if session is None or not session.active:
            self._json_error(404, "session not active")
            return
        try:
            result = session.stop_recording()
            self._json_response({"status": "stopped", **result})
        except Exception as exc:
            logger.warning("停止 Web 操作录制失败: %s", exc)
            self._json_error(500, str(exc))

    def _api_record_action(self, body: dict):
        """校验并记录一条由 Viewer 发出的语义操作。"""
        serial = body.get("serial")
        action = body.get("action")
        params = body.get("params")
        if not serial or not action or not isinstance(params, dict):
            self._json_error(400, "missing serial, action or params")
            return
        session = self.registry.get_session(serial)
        if session is None or not session.active:
            self._json_error(404, "session not active")
            return
        try:
            result = session.record_web_action(action, params)
            self._json_response(result)
        except Exception as exc:
            logger.warning("记录 Web 操作失败: %s", exc)
            self._json_error(400, str(exc))

    def _api_record_delete(self, body: dict):
        """按会话内稳定事件 ID 删除单条脚本。"""
        serial = body.get("serial")
        event_id = body.get("event_id")
        if not serial or isinstance(event_id, bool):
            self._json_error(400, "missing serial or event_id")
            return
        try:
            event_id = int(event_id)
        except (TypeError, ValueError):
            self._json_error(400, "event_id must be an integer")
            return
        session = self.registry.get_session(serial)
        if session is None or not session.active:
            self._json_error(404, "session not active")
            return
        try:
            self._json_response(session.delete_recording_event(event_id))
        except Exception as exc:
            self._json_error(404, str(exc))

    def _api_record_clear(self, body: dict):
        """清空当前脚本事件但不改变录制开关。"""
        serial = body.get("serial")
        if not serial:
            self._json_error(400, "missing serial")
            return
        session = self.registry.get_session(serial)
        if session is None or not session.active:
            self._json_error(404, "session not active")
            return
        self._json_response(session.clear_recording_events())

    def _api_record_state(self, parsed):
        """返回录制开关、脚本事件和最近生成错误。"""
        params = parse_qs(parsed.query)
        serial = params.get("serial", [None])[0]
        if not serial:
            self._json_error(400, "missing serial")
            return
        session = self.registry.get_session(serial)
        if session is None or not session.active:
            self._json_error(404, "session not active")
            return
        self._json_response(session.get_recording_state())

    # ============================================================
    # 辅助
    # ============================================================

    def _serve_static(self, filename: str):
        """安全读取 static 目录内的资源并返回内容。"""
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
        """读取有限大小的 JSON 对象；失败时立即写入错误响应。"""
        raw_content_length = self.headers.get("Content-Length")
        try:
            content_length = int(raw_content_length or 0)
        except (TypeError, ValueError):
            self.close_connection = True
            self._json_error(400, "invalid Content-Length")
            return None
        if content_length <= 0:
            self._json_error(400, "empty body")
            return None
        if content_length > _MAX_JSON_BODY_SIZE:
            self.close_connection = True
            self._json_error(413, "JSON body too large")
            return None

        raw = self.rfile.read(content_length)
        try:
            body = json.loads(raw.decode("utf-8"))
        except (json.JSONDecodeError, UnicodeDecodeError) as e:
            self._json_error(400, "invalid JSON: %s" % e)
            return None
        if not isinstance(body, dict):
            self._json_error(400, "JSON body must be an object")
            return None
        return body

    def _json_response(self, data, status=200):
        """序列化 JSON 数据并写入 HTTP 响应。"""
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
    """创建控制面 HTTP 服务并注入共享会话注册表与运行端口。"""
    server = ThreadingHTTPServer((host, port), ControlRequestHandler)
    ControlRequestHandler.registry = registry
    ControlRequestHandler.jpeg_port = jpeg_port
    ControlRequestHandler.control_port = int(server.server_address[1])
    server.daemon_threads = True
    return server
