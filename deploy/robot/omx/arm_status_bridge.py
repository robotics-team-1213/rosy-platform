#!/usr/bin/env python3
"""Arm S joint positions and guard motor health to Fleet's existing workcell observation ingest.

Arm S has no ROS graph, so the workcell observation bridge cannot subscribe to its joint states.
chunk_runner writes chunk-io/live.json about twice a second; this bridge converts the follower's
LeRobot units to radians (calibration range, tick 2048 = 0 rad) and posts ArmObservation through the
bridge's own ArmSender (verified TLS, token header, epoch/sequence, 409 recovery). Read only: it never
commands the arm. Needs a source entry and token for arm S in the Fleet manifest (site setting).

With --health-file the guard's rosy.motor-health.v1 snapshot (chunk_runner's MotorHealth monitor at
ROSY_OMX_MONITOR_STATE; start the runner with ROSY_OMX_MONITOR_OWNER=<arm_id>) rides on the same
observation: per-motor PWM, temperature, voltage and following error while active, and the guard's
fault or session end with its stop reasons, sent once without positions after the runner stops.
Fleet's Cell page shows it in the arm's motor health panel.

  arm_status_bridge.py --live chunk-io/live.json --fleet-url https://<fleet> --source-id omx_arm_s \\
      --token-env ROSY_ARM_S_TOKEN [--ca-file ca.pem] [--calibration omx_follower_arm.json] \\
      [--arm-id omx_s --health-file /abs/motor-health-current.json]
"""
from __future__ import annotations

import argparse
import json
import math
import os
import ssl
import time
from pathlib import Path

JOINTS = ["joint1", "joint2", "joint3", "joint4", "joint5", "gripper_joint_1"]
MOTORS = ["shoulder_pan", "shoulder_lift", "elbow_flex", "wrist_flex", "wrist_roll", "gripper"]
TICKS = 4096
STALE_S = 2.0  # a live file older than this means the runner stopped; positions are not re-sent


def to_radians(state, calibration=None) -> dict:
    """LeRobot follower units -> Dynamixel radians: body joints use -100..100, the gripper 0..100."""
    positions = {}
    for joint, motor, value in zip(JOINTS, MOTORS, state):
        cal = (calibration or {}).get(motor, {})
        lo, hi = cal.get("range_min", 0), cal.get("range_max", 4095)
        raw = (value / 100 if motor == "gripper" else (value + 100) / 200) * (hi - lo) + lo
        positions[joint] = round(raw * 2 * math.pi / TICKS - math.pi, 5)
    return positions


class Sample:  # the shape ArmSender.send() reads
    def __init__(self, captured_at, positions, motor_health=None):
        self.captured_at, self.value, self.motor_health = captured_at, positions, motor_health


def fresh_sample(row, last_t, now, calibration=None):
    """A sample to send, or None when the live row is stale, not newer than the last sent, or empty."""
    t = row.get("t")
    if not isinstance(t, (int, float)) or not row.get("state") or now - t > STALE_S or (last_t and t <= last_t):
        return None
    return Sample(t, to_radians(row["state"], calibration))


def arm_health(path, arm_id, now):
    """(MotorHealthResponse, event time) in Fleet's registered names, or (None, None) when absent or partial.

    The monitor names follower motors by LeRobot motor with group "follower"; Fleet wants the registered
    joint, the arm id as group, every joint covered and IDs 11-16, or it refuses the whole observation
    (positions included). Anything else is dropped here so the positions still go."""
    from core_common.motor_health import read_motor_health_snapshot

    try:
        health, event = read_motor_health_snapshot(path, arm_id, now=now)
    except (OSError, ValueError, TypeError, KeyError, OverflowError, RecursionError):
        return None, None  # no snapshot yet, or another owner's: absence is never reported as healthy
    by_name = {m.joint: m for m in health.motors}
    if len(health.motors) != len(MOTORS) or set(by_name) != set(MOTORS):
        return None, None
    motors = [by_name[motor].model_copy(update={"joint": joint, "group": arm_id})
              for joint, motor in zip(JOINTS, MOTORS)]
    if any(m.id != 11 + i for i, m in enumerate(motors)):
        return None, None
    return health.model_copy(update={"motors": motors}), event


def next_sample(row, health, last_t, now, calibration=None):
    """A guard fault or session end once (no positions: the runner has stopped), else fresh positions with health."""
    health, event = health
    if (health is not None and health.status in ("fault", "ended")
            and (not last_t or event > last_t) and now - event <= STALE_S):
        return Sample(event, None, health)
    sample = fresh_sample(row, last_t, now, calibration)
    if sample is not None:
        sample.motor_health = health
    return sample


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--live", type=Path, required=True)
    parser.add_argument("--fleet-url", required=True)
    parser.add_argument("--source-id", required=True)
    parser.add_argument("--token-env", required=True)
    parser.add_argument("--ca-file", type=Path)
    parser.add_argument("--calibration", type=Path)
    parser.add_argument("--period", type=float, default=0.5)
    parser.add_argument("--arm-id", help="registered arm_id: the motor-health owner and group Fleet expects")
    parser.add_argument("--health-file", type=Path, help="absolute motor-health snapshot of the runner's guard")
    args = parser.parse_args(argv)
    if bool(args.arm_id) != bool(args.health_file):
        parser.error("--arm-id and --health-file go together")
    token = os.environ.get(args.token_env)
    if not token:
        raise SystemExit(f"{args.token_env} is not set")
    calibration = json.loads(args.calibration.read_text()) if args.calibration else None
    from workcell_observation_bridge import ArmSender

    sender = ArmSender(args.fleet_url, args.source_id, token, context=ssl.create_default_context(cafile=args.ca_file))
    last_t = None
    while True:
        try:
            now = time.time()
            health = arm_health(args.health_file, args.arm_id, now) if args.health_file else (None, None)
            try:
                row = json.loads(args.live.read_text())
            except (OSError, ValueError):
                row = {}  # the runner exited; its terminal health can still go
            sample = next_sample(row, health, last_t, now, calibration)
            if sample is not None:
                sender.send(sample)
                last_t = sample.captured_at
        except (OSError, ValueError) as error:  # a refused post never stops the bridge
            print(json.dumps({"error": str(error)[:200], "t": round(time.time(), 3)}), flush=True)
        time.sleep(args.period)


if __name__ == "__main__":
    main()
