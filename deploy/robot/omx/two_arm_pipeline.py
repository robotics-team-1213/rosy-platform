#!/usr/bin/env python3
"""Two-arm OMX pipeline: drive the Leader as a commanded reference and mirror it on the Followers.

The Leader is the device a person holds, so the pipeline never drives it without an explicit
hands-off attestation, and it drives it only through `leader_actuator.py`. The Followers keep
their own guard (`guarded_native.NativeJointMotion`): the pipeline supplies the target and the
Leader's motion, never a second writer on a bus. Configuration, caps and gains live in
`two_arm_config.py`.

Stages, each run on its own and each writing a receipt:

  health     read-only motor report: per-joint hardware error, torque, temperature, position.
  preflight  identity, rest state, resting caps, bus ownership. Nothing is commanded.
  gap        read-only Leader/Follower gap per joint.
  park       write the Followers' present pose into the pose file as the park pose.
  align      Follower -> Leader pose with the Follower guard; a blocked joint is reported
             as a load, not as a timeout.
  drive      Leader -> named pose while the Followers mirror it.
  verify     the gap after the drive, against the tolerance.

The pipeline raises the Followers' caps and sets their position gains with torque OFF at the
start of `align`/`drive`, and restores both at the end. A gain is a RAM register, so it must be
restated every run: without an I gain a loaded joint stops short of its goal by a steady-state
error, which is the droop a Follower shows as "almost aligned, PWM well under the cap".

The pipeline owns both buses while it runs. The torque-OFF observers hold the Follower bus
exclusively, so they must be stopped before a run and started again afterwards; the
preflight refuses to continue when another process still holds a port.

  two_arm_pipeline.py --config pipeline.json --stage health
  two_arm_pipeline.py --config pipeline.json --stage preflight
  two_arm_pipeline.py --config pipeline.json --stage gap
  two_arm_pipeline.py --config pipeline.json --stage park
  two_arm_pipeline.py --config pipeline.json --stage align
  two_arm_pipeline.py --config pipeline.json --stage drive --pose park \
      --attest "hands-off:<who>:<iso8601>"
  two_arm_pipeline.py --config pipeline.json --stage verify
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import guarded_native  # noqa: E402
from guarded_native import BODY, NAMES, TURN, normalized  # noqa: E402
from joint_tune import session_lock  # noqa: E402
from leader_actuator import DEFAULT_CURRENT, DEFAULT_PWM, LeaderActuator  # noqa: E402
from two_arm_config import (  # noqa: E402,F401  (configuration, caps and gains; re-exported)
    ALIGN_TOLERANCE_DEG, POSE_SCHEMA, SCHEMA, Arm, close_arm, effective_gains, follower_caps,
    follower_gain_state, follower_gains, follower_limits, gap_degrees, leader_gains,
    leader_gravity_ticks, load_json, open_arm, read_positions, restore_follower_caps,
    restore_follower_gains, set_follower_caps, set_follower_gains, validate_config,
    validate_poses)

STAGES = ("health", "preflight", "gap", "park", "align", "drive", "verify")
#: The Follower's commissioning resting cap (PWM Limit). A run may not start above it.
FOLLOWER_RESTING_PWM = 20
#: The control loop period of the drive stage.
LOOP_S = 1 / 30
#: How long one drive stage may take before it stops and reports where it got to.
DRIVE_TIMEOUT_S = 180.0


def stage_health(arms, *, log) -> dict:
    """Read-only: what every motor reports, including a latched hardware error.

    `preflight` refuses an arm that is not at rest, so it cannot tell a latched error from a
    missing motor. This stage writes nothing and reports the facts instead: it is the first
    thing to run after a failed drive or a power cycle.
    """
    rows = []
    for arm in arms:
        for role, bus in (("follower", arm.follower_bus), ("leader", arm.leader_bus)):
            rows.append({"arm": arm.arm_id, "role": role,
                         "motors": {name: {"id": bus.motors[name].id,
                                           "hardware_error": bus.read("Hardware_Error_Status", name),
                                           "torque": bus.read("Torque_Enable", name),
                                           "temperature": bus.read("Present_Temperature", name),
                                           "position": bus.read("Present_Position", name)}
                                    for name in NAMES}})
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
                    raise ValueError(f"{arm.arm_id} {role} {name}: hardware error {error} latched; "
                                     "power-cycle that arm and re-run preflight")
        caps = {name: follower.read("PWM_Limit", name) for name in BODY}
        if any(value != FOLLOWER_RESTING_PWM for value in caps.values()):
            raise ValueError(f"{arm.arm_id}: follower caps {caps} are not the resting baseline "
                             f"({FOLLOWER_RESTING_PWM}); lower them with commissioning_limits.py first")
        rows.append({"arm": arm.arm_id,
                     "follower_ids": {name: follower.motors[name].id for name in NAMES},
                     "leader_ids": {name: leader.motors[name].id for name in NAMES},
                     "follower_pwm_limits": caps,
                     "leader_pwm_limits": {name: leader.read("PWM_Limit", name) for name in BODY},
                     "leader_current_limits": {name: leader.read("Current_Limit", name) for name in BODY}})
    log(stage="preflight", arms=rows)
    return {"stage": "preflight", "arms": rows}


def stage_gap(arms, *, log) -> dict:
    """Read the Leader and Follower poses and the gap between them. Nothing is commanded."""
    rows = []
    for arm in arms:
        leader = read_positions(arm.leader_bus)
        follower = read_positions(arm.follower_bus)
        rows.append({"arm": arm.arm_id, "leader": leader, "follower": follower,
                     "gap_degrees": gap_degrees(leader, follower)})
    log(stage="gap", arms=rows)
    return {"stage": "gap", "arms": rows}


def stage_park(arms, *, poses_path, log) -> dict:
    """Write the Followers' present pose into the pose file as the park pose.

    The park pose is the pose the arms already hold, so a later drive asks the Leader to
    come to a pose the Follower can reach without moving far.
    """
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


def _guard(arm: Arm, label: str, monitor=None, offsets=None, clock=time.monotonic):
    """The Follower guard for one arm; the Leader stays the target, never a writer."""
    return guarded_native.NativeJointMotion(arm.follower_bus, arm.leader_bus, body_only=True,
                                        label=label, monitor=monitor, offsets=offsets, clock=clock)


def _diagnosis(arm: Arm, guard, last: dict, error=None) -> dict:
    """Say which joint stopped the Follower and whether it was load or a slow ramp.

    The guard names the joint it stopped; that joint is the answer even when another
    joint still holds the larger gap, which is only the next target.
    """
    leader = read_positions(arm.leader_bus)
    follower = read_positions(arm.follower_bus)
    gap = gap_degrees(leader, follower)
    pwm = last.get("pwm", {})
    cap = last.get("cap", {})
    named = None
    if error is not None:
        text = str(error)
        named = next((name for name in BODY if f"{name}:" in text), None)
    loaded = [name for name, value in pwm.items()
              if value is not None and cap.get(name) and abs(value) >= 0.5 * cap[name]]
    joint = named or (max(loaded, key=lambda name: abs(pwm[name])) if loaded else None) \
        or max(BODY, key=lambda name: abs(gap[name]))
    return {"joint": joint, "stop_joint": named, "gap_degrees": gap,
            "pwm": pwm.get(joint), "pwm_limit": cap.get(joint), "pwm_limits": cap,
            "reason": "blocked_by_load" if joint in loaded else "alignment_timeout",
            "action": ("support the arm so the joint is not loaded, then run align again"
                       if joint in loaded else "bring the Leader closer to the Follower pose and run align again")}


def stage_align(arms, *, config: dict, log, clock=time.monotonic, sleep=time.sleep,
                timeout_s=DRIVE_TIMEOUT_S) -> dict:
    """Move every Follower onto the Leader's pose with the Follower guard.

    The guard owns the ramp, the caps and the stop rules. This stage only reports where the
    run stopped, so a Follower that is loaded on the table is diagnosed instead of timing out.
    """
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
                for name in BODY:
                    last["pwm"][name] = arm.follower_bus.read("Present_PWM", name)
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
        row = {"arm": arm.arm_id, "aligned": guard.tracking,
               "pwm_limits": guard.pwm_limits,
               "p_gains": {name: values["p"] for name, values in effective_gains(saved_gains, gains).items()},
               "gap_degrees": gap_degrees(read_positions(arm.leader_bus), read_positions(arm.follower_bus))}
        rows.append(row)
        log(stage="align", **row)
    return {"stage": "align", "arms": rows}


def _end_follower(arm: Arm, saved: dict, saved_gains: dict | None = None,
                  applied_gains: dict | None = None) -> list[str]:
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


def stage_drive(arms, *, poses, pose_name, attestation, config: dict, log,
                clock=time.monotonic, sleep=time.sleep, timeout_s=DRIVE_TIMEOUT_S) -> dict:
    """Drive the Leaders to a named pose while the Followers mirror them.

    The Leader is only driven after an explicit hands-off attestation: it is the device a
    person holds. The Followers follow through their own guard, so the pipeline never writes
    a Follower goal itself.

    The Followers copy the Leader's *relative* motion: the guard's offset is seeded with the
    difference the arms started with, so a Follower that already holds its pose does not jump
    to the Leader's absolute pose and the drive starts from a zero error.
    """
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
            actuator.admit(pwm=pwm, current=current, gains=leader_gains_for_run,
                           gravity=leader_gravity_for_run)
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
                actuator.check_effort(read_positions(arm.leader_bus))
                guard = guards[arm.arm_id]
                prepared = guard.prepare(_action(arm))
                guard.commit(prepared)
                present = read_positions(arm.leader_bus)
                if any(abs(present[name] - target[name]) > tolerance * TURN / 360 for name in BODY):
                    reached = False
                # The tolerance is the acceptance band; the ramp still has to settle on the
                # pose, so a drive does not stop a few degrees short of it.
                if any(abs(actuator.command[name] - target[name]) > 1 for name in BODY):
                    settled = False
            if reached and settled:
                break
            sleep(LOOP_S)
        else:
            raise RuntimeError(f"drive did not reach the pose {pose_name} within {timeout_s}s")
        for arm in arms:
            rows.append({"arm": arm.arm_id, "pose": pose_name,
                         "leader": read_positions(arm.leader_bus),
                         "follower": read_positions(arm.follower_bus),
                         "pwm_limits": guards[arm.arm_id].pwm_limits,
                         "p_gains": {name: values["p"] for name, values
                                     in effective_gains(saved_gains[arm.arm_id], gains).items()},
                         "leader_p_gains": {
                             name: leader_gains_for_run.get(name, {}).get(
                                 "p", actuators[arm.arm_id].saved[name]["Position_P_Gain"])
                             for name in BODY},
                         "leader_gravity_ticks": {name: leader_gravity_for_run.get(name, 0)
                                                  for name in BODY},
                         "tracking": guards[arm.arm_id].tracking})
    finally:
        for arm in arms:
            failures = _end_follower(arm, saved_caps[arm.arm_id], saved_gains.get(arm.arm_id), gains)
            failures.extend(actuators[arm.arm_id].restore())
            if failures:
                log(stage="drive", arm=arm.arm_id, restore_failures=failures)
                raise RuntimeError(f"{arm.arm_id}: the arms did not end safely: {failures}")
    log(stage="drive", pose=pose_name, attestation=attestation, arms=rows)
    return {"stage": "drive", "pose": pose_name, "attestation": attestation, "arms": rows}


def stage_verify(arms, *, config: dict, log) -> dict:
    """The gap after the drive, against the tolerance."""
    tolerance = float(config.get("limits", {}).get("tolerance_deg", ALIGN_TOLERANCE_DEG))
    rows = []
    for arm in arms:
        leader = read_positions(arm.leader_bus)
        follower = read_positions(arm.follower_bus)
        gap = gap_degrees(leader, follower)
        worst = max(BODY, key=lambda name: abs(gap[name]))
        rows.append({"arm": arm.arm_id, "gap_degrees": gap, "worst_joint": worst,
                     "within_tolerance": abs(gap[worst]) <= tolerance})
    log(stage="verify", tolerance_deg=tolerance, arms=rows)
    return {"stage": "verify", "tolerance_deg": tolerance, "arms": rows}


# --------------------------------------------------------------------- receipts


def write_receipt(directory, stage: str, payload: dict) -> Path:
    """One receipt per stage: the facts of the run, not a promise about it.

    Two runs of the same stage in one second are two pieces of evidence, so the second one
    gets a counter instead of overwriting the first.
    """
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
            payload = stage_drive(arms, poses=poses, pose_name=args.pose, attestation=args.attest,
                                  config=config, log=log, timeout_s=args.timeout_s)
        elif args.stage == "verify":
            payload = stage_verify(arms, config=config, log=log)
        else:  # pragma: no cover - argparse already restricts the choices
            raise SystemExit(f"unknown stage {args.stage}")
        rows.append(payload)
    except BaseException as exc:
        # A stage that stops mid-run still has to say where: the receipt is evidence of the
        # failure, and the same error is re-raised so the caller's exit code does not change.
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
            receipt = write_receipt(args.receipts, args.stage,
                                    {"stage": args.stage, "result": rows, "error": failure})
        except Exception as exc:  # an unwritable receipt directory must not hide the failure
            log(stage="receipt", error=str(exc))
        else:
            log(stage="receipt", path=str(receipt))


if __name__ == "__main__":
    main()
