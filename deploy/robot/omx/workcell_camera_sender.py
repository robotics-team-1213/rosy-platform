"""Authenticated workcell preview delivery into one Vision receiver."""
from __future__ import annotations

import json
import logging
import math
import time
from urllib.parse import urlsplit

from rosy_vision import protocol
from workcell_incident_client import _verified, secure_url
from workcell_observation_sources import sample_age


def camera_hello(source_id, width, height):
    message = {
        "type": "hello",
        "proto": protocol.PROTO,
        "source": source_id,
        "sensor": {"width": width, "height": height, "rotation_deg": 0},
    }
    protocol.validate_hello(message)
    return message


def camera_packet(sample, *, wall=None, monotonic=None):
    age = sample_age(
        sample,
        time.time() if wall is None else wall,
        time.monotonic() if monotonic is None else monotonic,
    )
    jpeg, width, height = sample.value
    if not isinstance(jpeg, bytes) or not jpeg or len(jpeg) > protocol.DEFAULT_CONFIG["max_bytes"]:
        raise ValueError("invalid or oversized camera JPEG")
    return protocol.pack_header(protocol.FrameHeader(sample.sequence, math.ceil(age * 1000), width, height, 0)) + jpeg


class CameraSender:
    def __init__(self, vision_url, source_id, token, *, context, follow_receiver=False):
        self.url = secure_url(vision_url, "wss")
        if urlsplit(self.url).path in ("", "/"):
            self.url += protocol.WS_PATH
        self.source_id, self.token, self.context = source_id, token, _verified(context)
        self.connection = None
        self._follow_receiver = follow_receiver
        self._wanted = True
        self._frame_interval = 0.0
        self._last_frame_sent_at = -math.inf
        self._next_oversize_warning = -math.inf

    def close(self):
        self._wanted = True
        self._frame_interval = 0.0
        self._last_frame_sent_at = -math.inf
        if self.connection is not None:
            connection, self.connection = self.connection, None
            try:
                connection.close()
            except Exception:
                pass

    def _apply_receiver_control(self, message):
        if not isinstance(message, str):
            return
        try:
            config = json.loads(message)
            if not isinstance(config, dict):
                return
            if config.get("type") == "demand":
                if type(config.get("wanted")) is bool:
                    self._wanted = config["wanted"]
                return
            if config.get("type") != "config":
                return
            fps = config.get("fps")
            if type(fps) is not int or fps <= 0:
                return
            interval = 1 / fps
        except (ValueError, OverflowError, RecursionError):
            return
        if 0 < interval < math.inf:
            self._frame_interval = interval

    def send(self, sample):
        from websockets.sync.client import connect

        try:
            jpeg = sample.value[0]
            limit = protocol.DEFAULT_CONFIG["max_bytes"]
            if isinstance(jpeg, bytes) and len(jpeg) > limit:
                # This capture cannot become sendable by reconnecting or retrying.
                now = time.monotonic()
                if now >= self._next_oversize_warning:
                    logging.getLogger(__name__).warning(
                        "camera preview JPEG exceeds Vision limit source=%s host=%s bytes=%d limit=%d",
                        self.source_id, urlsplit(self.url).hostname, len(jpeg), limit,
                    )
                    self._next_oversize_warning = now + 30
                return

            if self.connection is None:
                self.connection = connect(
                    self.url,
                    ssl=self.context,
                    compression=None,
                    additional_headers={"Authorization": f"Bearer {self.token}"},
                    open_timeout=2,
                    close_timeout=1,
                    max_queue=1,
                    max_size=65536,
                )
                self.connection.socket.settimeout(2)
                try:
                    import socket as _socket

                    self.connection.socket.setsockopt(_socket.IPPROTO_TCP, _socket.TCP_NODELAY, 1)
                except (AttributeError, OSError):
                    pass
                self.connection.send(json.dumps(camera_hello(self.source_id, sample.value[1], sample.value[2])))
            for _ in range(8):
                try:
                    message = self.connection.recv(timeout=0)
                except TimeoutError:
                    break
                if self._follow_receiver:
                    self._apply_receiver_control(message)
            # Return without a backlog: the worker can take the next capture when due.
            if self._follow_receiver and (
                not self._wanted or time.monotonic() - self._last_frame_sent_at < self._frame_interval
            ):
                return
            self.connection.send(camera_packet(sample))
            if self._follow_receiver:
                self._last_frame_sent_at = time.monotonic()
        except Exception:
            self.close()
            raise
