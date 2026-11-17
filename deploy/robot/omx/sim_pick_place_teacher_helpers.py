"""Teacher Contact, Clearance & Watchdog Evidence Helpers (`sim_pick_place_teacher_helpers.py`).

Single Responsibility:
  - Serialize owner watchdog observation (`teacher_watchdog_evidence`).
  - Compute contact hold target (`contact_hold_target`) and verify grasp contact (`grasp_contact_reached`).
  - Compute place clearance pose (`teacher_place_pose`) and pre-detach release clearance evidence (`release_clearance_evidence`).
"""
from __future__ import annotations

from dataclasses import asdict, replace
import json
import math
from pathlib import Path
import sys

_HERE = str(Path(__file__).resolve().parent)
if _HERE not in sys.path:
    sys.path.insert(0, _HERE)

from sim_pick_place_demonstrations import TEACHER_STEP_RAD  # noqa: E402
from sim_policy_trial_evidence import contact_held  # noqa: E402

PLACE_CLEARANCE_M = 0.005


def teacher_watchdog_evidence(owner):
    try:
        from omx_adapter.watchdog_observation import WatchdogObservation

        observation = owner.watchdog_observation
        if observation is None:
            return None
        if type(observation) is not WatchdogObservation:
            raise TypeError("invalid watchdog observation")
        evidence = asdict(observation)
        json.dumps(evidence, allow_nan=False)
        return evidence
    except Exception as exc:
        # Diagnostic failure must preserve the original outcome and shutdown path.
        return {"error": type(exc).__name__}


def contact_hold_target(position, *, close, contact):
    if not contact_held(position, close=close, contact=contact):
        raise RuntimeError("teacher_hold_contact_not_confirmed")
    return max(close, position - TEACHER_STEP_RAD)


def grasp_contact_reached(current, target, *, gripper, close, contact, arm_tolerance):
    if not contact_held(current[gripper], close=close, contact=contact):
        return False
    if any(
        not math.isfinite(current[name]) or not math.isfinite(value) or abs(current[name] - value) > arm_tolerance
        for name, value in target.items()
        if name != gripper
    ):
        raise RuntimeError("teacher_grasp_arm_not_at_target")
    return True


def teacher_place_pose(pose):
    return replace(pose, z=pose.z + PLACE_CLEARANCE_M)


def release_clearance_evidence(observation, tcp, box, goal):
    pose = observation["model_pose_base"]
    roll, pitch = pose["roll_rad"], pose["pitch_rad"]
    half_height = (
        abs(math.sin(pitch)) * box.length
        + abs(math.cos(pitch) * math.sin(roll)) * box.width
        + abs(math.cos(pitch) * math.cos(roll)) * box.height
    ) / 2
    bottom = pose["z_m"] - half_height
    surface = goal[2] - box.height / 2
    clearance = bottom - surface
    if not math.isfinite(clearance) or clearance < PLACE_CLEARANCE_M / 2:
        raise RuntimeError("measured_release_clearance_too_small")
    return dict(
        observation=observation,
        tcp_m=dict(x=tcp.x, y=tcp.y, z=tcp.z),
        object_bottom_z_m=bottom,
        support_surface_z_m=surface,
        clearance_m=clearance,
    )
