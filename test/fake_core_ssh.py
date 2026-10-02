"""A fake CORE for the D-418 PC tools: login-code pairing plus /api/v1/host/ssh on localhost.

Speaks the shared contract in docs/plans/2026-10-02-d418-robot-ssh-access.md and the CORE error
envelope ({"error": {"code", "message", "detail"}}). It records every request, every token issued
and every logout so a test can prove the tool logged out and never leaked a token.
"""

from __future__ import annotations

import base64
import hashlib
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import re
import secrets
import struct
import threading

LABEL = re.compile(r"[a-z0-9][a-z0-9._:-]{0,47}")
CLIENT_TYPES = {"ssh-ed25519", "sk-ssh-ed25519@openssh.com",
                "ecdsa-sha2-nistp256", "ecdsa-sha2-nistp384", "ecdsa-sha2-nistp521"}
PREFIX = "/api/v1/host/ssh"


def ed25519_public_key(seed: bytes, comment: str = "") -> str:
    """A syntactically real ssh-ed25519 public key line (32 bytes derived from seed)."""
    raw = hashlib.sha256(seed).digest()
    blob = _string(b"ssh-ed25519") + _string(raw)
    line = "ssh-ed25519 " + base64.b64encode(blob).decode("ascii")
    return f"{line} {comment}".rstrip()


def _string(data: bytes) -> bytes:
    return struct.pack(">I", len(data)) + data


def fingerprint(public_key: str) -> str:
    blob = base64.b64decode(public_key.split()[1])
    return "SHA256:" + base64.b64encode(hashlib.sha256(blob).digest()).decode("ascii").rstrip("=")


class FakeCore:
    def __init__(self, *, codes: dict[str, str] | None = None, hostname: str = "rosy-pinky-test1",
                 host_keys: list[str] | None = None):
        self.codes = dict(codes or {})          # code -> role, one use
        self.hostname = hostname
        self.host_keys = list(host_keys if host_keys is not None else [
            ed25519_public_key(hostname.encode(), "root@" + hostname)])
        self.tokens: dict[str, str] = {}        # live token -> role
        self.issued: list[str] = []
        self.logged_out: list[str] = []
        self.keys: dict[str, dict] = {}
        self.public_keys: dict[str, str] = {}
        self.requests: list[tuple[str, str, dict | None]] = []
        self.max_keys = 32
        self._server = ThreadingHTTPServer(("127.0.0.1", 0), self._handler())
        self._thread = threading.Thread(target=self._server.serve_forever, daemon=True)

    @property
    def base_url(self) -> str:
        return f"http://127.0.0.1:{self._server.server_address[1]}"

    def __enter__(self) -> "FakeCore":
        self._thread.start()
        return self

    def __exit__(self, *exc) -> None:
        self._server.shutdown()
        self._server.server_close()

    def paths(self, method: str | None = None) -> list[str]:
        return [path for m, path, _ in self.requests if method is None or m == method]

    # --- routing ---------------------------------------------------------------

    def _route(self, method: str, path: str, headers, body: dict | None) -> tuple[int, dict | None]:
        self.requests.append((method, path, body))
        if method == "POST" and path == "/api/v1/auth/pair":
            code = (body or {}).get("code")
            role = self.codes.pop(code, None) if isinstance(code, str) else None
            if role is None:
                return 401, _error("pair_rejected", "the code is wrong, used or expired")
            token = f"fake-token-{secrets.token_hex(8)}-SECRET"
            self.tokens[token] = role
            self.issued.append(token)
            return 201, {"token": token, "role": role, "id": "tok-1", "label": body.get("label"),
                         "source": "pair-physical", "expires_at": "2026-10-03T00:00:00Z"}
        token = _bearer(headers)
        if token not in self.tokens:
            return 401, _error("unauthorized", "a valid token is required")
        if method == "POST" and path == "/api/v1/auth/logout":
            del self.tokens[token]
            self.logged_out.append(token)
            return 204, None
        if not path.startswith(PREFIX + "/"):
            return 404, _error("not_found", path)
        if self.tokens[token] != "administrator":
            return 403, _error("forbidden", "administrator role required")
        route = path[len(PREFIX):]
        if method == "GET" and route == "/host-keys":
            return 200, {"hostname": self.hostname, "host_keys": self.host_keys}
        if method == "GET" and route == "/keys":
            return 200, {"keys": list(self.keys.values())}
        if method == "POST" and route == "/keys":
            return self._add(body or {})
        if method == "DELETE" and route.startswith("/keys/"):
            label = route[len("/keys/"):]
            if label not in self.keys:
                return 404, _error("not_found", f"no key labelled {label}")
            del self.keys[label]
            del self.public_keys[label]
            return 204, None
        return 404, _error("not_found", path)

    def _add(self, body: dict) -> tuple[int, dict | None]:
        label, public_key, days = body.get("label"), body.get("public_key"), body.get("expires_days")
        if not isinstance(label, str) or not LABEL.fullmatch(label):
            return 422, _error("invalid_label", "bad label")
        if not isinstance(public_key, str) or public_key.split(" ")[0] not in CLIENT_TYPES:
            return 422, _error("invalid_key", "bad key")
        if not isinstance(days, int) or isinstance(days, bool) or not 1 <= days <= 365:
            return 422, _error("invalid_days", "bad days")
        if label in self.keys:
            return 409, _error("label_exists", f"{label} already exists")
        if len(self.keys) >= self.max_keys:
            return 409, _error("too_many_keys", "32 managed keys exist")
        record = {"label": label, "type": public_key.split(" ")[0], "fingerprint": fingerprint(public_key),
                  "added_at": "2026-10-02T00:00:00Z", "expires_at": "2026-12-31T00:00:00Z", "added_by": "ssh-tool"}
        self.keys[label] = record
        self.public_keys[label] = public_key
        return 201, {"label": label, "fingerprint": record["fingerprint"], "expires_at": record["expires_at"]}

    def _handler(self):
        core = self

        class Handler(BaseHTTPRequestHandler):
            def _serve(self, method: str) -> None:
                length = int(self.headers.get("Content-Length") or 0)
                raw = self.rfile.read(length) if length else b""
                body = json.loads(raw) if raw else None
                status, payload = core._route(method, self.path, self.headers, body)
                data = b"" if payload is None else json.dumps(payload).encode("utf-8")
                self.send_response(status)
                if data:
                    self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(data)))
                self.end_headers()
                self.wfile.write(data)

            def do_GET(self):  # noqa: N802
                self._serve("GET")

            def do_POST(self):  # noqa: N802
                self._serve("POST")

            def do_DELETE(self):  # noqa: N802
                self._serve("DELETE")

            def log_message(self, *args):
                pass

        return Handler


def _bearer(headers) -> str | None:
    value = headers.get("Authorization") or ""
    return value[len("Bearer "):] if value.startswith("Bearer ") else None


def _error(code: str, message: str) -> dict:
    return {"error": {"code": code, "message": message, "detail": {}}}
