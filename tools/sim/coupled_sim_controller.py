#!/usr/bin/env python3
"""Event-driven coupled simulation & boundary fault-injection controller (D-1088).

Owns ONLY the single cargo ownership ledger (SSOT), boundary handoff events between
Gazebo Pinky Nav2 and MuJoCo OMX 3-arm cell, boundary-only field fault toggles, and
Read-Only ROSY World projection publishing. Never embeds simulator branches into
CORE or Fleet, and never impersonates ``adapter="real"`` or ``world_id="real-site"``.
"""
from __future__ import annotations

import argparse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import os
from pathlib import Path
import re
import sys
import threading
import time
from typing import Any
from urllib.parse import urlsplit

SIM_DIR = Path(__file__).resolve().parent
if str(SIM_DIR) not in sys.path:
    sys.path.insert(0, str(SIM_DIR))

from coupled_sim_faults import (  # noqa: E402
    ALLOWED_FAULTS,
    FAULT_SCHEMA,
    FaultRegistry,
    _finite_float,
)
from world_env_adapter import (  # noqa: E402
    BACKENDS,
    CANONICAL_FLEET_ROBOTS,
    FACTORY_STATE_SCHEMA,
    WorldPublisher,
    build_parity_fingerprint,
    validate_world_id,
)

__all__ = [
    "ALLOWED_FAULTS", "CARGO_STATES", "CoupledSimController", "EVENT_SCHEMA",
    "FAULT_SCHEMA", "FaultRegistry", "LOOPBACK_HOSTS", "MIN_VALID_RTF",
    "build_server", "main",
]

EVENT_SCHEMA = "rosy.sim.coupled-event.v1"
CARGO_STATES = ("ON_PINKY", "HANDOFF_AT_S3", "IN_CELL_ARM_S", "ON_BELT", "IN_CELL_AB", "ON_SHIP", "CARGO_FAULT")
_CELL_STAGE_ORDER = ("IN_CELL_ARM_S", "ON_BELT", "IN_CELL_AB", "ON_SHIP")
_STAGE_TO_ARMS: dict[str, tuple[str, ...]] = {"ON_BELT": ("arm_s",), "IN_CELL_AB": ("arm_a", "arm_b"), "ON_SHIP": ("arm_a", "arm_b")}
MIN_VALID_RTF = 0.9
LOOPBACK_HOSTS = frozenset({"127.0.0.1", "::1", "localhost"})
SHA256_RE = re.compile(r"^[0-9a-f]{64}$")

_DEFAULT_PINKY_POSES = {
    "rosy_42": [-0.414, 0.47, 0.0],
    "rosy_45": [-0.1914, 0.47, 0.0],
    "rosy_46": [0.032, 0.47, 0.0],
}
_DEFAULT_ARM_JOINTS = {
    "arm_s": [0.18, -0.78, 0.74, 0.72, 1.5708, 0.72],
    "arm_a": [-0.62, -0.78, 0.72, 0.72, 1.5708, 0.72],
    "arm_b": [0.62, -0.78, 0.72, 0.72, 1.5708, 0.72],
}
_CARGO_ZONE_BY_STATE = {
    "ON_PINKY": "pinky_tray",
    "HANDOFF_AT_S3": "s3",
    "IN_CELL_ARM_S": "arm_s",
    "ON_BELT": "belt",
    "IN_CELL_AB": "cell_ab",
    "ON_SHIP": "ship",
    "CARGO_FAULT": "fault_hold",
}


class CoupledSimController:
    """Single cargo ownership ledger and 3-event coupled sim state machine."""

    def __init__(
        self,
        *,
        world_id: str = "coupled-sim",
        adapter: str = "gazebo",
        site_map_sha256: str,
        robot_id: str = "rosy_45",
        cargo_id: str = "cargo-sim-01",
        run_id: str | None = None,
        world_publisher: WorldPublisher | None = None,
    ) -> None:
        wid = validate_world_id(world_id)
        if wid == "real-site":
            raise ValueError("SIM_CANNOT_IMPERSONATE_REAL_SITE")
        if adapter not in BACKENDS or adapter == "real":
            raise ValueError(f"INVALID_SIM_ADAPTER:{adapter}")
        sha = str(site_map_sha256 or "").lower()
        if not SHA256_RE.fullmatch(sha):
            raise ValueError("VALID_SITE_MAP_SHA256_REQUIRED")
        if robot_id not in CANONICAL_FLEET_ROBOTS["pinkys"]:
            raise ValueError(f"UNKNOWN_PINKY_ROBOT:{robot_id}")

        self.world_id = wid
        self.adapter = adapter
        self.site_map_sha256 = sha
        self.robot_id = robot_id
        self.cargo_id = str(cargo_id)
        self.run_id = run_id or f"{wid}-run-1"
        self.world_publisher = world_publisher
        self.faults = FaultRegistry()
        self._lock = threading.Lock()
        self._parity = build_parity_fingerprint(site_map_sha256=self.site_map_sha256, has_cargo_tray=True)
        self._started_at_s = time.monotonic()
        self.cargo_state = "ON_PINKY"
        self.pinky_has_cargo = True
        self.arm_in_bed_zone = False
        self.s3_pose_error: dict[str, float] | None = None
        self.mujoco_intake_pose: dict[str, Any] | None = None
        self.min_rtf = 1.0
        self.inconclusive = False
        self.events: list[dict[str, Any]] = []

    def _record_rtf(self, rtf: float) -> float:
        val = _finite_float(rtf, "rtf")
        if val <= 0.0:
            raise ValueError("rtf must be positive")
        self.min_rtf = min(self.min_rtf, val)
        if val < MIN_VALID_RTF:
            self.inconclusive = True
        return val

    def _record_event(self, event_type: str, payload: dict[str, Any]) -> None:
        self.events.append({
            "schema": EVENT_SCHEMA,
            "seq": len(self.events) + 1,
            "event": event_type,
            "observed_at_ms": time.time_ns() // 1_000_000,
            **payload,
        })

    def _publish_world(self) -> None:
        if self.world_publisher is not None:
            self.world_publisher.publish(self._build_world_state_locked(time.time_ns() // 1_000_000))

    def handle_s3_arrived_settled(
        self,
        *,
        robot_id: str,
        dx_m: float,
        dy_m: float,
        dyaw_rad: float,
        bed_velocity_measured: bool = True,
        rtf: float = 1.0,
    ) -> dict[str, Any]:
        """Event 1: Gazebo S3 arrival settled -> forward pose error to MuJoCo S3 intake."""
        dx = _finite_float(dx_m, "dx_m")
        dy = _finite_float(dy_m, "dy_m")
        dyaw = _finite_float(dyaw_rad, "dyaw_rad")
        if robot_id != self.robot_id:
            raise ValueError(f"ROBOT_MISMATCH:{robot_id}")

        with self._lock:
            if self.cargo_state != "ON_PINKY":
                raise ValueError(f"INVALID_CARGO_TRANSITION:{self.cargo_state}->HANDOFF_AT_S3")
            val_rtf = self._record_rtf(rtf)

            reason = None
            if not bed_velocity_measured or self.faults.is_active("pinky.s3_brake_unmeasured"):
                reason = "AMR_BRAKE_BED_VELOCITY_UNMEASURED"
            elif not self.faults.apply_arm_presence_boundary("arm_s", True):
                reason = "ARM_USB_UNPLUGGED:arm_s"

            if reason is not None:
                self._record_event("S3_ARRIVED_SETTLED", {"accepted": False, "reason": reason, "rtf": val_rtf})
                self._publish_world()
                return {"accepted": False, "reason": reason, "cargo_state": self.cargo_state, "inconclusive": self.inconclusive}

            self.s3_pose_error = {"dx_m": dx, "dy_m": dy, "dyaw_rad": dyaw}
            self.mujoco_intake_pose = {"dx_m": dx, "dy_m": dy, "dyaw_rad": dyaw, "cargo_id": self.cargo_id, "robot_id": robot_id}
            self.cargo_state = "HANDOFF_AT_S3"
            self.arm_in_bed_zone = True
            self._record_event("S3_ARRIVED_SETTLED", {"accepted": True, "pose_error": dict(self.s3_pose_error), "rtf": val_rtf})
            self._publish_world()
            return {"accepted": True, "cargo_state": self.cargo_state, "mujoco_intake_pose": dict(self.mujoco_intake_pose), "inconclusive": self.inconclusive}

    def handle_cargo_lifted_or_dropped(
        self,
        *,
        arm_id: str = "arm_s",
        lifted: bool,
        bilateral_lift: bool = True,
        rtf: float = 1.0,
    ) -> dict[str, Any]:
        """Event 2: MuJoCo arm_s grasp outcome updates Gazebo Pinky tray or faults cargo."""
        with self._lock:
            if self.cargo_state != "HANDOFF_AT_S3":
                raise ValueError(f"INVALID_CARGO_TRANSITION:{self.cargo_state}->CARGO_LIFTED_OR_DROPPED")
            val_rtf = self._record_rtf(rtf)

            if not self.faults.apply_arm_presence_boundary(arm_id, True):
                reason = f"ARM_USB_UNPLUGGED:{arm_id}"
                self._record_event("CARGO_LIFTED_OR_DROPPED", {"accepted": False, "reason": reason, "rtf": val_rtf})
                self._publish_world()
                return {"accepted": False, "cargo_state": self.cargo_state, "reason": reason, "inconclusive": self.inconclusive}

            bridge_res = self.faults.apply_workcell_bridge_boundary(arm_id, len(self.events) + 1)
            if not bridge_res["ok"]:
                reason = f"BRIDGE_SEQ_CONFLICT_409:{arm_id}"
                self._record_event("CARGO_LIFTED_OR_DROPPED", {"accepted": False, "status_code": 409, "reason": reason, "rtf": val_rtf})
                self._publish_world()
                return {"accepted": False, "status_code": 409, "reason": reason, "cargo_state": self.cargo_state, "inconclusive": self.inconclusive}

            if lifted and bilateral_lift:
                self.cargo_state = "IN_CELL_ARM_S"
                self.pinky_has_cargo = False
                self._record_event("CARGO_LIFTED_OR_DROPPED", {"accepted": True, "arm_id": arm_id, "rtf": val_rtf})
                self._publish_world()
                return {"accepted": True, "cargo_state": self.cargo_state, "gazebo_tray_empty": True, "inconclusive": self.inconclusive}

            self.cargo_state = "CARGO_FAULT"
            self._record_event("CARGO_LIFTED_OR_DROPPED", {"accepted": False, "reason": "CARGO_DROP_OR_UNILATERAL_LIFT", "rtf": val_rtf})
            self._publish_world()
            return {"accepted": False, "cargo_state": self.cargo_state, "reason": "CARGO_DROP_OR_UNILATERAL_LIFT", "hitl_required": True, "inconclusive": self.inconclusive}

    def handle_cell_bed_clear(
        self,
        *,
        arm_id: str = "arm_s",
        arm_in_bed_zone: bool,
        rtf: float = 1.0,
    ) -> dict[str, Any]:
        """Event 3: MuJoCo arm_s clearance permits or blocks Gazebo/Fleet Pinky departure."""
        with self._lock:
            in_zone = bool(arm_in_bed_zone)
            stall_cfg = self.faults.params("pinky.tangled_or_stall")
            stall_blocks = stall_cfg is not None and (
                stall_cfg.get("robot_id") is None or str(stall_cfg.get("robot_id")) == self.robot_id
            )

            reason = None
            if in_zone:
                reason = "ARM_IN_BED_ZONE"
            elif self.cargo_state == "CARGO_FAULT":
                reason = "CARGO_FAULT_HOLD"
            elif stall_blocks:
                reason = "PINKY_TANGLED_OR_STALL"
            elif self.cargo_state != "IN_CELL_ARM_S":
                raise ValueError(f"INVALID_CARGO_TRANSITION:{self.cargo_state}->CELL_BED_CLEAR")

            val_rtf = self._record_rtf(rtf)
            self.arm_in_bed_zone = in_zone

            if reason is not None:
                self._record_event("CELL_BED_CLEAR", {"accepted": False, "reason": reason, "rtf": val_rtf})
                self._publish_world()
                return {"accepted": False, "pinky_departure_permitted": False, "reason": reason, "cargo_state": self.cargo_state, "inconclusive": self.inconclusive}

            self._record_event("CELL_BED_CLEAR", {"accepted": True, "arm_id": arm_id, "rtf": val_rtf})
            self._publish_world()
            return {"accepted": True, "pinky_departure_permitted": True, "cargo_state": self.cargo_state, "inconclusive": self.inconclusive}

    def advance_cell_stage(self, stage: str, *, rtf: float = 1.0) -> dict[str, Any]:
        """Advance downstream cell cargo stages cleanly in canonical order."""
        if stage not in _CELL_STAGE_ORDER[1:]:
            raise ValueError(f"INVALID_CELL_STAGE:{stage}")
        expected_prev = _CELL_STAGE_ORDER[_CELL_STAGE_ORDER.index(stage) - 1]
        with self._lock:
            if self.cargo_state != expected_prev:
                raise ValueError(f"INVALID_CARGO_TRANSITION:{self.cargo_state}->{stage}")
            val_rtf = self._record_rtf(rtf)
            for arm_id in _STAGE_TO_ARMS[stage]:
                if not self.faults.apply_arm_presence_boundary(arm_id, True):
                    reason = f"ARM_USB_UNPLUGGED:{arm_id}"
                    self._record_event("CELL_STAGE", {"stage": stage, "accepted": False, "reason": reason, "rtf": val_rtf})
                    self._publish_world()
                    return {"accepted": False, "cargo_state": self.cargo_state, "reason": reason, "inconclusive": self.inconclusive}
            for arm_id in _STAGE_TO_ARMS[stage]:
                bridge_res = self.faults.apply_workcell_bridge_boundary(arm_id, len(self.events) + 1)
                if not bridge_res["ok"]:
                    reason = f"BRIDGE_SEQ_CONFLICT_409:{arm_id}"
                    self._record_event("CELL_STAGE", {"stage": stage, "accepted": False, "status_code": 409, "reason": reason, "rtf": val_rtf})
                    self._publish_world()
                    return {"accepted": False, "status_code": 409, "reason": reason, "cargo_state": self.cargo_state, "inconclusive": self.inconclusive}
            self.cargo_state = stage
            self._record_event("CELL_STAGE", {"stage": stage, "accepted": True, "rtf": val_rtf})
            self._publish_world()
            return {"accepted": True, "cargo_state": self.cargo_state, "inconclusive": self.inconclusive}

    def reset(self, *, clear_faults: bool = False) -> dict[str, Any]:
        """Reset scenario ledger back to initial ON_PINKY state."""
        with self._lock:
            self.cargo_state = "ON_PINKY"
            self.pinky_has_cargo = True
            self.arm_in_bed_zone = False
            self.s3_pose_error = None
            self.mujoco_intake_pose = None
            self.min_rtf = 1.0
            self.inconclusive = False
            self.events.clear()
            if clear_faults:
                self.faults.clear()
            self._publish_world()
            return self._snapshot_locked()

    def _snapshot_locked(self) -> dict[str, Any]:
        return {
            "world_id": self.world_id,
            "adapter": self.adapter,
            "robot_id": self.robot_id,
            "cargo_id": self.cargo_id,
            "cargo_state": self.cargo_state,
            "pinky_has_cargo": self.pinky_has_cargo,
            "arm_in_bed_zone": self.arm_in_bed_zone,
            "s3_pose_error": dict(self.s3_pose_error) if self.s3_pose_error else None,
            "mujoco_intake_pose": dict(self.mujoco_intake_pose) if self.mujoco_intake_pose else None,
            "min_rtf": self.min_rtf,
            "inconclusive": self.inconclusive,
            "faults": self.faults.snapshot()["active"],
            "events": list(self.events),
        }

    def state_snapshot(self) -> dict[str, Any]:
        with self._lock:
            return self._snapshot_locked()

    def _build_world_state_locked(self, obs_ms: int) -> dict[str, Any]:
        pose_map = {k: list(v) for k, v in _DEFAULT_PINKY_POSES.items()}
        active_faults = self.faults.snapshot()["active"]
        arms_observed = {
            arm_id: self.faults.apply_arm_presence_boundary(arm_id, True)
            for arm_id in CANONICAL_FLEET_ROBOTS["arms"]
        }
        pinkys = [
            {
                "id": rid,
                "pose_m": pose_map[rid],
                "yaw_rad": -1.5708,
                "observed": True,
                "has_cargo": self.pinky_has_cargo if rid == self.robot_id else False,
            }
            for rid in CANONICAL_FLEET_ROBOTS["pinkys"]
        ]
        lead_pose = pose_map[self.robot_id]
        return {
            "schema": FACTORY_STATE_SCHEMA,
            "stream_mode": "live",
            "world_id": self.world_id,
            "adapter": self.adapter,
            "simulator": self.adapter,
            "run_id": self.run_id,
            "sim_time_s": round(time.monotonic() - self._started_at_s, 3),
            "observed_at_ms": obs_ms,
            "has_cargo_tray": True,
            "site_map_sha256": self.site_map_sha256,
            "fleet_robots": {k: list(v) for k, v in CANONICAL_FLEET_ROBOTS.items()},
            "parity": dict(self._parity),
            "stage": self.cargo_state.lower(),
            "phase": self.cargo_state,
            "pinky": {
                "id": self.robot_id,
                "pose_m": list(lead_pose),
                "yaw_rad": -1.5708,
                "has_cargo": self.pinky_has_cargo,
                "s3_in_bounds": self.cargo_state != "ON_PINKY",
            },
            "pinkys": pinkys,
            "arms": {k: list(v) for k, v in _DEFAULT_ARM_JOINTS.items()},
            "arms_observed": arms_observed,
            "cargo": {
                "id": self.cargo_id,
                "zone": _CARGO_ZONE_BY_STATE[self.cargo_state],
                "state": self.cargo_state,
                "pose_m": list(lead_pose),
                "yaw_rad": 0.0,
                "observed": True,
            },
            "cell_ab": {
                "active_arm": "arm_a" if self.cargo_state == "IN_CELL_AB" else None,
                "active_step": self.cargo_state.lower(),
                "stacked": [self.cargo_id] if self.cargo_state == "ON_SHIP" else [],
            },
            "read_only": True,
            "active_faults": active_faults,
            "rtf": self.min_rtf,
            "inconclusive": self.inconclusive,
        }

    def build_world_state(self, now_ms: int | None = None) -> dict[str, Any]:
        """Build a Read-Only ``rosy.world.factory-state.v1`` projection snapshot."""
        obs_ms = time.time_ns() // 1_000_000 if now_ms is None else int(now_ms)
        with self._lock:
            return self._build_world_state_locked(obs_ms)


def _make_handler(controller: CoupledSimController) -> type[BaseHTTPRequestHandler]:
    class CoupledSimHandler(BaseHTTPRequestHandler):
        def log_message(self, format: str, *args: object) -> None:  # noqa: A003
            return

        def _reply(self, status: int, value: dict[str, Any]) -> None:
            raw = json.dumps(value, allow_nan=False, ensure_ascii=False).encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Cache-Control", "no-store")
            self.send_header("Content-Length", str(len(raw)))
            self.end_headers()
            self.wfile.write(raw)

        def _read_json(self) -> dict[str, Any]:
            length = int(self.headers.get("Content-Length") or 0)
            if length < 0 or length > 65536:
                raise ValueError("INVALID_BODY_LENGTH")
            raw = self.rfile.read(length) if length > 0 else b"{}"
            data = json.loads(raw.decode("utf-8") or "{}")
            if not isinstance(data, dict):
                raise ValueError("EXPECTED_JSON_OBJECT")
            return data

        def do_GET(self) -> None:  # noqa: N802
            path = urlsplit(self.path).path
            if path == "/healthz":
                self._reply(200, {"status": "ok", "world_id": controller.world_id})
            elif path == "/api/sim/state":
                self._reply(200, controller.state_snapshot())
            elif path == "/api/sim/world-projection":
                self._reply(200, controller.build_world_state())
            elif path == "/api/sim/faults":
                self._reply(200, controller.faults.snapshot())
            else:
                self._reply(404, {"error": "NOT_FOUND"})

        def do_POST(self) -> None:  # noqa: N802
            path = urlsplit(self.path).path
            try:
                body = self._read_json()
                if path.startswith("/api/sim/faults/"):
                    fault_id = path.removeprefix("/api/sim/faults/")
                    res = (
                        controller.faults.enable(fault_id, body.get("params"))
                        if bool(body.get("enabled", True))
                        else controller.faults.disable(fault_id)
                    )
                    self._reply(200, res)
                elif path == "/api/sim/reset":
                    self._reply(200, controller.reset(clear_faults=bool(body.get("clear_faults", False))))
                elif path == "/api/sim/events/s3-arrived":
                    self._reply(200, controller.handle_s3_arrived_settled(
                        robot_id=str(body.get("robot_id") or controller.robot_id),
                        dx_m=body.get("dx_m", 0.0),
                        dy_m=body.get("dy_m", 0.0),
                        dyaw_rad=body.get("dyaw_rad", 0.0),
                        bed_velocity_measured=bool(body.get("bed_velocity_measured", True)),
                        rtf=body.get("rtf", 1.0),
                    ))
                elif path == "/api/sim/events/cargo-lifted":
                    self._reply(200, controller.handle_cargo_lifted_or_dropped(
                        arm_id=str(body.get("arm_id") or "arm_s"),
                        lifted=bool(body.get("lifted", True)),
                        bilateral_lift=bool(body.get("bilateral_lift", True)),
                        rtf=body.get("rtf", 1.0),
                    ))
                elif path == "/api/sim/events/cell-bed-clear":
                    self._reply(200, controller.handle_cell_bed_clear(
                        arm_id=str(body.get("arm_id") or "arm_s"),
                        arm_in_bed_zone=bool(body.get("arm_in_bed_zone", False)),
                        rtf=body.get("rtf", 1.0),
                    ))
                elif path == "/api/sim/events/cell-stage":
                    self._reply(200, controller.advance_cell_stage(
                        stage=str(body.get("stage") or ""),
                        rtf=body.get("rtf", 1.0),
                    ))
                else:
                    self._reply(404, {"error": "NOT_FOUND"})
            except ValueError as err:
                msg = str(err)
                status = 404 if msg.startswith("UNKNOWN_FAULT_ID") else 400
                self._reply(status, {"error": msg})

    return CoupledSimHandler


def build_server(
    controller: CoupledSimController,
    *,
    host: str = "127.0.0.1",
    port: int = 8190,
    allow_non_loopback: bool = False,
) -> ThreadingHTTPServer:
    """Create a loopback-guarded HTTP server for coupled sim events and fault toggles."""
    if host not in LOOPBACK_HOSTS and not allow_non_loopback:
        raise ValueError(f"REFUSING_NON_LOOPBACK_BIND:{host}")
    return ThreadingHTTPServer((host, int(port)), _make_handler(controller))


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--serve", action="store_true")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8190)
    parser.add_argument("--allow-non-loopback", action="store_true")
    parser.add_argument("--world-id", default="coupled-sim")
    parser.add_argument("--adapter", default="gazebo")
    parser.add_argument("--site-map-sha256", default="0" * 64)
    parser.add_argument("--world-out", type=Path, default=None)
    parser.add_argument("--world-url", default=None)
    args = parser.parse_args(argv)

    publisher = (
        WorldPublisher(
            world_id=args.world_id,
            worlds_dir=args.world_out,
            world_url=args.world_url,
            token=os.environ.get("ROSY_WORLD_INGEST_TOKEN") or None,
        )
        if (args.world_out or args.world_url)
        else None
    )
    controller = CoupledSimController(
        world_id=args.world_id,
        adapter=args.adapter,
        site_map_sha256=args.site_map_sha256,
        world_publisher=publisher,
    )
    if not args.serve:
        print(json.dumps(controller.state_snapshot(), ensure_ascii=False))
        return 0

    server = build_server(
        controller, host=args.host, port=args.port, allow_non_loopback=args.allow_non_loopback,
    )
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
