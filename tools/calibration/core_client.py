"""CORE HTTP(S) client for run_calibration (split out to keep the runner inside its size budget)."""
from __future__ import annotations

import http.client
import json
import ssl
import threading
import time
import urllib.error
import urllib.request


class Core:
    def __init__(self, host, token=None, port=8080, ca_file=None):
        # A robot with ROSY_API_TLS=required answers HTTPS only: verify against its CA
        # (/etc/rosy/tls/ca.pem). The leaf names <hostname>.local, not the IP, so the
        # chain is pinned to that CA and the name is not checked.
        self.context = None
        if ca_file:
            self.context = ssl.create_default_context(cafile=str(ca_file))
            self.context.check_hostname = False
        self.base, self.token = f"{'https' if ca_file else 'http'}://{host}:{port}", token
        self.host, self.port, self._conn = host, port, None
        self._conn_lock = threading.Lock()   # the Ctrl-C stop shares the robot thread's connection

    def call(self, method, path, body=None, timeout=2.0):
        if self.context is not None:
            with self._conn_lock:
                return self._call_kept(method, path, body, timeout)
        req = urllib.request.Request(self.base + path, method=method,
                                     data=None if body is None else json.dumps(body).encode(),
                                     headers={"Content-Type": "application/json",
                                              **({"Authorization": f"Bearer {self.token}"} if self.token else {})})
        with urllib.request.urlopen(req, timeout=timeout, context=self.context) as resp:
            text = resp.read().decode() or "null"
            return resp.status, json.loads(text)

    def _call_kept(self, method, path, body, timeout):
        """HTTPS on one kept-alive connection: a TLS handshake per 10 Hz teleop overran the
        0.4 s budget on Wi-Fi (9dfk, 2026-10-07). One reconnect on a dropped connection."""
        data = None if body is None else json.dumps(body).encode()
        headers = {"Content-Type": "application/json",
                   **({"Authorization": f"Bearer {self.token}"} if self.token else {})}
        for attempt in (0, 1):
            if self._conn is None:
                self._conn = http.client.HTTPSConnection(self.host, self.port, context=self.context,
                                                         timeout=timeout)
            self._conn.timeout = timeout
            if self._conn.sock is not None:
                self._conn.sock.settimeout(timeout)
            try:
                self._conn.request(method, path, body=data, headers=headers)
                resp = self._conn.getresponse()
                text = resp.read().decode() or "null"
            except (http.client.HTTPException, ConnectionError) as exc:
                self._conn.close()
                self._conn = None
                if attempt:
                    raise urllib.error.URLError(exc) from exc
                continue
            except OSError:
                self._conn.close()
                self._conn = None
                raise
            if resp.status >= 400:
                raise urllib.error.HTTPError(self.base + path, resp.status, text, resp.headers, None)
            return resp.status, json.loads(text)

    def pair(self, code, label="Rosy calibration (PC)"):
        _status, doc = self.call("POST", "/api/v1/auth/pair", {"code": code.upper(), "label": label})
        self.token = doc["token"]

    def lidar(self):
        try:
            return self.call("GET", "/api/v1/sensors/lidar", timeout=0.5)[1]
        except (urllib.error.URLError, OSError, ValueError):
            return None

    def teleop(self, linear, angular):
        # 1.0 s, not 0.4 s: with the bench recorder running a Pi answers late now and then
        # (9dfk aborted twice, 2026-10-07). A late command is still safe: the robot's 300 ms
        # teleop watchdog stops the wheels first.
        self.call("POST", "/api/v1/teleop", {"linear": linear, "angular": angular}, timeout=1.0)

    def stop(self):
        for _ in range(3):
            try:
                self.teleop(0.0, 0.0)
            except (urllib.error.URLError, OSError, ValueError):
                pass
            time.sleep(0.1)

    def session_api(self, action, path):
        """CORE calibration session start/stop (feat/calibration-session-mode); absent API tolerated."""
        try:
            return self.call("POST", path, {"action": action})
        except urllib.error.HTTPError as exc:
            if exc.code in (404, 405, 501):
                return exc.code, {"skipped": "calibration session API not available"}
            raise
