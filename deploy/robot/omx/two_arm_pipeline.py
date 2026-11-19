#!/usr/bin/env python3
"""Two-arm OMX pipeline: drive the Leader as a commanded reference and mirror it on the Followers.

Single Responsibility:
  - Active closed-loop Follower alignment (`stage_align`) and synchronized Leader/Follower motion (`stage_drive`).
  - Read-only inspection stages (`stage_health`, `stage_preflight`, `stage_gap`, `stage_park`, `stage_verify`)
    and receipt writing (`write_receipt`) live in `two_arm_stages_readonly.py` and are re-exported here unchanged.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys
import time

sys.path.insert(0, str(Path(__file__).resolve().parent))

import guarded_native  # noqa: E402
from guarded_native import BODY, NAMES, TURN, normalized  # noqa: E402,F401
from joint_tune import session_lock  # noqa: E402
from leader_actuator import DEFAULT_CURRENT, DEFAULT_PWM, LeaderActuator  # noqa: E402
from two_arm_config import (  # noqa: E402,F401  (configuration, caps and gains; re-exported)
    ALIGN_TOLERANCE_DEG,
    POSE_SCHEMA,
    SCHEMA,
    Arm,
    close_arm,
    effective_gains,
    follower_caps,
    follower_gain_state,
    follower_gains,
    follower_limits,
    gap_degrees,
    leader_gains,
    leader_gravity_ticks,
    load_json,
    open_arm,
    read_positions,
    restore_follower_caps,
    restore_follower_gains,
    set_follower_caps,
    set_follower_gains,
    validate_config,
    validate_poses,
)
from two_arm_stages_readonly import (  # noqa: E402,F401  (re-exported)
    FOLLOWER_RESTING_PWM,
    stage_gap,
    stage_health,
    stage_park,
    stage_preflight,
    stage_verify,
    write_receipt,
)

STAGES = ("health", "preflight", "gap", "park", "align", "drive", "verify")
#: The control loop period of the drive stage.
LOOP_S = 1 / 30
#: How long one drive stage may take before it stops and reports where it got to.
DRIVE_TIMEOUT_S = 180.0


def _guard(arm: Arm, label: str, monitor=None, offsets=None, clock=time.monotonic):
    """The Follower guard for one arm; the Leader stays the target, never a writer."""
    return guarded_native.NativeJointMotion(
        arm.follower_bus, arm.leader_bus, body_only=True, label=label, monitor=monitor, offsets=offsets, clock=clock
    )


def _diagnosis(arm: Arm, guard, last: dict, error=None) -> dict:
    """Say which joint stopped the Follower and whether it was load or a slow ramp."""
    leader = read_positions(arm.leader_bus)
    follower = read_positions(arm.follower_bus)
    gap = gap_degrees(leader, follower)
    pwm = last.get("pwm", {})
    cap = last.get("cap", {})
    named = None
    if error is not None:
        text = str(error)
        named = next((name for name in BODY if f"{name}:" in text), None)
    loaded = [
        name for name, value in pwm.items() if value is not None and cap.get(name) and abs(value) >= 0.5 * cap[name]
    ]
    joint = (
        named
        or (max(loaded, key=lambda name: abs(pwm[name])) if loaded else None)
        or max(BODY, key=lambda name: abs(gap[name]))
    )
    return {
        "joint": joint,
        "stop_joint": named,
        "gap_degrees": gap,
        "pwm": pwm.get(joint),
        "pwm_limit": cap.get(joint),
        "pwm_limits": cap,
        "reason": "blocked_by_load" if joint in loaded else "alignment_timeout",
        "action": (
            "support the arm so the joint is not loaded, then run align again"
            if joint in loaded
            else "bring the Leader closer to the Follower pose and run align again"
        ),
    }


def stage_align(
    arms, *, config: dict, log, clock=time.monotonic, sleep=time.sleep, timeout_s=DRIVE_TIMEOUT_S
) -> dict:
    """Move every Follower onto the Leader's pose with the Follower guard."""
    limits = follower_limits(config)
    gains = follower_gains(config)
    rows = []
    for arm in arms:
        saved = follower_caps(arm)
        saved_gains = follower_gain_state(arm)
        set_follower_caps(arm, saved, limits)
        set_follower_gains(arm, gains)
        guard = _guard(arm, arm.arm_id, clock=clock)
        last = {"pwm": {}, "cap": {}}
        started = clock()
        action = _action(arm)
        error = None
        try:
            while clock() - started < timeout_s:
                try:
                    prepared = guard.prepare(action)
                    guard.commit(prepared)
                except ValueError as exc:
                    error = exc
                    break
                pwms = guard._read_body_pwm()
                for name in BODY:
                    last["pwm"][name] = pwms[name]
                    last["cap"][name] = guard.pwm_limits.get(name)
                if guard.tracking:
                    break
                sleep(LOOP_S)
        finally:
            failures = _end_follower(arm, saved, saved_gains, gains)
            if failures:
                log(stage="align", arm=arm.arm_id, restore_failures=failures)
                raise RuntimeError(f"{arm.arm_id}: the Follower did not end safely: {failures}")
        if error is not None:
            diagnosis = _diagnosis(arm, guard, last, error=error)
            diagnosis["error"] = str(error)
            log(stage="align", arm=arm.arm_id, **diagnosis)
            raise RuntimeError(f"align failed: {diagnosis}")
        row = {
            "arm": arm.arm_id,
            "aligned": guard.tracking,
            "pwm_limits": guard.pwm_limits,
            "p_gains": {name: values["p"] for name, values in effective_gains(saved_gains, gains).items()},
            "gap_degrees": gap_degrees(read_positions(arm.leader_bus), read_positions(arm.follower_bus)),
        }
        rows.append(row)
        log(stage="align", **row)
    return {"stage": "align", "arms": rows}


def _end_follower(
    arm: Arm, saved: dict, saved_gains: dict | None = None, applied_gains: dict | None = None
) -> list[str]:
    """Torque OFF on the Follower and its caps and gains back to the values that were found."""
    failures = []
    try:
        guarded_native.torque_off(arm.follower_bus)
    except Exception as exc:
        failures.append(f"torque OFF: {exc}")
    if applied_gains:
        failures.extend(restore_follower_gains(arm, saved_gains, applied_gains))
    failures.extend(restore_follower_caps(arm, saved))
    return failures


def _action(arm: Arm) -> dict:
    """The action shape the guard expects; the target itself comes from the Leader readback."""
    raw = read_positions(arm.leader_bus)
    return normalized(arm.leader_bus, raw)


def stage_drive(
    arms,
    *,
    poses,
    pose_name,
    attestation,
    config: dict,
    log,
    clock=time.monotonic,
    sleep=time.sleep,
    timeout_s=DRIVE_TIMEOUT_S,
) -> dict:
    """Drive the Leaders to a named pose while the Followers mirror them."""
    if not attestation or not attestation.startswith("hands-off:"):
        raise ValueError("the drive stage needs --attest 'hands-off:<who>:<iso8601>'")
    validate_poses(poses, {arm.arm_id: arm for arm in arms})
    targets = {}
    for arm in arms:
        named = poses["poses"].get(arm.arm_id, {})
        if pose_name not in named:
            raise ValueError(f"{arm.arm_id}: the pose file has no pose named {pose_name}")
        targets[arm.arm_id] = named[pose_name]
    drive = config.get("leader_drive", {})
    pwm = int(drive.get("pwm", DEFAULT_PWM))
    current = int(drive.get("current", DEFAULT_CURRENT))
    leader_gains_for_run = leader_gains(config)
    leader_gravity_for_run = leader_gravity_ticks(config)
    follower_limits_for_run = follower_limits(config)
    gains = follower_gains(config)
    tolerance = float(config.get("limits", {}).get("tolerance_deg", ALIGN_TOLERANCE_DEG))
    guards, actuators = {}, {}
    saved_caps, saved_gains = {}, {}
    rows = []
    try:
        for arm in arms:
            saved_caps[arm.arm_id] = follower_caps(arm)
            saved_gains[arm.arm_id] = follower_gain_state(arm)
            set_follower_caps(arm, saved_caps[arm.arm_id], follower_limits_for_run)
            set_follower_gains(arm, gains)
            leader_start = read_positions(arm.leader_bus)
            follower_start = read_positions(arm.follower_bus)
            offsets = {name: follower_start[name] - leader_start[name] for name in BODY}
            guards[arm.arm_id] = _guard(arm, arm.arm_id, offsets=offsets, clock=clock)
            actuator = LeaderActuator(arm.leader_bus, clock=clock, log=log, label=f"{arm.arm_id}_leader")
            actuator.admit(pwm=pwm, current=current, gains=leader_gains_for_run, gravity=leader_gravity_for_run)
            actuator.enable()
            actuator.seed(leader_start)
            actuators[arm.arm_id] = actuator
        started = clock()
        last = started
        while clock() - started < timeout_s:
            now = clock()
            elapsed = max(LOOP_S, min(0.1, now - last))
            last = now
            reached = True
            settled = True
            for arm in arms:
                actuator = actuators[arm.arm_id]
                target = targets[arm.arm_id]
                command = actuator.step(target, elapsed)
                actuator.write(command)
                present = read_positions(arm.leader_bus)
                actuator.check_effort(present)
                guard = guards[arm.arm_id]
                prepared = guard.prepare(normalized(arm.leader_bus, present))
                guard.commit(prepared)
                if any(abs(present[name] - target[name]) > tolerance * TURN / 360 for name in BODY):
                    reached = False
                if any(abs(actuator.command[name] - target[name]) > 1 for name in BODY):
                    settled = False
            if reached and settled:
                break
            sleep(LOOP_S)
        else:
            raise RuntimeError(f"drive did not reach the pose {pose_name} within {timeout_s}s")
        for arm in arms:
            rows.append(
                {
                    "arm": arm.arm_id,
                    "pose": pose_name,
                    "leader": read_positions(arm.leader_bus),
                    "follower": read_positions(arm.follower_bus),
                    "pwm_limits": guards[arm.arm_id].pwm_limits,
                    "p_gains": {
                        name: values["p"] for name, values in effective_gains(saved_gains[arm.arm_id], gains).items()
                    },
                    "leader_p_gains": {
                        name: leader_gains_for_run.get(name, {}).get(
                            "p", actuators[arm.arm_id].saved[name]["Position_P_Gain"]
                        )
                        for name in BODY
                    },
                    "leader_gravity_ticks": {name: leader_gravity_for_run.get(name, 0) for name in BODY},
                    "tracking": guards[arm.arm_id].tracking,
                }
            )
    finally:
        for arm in arms:
            failures = _end_follower(arm, saved_caps[arm.arm_id], saved_gains.get(arm.arm_id), gains)
            failures.extend(actuators[arm.arm_id].restore())
            if failures:
                log(stage="drive", arm=arm.arm_id, restore_failures=failures)
                raise RuntimeError(f"{arm.arm_id}: the arms did not end safely: {failures}")
    log(stage="drive", pose=pose_name, attestation=attestation, arms=rows)
    return {"stage": "drive", "pose": pose_name, "attestation": attestation, "arms": rows}


def parse(argv=None):
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--config", required=True, type=Path)
    parser.add_argument("--stage", required=True, choices=STAGES)
    parser.add_argument("--pose", help="the named pose the drive stage aims at")
    parser.add_argument("--attest", help="'hands-off:<who>:<iso8601>'; the Leader is only driven with it")
    parser.add_argument("--receipts", type=Path, default=Path("pipeline-receipts"))
    parser.add_argument("--poses", type=Path, help="the pose file the park stage writes and the drive stage reads")
    parser.add_argument("--timeout-s", type=float, default=DRIVE_TIMEOUT_S)
    return parser.parse_args(argv)


def main(argv=None):
    args = parse(argv)
    config = load_json(args.config)
    validate_config(config)
    poses_path = args.poses or Path(args.config).parent / "two-arm-poses.json"
    rows = []

    def log(**row):
        row["t"] = round(time.time(), 3)
        print(json.dumps(row, default=str), flush=True)

    arms = []
    failure = None
    lock = session_lock()
    try:
        for arm_id, arm_config in config["arms"].items():
            arms.append(open_arm(arm_id, arm_config["follower"], arm_config["leader"]))
        if args.stage == "health":
            payload = stage_health(arms, log=log)
        elif args.stage == "preflight":
            payload = stage_preflight(arms, config=config, log=log)
        elif args.stage == "gap":
            payload = stage_gap(arms, log=log)
        elif args.stage == "park":
            payload = stage_park(arms, poses_path=poses_path, log=log)
        elif args.stage == "align":
            payload = stage_align(arms, config=config, log=log, timeout_s=args.timeout_s)
        elif args.stage == "drive":
            if not args.pose:
                raise SystemExit("the drive stage needs --pose")
            poses = load_json(poses_path)
            payload = stage_drive(
                arms,
                poses=poses,
                pose_name=args.pose,
                attestation=args.attest,
                config=config,
                log=log,
                timeout_s=args.timeout_s,
            )
        elif args.stage == "verify":
            payload = stage_verify(arms, config=config, log=log)
        else:  # pragma: no cover
            raise SystemExit(f"unknown stage {args.stage}")
        rows.append(payload)
    except BaseException as exc:
        failure = f"{type(exc).__name__}: {exc}"
        raise
    finally:
        for arm in arms:
            try:
                close_arm(arm)
            except Exception as exc:
                log(stage="close", arm=arm.arm_id, error=str(exc))
        lock.close()
        try:
            receipt = write_receipt(args.receipts, args.stage, {"stage": args.stage, "result": rows, "error": failure})
        except Exception as exc:
            log(stage="receipt", error=str(exc))
        else:
            log(stage="receipt", path=str(receipt))


if __name__ == "__main__":
    main()
