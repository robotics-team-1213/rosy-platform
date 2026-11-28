#!/usr/bin/env python3
"""Boundary fault registry and perturbation helpers for coupled simulation (D-1088).

All 7 operational field faults are injected strictly at simulator/bridge boundaries,
never inside production Fleet, CORE, or ACT decision logic (D-182).
"""
from __future__ import annotations

import math
import threading
from typing import Any

FAULT_SCHEMA = "rosy.sim.fault-state.v1"
ALLOWED_FAULTS = (
    "pinky.tangled_or_stall",
    "pinky.s3_brake_unmeasured",
    "arm.usb_unplugged",
    "vision.calibration_mismatch",
    "vision.camera_drop",
    "bridge.seq_conflict_409",
    "hub.heartbeat_lag",
)


def _finite_float(value: object, name: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(f"{name} must be finite number")
    num = float(value)
    if not math.isfinite(num):
        raise ValueError(f"{name} must be finite")
    return num


def _validate_params(params: dict[str, Any] | None) -> dict[str, Any]:
    if params is None:
        return {}
    if not isinstance(params, dict):
        raise ValueError("fault params must be an object")
    clean: dict[str, Any] = {}
    for key, val in params.items():
        if not isinstance(key, str) or not key:
            raise ValueError("fault param key must be non-empty string")
        if isinstance(val, (int, float)) and not isinstance(val, bool):
            clean[key] = _finite_float(val, f"params.{key}")
        elif isinstance(val, (str, bool)) or val is None:
            clean[key] = val
        else:
            raise ValueError(f"unsupported fault param type for {key}")
    return clean


class FaultRegistry:
    """Thread-safe boundary fault toggles and pure boundary perturbation helpers."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._active: dict[str, dict[str, Any]] = {}

    @staticmethod
    def _require_known(fault_id: str) -> None:
        if fault_id not in ALLOWED_FAULTS:
            raise ValueError(f"UNKNOWN_FAULT_ID:{fault_id}")

    def enable(self, fault_id: str, params: dict[str, Any] | None = None) -> dict[str, Any]:
        """Activate ``fault_id`` with validated optional parameters."""
        self._require_known(fault_id)
        clean = _validate_params(params)
        with self._lock:
            self._active[fault_id] = clean
        return {"fault_id": fault_id, "enabled": True, "params": dict(clean)}

    def disable(self, fault_id: str) -> dict[str, Any]:
        """Deactivate ``fault_id`` cleanly."""
        self._require_known(fault_id)
        with self._lock:
            self._active.pop(fault_id, None)
        return {"fault_id": fault_id, "enabled": False}

    def clear(self) -> None:
        with self._lock:
            self._active.clear()

    def is_active(self, fault_id: str) -> bool:
        with self._lock:
            return fault_id in self._active

    def params(self, fault_id: str) -> dict[str, Any] | None:
        with self._lock:
            cfg = self._active.get(fault_id)
            return dict(cfg) if cfg is not None else None

    def snapshot(self) -> dict[str, Any]:
        with self._lock:
            active = {k: dict(v) for k, v in sorted(self._active.items())}
        return {"schema": FAULT_SCHEMA, "active": active}

    def apply_vision_boundary(self, observation: dict[str, Any]) -> dict[str, Any] | None:
        """Perturb or drop an overhead observation copy at the vision bridge boundary."""
        drop_cfg = self.params("vision.camera_drop")
        if drop_cfg is not None:
            if "source_id" in drop_cfg:
                target_drop = drop_cfg["source_id"]
                if target_drop is None or str(observation.get("source_id") or "") == str(target_drop):
                    return None
            elif str(observation.get("source_id") or "") == "ceiling_north":
                return None

        out = dict(observation)
        cfg = self.params("vision.calibration_mismatch")
        if cfg is None:
            return out
        target_src = str(cfg.get("source_id") or "ceiling_north")
        if str(observation.get("source_id") or "") != target_src:
            return out
        dx = float(cfg.get("dx_m", 0.18))
        dy = float(cfg.get("dy_m", -0.12))
        dyaw = float(cfg.get("dyaw_rad", 0.25))
        out["score"] = float(cfg.get("score", 0.472))
        out["calibration_mismatch_injected"] = True
        if isinstance(observation.get("x_m"), (int, float)) and not isinstance(observation.get("x_m"), bool):
            out["x_m"] = float(observation["x_m"]) + dx
        if isinstance(observation.get("y_m"), (int, float)) and not isinstance(observation.get("y_m"), bool):
            out["y_m"] = float(observation["y_m"]) + dy
        if isinstance(observation.get("yaw_rad"), (int, float)) and not isinstance(observation.get("yaw_rad"), bool):
            out["yaw_rad"] = math.remainder(float(observation["yaw_rad"]) + dyaw, math.tau)
        return out

    def apply_pinky_motion_boundary(
        self, robot_id: str, linear_mps: float, angular_rps: float,
    ) -> tuple[float, float]:
        """Clamp wheel motion to zero at the Gazebo velocity bridge when tangled/stalled."""
        v = _finite_float(linear_mps, "linear_mps")
        w = _finite_float(angular_rps, "angular_rps")
        cfg = self.params("pinky.tangled_or_stall")
        if cfg is None:
            return (v, w)
        target = cfg.get("robot_id")
        if target is None or str(target) == robot_id:
            return (0.0, 0.0)
        return (v, w)

    def apply_arm_presence_boundary(self, arm_id: str, connected: bool) -> bool:
        """Report USB disconnect at the OMX observer bridge when ``arm.usb_unplugged`` is set."""
        cfg = self.params("arm.usb_unplugged")
        if cfg is None:
            return bool(connected)
        target = str(cfg.get("arm_id") or "arm_s")
        if arm_id == target:
            return False
        return bool(connected)

    def apply_workcell_bridge_boundary(self, arm_id: str, expected_seq: int) -> dict[str, Any]:
        """Inject a 409 sequence conflict at the workcell bridge when ``bridge.seq_conflict_409`` is set."""
        seq = int(expected_seq)
        cfg = self.params("bridge.seq_conflict_409")
        if cfg is not None:
            target = cfg.get("arm_id")
            if target is None or str(target) == arm_id:
                return {"ok": False, "status_code": 409, "reason": "SEQ_CONFLICT_409", "arm_id": arm_id, "expected_seq": seq}
        return {"ok": True, "status_code": 200, "reason": None, "arm_id": arm_id, "expected_seq": seq}

    def apply_hub_heartbeat_boundary(self, robot_id: str, heartbeat_age_s: float) -> dict[str, Any]:
        """Inject heartbeat lag at the hub telemetry boundary when ``hub.heartbeat_lag`` is set."""
        age = _finite_float(heartbeat_age_s, "heartbeat_age_s")
        cfg = self.params("hub.heartbeat_lag")
        if cfg is not None and (cfg.get("robot_id") is None or str(cfg.get("robot_id")) == robot_id):
            lag_s = _finite_float(cfg.get("lag_s", 8.0), "lag_s")
            fault_injected = True
        else:
            lag_s = 0.0
            fault_injected = False
        threshold_s = _finite_float((cfg or {}).get("threshold_s", 5.0), "threshold_s")
        effective_age = age + lag_s
        return {
            "robot_id": robot_id,
            "heartbeat_age_s": age,
            "effective_age_s": effective_age,
            "threshold_s": threshold_s,
            "degraded": effective_age >= threshold_s,
            "fault_injected": fault_injected,
        }
