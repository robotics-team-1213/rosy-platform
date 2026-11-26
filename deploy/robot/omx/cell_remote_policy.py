"""Fail-closed LAN GPU HTTP client compatible with `LeRobotShadow` (D-1073).

Imports zero `torch` or `lerobot` dependencies so `rosy-arm-cell` stays thin
while running concurrent per-arm 6-DoF ACT inference against a LAN GPU server.
"""
from __future__ import annotations

import base64
from hashlib import sha256
import http.client
import json
import math
from pathlib import Path
import socket
import threading
import time
from types import SimpleNamespace
from typing import Any, Mapping, Sequence
import urllib.error
import urllib.parse
import urllib.request
import uuid

import arm_status_bridge
import cell_act_inputs
from cell_lerobot_shadow import CAMERA_ROLES, JOINT_NAMES, UNITS, read_sim_rule

_HEX64_CHARS = frozenset("0123456789abcdef")
_LOOPBACK_HOSTS = frozenset({"127.0.0.1", "::1", "localhost"})
MAX_TIMEOUT_S, DEFAULT_JPEG_QUALITY = 2.0, 85


def _pos_int(val: Any) -> int | None:
    if isinstance(val, int) and not isinstance(val, bool) and val > 0:
        return int(val)
    return None


class RemotePolicyError(RuntimeError):
    """Raised on any remote health, transport, timeout, revision, or shape failure."""


def _validate_revision(revision: str) -> str:
    if not isinstance(revision, str) or len(revision) != 64 or any(c not in _HEX64_CHARS for c in revision):
        raise ValueError(f"policy_revision must be 64-char lowercase hex sha256, got {revision!r}")
    return revision


def _finite_floats(seq: Any, expected_len: int, label: str) -> list[float]:
    if not isinstance(seq, Sequence) or isinstance(seq, (str, bytes)) or len(seq) != expected_len:
        raise ValueError(f"{label} must be length-{expected_len} sequence, got {seq!r}")
    out: list[float] = []
    for raw in seq:
        if isinstance(raw, bool) or not isinstance(raw, (int, float)) or not math.isfinite(float(raw)):
            raise ValueError(f"{label} must contain {expected_len} finite numbers")
        out.append(float(raw))
    return out


def _rad_to_body_units(rad: float) -> float:
    raw_tick = float(rad) * 4096.0 / (2.0 * math.pi) + 2048.0
    return raw_tick * 200.0 / 4095.0 - 100.0


def _encode_jpeg_bgr(image: Any, expected_hw: tuple[int, int], *, quality: int = DEFAULT_JPEG_QUALITY) -> bytes:
    import cv2
    import numpy as np

    arr = np.asarray(image)
    h, w = expected_hw
    if arr.ndim != 3 or arr.shape != (h, w, 3) or arr.dtype != np.uint8:
        raise ValueError(f"camera image shape/dtype {arr.shape}/{arr.dtype} != ({h}, {w}, 3)/uint8")
    ok, encoded = cv2.imencode(".jpg", arr, [int(cv2.IMWRITE_JPEG_QUALITY), int(quality)])
    if not ok:
        raise ValueError("cv2.imencode('.jpg', ...) failed")
    return bytes(encoded.tobytes())


class RemotePolicyShadow:
    """Drop-in `LeRobotShadow` client delegating per-arm 6-DoF ACT inference over HTTP."""

    policy_environment = "remote_lerobot"
    joint_names = JOINT_NAMES

    def __init__(
        self, endpoint_url: str, arm_id: str, policy_revision: str, *,
        token: str | None = None, timeout_s: float = 0.8, expected_views: Mapping[str, tuple[int, int]] | None = None,
        sim_rule: dict[str, Any] | None = None, policy_root: Path | None = None, config: dict[str, Any] | None = None,
        opener: Any = None, jpeg_quality: int = DEFAULT_JPEG_QUALITY,
    ) -> None:
        self._conn_lock = threading.Lock()
        self._conn: http.client.HTTPConnection | None = None
        self._closed = False
        self._resolved_addrs: list[tuple[int, int, int, Any]] = []
        parsed = urllib.parse.urlsplit(endpoint_url)
        if parsed.scheme not in ("http", "https") or not parsed.netloc or not parsed.hostname:
            raise ValueError(f"invalid endpoint_url {endpoint_url!r}")
        if parsed.username or parsed.password or parsed.query or parsed.fragment:
            raise ValueError("endpoint_url must not contain credentials, query, or fragment")
        if not isinstance(arm_id, str) or not arm_id.strip():
            raise ValueError("arm_id must be a non-empty string")
        host = parsed.hostname.lower()
        if host not in _LOOPBACK_HOSTS and not token:
            raise ValueError(f"bearer token required for non-loopback endpoint {endpoint_url!r}")
        if token is not None and not token.strip():
            raise ValueError("bearer token cannot be blank")
        if isinstance(timeout_s, bool) or not isinstance(timeout_s, (int, float)) or not (0.0 < float(timeout_s) <= MAX_TIMEOUT_S):
            raise ValueError(f"timeout_s must be in (0, {MAX_TIMEOUT_S}], got {timeout_s!r}")
        if type(jpeg_quality) is not int or not (50 <= jpeg_quality <= 100):
            raise ValueError(f"jpeg_quality must be an int in [50, 100], got {jpeg_quality!r}")

        self.endpoint_url = endpoint_url.rstrip("/")
        self.arm_id = arm_id
        self.policy_revision = _validate_revision(policy_revision)
        self._token = token
        self.timeout_s = float(timeout_s)
        self.jpeg_quality = jpeg_quality
        self._opener = opener
        self._scheme = parsed.scheme
        self._host = parsed.hostname or ""
        self._port = parsed.port or (443 if parsed.scheme == "https" else 80)
        self._host_header = parsed.netloc
        self._base_path = parsed.path.rstrip("/")
        self.files: dict[str, str] = {}
        self.sim_rule = sim_rule if sim_rule is not None else (
            read_sim_rule(Path(policy_root) / UNITS, config) if policy_root is not None else None
        )

        try:
            health = self._request_json("GET", "/health")
            if not isinstance(health, dict) or health.get("ok") is not True:
                raise RemotePolicyError(f"unhealthy remote policy server at {self.endpoint_url}")
            arm_meta = (health.get("arms") or {}).get(arm_id)
            if not isinstance(arm_meta, dict):
                raise RemotePolicyError(f"remote server does not host arm {arm_id!r}")
            if arm_meta.get("revision") != self.policy_revision:
                raise RemotePolicyError(
                    f"remote revision {arm_meta.get('revision')!r} != pinned {self.policy_revision!r}"
                )
            raw_views = arm_meta.get("views")
            if not isinstance(raw_views, dict) or not raw_views:
                raise RemotePolicyError(f"remote arm {arm_id!r} returned invalid views {raw_views!r}")
            views: dict[str, tuple[int, int]] = {}
            for role, hw in raw_views.items():
                if (role not in CAMERA_ROLES or not isinstance(hw, list) or len(hw) != 2
                        or _pos_int(hw[0]) is None or _pos_int(hw[1]) is None):
                    raise RemotePolicyError(f"unsupported remote camera view {role!r}: {hw!r}")
                views[role] = (int(hw[0]), int(hw[1]))
            if expected_views is not None and views != {k: tuple(v) for k, v in expected_views.items()}:
                raise RemotePolicyError(f"remote views {views} != expected {dict(expected_views)}")

            n_steps = _pos_int(arm_meta.get("n_action_steps"))
            chunk_sz = _pos_int(arm_meta.get("chunk_size"))
            raw_goal_sz = arm_meta.get("goal_size")
            goal_sz = None if raw_goal_sz is None else _pos_int(raw_goal_sz)
            if n_steps is None or chunk_sz is None or n_steps > chunk_sz or (raw_goal_sz is not None and goal_sz is None):
                raise RemotePolicyError(f"invalid remote arm metadata: {arm_meta!r}")
        except BaseException:
            self.close()
            raise

        self.image_views = views
        self.n_action_steps = n_steps
        self.chunk_size = chunk_sz
        self.goal_size = goal_sz

    def _resolve_addrs(self) -> list[tuple[int, int, int, Any]]:
        infos = socket.getaddrinfo(self._host, self._port, socket.AF_UNSPEC, socket.SOCK_STREAM)
        ordered = [i for i in infos if i[0] == socket.AF_INET] + [i for i in infos if i[0] != socket.AF_INET]
        self._resolved_addrs = list(dict.fromkeys((i[0], i[1], i[2], i[4]) for i in ordered))
        if not self._resolved_addrs:
            raise OSError(f"no addresses resolved for {self._host}:{self._port}")
        return self._resolved_addrs

    def _close_conn_locked(self, *, reset_dns: bool = False) -> None:
        conn, self._conn = self._conn, None
        if reset_dns:
            self._resolved_addrs = []
        if conn is not None:
            try:
                conn.close()
            except Exception:
                pass

    def _set_nodelay(self, sock: socket.socket | None) -> None:
        if sock is not None:
            try:
                sock.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
            except OSError:
                pass

    def _connect_addr(self, addr: tuple[int, int, int, Any], timeout: float) -> http.client.HTTPConnection:
        family, socktype, proto, sockaddr = addr
        sock = socket.socket(family, socktype, proto)
        try:
            sock.settimeout(timeout)
            sock.connect(sockaddr)
            sock.settimeout(self.timeout_s)
            self._set_nodelay(sock)
        except Exception:
            sock.close()
            raise
        conn = http.client.HTTPConnection(self._host, self._port, timeout=self.timeout_s)
        conn.sock = sock
        return conn

    def _ensure_conn(self) -> http.client.HTTPConnection:
        if self._conn is not None:
            return self._conn
        if self._scheme == "https":
            conn = http.client.HTTPSConnection(self._host, self._port, timeout=self.timeout_s)
            try:
                conn.connect()
            except Exception:
                conn.close()
                raise
            self._set_nodelay(conn.sock)
            self._conn = conn
            return conn
        deadline = time.monotonic() + self.timeout_s
        used_cache = bool(self._resolved_addrs)
        addrs, tried, last_exc = (list(self._resolved_addrs) if used_cache else self._resolve_addrs()), set(), None
        while True:
            pending = [a for a in addrs if a not in tried]
            for idx, addr in enumerate(pending):
                tried.add(addr)
                rem = deadline - time.monotonic()
                if rem <= 0:
                    last_exc = last_exc or TimeoutError(f"connect timeout to {self._host}:{self._port}")
                    break
                slots = (len(pending) - idx) + (1 if used_cache else 0)
                try:
                    self._conn = self._connect_addr(addr, rem / slots)
                    self._resolved_addrs = [addr] + [a for a in self._resolved_addrs if a != addr]
                    return self._conn
                except OSError as exc:
                    last_exc = exc
            if not used_cache or deadline - time.monotonic() <= 0:
                break
            used_cache, addrs = False, self._resolve_addrs()
        self._resolved_addrs = []
        raise last_exc or OSError(f"failed to connect to {self._host}:{self._port}")

    def close(self) -> None:
        with self._conn_lock:
            self._closed = True
            self._close_conn_locked(reset_dns=False)

    def __enter__(self) -> "RemotePolicyShadow":
        return self

    def __exit__(self, *_exc: Any) -> None:
        self.close()

    def __del__(self) -> None:
        if getattr(self, "_conn_lock", None) is not None:
            try:
                self.close()
            except Exception:
                pass

    def _headers(self, *, content_type: str | None = None) -> dict[str, str]:
        hdrs = {"Content-Type": content_type} if content_type else {}
        if self._token is not None:
            hdrs["Authorization"] = f"Bearer {self._token}"
        return hdrs

    def _request_json(self, method: str, route: str, body: dict[str, Any] | None = None) -> dict[str, Any]:
        with self._conn_lock:
            if getattr(self, "_closed", False):
                raise RemotePolicyError("remote policy shadow is closed")
        raw_req = json.dumps(body).encode("utf-8") if body is not None else None
        ct = "application/json" if body is not None else None
        if self._opener is not None:
            req = urllib.request.Request(f"{self.endpoint_url}{route}", data=raw_req, headers=self._headers(content_type=ct), method=method)
            try:
                with self._opener(req, timeout=self.timeout_s) as resp:
                    return json.loads(resp.read().decode("utf-8"))
            except urllib.error.HTTPError as exc:
                detail = exc.read().decode("utf-8", errors="replace")[:200] if exc.fp else ""
                raise RemotePolicyError(f"{method} {route} HTTP {exc.code}: {detail}") from exc
            except Exception as exc:
                raise RemotePolicyError(f"{method} {route} failed: {exc}") from exc

        target = f"{self._base_path}{route}" if self._base_path else route
        headers = {"Host": self._host_header, "Connection": "keep-alive", **self._headers(content_type=ct)}
        with self._conn_lock:
            if getattr(self, "_closed", False):
                raise RemotePolicyError("remote policy shadow is closed")
            try:
                conn = self._ensure_conn()
                conn.request(method, target, body=raw_req, headers=headers)
                resp = conn.getresponse()
                raw = resp.read()
            except Exception as exc:
                self._close_conn_locked(reset_dns=True)
                raise RemotePolicyError(f"{method} {route} failed: {exc}") from exc
            will_close = bool(getattr(resp, "will_close", False)) or "close" in (resp.getheader("Connection") or "").lower()
            if resp.status != 200:
                detail = raw.decode("utf-8", errors="replace")[:200]
                if will_close or resp.status >= 500 or resp.status in (400, 401, 404, 411, 413):
                    self._close_conn_locked(reset_dns=False)
                raise RemotePolicyError(f"{method} {route} HTTP {resp.status}: {detail}")
            if will_close:
                self._close_conn_locked(reset_dns=False)
            try:
                return json.loads(raw.decode("utf-8"))
            except Exception as exc:
                self._close_conn_locked(reset_dns=True)
                raise RemotePolicyError(f"{method} {route} failed: {exc}") from exc

    def inputs(self, state: Sequence[float], frames: Mapping[str, Any], *, goal: Sequence[float] | None = None) -> tuple[dict[str, Any], dict[str, Any]]:
        nums = _finite_floats(state, 6, "state")

        if self.sim_rule is not None:
            rad = arm_status_bridge.to_radians(nums)
            model_state = [float(rad[f"joint{i}"]) for i in range(1, 6)] + [
                float(cell_act_inputs.sim_gripper(nums[5], self.sim_rule)),
            ]
        else:
            model_state = nums

        missing = [r for r in self.image_views if r not in frames]
        extra = [r for r in frames if r not in self.image_views]
        if missing or extra:
            raise ValueError(f"camera view mismatch missing={missing}, extra={extra}")

        encoded_frames: dict[str, str] = {}
        frame_hashes: dict[str, str] = {}
        for role, hw in self.image_views.items():
            jpg = _encode_jpeg_bgr(frames[role], hw, quality=self.jpeg_quality)
            encoded_frames[role] = base64.b64encode(jpg).decode("ascii")
            frame_hashes[role] = sha256(jpg).hexdigest()

        goal_vec: list[float] | None = None
        goal_slot: int | None = None
        if self.goal_size is None:
            if goal is not None:
                raise ValueError("policy accepts no goal, but goal was supplied")
        else:
            if goal is None:
                raise ValueError(f"goal must have length {self.goal_size}")
            if isinstance(goal, int) and not isinstance(goal, bool):
                if not 0 <= goal < self.goal_size:
                    raise ValueError(f"goal slot must be 0..{self.goal_size - 1}")
                goal_vec = [0.0] * self.goal_size
                goal_vec[goal] = 1.0
                goal_slot = int(goal)
            else:
                goal_vec = _finite_floats(goal, self.goal_size, "goal")

        obs = {"arm_id": self.arm_id, "revision": self.policy_revision, "state": model_state, "frames": encoded_frames, **({"goal": goal_vec} if goal_vec is not None else {})}
        meta = {"model_frame_sha256": frame_hashes, "frame_count": len(frame_hashes), "sim_converted": self.sim_rule is not None, **({"goal_slot": goal_slot} if goal_slot is not None else {})}
        return obs, meta

    def infer(self, obs: dict[str, Any], *, state: Any = None) -> SimpleNamespace:
        t0 = time.perf_counter()
        req_id = f"{self.arm_id}-{uuid.uuid4().hex[:16]}"
        reply = self._request_json("POST", "/infer", {**obs, "request_id": req_id, **({"full_chunk": True} if getattr(self, "full_chunk", False) else {})})
        rtt_s = time.perf_counter() - t0
        if not isinstance(reply, dict) or reply.get("ok") is not True:
            raise RemotePolicyError(f"inference error reply: {reply!r}")
        if reply.get("request_id") != req_id:
            raise RemotePolicyError(f"reply request_id mismatch expected={req_id!r} got={reply.get('request_id')!r}")
        if reply.get("arm_id") != self.arm_id or reply.get("revision") != self.policy_revision:
            raise RemotePolicyError(f"reply mismatch arm={reply.get('arm_id')!r} rev={reply.get('revision')!r}")
        raw_chunk = reply.get("chunk")
        if not isinstance(raw_chunk, list) or not (1 <= len(raw_chunk) <= self.chunk_size):
            raise RemotePolicyError(f"invalid chunk length {len(raw_chunk) if isinstance(raw_chunk, list) else None}")

        parsed_rows: list[tuple[float, ...]] = []
        for row in raw_chunk:
            try:
                parsed_rows.append(tuple(_finite_floats(row, 6, "action row")))
            except ValueError as exc:
                raise RemotePolicyError(str(exc)) from exc

        if self.sim_rule is not None:
            angles = [r[5] for r in parsed_rows]
            if any(a < 0.0 or a > 1.0 for a in angles):
                raise RemotePolicyError("policy sim jaw output is outside 0..1")
            grippers = [float(g) for g in cell_act_inputs.real_grippers(angles, self.sim_rule)]
            if state is not None:
                st_nums = _finite_floats(state, 6, "state")
                held = float(self.sim_rule["held_30mm"])
                slope = float(self.sim_rule["gap_mm_per_unit"])
                gap = 30.0 + (st_nums[-1] - held) * slope
                obs_grip = float(obs["state"][-1])
                if not 12.0 <= gap <= 60.0:
                    grippers = [(st_nums[-1] if abs(ang - obs_grip) <= 1e-6 else g) for ang, g in zip(angles, grippers)]
            converted: list[tuple[float, ...]] = []
            for row, g_unit in zip(parsed_rows, grippers):
                converted.append(tuple([_rad_to_body_units(v) for v in row[:5]] + [float(g_unit)]))
            chunk = converted
        else:
            chunk = parsed_rows

        return SimpleNamespace(chunk=chunk, rtt_s=rtt_s, policy_revision=self.policy_revision)
