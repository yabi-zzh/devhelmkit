# !/usr/bin/env python
# -*- coding: utf-8 -*-
"""JpegServer：jpeg_port 独立图片流服务。

只负责输出 JPEG 单帧和 MJPEG 实时流，不处理 touch 或 API。
"""
from __future__ import annotations

import logging
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlparse, parse_qs

from devhelmkit.uiviewer.protocol import CaptureMode
from devhelmkit.uiviewer.registry import DeviceSessionRegistry
from devhelmkit.uiviewer import perf

logger = logging.getLogger(__name__)

_MJPEG_BOUNDARY = "uvframeboundary"
_MJPEG_CONTENT_TYPE = "multipart/x-mixed-replace; boundary=%s" % _MJPEG_BOUNDARY


class JpegRequestHandler(BaseHTTPRequestHandler):
    """jpeg_port 请求处理器。"""

    registry: DeviceSessionRegistry = None  # type: ignore
    # snapshot.jpg 高频拉取时复用连接；MJPEG 为长连接不受影响
    protocol_version = "HTTP/1.1"

    def log_message(self, format, *args):
        """将 HTTP 访问日志降到 debug，避免 MJPEG 和快照请求刷屏。"""
        logger.debug("jpeg_server %s - %s", self.address_string(), format % args)

    def do_GET(self):
        """分发快照图片与 MJPEG 实时流请求。"""
        parsed = urlparse(self.path)
        path = parsed.path
        params = parse_qs(parsed.query)

        if path == "/snapshot.jpg":
            self._handle_snapshot(params)
        elif path == "/stream.mjpeg":
            self._handle_mjpeg(params)
        else:
            self.send_error(404, "Not Found")

    def _handle_snapshot(self, params: dict):
        """返回 snapshot 模式指定帧的 JPEG 数据。"""
        serial = params.get("serial", [None])[0]
        if not serial:
            self._json_error(400, "missing serial")
            return

        session = self.registry.get_session(serial)
        if session is None or not session.active:
            self._json_error(404, "session not active")
            return

        if session.mode != CaptureMode.SNAPSHOT:
            self._json_error(400, "snapshot mode required")
            return

        frame_id = None
        raw_frame_id = params.get("frame", [None])[0]
        if raw_frame_id:
            try:
                frame_id = int(raw_frame_id)
            except ValueError:
                self._json_error(400, "invalid frame")
                return

        try:
            if frame_id is None:
                jpeg_bytes, _ = session.capture_jpeg()
            else:
                jpeg_bytes = session.get_cached_jpeg(frame_id)
                if jpeg_bytes is None:
                    self._json_error(404, "frame not found")
                    return
        except Exception as e:
            logger.warning("snapshot 截图失败: %s", e)
            self._json_error(500, str(e))
            return

        self.send_response(200)
        self.send_header("Content-Type", "image/jpeg")
        self.send_header("Content-Length", str(len(jpeg_bytes)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(jpeg_bytes)

    def _handle_mjpeg(self, params: dict):
        """按帧序号阻塞推送 MJPEG，并用低频心跳探测静止画面断连。"""
        serial = params.get("serial", [None])[0]
        if not serial:
            self._json_error(400, "missing serial")
            return

        session = self.registry.get_session(serial)
        if session is None or not session.active:
            self._json_error(404, "session not active")
            return

        if session.mode != CaptureMode.LIVE:
            self._json_error(400, "live mode required for mjpeg stream")
            return

        self.send_response(200)
        self.send_header("Content-Type", _MJPEG_CONTENT_TYPE)
        self.send_header("Cache-Control", "no-store")
        self.end_headers()

        try:
            last_seq = -1
            last_frame_ts = time.time()
            meter = perf.RateMeter("mjpeg[%s]" % serial)
            t_write0 = 0.0
            while True:
                current_session = self.registry.get_session(serial)
                if current_session is None or not current_session.active:
                    break
                if current_session.mode != CaptureMode.LIVE:
                    break
                # 阻塞等待新帧：帧到即返回，无新帧则 1s 后返回做心跳。
                # 消除固定轮询延迟，帧到即推。
                seq, frame = current_session.wait_stream_frame_seq(last_seq, 1.0)
                if frame is not None and seq != last_seq:
                    seq_skipped = (
                        max(seq - last_seq - 1, 0) if last_seq >= 0 else 0
                    )
                    last_seq = seq
                    last_frame_ts = time.time()
                    # 低比例帧在服务端严格保持字节不变；有效区域由浏览器布局层裁剪。
                    header = (
                        "\r\n--%s\r\n"
                        "Content-Type: image/jpeg\r\n"
                        "Content-Length: %d\r\n\r\n"
                    ) % (_MJPEG_BOUNDARY, len(frame))
                    if perf.enabled():
                        t_write0 = perf.now_ms()
                    self.wfile.write(header.encode("ascii"))
                    self.wfile.write(frame)
                    self.wfile.flush()
                    if perf.enabled():
                        write_ms = perf.now_ms() - t_write0
                        meter.tick(len(frame), skipped=seq_skipped)
                        # 单帧 socket 写入超过阈值时单独告警（可能是浏览器/网络背压）
                        if write_ms > 20.0:
                            perf.log("[perf] mjpeg slow write: %.1fms size=%.1fKB",
                                     write_ms, len(frame) / 1024.0)
                else:
                    if time.time() - last_frame_ts >= 5.0:
                        # 长时间无新帧时发送空白注释行做心跳，探测断连
                        last_frame_ts = time.time()
                        self.wfile.write(b"\r\n")
                        self.wfile.flush()
                    if frame is None:
                        # 流未就绪或已停止时 wait 会立即返回，短暂退避防止
                        # 本连接线程忙等自旋吃满 CPU（与底层条件循环双保险）
                        time.sleep(0.05)
        except (BrokenPipeError, ConnectionResetError):
            # 浏览器关闭或切换 MJPEG 地址属于正常的流生命周期。
            return
        except Exception as e:
            logger.warning("mjpeg 流中断: %s", e)

    def _json_error(self, status: int, message: str) -> None:
        """统一错误响应：JSON body 承载消息，避免非 ASCII 进入 status line。"""
        import json
        body = json.dumps({"error": message}, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)


def create_jpeg_server(host: str, port: int,
                       registry: DeviceSessionRegistry) -> ThreadingHTTPServer:
    """创建 jpeg_port HTTP 服务。"""
    JpegRequestHandler.registry = registry
    server = ThreadingHTTPServer((host, port), JpegRequestHandler)
    server.daemon_threads = True
    return server
