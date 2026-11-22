"""Fail-closed LAN GPU HTTP client compatible with `LeRobotShadow` (D-1073).

Imports zero `torch` or `lerobot` dependencies so `rosy-arm-cell` stays thin
while running concurrent per-arm 6-DoF ACT inference against a LAN GPU server.
"""
from __future__ import annotations

import base64
from hashlib import sha256
import json
import math
from pathlib import Path
import time
from types import SimpleNamespace
from typing import Any, Mapping, Sequence
import urllib.error
import urllib.parse
import urllib.request

import arm_status_bridge
import cell_act_inputs
from cell_lerobot_shadow import CAMERA_ROLES, JOINT_NAMES, UNITS, read_sim_rule

_HEX64_CHARS = frozenset("0123456789abcdef")
_LOOPBACK_HOSTS = frozenset({"127.0.0.1", "::1", "localhost"})
MAX_TIMEOUT_S = 2.0


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


def _encode_jpeg_bgr(image: Any, expected_hw: tuple[int, int]) -> bytes:
    import cv2
    import numpy as np

    arr = np.asarray(image)
    h, w = expected_hw
    if arr.ndim != 3 or arr.shape != (h, w, 3) or arr.dtype != np.uint8:
        raise ValueError(f"camera image shape/dtype {arr.shape}/{arr.dtype} != ({h}, {w}, 3)/uint8")
    ok, encoded = cv2.imencode(".jpg", arr)
    if not ok:
        raise ValueError("cv2.imencode('.jpg', ...) failed")
    return bytes(encoded.tobytes())


class RemotePolicyShadow:
    """Drop-in `LeRobotShadow` client delegating per-arm 6-DoF ACT inference over HTTP."""

    policy_environment = "remote_lerobot"
    joint_names = JOINT_NAMES

    def __init__(
        self,
        endpoint_url: str,
        arm_id: str,
        policy_revision: str,
        *,
        token: str | None = None,
        timeout_s: float = 0.8,
        expected_views: Mapping[str, tuple[int, int]] | None = None,
        sim_rule: dict[str, Any] | None = None,
        policy_root: Path | None = None,
        config: dict[str, Any] | None = None,
        opener: Any = None,
    ) -> None:
        parsed = urllib.parse.urlsplit(endpoint_url)
        if parsed.scheme not in ("http", "https") or not parsed.netloc:
            raise ValueError(f"invalid endpoint_url {endpoint_url!r}")
        if not isinstance(arm_id, str) or not arm_id.strip():
            raise ValueError("arm_id must be a non-empty string")
        host = (parsed.hostname or "").lower()
        if host not in _LOOPBACK_HOSTS and not token:
            raise ValueError(f"bearer token required for non-loopback endpoint {endpoint_url!r}")
        if token is not None and not token.strip():
            raise ValueError("bearer token cannot be blank")
        if isinstance(timeout_s, bool) or not isinstance(timeout_s, (int, float)) or not (0.0 < float(timeout_s) <= MAX_TIMEOUT_S):
            raise ValueError(f"timeout_s must be in (0, {MAX_TIMEOUT_S}], got {timeout_s!r}")

        self.endpoint_url = endpoint_url.rstrip("/")
        self.arm_id = arm_id
        self.policy_revision = _validate_revision(policy_revision)
        self._token = token
        self.timeout_s = float(timeout_s)
        self._opener = opener or urllib.request.urlopen
        self.files: dict[str, str] = {}
        self.sim_rule = sim_rule if sim_rule is not None else (
            read_sim_rule(Path(policy_root) / UNITS, config) if policy_root is not None else None
        )

        health = self._get_json("/health")
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

        self.image_views = views
        self.n_action_steps = n_steps
        self.chunk_size = chunk_sz
        self.goal_size = goal_sz

    def _headers(self, *, content_type: str | None = None) -> dict[str, str]:
        hdrs: dict[str, str] = {}
        if content_type:
            hdrs["Content-Type"] = content_type
        if self._token is not None:
            hdrs["Authorization"] = f"Bearer {self._token}"
        return hdrs

    def _get_json(self, route: str) -> dict[str, Any]:
        req = urllib.request.Request(f"{self.endpoint_url}{route}", headers=self._headers(), method="GET")
        try:
            with self._opener(req, timeout=self.timeout_s) as resp:
                return json.loads(resp.read().decode("utf-8"))
        except Exception as exc:
            raise RemotePolicyError(f"GET {route} failed: {exc}") from exc

    def _post_json(self, route: str, body: dict[str, Any]) -> dict[str, Any]:
        raw = json.dumps(body).encode("utf-8")
        req = urllib.request.Request(
            f"{self.endpoint_url}{route}",
            data=raw,
            headers=self._headers(content_type="application/json"),
            method="POST",
        )
        try:
            with self._opener(req, timeout=self.timeout_s) as resp:
                return json.loads(resp.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="replace")[:200] if exc.fp else ""
            raise RemotePolicyError(f"POST {route} HTTP {exc.code}: {detail}") from exc
        except Exception as exc:
            raise RemotePolicyError(f"POST {route} failed: {exc}") from exc

    def inputs(
        self,
        state: Sequence[float],
        frames: Mapping[str, Any],
        *,
        goal: Sequence[float] | None = None,
    ) -> tuple[dict[str, Any], dict[str, Any]]:
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
            jpg = _encode_jpeg_bgr(frames[role], hw)
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

        obs = {
            "arm_id": self.arm_id,
            "revision": self.policy_revision,
            "state": model_state,
            "frames": encoded_frames,
            **({"goal": goal_vec} if goal_vec is not None else {}),
        }
        meta = {
            "model_frame_sha256": frame_hashes,
            "frame_count": len(frame_hashes),
            "sim_converted": self.sim_rule is not None,
            **({"goal_slot": goal_slot} if goal_slot is not None else {}),
        }
        return obs, meta

    def infer(self, obs: dict[str, Any], *, state: Any = None) -> SimpleNamespace:
        t0 = time.perf_counter()
        reply = self._post_json("/infer", obs)
        rtt_s = time.perf_counter() - t0
        if not isinstance(reply, dict) or reply.get("ok") is not True:
            raise RemotePolicyError(f"inference error reply: {reply!r}")
        if reply.get("arm_id") != self.arm_id or reply.get("revision") != self.policy_revision:
            raise RemotePolicyError(
                f"reply mismatch arm={reply.get('arm_id')!r} rev={reply.get('revision')!r}"
            )
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
                    grippers = [
                        (st_nums[-1] if abs(ang - obs_grip) <= 1e-6 else g)
                        for ang, g in zip(angles, grippers)
                    ]
            converted: list[tuple[float, ...]] = []
            for row, g_unit in zip(parsed_rows, grippers):
                converted.append(tuple([_rad_to_body_units(v) for v in row[:5]] + [float(g_unit)]))
            chunk = converted
        else:
            chunk = parsed_rows

        return SimpleNamespace(chunk=chunk, rtt_s=rtt_s, policy_revision=self.policy_revision)
