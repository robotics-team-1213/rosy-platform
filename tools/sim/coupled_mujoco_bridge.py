#!/usr/bin/env python3
"""Coupled MuJoCo S3 intake & cell-stage bridge for D-1088 Slice 3.

Polls ``CoupledSimController`` over loopback HTTP, executes paced MuJoCo (or stub)
S3 intake grasps within the geometric envelope, optionally enforces a fail-closed
ACT policy hook, and reports boundary/stage events back to the controller.
"""
from __future__ import annotations

import argparse
import functools
import json
import math
import time
from typing import Any, Callable
import urllib.error
import urllib.request

DEFAULT_DX_LIMIT_M = 0.06
DEFAULT_DY_LIMIT_M = 0.06
DEFAULT_DYAW_LIMIT_RAD = 0.20

BACKENDS = ("auto", "mujoco", "stub")
_DOWNSTREAM_STAGES: dict[str, tuple[str, ...]] = {
    "IN_CELL_ARM_S": ("ON_BELT", "IN_CELL_AB", "ON_SHIP"),
    "ON_BELT": ("IN_CELL_AB", "ON_SHIP"),
    "IN_CELL_AB": ("ON_SHIP",),
}

_MINIMAL_CELL_MJCF = """<mujoco model="coupled_s3_intake">
  <option timestep="0.02" gravity="0 0 -9.81"/>
  <worldbody>
    <geom name="table" type="plane" size="1 1 0.1" pos="0 0 0"/>
    <body name="pinky_bed" pos="0 0 0.05">
      <geom name="pinky_bed_geom" type="box" size="0.12 0.12 0.02" rgba="0.2 0.2 0.2 1"/>
    </body>
    <body name="cargo" pos="0 0 0.10">
      <joint name="cargo_x" type="slide" axis="1 0 0" damping="1.0"/>
      <joint name="cargo_y" type="slide" axis="0 1 0" damping="1.0"/>
      <joint name="cargo_yaw" type="hinge" axis="0 0 1" damping="0.2"/>
      <geom name="cargo_geom" type="box" size="0.03 0.03 0.03" mass="0.2"/>
    </body>
    <body name="arm_s_ee" pos="0 0 0.25">
      <joint name="ee_x" type="slide" axis="1 0 0" damping="2.0"/>
      <joint name="ee_y" type="slide" axis="0 1 0" damping="2.0"/>
      <joint name="ee_z" type="slide" axis="0 0 1" damping="2.0"/>
      <geom name="ee_geom" type="sphere" size="0.02" mass="0.1" contype="0" conaffinity="0"/>
    </body>
  </worldbody>
  <actuator>
    <position name="act_ee_x" joint="ee_x" kp="50"/>
    <position name="act_ee_y" joint="ee_y" kp="50"/>
    <position name="act_ee_z" joint="ee_z" kp="50"/>
  </actuator>
</mujoco>"""


def _finite_positive(value: float, name: str) -> float:
    num = float(value)
    if not math.isfinite(num) or num <= 0.0:
        raise ValueError(f"{name} must be finite and positive")
    return num


def _request_json(
    url: str,
    *,
    method: str = "GET",
    payload: dict[str, Any] | None = None,
    timeout_s: float = 5.0,
) -> dict[str, Any]:
    """Perform a stdlib HTTP JSON request and fail closed on non-2xx or bad payloads."""
    data = None if payload is None else json.dumps(payload, allow_nan=False).encode("utf-8")
    headers = {"Accept": "application/json"}
    if data is not None:
        headers["Content-Type"] = "application/json"
    req = urllib.request.Request(url, data=data, method=method, headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=timeout_s) as resp:
            raw = resp.read().decode("utf-8")
    except urllib.error.HTTPError as err:
        body_text = ""
        try:
            body_text = err.read().decode("utf-8", errors="replace")
            parsed = json.loads(body_text) if body_text else None
        except Exception:
            parsed = None
        detail = json.dumps(parsed, ensure_ascii=False) if isinstance(parsed, dict) else (body_text or err.reason)
        raise RuntimeError(f"HTTP_{err.code}:{url}:{detail}") from err
    except (urllib.error.URLError, TimeoutError, OSError, UnicodeDecodeError) as err:
        raise RuntimeError(f"HTTP_REQUEST_FAILED:{url}:{err}") from err

    try:
        parsed_ok = json.loads(raw)
    except json.JSONDecodeError as err:
        raise RuntimeError(f"INVALID_JSON_RESPONSE:{url}:{err}") from err
    if not isinstance(parsed_ok, dict):
        raise RuntimeError(f"EXPECTED_JSON_OBJECT:{url}")
    return parsed_ok


@functools.lru_cache(maxsize=1)
def _load_s3_model(mujoco_mod: Any) -> Any:
    """Compile and cache the minimal in-memory MJCF model without temp files."""
    return mujoco_mod.MjModel.from_xml_string(_MINIMAL_CELL_MJCF)


class WallClockPacer:
    """Pace simulation steps against wall-clock time and measure achieved RTF."""

    def __init__(
        self,
        *,
        step_dt_s: float = 0.02,
        pace_factor: float = 1.0,
        clock: Callable[[], float] = time.monotonic,
        sleeper: Callable[[float], None] = time.sleep,
    ) -> None:
        self.step_dt_s = _finite_positive(step_dt_s, "step_dt_s")
        self.pace_factor = _finite_positive(pace_factor, "pace_factor")
        self.clock = clock
        self.sleeper = sleeper

    def run_steps(self, count: int, step_fn: Callable[[int], None] | None = None) -> float:
        """Execute ``count`` paced steps and return measured real-time factor."""
        n = int(count)
        if n <= 0:
            return 1.0
        t0 = float(self.clock())
        for idx in range(n):
            if step_fn is not None:
                step_fn(idx)
            target_elapsed = ((idx + 1) * self.step_dt_s) / self.pace_factor
            remaining = target_elapsed - (float(self.clock()) - t0)
            if remaining > 0.0:
                self.sleeper(remaining)
        wall_dt = float(self.clock()) - t0
        sim_dt_total = n * self.step_dt_s
        return sim_dt_total / max(wall_dt, 1e-9)


class ActPolicyClient:
    """Fail-closed HTTP client for optional ACT policy health and inference."""

    def __init__(self, base_url: str, *, timeout_s: float = 2.0) -> None:
        cleaned = str(base_url or "").strip().rstrip("/")
        if not cleaned:
            raise ValueError("base_url must be non-empty")
        self.base_url = cleaned
        self.timeout_s = _finite_positive(timeout_s, "timeout_s")

    def health(self) -> dict[str, Any]:
        """Query ``/healthz`` (falling back to ``/health`` on 404)."""
        try:
            return _request_json(f"{self.base_url}/healthz", timeout_s=self.timeout_s)
        except RuntimeError as err:
            if not str(err).startswith("HTTP_404:"):
                raise
            return _request_json(f"{self.base_url}/health", timeout_s=self.timeout_s)

    def predict(self, observation: dict[str, Any]) -> dict[str, Any]:
        """Request an ACT policy decision for ``observation``."""
        return _request_json(
            f"{self.base_url}/predict",
            method="POST",
            payload=dict(observation),
            timeout_s=self.timeout_s,
        )


class MujocoCellRunner:
    """Execute paced S3 intake grasps using MuJoCo physics or a deterministic stub."""

    def __init__(
        self,
        *,
        backend: str = "auto",
        pacer: WallClockPacer | None = None,
        step_count: int = 5,
    ) -> None:
        if backend not in BACKENDS:
            raise ValueError(f"INVALID_BACKEND:{backend}")
        if int(step_count) < 1:
            raise ValueError("step_count must be >= 1")
        self.pacer = pacer or WallClockPacer()
        self.step_count = int(step_count)
        self._mujoco: Any = None
        self._np: Any = None

        if backend in ("auto", "mujoco"):
            try:
                import mujoco  # type: ignore[import-not-found]
                import numpy as np
            except (ImportError, OSError) as err:
                if backend == "mujoco":
                    raise RuntimeError("MUJOCO_UNAVAILABLE") from err
                self.backend = "stub"
            else:
                self._mujoco = mujoco
                self._np = np
                self.backend = "mujoco"
        else:
            self.backend = "stub"

    def _step_mujoco(self, dx_m: float, dy_m: float, dyaw_rad: float) -> float:
        model = _load_s3_model(self._mujoco)
        data = self._mujoco.MjData(model)
        data.qpos[0] = dx_m
        data.qpos[1] = dy_m
        data.qpos[2] = dyaw_rad
        self._mujoco.mj_forward(model, data)
        data.ctrl[0] = dx_m
        data.ctrl[1] = dy_m
        data.ctrl[2] = -0.10
        measured_rtf = self.pacer.run_steps(
            self.step_count,
            lambda _idx: self._mujoco.mj_step(model, data),
        )
        if self._np.isnan(data.qpos).any() or not self._np.isfinite(data.qpos).all():
            raise RuntimeError("MUJOCO_NONFINITE_STATE")
        return measured_rtf

    def execute_s3_grasp(
        self,
        *,
        dx_m: float,
        dy_m: float,
        dyaw_rad: float,
        act_client: ActPolicyClient | None = None,
    ) -> dict[str, Any]:
        """Run paced S3 intake grasp and check pose envelope and optional ACT hook."""
        dx = float(dx_m)
        dy = float(dy_m)
        dyaw = float(dyaw_rad)
        if not (math.isfinite(dx) and math.isfinite(dy) and math.isfinite(dyaw)):
            raise ValueError("S3 pose error values must be finite")

        if self.backend == "mujoco":
            measured_rtf = self._step_mujoco(dx, dy, dyaw)
        else:
            measured_rtf = self.pacer.run_steps(self.step_count)

        in_envelope = (
            abs(dx) <= DEFAULT_DX_LIMIT_M
            and abs(dy) <= DEFAULT_DY_LIMIT_M
            and abs(dyaw) <= DEFAULT_DYAW_LIMIT_RAD
        )
        if not in_envelope:
            return {
                "lifted": False,
                "bilateral_lift": False,
                "arm_in_bed_zone": False,
                "reason": "POSE_OUT_OF_ENVELOPE",
                "rtf": measured_rtf,
                "backend": self.backend,
            }

        if act_client is not None:
            pred = act_client.predict({"dx_m": dx, "dy_m": dy, "dyaw_rad": dyaw})
            if not bool(pred.get("ok", False)):
                return {
                    "lifted": False,
                    "bilateral_lift": False,
                    "arm_in_bed_zone": False,
                    "reason": str(pred.get("reason") or "ACT_POLICY_REFUSED"),
                    "rtf": measured_rtf,
                    "backend": self.backend,
                }

        return {
            "lifted": True,
            "bilateral_lift": True,
            "arm_in_bed_zone": False,
            "reason": None,
            "rtf": measured_rtf,
            "backend": self.backend,
        }


class CoupledMujocoBridge:
    """Loopback bridge driving S3 MuJoCo grasps and downstream cell stages."""

    def __init__(
        self,
        controller_url: str,
        *,
        arm_id: str = "arm_s",
        runner: MujocoCellRunner | None = None,
        act_client: ActPolicyClient | None = None,
        advance_downstream: bool = True,
        timeout_s: float = 5.0,
    ) -> None:
        cleaned = str(controller_url or "").strip().rstrip("/")
        if not cleaned:
            raise ValueError("controller_url must be non-empty")
        self.controller_url = cleaned
        self.arm_id = str(arm_id)
        self.runner = runner or MujocoCellRunner()
        self.act_client = act_client
        self.advance_downstream = bool(advance_downstream)
        self.timeout_s = _finite_positive(timeout_s, "timeout_s")

    def _get(self, path: str) -> dict[str, Any]:
        return _request_json(f"{self.controller_url}{path}", timeout_s=self.timeout_s)

    def _post(self, path: str, payload: dict[str, Any]) -> dict[str, Any]:
        return _request_json(
            f"{self.controller_url}{path}",
            method="POST",
            payload=payload,
            timeout_s=self.timeout_s,
        )

    def _advance_downstream(self, cargo_state: str, *, rtf: float) -> dict[str, Any]:
        current = cargo_state
        stages: list[dict[str, Any]] = []
        for stage in _DOWNSTREAM_STAGES.get(current, ()):
            reply = self._post("/api/sim/events/cell-stage", {"stage": stage, "rtf": rtf})
            stages.append(reply)
            current = str(reply.get("cargo_state") or current)
            if not reply.get("accepted"):
                return {
                    "action": "stage_held",
                    "cargo_state": current,
                    "reply": reply,
                    "stages": stages,
                }
        return {"action": "advanced", "cargo_state": current, "stages": stages}

    def poll_once(self) -> dict[str, Any]:
        """Poll controller state once and process pending S3 or cell-stage work."""
        state = self._get("/api/sim/state")
        cargo_state = str(state.get("cargo_state") or "")
        intake_pose = state.get("mujoco_intake_pose")

        if cargo_state == "HANDOFF_AT_S3" and isinstance(intake_pose, dict):
            grasp = self.runner.execute_s3_grasp(
                dx_m=float(intake_pose["dx_m"]),
                dy_m=float(intake_pose["dy_m"]),
                dyaw_rad=float(intake_pose["dyaw_rad"]),
                act_client=self.act_client,
            )
            rtf = float(grasp["rtf"])
            lift_reply = self._post(
                "/api/sim/events/cargo-lifted",
                {
                    "arm_id": self.arm_id,
                    "lifted": bool(grasp["lifted"]),
                    "bilateral_lift": bool(grasp["bilateral_lift"]),
                    "rtf": rtf,
                },
            )
            cargo_state = str(lift_reply.get("cargo_state") or cargo_state)
            if not lift_reply.get("accepted"):
                return {
                    "action": "cargo_lifted_held",
                    "reply": lift_reply,
                    "cargo_state": cargo_state,
                    "grasp": grasp,
                }

            clear_reply = self._post(
                "/api/sim/events/cell-bed-clear",
                {"arm_id": self.arm_id, "arm_in_bed_zone": False, "rtf": rtf},
            )
            if not self.advance_downstream:
                return {
                    "action": "bed_cleared",
                    "cargo_state": cargo_state,
                    "lift_reply": lift_reply,
                    "clear_reply": clear_reply,
                }
            res = self._advance_downstream(cargo_state, rtf=rtf)
            res["lift_reply"] = lift_reply
            res["clear_reply"] = clear_reply
            return res

        if cargo_state in _DOWNSTREAM_STAGES:
            clear_reply = None
            if cargo_state == "IN_CELL_ARM_S" and bool(state.get("arm_in_bed_zone")):
                clear_reply = self._post(
                    "/api/sim/events/cell-bed-clear",
                    {"arm_id": self.arm_id, "arm_in_bed_zone": False, "rtf": 1.0},
                )
            if self.advance_downstream:
                res = self._advance_downstream(cargo_state, rtf=1.0)
                if clear_reply is not None:
                    res["clear_reply"] = clear_reply
                return res
            if clear_reply is not None:
                return {
                    "action": "bed_cleared",
                    "cargo_state": cargo_state,
                    "clear_reply": clear_reply,
                }

        return {"action": "idle", "cargo_state": cargo_state}


def main(argv: list[str] | None = None) -> int:
    """CLI entrypoint for the coupled MuJoCo bridge."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--controller-url", default="http://127.0.0.1:8190")
    parser.add_argument("--act-url", default=None)
    parser.add_argument("--backend", choices=BACKENDS, default="auto")
    parser.add_argument("--once", action="store_true")
    parser.add_argument("--poll-interval", type=float, default=0.1)
    parser.add_argument("--no-downstream", action="store_true")
    args = parser.parse_args(argv)

    act_client = ActPolicyClient(args.act_url) if args.act_url else None
    runner = MujocoCellRunner(backend=args.backend)
    bridge = CoupledMujocoBridge(
        args.controller_url,
        runner=runner,
        act_client=act_client,
        advance_downstream=not args.no_downstream,
    )
    if args.once:
        print(json.dumps(bridge.poll_once(), ensure_ascii=False))
        return 0

    interval = _finite_positive(args.poll_interval, "poll_interval")
    try:
        while True:
            try:
                bridge.poll_once()
            except RuntimeError as err:
                print(f"[coupled_mujoco_bridge] transient error: {err}", file=sys.stderr)
            time.sleep(interval)
    except KeyboardInterrupt:
        pass
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
