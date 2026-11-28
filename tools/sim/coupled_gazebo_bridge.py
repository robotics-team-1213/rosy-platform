#!/usr/bin/env python3
"""Gazebo/Nav2 <-> CoupledSimController HTTP bridge & S3 arrival validator (D-1088 Slice 3).

Pure stdlib bridge:
- Computes S3 arrival pose error, uncertainty bounds, bed velocity check, and RTF.
- Filters Gazebo cmd_vel at the velocity bridge boundary on ``pinky.tangled_or_stall``.
- Posts ``S3_ARRIVED_SETTLED`` and polls fail-closed Pinky departure permission.
- Evaluates hub heartbeat lag boundary (``hub.heartbeat_lag``) cleanly.
"""
from __future__ import annotations

import argparse
import json
import math
import time
from pathlib import Path
from typing import Any
import urllib.error
import urllib.request


DEFAULT_S3_LIMITS: dict[str, Any] = {
    "reference_pose": [-0.1914, -0.207, -1.5708],
    "longitudinal_m": 0.05,
    "lateral_m": 0.04,
    "heading_rad": 0.12,
    "position_uncertainty_m": 0.005,
    "heading_uncertainty_rad": 0.01,
}
DEFAULT_BED_LINEAR_MAX_M_S = 0.01
DEFAULT_BED_ANGULAR_MAX_RAD_S = 0.05
MIN_STATIONARY_SAMPLES = 4
PERMITTED_DEPARTURE_STATES = frozenset({"IN_CELL_ARM_S", "ON_BELT", "IN_CELL_AB", "ON_SHIP"})


def _finite_float(value: object, name: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(f"{name} must be a finite number")
    num = float(value)
    if not math.isfinite(num):
        raise ValueError(f"{name} must be finite")
    return num


def _circular_mean(angles: list[float], fallback_yaw: float) -> float:
    sin_sum = sum(math.sin(a) for a in angles)
    cos_sum = sum(math.cos(a) for a in angles)
    if math.hypot(sin_sum, cos_sum) > 1e-12:
        return math.atan2(sin_sum, cos_sum)
    delta_mean = sum(math.remainder(a - fallback_yaw, math.tau) for a in angles) / len(angles)
    return math.remainder(fallback_yaw + delta_mean, math.tau)


def compute_s3_arrival_observation(
    samples: list[dict[str, Any]],
    s3_limits: dict[str, Any],
    wall_elapsed_s: float,
) -> dict[str, Any]:
    """Summarize stationary S3 odom samples against ``s3_limits`` and wall elapsed time."""
    if not isinstance(samples, list) or not samples:
        raise ValueError("samples must be a non-empty list")
    wall_s = _finite_float(wall_elapsed_s, "wall_elapsed_s")
    if wall_s <= 0.0:
        raise ValueError("wall_elapsed_s must be positive")
    if not isinstance(s3_limits, dict):
        raise ValueError("s3_limits must be a dict")

    ref_pose = s3_limits.get("reference_pose")
    if not isinstance(ref_pose, (list, tuple)) or len(ref_pose) != 3:
        raise ValueError("s3_limits.reference_pose must have 3 elements")
    rx = _finite_float(ref_pose[0], "reference_pose[0]")
    ry = _finite_float(ref_pose[1], "reference_pose[1]")
    ryaw = _finite_float(ref_pose[2], "reference_pose[2]")
    lon_lim = _finite_float(s3_limits["longitudinal_m"], "longitudinal_m")
    lat_lim = _finite_float(s3_limits["lateral_m"], "lateral_m")
    head_lim = _finite_float(s3_limits["heading_rad"], "heading_rad")
    xy_err = _finite_float(s3_limits.get("position_uncertainty_m", 0.0), "position_uncertainty_m")
    yaw_err = _finite_float(s3_limits.get("heading_uncertainty_rad", 0.0), "heading_uncertainty_rad")

    xs: list[float] = []
    ys: list[float] = []
    yaws: list[float] = []
    sim_times: list[float] = []
    stationary_ok = True

    for idx, sample in enumerate(samples):
        if not isinstance(sample, dict):
            raise ValueError(f"samples[{idx}] must be a dict")
        sim_t = _finite_float(sample["sim_time_s"], f"samples[{idx}].sim_time_s")
        pose = sample.get("pose_xy_yaw")
        if not isinstance(pose, (list, tuple)) or len(pose) != 3:
            raise ValueError(f"samples[{idx}].pose_xy_yaw must have 3 elements")
        px = _finite_float(pose[0], f"samples[{idx}].pose_xy_yaw[0]")
        py = _finite_float(pose[1], f"samples[{idx}].pose_xy_yaw[1]")
        pyaw = _finite_float(pose[2], f"samples[{idx}].pose_xy_yaw[2]")
        lin = _finite_float(sample["linear_m_s"], f"samples[{idx}].linear_m_s")
        ang = _finite_float(sample["angular_rad_s"], f"samples[{idx}].angular_rad_s")

        sim_times.append(sim_t)
        xs.append(px)
        ys.append(py)
        yaws.append(pyaw)
        if abs(lin) > DEFAULT_BED_LINEAR_MAX_M_S or abs(ang) > DEFAULT_BED_ANGULAR_MAX_RAD_S:
            stationary_ok = False

    n = len(samples)
    mean_x = sum(xs) / n
    mean_y = sum(ys) / n
    mean_yaw = _circular_mean(yaws, ryaw)

    raw_dx = mean_x - rx
    raw_dy = mean_y - ry
    dx_m = raw_dx * math.cos(ryaw) + raw_dy * math.sin(ryaw)
    dy_m = -raw_dx * math.sin(ryaw) + raw_dy * math.cos(ryaw)
    dyaw_rad = math.remainder(mean_yaw - ryaw, math.tau)

    in_bounds = (
        (abs(dx_m) + xy_err <= lon_lim)
        and (abs(dy_m) + xy_err <= lat_lim)
        and (abs(dyaw_rad) + yaw_err <= head_lim)
    )
    bed_velocity_measured = (n >= MIN_STATIONARY_SAMPLES) and stationary_ok
    sim_span = sim_times[-1] - sim_times[0]
    rtf = max(sim_span, 1e-6) / max(wall_s, 1e-6)

    return {
        "dx_m": dx_m,
        "dy_m": dy_m,
        "dyaw_rad": dyaw_rad,
        "in_bounds": bool(in_bounds),
        "bed_velocity_measured": bool(bed_velocity_measured),
        "rtf": rtf,
        "sample_count": n,
    }


def _active_faults_from_payload(payload: dict[str, Any]) -> dict[str, Any]:
    active = payload.get("active")
    if isinstance(active, dict):
        return active
    return payload


def _target_matches_robot(cfg: Any, robot_id: str) -> bool:
    if not isinstance(cfg, dict):
        return False
    target = cfg.get("robot_id")
    return target is None or str(target) == robot_id


class CoupledGazeboBridge:
    """HTTP bridge connecting Gazebo Pinky Nav2/cmd_vel to CoupledSimController."""

    def __init__(
        self,
        controller_url: str,
        *,
        robot_id: str = "rosy_45",
        timeout_s: float = 5.0,
    ) -> None:
        base = str(controller_url or "").strip().rstrip("/")
        if not base:
            raise ValueError("controller_url must be non-empty")
        timeout_val = _finite_float(timeout_s, "timeout_s")
        if timeout_val <= 0.0:
            raise ValueError("timeout_s must be positive")
        self.controller_url = base
        self.robot_id = str(robot_id)
        self.timeout_s = timeout_val

    def _request_json(
        self,
        method: str,
        path: str,
        payload: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        url = f"{self.controller_url}{path}"
        headers = {"Accept": "application/json"}
        data: bytes | None = None
        if payload is not None:
            data = json.dumps(payload, allow_nan=False, ensure_ascii=False).encode("utf-8")
            headers["Content-Type"] = "application/json; charset=utf-8"
        req = urllib.request.Request(url, data=data, headers=headers, method=method)
        try:
            with urllib.request.urlopen(req, timeout=self.timeout_s) as resp:
                raw = resp.read().decode("utf-8")
                parsed = json.loads(raw) if raw else {}
        except urllib.error.HTTPError as err:
            detail = err.read().decode("utf-8", errors="replace")
            raise RuntimeError(f"controller {method} {path} failed ({err.code}): {detail}") from err
        except (urllib.error.URLError, TimeoutError, OSError, json.JSONDecodeError) as err:
            raise RuntimeError(f"controller {method} {path} failed: {err}") from err
        if not isinstance(parsed, dict):
            raise RuntimeError(f"controller {method} {path} returned non-object JSON")
        return parsed

    def filter_cmd_vel(self, linear_mps: float, angular_rps: float) -> tuple[float, float]:
        """Clamp wheel velocity to (0.0, 0.0) when ``pinky.tangled_or_stall`` is active."""
        lin = _finite_float(linear_mps, "linear_mps")
        ang = _finite_float(angular_rps, "angular_rps")
        faults = _active_faults_from_payload(self._request_json("GET", "/api/sim/faults"))
        stall_cfg = faults.get("pinky.tangled_or_stall")
        if stall_cfg is not None and _target_matches_robot(stall_cfg, self.robot_id):
            return (0.0, 0.0)
        return (lin, ang)

    def report_s3_arrival(self, observation: dict[str, Any]) -> dict[str, Any]:
        """Forward a measured S3 arrival observation to ``POST /api/sim/events/s3-arrived``."""
        payload = {
            "robot_id": self.robot_id,
            "dx_m": _finite_float(observation["dx_m"], "observation.dx_m"),
            "dy_m": _finite_float(observation["dy_m"], "observation.dy_m"),
            "dyaw_rad": _finite_float(observation["dyaw_rad"], "observation.dyaw_rad"),
            "bed_velocity_measured": bool(observation["bed_velocity_measured"]),
            "rtf": _finite_float(observation["rtf"], "observation.rtf"),
        }
        return self._request_json("POST", "/api/sim/events/s3-arrived", payload)

    def check_departure_permission(self) -> dict[str, Any]:
        """Evaluate fail-closed Pinky departure permission from ``GET /api/sim/state``."""
        state = self._request_json("GET", "/api/sim/state")
        cargo_state = state.get("cargo_state")
        arm_in_bed_zone = bool(state.get("arm_in_bed_zone"))
        faults = state.get("faults") or {}
        stall_cfg = faults.get("pinky.tangled_or_stall")
        stalled = stall_cfg is not None and _target_matches_robot(stall_cfg, self.robot_id)

        if stalled:
            reason = "PINKY_TANGLED_OR_STALL"
            permitted = False
        elif arm_in_bed_zone:
            reason = "ARM_IN_BED_ZONE"
            permitted = False
        elif cargo_state == "CARGO_FAULT":
            reason = "CARGO_FAULT_HOLD"
            permitted = False
        elif cargo_state in PERMITTED_DEPARTURE_STATES:
            reason = "OK"
            permitted = True
        else:
            reason = f"CARGO_STATE_NOT_CLEARED:{cargo_state}"
            permitted = False

        return {
            "permitted": permitted,
            "cargo_state": cargo_state,
            "arm_in_bed_zone": arm_in_bed_zone,
            "reason": reason,
        }

    def wait_for_departure_permission(
        self,
        timeout_s: float = 5.0,
        poll_s: float = 0.05,
    ) -> dict[str, Any]:
        """Poll departure permission until permitted, terminal ``CARGO_FAULT``, or timeout."""
        timeout_val = _finite_float(timeout_s, "timeout_s")
        poll_val = _finite_float(poll_s, "poll_s")
        if timeout_val < 0.0 or poll_val <= 0.0:
            raise ValueError("timeout_s must be >= 0 and poll_s must be > 0")
        deadline = time.monotonic() + timeout_val
        while True:
            status = self.check_departure_permission()
            if status["permitted"] or status["cargo_state"] == "CARGO_FAULT":
                return status
            remaining = deadline - time.monotonic()
            if remaining <= 0.0:
                return status
            time.sleep(min(poll_val, remaining))

    def evaluate_heartbeat(self, heartbeat_age_s: float) -> dict[str, Any]:
        """Evaluate hub heartbeat staleness with ``hub.heartbeat_lag`` fault boundary."""
        age = _finite_float(heartbeat_age_s, "heartbeat_age_s")
        if age < 0.0:
            raise ValueError("heartbeat_age_s must be non-negative")
        faults = _active_faults_from_payload(self._request_json("GET", "/api/sim/faults"))
        lag_cfg = faults.get("hub.heartbeat_lag")
        fault_injected = lag_cfg is not None and _target_matches_robot(lag_cfg, self.robot_id)
        if fault_injected:
            lag_s = _finite_float(lag_cfg.get("lag_s", 8.0), "hub.heartbeat_lag.lag_s")
            threshold_s = _finite_float(lag_cfg.get("threshold_s", 5.0), "hub.heartbeat_lag.threshold_s")
        else:
            lag_s = 0.0
            threshold_s = 5.0
        effective_age_s = age + lag_s
        return {
            "robot_id": self.robot_id,
            "heartbeat_age_s": age,
            "effective_age_s": effective_age_s,
            "threshold_s": threshold_s,
            "degraded": effective_age_s >= threshold_s,
            "fault_injected": fault_injected,
        }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--controller-url", default="http://127.0.0.1:8190")
    parser.add_argument("--robot-id", default="rosy_45")
    parser.add_argument("--s3-obs-json", type=Path, default=None)
    parser.add_argument("--once", action="store_true")
    args = parser.parse_args(argv)

    bridge = CoupledGazeboBridge(args.controller_url, robot_id=args.robot_id)
    if args.s3_obs_json is not None:
        raw = json.loads(args.s3_obs_json.read_text(encoding="utf-8"))
        if "samples" in raw:
            obs = compute_s3_arrival_observation(
                raw["samples"],
                raw.get("s3_limits") or DEFAULT_S3_LIMITS,
                raw.get("wall_elapsed_s", 1.5),
            )
        else:
            obs = raw
        result = bridge.report_s3_arrival(obs)
    else:
        result = bridge.check_departure_permission()

    print(json.dumps(result, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
