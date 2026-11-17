#!/usr/bin/env python3
"""Read-only Inspection, Pose-Park & Receipt Stages for Two-Arm OMX Pipeline (`two_arm_stages_readonly.py`).

Single Responsibility:
  - Read-only motor/bus inspection stages (`stage_health`, `stage_preflight`, `stage_gap`, `stage_verify`).
  - Present Follower pose recording (`stage_park`) and stage evidence receipts (`write_receipt`).
"""
from __future__ import annotations

import json
from pathlib import Path
import sys
import time

sys.path.insert(0, str(Path(__file__).resolve().parent))

from guarded_native import BODY, NAMES  # noqa: E402
from two_arm_config import (  # noqa: E402
    ALIGN_TOLERANCE_DEG,
    POSE_SCHEMA,
    gap_degrees,
    load_json,
    read_positions,
)

#: The Follower's commissioning resting cap (PWM Limit). A run may not start above it.
FOLLOWER_RESTING_PWM = 20


def stage_health(arms, *, log) -> dict:
    """Read-only: what every motor reports, including a latched hardware error."""
    rows = []
    for arm in arms:
        for role, bus in (("follower", arm.follower_bus), ("leader", arm.leader_bus)):
            rows.append(
                {
                    "arm": arm.arm_id,
                    "role": role,
                    "motors": {
                        name: {
                            "id": bus.motors[name].id,
                            "hardware_error": bus.read("Hardware_Error_Status", name),
                            "torque": bus.read("Torque_Enable", name),
                            "temperature": bus.read("Present_Temperature", name),
                            "position": bus.read("Present_Position", name),
                        }
                        for name in NAMES
                    },
                }
            )
    log(stage="health", buses=rows)
    return {"stage": "health", "buses": rows}


def stage_preflight(arms, *, config: dict, log) -> dict:
    """Every arm must be at rest and identifiable before the pipeline owns the buses."""
    rows = []
    for arm in arms:
        follower, leader = arm.follower_bus, arm.leader_bus
        for name in NAMES:
            for role, bus in (("follower", follower), ("leader", leader)):
                if bus.read("Torque_Enable", name):
                    raise ValueError(f"{arm.arm_id} {role} {name}: torque is ON; the pipeline needs a resting arm")
                error = bus.read("Hardware_Error_Status", name)
                if error:
                    raise ValueError(
                        f"{arm.arm_id} {role} {name}: hardware error {error} latched; "
                        "power-cycle that arm and re-run preflight"
                    )
        caps = {name: follower.read("PWM_Limit", name) for name in BODY}
        if any(value != FOLLOWER_RESTING_PWM for value in caps.values()):
            raise ValueError(
                f"{arm.arm_id}: follower caps {caps} are not the resting baseline "
                f"({FOLLOWER_RESTING_PWM}); lower them with commissioning_limits.py first"
            )
        rows.append(
            {
                "arm": arm.arm_id,
                "follower_ids": {name: follower.motors[name].id for name in NAMES},
                "leader_ids": {name: leader.motors[name].id for name in NAMES},
                "follower_pwm_limits": caps,
                "leader_pwm_limits": {name: leader.read("PWM_Limit", name) for name in BODY},
                "leader_current_limits": {name: leader.read("Current_Limit", name) for name in BODY},
            }
        )
    log(stage="preflight", arms=rows)
    return {"stage": "preflight", "arms": rows}


def stage_gap(arms, *, log) -> dict:
    """Read the Leader and Follower poses and the gap between them. Nothing is commanded."""
    rows = []
    for arm in arms:
        leader = read_positions(arm.leader_bus)
        follower = read_positions(arm.follower_bus)
        rows.append(
            {
                "arm": arm.arm_id,
                "leader": leader,
                "follower": follower,
                "gap_degrees": gap_degrees(leader, follower),
            }
        )
    log(stage="gap", arms=rows)
    return {"stage": "gap", "arms": rows}


def stage_park(arms, *, poses_path, log) -> dict:
    """Write the Followers' present pose into the pose file as the park pose."""
    poses = load_json(poses_path) if Path(poses_path).exists() else {"schema": POSE_SCHEMA, "poses": {}}
    table = poses.setdefault("poses", {})
    rows = []
    for arm in arms:
        follower = read_positions(arm.follower_bus)
        table.setdefault(arm.arm_id, {})["park"] = {name: int(follower[name]) for name in BODY}
        rows.append({"arm": arm.arm_id, "park": table[arm.arm_id]["park"]})
    poses["schema"] = POSE_SCHEMA
    Path(poses_path).write_text(json.dumps(poses, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    log(stage="park", poses=str(poses_path), arms=rows)
    return {"stage": "park", "poses": str(poses_path), "arms": rows}


def stage_verify(arms, *, config: dict, log) -> dict:
    """The gap after the drive, against the tolerance."""
    tolerance = float(config.get("limits", {}).get("tolerance_deg", ALIGN_TOLERANCE_DEG))
    rows = []
    for arm in arms:
        leader = read_positions(arm.leader_bus)
        follower = read_positions(arm.follower_bus)
        gap = gap_degrees(leader, follower)
        worst = max(BODY, key=lambda name: abs(gap[name]))
        rows.append(
            {
                "arm": arm.arm_id,
                "gap_degrees": gap,
                "worst_joint": worst,
                "within_tolerance": abs(gap[worst]) <= tolerance,
            }
        )
    log(stage="verify", tolerance_deg=tolerance, arms=rows)
    return {"stage": "verify", "tolerance_deg": tolerance, "arms": rows}


def write_receipt(directory, stage: str, payload: dict) -> Path:
    """One receipt per stage: the facts of the run, not a promise about it."""
    directory = Path(directory)
    directory.mkdir(parents=True, exist_ok=True)
    stamp = time.strftime("%Y%m%dT%H%M%S")
    path = directory / f"{stage}-{stamp}.json"
    counter = 2
    while path.exists():
        path = directory / f"{stage}-{stamp}-{counter}.json"
        counter += 1
    body = dict(payload)
    body["recorded_at"] = time.strftime("%Y-%m-%dT%H:%M:%S%z")
    path.write_text(json.dumps(body, indent=2, sort_keys=True, default=str) + "\n", encoding="utf-8")
    return path
