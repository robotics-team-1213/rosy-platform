#!/usr/bin/env python3
"""End-to-end boundary fault-injection regression suite for D-1088 (all 7 faults)."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys
from typing import Any

SIM_DIR = Path(__file__).resolve().parent
if str(SIM_DIR) not in sys.path:
    sys.path.insert(0, str(SIM_DIR))

from coupled_sim_controller import ALLOWED_FAULTS, CoupledSimController  # noqa: E402

RECEIPT_SCHEMA = "rosy.sim.fault-suite-receipt.v1"


def _new_controller(site_map_sha256: str) -> CoupledSimController:
    return CoupledSimController(site_map_sha256=site_map_sha256)


def _scenario_pinky_tangled_or_stall(site_map_sha256: str) -> dict[str, Any]:
    ctrl = _new_controller(site_map_sha256)
    ctrl.handle_s3_arrived_settled(robot_id="rosy_45", dx_m=0.0, dy_m=0.0, dyaw_rad=0.0)
    ctrl.handle_cargo_lifted_or_dropped(arm_id="arm_s", lifted=True, bilateral_lift=True)

    vel_base = ctrl.faults.apply_pinky_motion_boundary("rosy_45", 0.15, 0.0)
    clear_base = ctrl.handle_cell_bed_clear(arm_id="arm_s", arm_in_bed_zone=False)

    ctrl.faults.enable("pinky.tangled_or_stall", {"robot_id": "rosy_45"})
    vel_on = ctrl.faults.apply_pinky_motion_boundary("rosy_45", 0.15, 0.0)
    clear_on = ctrl.handle_cell_bed_clear(arm_id="arm_s", arm_in_bed_zone=False)

    ctrl.faults.disable("pinky.tangled_or_stall")
    vel_off = ctrl.faults.apply_pinky_motion_boundary("rosy_45", 0.15, 0.0)
    clear_off = ctrl.handle_cell_bed_clear(arm_id="arm_s", arm_in_bed_zone=False)

    passed = (
        vel_base == (0.15, 0.0)
        and clear_base["pinky_departure_permitted"] is True
        and vel_on == (0.0, 0.0)
        and clear_on["accepted"] is False
        and clear_on["reason"] == "PINKY_TANGLED_OR_STALL"
        and vel_off == (0.15, 0.0)
        and clear_off["pinky_departure_permitted"] is True
    )
    return {
        "fault_id": "pinky.tangled_or_stall",
        "passed": passed,
        "baseline_velocity": list(vel_base),
        "fault_on_velocity": list(vel_on),
        "fault_on_reason": clear_on.get("reason"),
        "recovered_velocity": list(vel_off),
        "recovered_departure_permitted": clear_off.get("pinky_departure_permitted"),
    }


def _scenario_pinky_s3_brake_unmeasured(site_map_sha256: str) -> dict[str, Any]:
    ctrl = _new_controller(site_map_sha256)
    base = ctrl.handle_s3_arrived_settled(robot_id="rosy_45", dx_m=0.01, dy_m=0.0, dyaw_rad=0.0)
    ctrl.reset()

    ctrl.faults.enable("pinky.s3_brake_unmeasured")
    fault_on = ctrl.handle_s3_arrived_settled(robot_id="rosy_45", dx_m=0.01, dy_m=0.0, dyaw_rad=0.0)

    ctrl.faults.disable("pinky.s3_brake_unmeasured")
    recovered = ctrl.handle_s3_arrived_settled(robot_id="rosy_45", dx_m=0.01, dy_m=0.0, dyaw_rad=0.0)

    passed = (
        base["accepted"] is True
        and fault_on["accepted"] is False
        and fault_on["reason"] == "AMR_BRAKE_BED_VELOCITY_UNMEASURED"
        and fault_on["cargo_state"] == "ON_PINKY"
        and recovered["accepted"] is True
        and recovered["cargo_state"] == "HANDOFF_AT_S3"
    )
    return {
        "fault_id": "pinky.s3_brake_unmeasured",
        "passed": passed,
        "baseline_state": base.get("cargo_state"),
        "fault_on_reason": fault_on.get("reason"),
        "recovered_state": recovered.get("cargo_state"),
    }


def _scenario_arm_usb_unplugged(site_map_sha256: str) -> dict[str, Any]:
    ctrl = _new_controller(site_map_sha256)
    arms_base = {a: ctrl.faults.apply_arm_presence_boundary(a, True) for a in ("arm_s", "arm_a", "arm_b")}
    s3_base = ctrl.handle_s3_arrived_settled(robot_id="rosy_45", dx_m=0.0, dy_m=0.0, dyaw_rad=0.0)

    ctrl.faults.enable("arm.usb_unplugged", {"arm_id": "arm_s"})
    arm_s_on = ctrl.faults.apply_arm_presence_boundary("arm_s", True)
    lift_on = ctrl.handle_cargo_lifted_or_dropped(arm_id="arm_s", lifted=True, bilateral_lift=True)

    ctrl.faults.disable("arm.usb_unplugged")
    lift_off = ctrl.handle_cargo_lifted_or_dropped(arm_id="arm_s", lifted=True, bilateral_lift=True)
    clear_off = ctrl.handle_cell_bed_clear(arm_id="arm_s", arm_in_bed_zone=False)
    ctrl.advance_cell_stage("ON_BELT")
    ctrl.advance_cell_stage("IN_CELL_AB")
    shipped = ctrl.advance_cell_stage("ON_SHIP")

    passed = (
        all(arms_base.values())
        and s3_base["accepted"] is True
        and arm_s_on is False
        and lift_on["accepted"] is False
        and lift_on["reason"] == "ARM_USB_UNPLUGGED:arm_s"
        and lift_off["accepted"] is True
        and clear_off["pinky_departure_permitted"] is True
        and shipped["accepted"] is True
        and shipped["cargo_state"] == "ON_SHIP"
    )
    return {
        "fault_id": "arm.usb_unplugged",
        "passed": passed,
        "baseline_arms": arms_base,
        "fault_on_reason": lift_on.get("reason"),
        "recovered_final_state": shipped.get("cargo_state"),
    }


def _scenario_vision_calibration_mismatch(site_map_sha256: str) -> dict[str, Any]:
    ctrl = _new_controller(site_map_sha256)
    raw = {"source_id": "ceiling_north", "x_m": 1.0, "y_m": 2.0, "yaw_rad": 0.1, "score": 0.98}

    base = ctrl.faults.apply_vision_boundary(raw)
    ctrl.faults.enable("vision.calibration_mismatch")
    fault_on = ctrl.faults.apply_vision_boundary(raw)
    ctrl.faults.disable("vision.calibration_mismatch")
    recovered = ctrl.faults.apply_vision_boundary(raw)

    passed = (
        base is not None
        and base["score"] == 0.98
        and base["x_m"] == 1.0
        and not base.get("calibration_mismatch_injected")
        and fault_on is not None
        and fault_on.get("calibration_mismatch_injected") is True
        and fault_on["score"] == 0.472
        and fault_on["x_m"] != 1.0
        and recovered is not None
        and recovered["score"] == 0.98
        and recovered["x_m"] == 1.0
        and not recovered.get("calibration_mismatch_injected")
    )
    return {
        "fault_id": "vision.calibration_mismatch",
        "passed": passed,
        "baseline_score": base.get("score") if base else None,
        "fault_on_score": fault_on.get("score") if fault_on else None,
        "recovered_score": recovered.get("score") if recovered else None,
    }


def _scenario_vision_camera_drop(site_map_sha256: str) -> dict[str, Any]:
    ctrl = _new_controller(site_map_sha256)
    raw = {"source_id": "ceiling_north", "x_m": 1.0, "y_m": 2.0, "yaw_rad": 0.1, "score": 0.98}

    base = ctrl.faults.apply_vision_boundary(raw)
    ctrl.faults.enable("vision.camera_drop")
    fault_on = ctrl.faults.apply_vision_boundary(raw)
    ctrl.faults.disable("vision.camera_drop")
    recovered = ctrl.faults.apply_vision_boundary(raw)

    passed = (
        isinstance(base, dict)
        and base.get("source_id") == "ceiling_north"
        and fault_on is None
        and isinstance(recovered, dict)
        and recovered.get("score") == 0.98
    )
    return {
        "fault_id": "vision.camera_drop",
        "passed": passed,
        "baseline_present": base is not None,
        "fault_on_dropped": fault_on is None,
        "recovered_present": recovered is not None,
    }


def _scenario_bridge_seq_conflict_409(site_map_sha256: str) -> dict[str, Any]:
    ctrl = _new_controller(site_map_sha256)
    ctrl.handle_s3_arrived_settled(robot_id="rosy_45", dx_m=0.0, dy_m=0.0, dyaw_rad=0.0)
    lift_base = ctrl.handle_cargo_lifted_or_dropped(arm_id="arm_s", lifted=True, bilateral_lift=True)
    ctrl.handle_cell_bed_clear(arm_id="arm_s", arm_in_bed_zone=False)
    belt_base = ctrl.advance_cell_stage("ON_BELT")

    ctrl.reset()
    ctrl.handle_s3_arrived_settled(robot_id="rosy_45", dx_m=0.0, dy_m=0.0, dyaw_rad=0.0)
    ctrl.faults.enable("bridge.seq_conflict_409", {"arm_id": "arm_s"})
    lift_on = ctrl.handle_cargo_lifted_or_dropped(arm_id="arm_s", lifted=True, bilateral_lift=True)
    ctrl.faults.disable("bridge.seq_conflict_409")

    lift_off = ctrl.handle_cargo_lifted_or_dropped(arm_id="arm_s", lifted=True, bilateral_lift=True)
    ctrl.handle_cell_bed_clear(arm_id="arm_s", arm_in_bed_zone=False)
    ctrl.advance_cell_stage("ON_BELT")

    ctrl.faults.enable("bridge.seq_conflict_409", {"arm_id": "arm_a"})
    stage_on = ctrl.advance_cell_stage("IN_CELL_AB")
    ctrl.faults.disable("bridge.seq_conflict_409")

    ctrl.advance_cell_stage("IN_CELL_AB")
    shipped = ctrl.advance_cell_stage("ON_SHIP")

    passed = (
        lift_base["accepted"] is True
        and belt_base["accepted"] is True
        and lift_on["accepted"] is False
        and lift_on["status_code"] == 409
        and lift_on["reason"] == "BRIDGE_SEQ_CONFLICT_409:arm_s"
        and lift_on["cargo_state"] == "HANDOFF_AT_S3"
        and lift_off["accepted"] is True
        and stage_on["accepted"] is False
        and stage_on["status_code"] == 409
        and stage_on["reason"] == "BRIDGE_SEQ_CONFLICT_409:arm_a"
        and stage_on["cargo_state"] == "ON_BELT"
        and shipped["accepted"] is True
        and shipped["cargo_state"] == "ON_SHIP"
    )
    return {
        "fault_id": "bridge.seq_conflict_409",
        "passed": passed,
        "lift_fault_reason": lift_on.get("reason"),
        "stage_fault_reason": stage_on.get("reason"),
        "recovered_final_state": shipped.get("cargo_state"),
    }


def _scenario_hub_heartbeat_lag(site_map_sha256: str) -> dict[str, Any]:
    ctrl = _new_controller(site_map_sha256)
    base = ctrl.faults.apply_hub_heartbeat_boundary("rosy_45", 0.5)

    ctrl.faults.enable("hub.heartbeat_lag", {"robot_id": "rosy_45"})
    fault_on = ctrl.faults.apply_hub_heartbeat_boundary("rosy_45", 0.5)

    ctrl.faults.disable("hub.heartbeat_lag")
    recovered = ctrl.faults.apply_hub_heartbeat_boundary("rosy_45", 0.5)

    passed = (
        base["degraded"] is False
        and base["fault_injected"] is False
        and fault_on["degraded"] is True
        and fault_on["fault_injected"] is True
        and recovered["degraded"] is False
        and recovered["fault_injected"] is False
    )
    return {
        "fault_id": "hub.heartbeat_lag",
        "passed": passed,
        "baseline_effective_age_s": base["effective_age_s"],
        "fault_on_effective_age_s": fault_on["effective_age_s"],
        "recovered_degraded": recovered["degraded"],
    }


_SCENARIO_RUNNERS = (
    _scenario_pinky_tangled_or_stall,
    _scenario_pinky_s3_brake_unmeasured,
    _scenario_arm_usb_unplugged,
    _scenario_vision_calibration_mismatch,
    _scenario_vision_camera_drop,
    _scenario_bridge_seq_conflict_409,
    _scenario_hub_heartbeat_lag,
)


def run_all_fault_scenarios(site_map_sha256: str = "a" * 64) -> dict[str, Any]:
    """Run baseline -> fault ON -> fault OFF recovery checks for all 7 D-1088 faults."""
    scenarios = [runner(site_map_sha256) for runner in _SCENARIO_RUNNERS]
    covered = {s["fault_id"] for s in scenarios}
    all_passed = all(s["passed"] for s in scenarios) and covered == set(ALLOWED_FAULTS)
    return {
        "schema": RECEIPT_SCHEMA,
        "all_passed": all_passed,
        "fault_count": len(ALLOWED_FAULTS),
        "scenarios": scenarios,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--site-map-sha256", default="a" * 64)
    parser.add_argument("--out", type=Path, default=None)
    args = parser.parse_args(argv)

    receipt = run_all_fault_scenarios(site_map_sha256=args.site_map_sha256)
    encoded = json.dumps(receipt, indent=2, ensure_ascii=False)
    if args.out is not None:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(encoded + "\n", encoding="utf-8", newline="\n")
    print(encoded)
    return 0 if receipt["all_passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
