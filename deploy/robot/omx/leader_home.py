#!/usr/bin/env python3
"""Guarded OMX Leader Home runner using LeaderActuator (D-846).

Moves only BODY (1..5) under explicit hands-off attestation, keeps gripper (6)
passive, and guarantees torque OFF + register restore on every exit path.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys
import time
import traceback

HERE = Path(__file__).resolve().parent
if str(HERE) not in sys.path:
    sys.path.insert(0, str(HERE))

import guarded_device
from guarded_device import close_device
from joint_tune import no_interrupts, protect_signals
from guarded_native_mount import check_mount
from guarded_native_cli import leader_mount
from leader_actuator import (
    BODY, DEFAULT_CURRENT, DEFAULT_PWM, RATE_DEG_S, TICKS_PER_DEGREE, TURN, LeaderActuator, validate_motion_limits)

DEFAULT_GAINS = {n: {"p": 1200, "i": 100} for n in BODY}
# a lighter Leader resting on its stand holds a small offset by itself; driving lift against gravity for less than this stalls at the PWM limit
KEEP_DEG = 30
# the Follower's resting pose; pan and roll carry no weight, so any offset moves onto the Follower.
MAX_TRAVEL_DEG = 100  # per joint, one automatic Leader move
GRAVITY_JOINTS = ("shoulder_lift", "elbow_flex", "wrist_flex")
HOME_RATE_DEG_S = 20.0
HOME_ACCEL_DEG_S2 = 80.0
# the Leader may lag its last command by this much; more means it is blocked or held, so no further command is sent
MAX_TRACK_DEG = 5.0
# What the last move_leader_home cleanup found, for the final JSON line of a failed run (the parent reads it).
_END = {"torque_off_confirmed": True, "restore_failures": []}


def _load_teleop_cfg(config_path: Path, arm: str) -> dict:
    cfg = json.loads(config_path.read_text(encoding="utf-8-sig"))
    teleop = cfg.get("teleop")
    if not isinstance(teleop, dict):
        raise ValueError(f"{config_path.name}: teleop 설정이 없습니다")
    if teleop.get("type") == "bi_omx_leader" and arm in ("arm_a", "arm_b"):
        sub = teleop.get(arm)
        if not isinstance(sub, dict):
            raise ValueError(f"{config_path.name}: teleop.{arm} 설정이 없습니다")
        return sub
    return teleop


def _connect_leader(teleop_cfg: dict):
    from lerobot.teleoperators import make_teleoperator_from_config
    from lerobot.teleoperators.omx_leader.config_omx_leader import OmxLeaderConfig

    cfg = OmxLeaderConfig(
        id=str(teleop_cfg.get("id") or "omx_leader_arm"),
        port=str(teleop_cfg["port"]),
    )
    leader = make_teleoperator_from_config(cfg)
    guarded_device.connect_passive(leader, follower=False)
    return leader


def _present_ticks(leader) -> dict[str, int]:
    return {name: int(leader.bus.read("Present_Position", name, normalize=False)) for name in BODY}


def _resolve_target(pose_path: Path, leader) -> dict[str, float]:
    data = json.loads(pose_path.read_text(encoding="utf-8"))
    raw = data.get("ticks") if isinstance(data, dict) else data
    if not isinstance(raw, dict):
        raise ValueError(f"유효한 리더 포즈 파일이 아닙니다: {pose_path}")
    target = {}
    cal = getattr(leader, "calibration", None) or {}
    for name in BODY:
        if name not in raw:
            raise ValueError(f"리더 포즈에 {name} 값이 없습니다")
        if name not in cal:
            raise ValueError(f"리더 {name} 캘리브레이션이 없습니다")
        val = int(round(float(raw[name])))
        lo, hi = int(cal[name].range_min), int(cal[name].range_max)
        if not (lo <= val <= hi):
            raise ValueError(f"리더 {name} 목표({val})가 캘리브레이션 범위({lo}..{hi}) 밖입니다")
        target[name] = float(val)
    return target


def _match_target(follower: list[int], present: dict[str, int], leader) -> dict[str, float]:
    """Leader ticks the guard maps onto the Follower's own: follower = leader + mount + one turn per k."""
    cal = getattr(leader, "calibration", None) or {}
    mount = leader_mount(leader)
    check_mount({k: v for k, v in mount.items() if k not in ("gripper", "follower_floor")})  # the guard's own rule, before any motion
    target = {}
    for name, f_raw in zip(BODY, follower):
        if name not in cal:
            raise ValueError(f"리더 {name} 캘리브레이션이 없습니다")
        lo, hi = int(cal[name].range_min), int(cal[name].range_max)
        base = int(f_raw) - int(mount.get(name, 0))
        found = [base + TURN * k for k in range(-3, 4) if lo <= base + TURN * k <= hi]
        if not found:
            raise ValueError(f"리더 {name}에서 팔로워 자세({f_raw})에 해당하는 값이 캘리브레이션 범위({lo}..{hi}) 밖입니다")
        want = min(found, key=lambda t: abs(t - present[name]))
        keep = name in GRAVITY_JOINTS and lo <= present[name] <= hi and abs(want - present[name]) < KEEP_DEG * TICKS_PER_DEGREE
        target[name] = float(present[name] if keep else want)
    return target


def _clear_wrist_roll_wrap(leader, present: dict[str, int], *, returning: bool = False) -> dict[str, int]:
    """`returning`: a move back into the range may start outside it (LeaderActuator.write bounds the way)."""
    cal = getattr(leader, "calibration", None) or {}
    if "wrist_roll" in cal:
        lo, hi = int(cal["wrist_roll"].range_min), int(cal["wrist_roll"].range_max)
        val = present.get("wrist_roll")
        if val is not None and not (lo <= val <= hi):
            bus = leader.bus
            if (
                hasattr(bus, "packet_handler")
                and hasattr(bus, "port_handler")
                and bus.read("Torque_Enable", "wrist_roll", normalize=False) == 0
                and bus.read("Hardware_Error_Status", "wrist_roll", normalize=False) == 0
                and bus.read("Operating_Mode", "wrist_roll", normalize=False) == 4
            ):
                reboot_res = bus.packet_handler.reboot(bus.port_handler, bus.motors["wrist_roll"].id)
                if isinstance(reboot_res, tuple) and len(reboot_res) >= 2 and (reboot_res[0] != 0 or reboot_res[1] != 0):
                    raise RuntimeError(f"리더 wrist_roll 리부트 실패: comm={reboot_res[0]}, err={reboot_res[1]}")
                time.sleep(0.4)
                if bus.read("Torque_Enable", "wrist_roll", normalize=False) != 0:
                    raise RuntimeError("리더 wrist_roll 리부트 후 토크 OFF 확인 실패")
                err = bus.read("Hardware_Error_Status", "wrist_roll", normalize=False)
                if err != 0:
                    raise RuntimeError(f"리더 wrist_roll 리부트 후 하드웨어 오류({err}) 감지")
                present = _present_ticks(leader)
    for name in BODY:
        if name not in cal:
            raise ValueError(f"리더 {name} 캘리브레이션이 없습니다")
        lo, hi = int(cal[name].range_min), int(cal[name].range_max)
        if not returning and not (lo <= present[name] <= hi):
            raise ValueError(f"리더 {name} 현재 위치({present[name]})가 캘리브레이션 범위({lo}..{hi}) 밖입니다")
    return present


class FollowerTorqueOn(RuntimeError):
    """The Follower reads torque ON: nothing was written, a person supports the arm first."""


def read_follower_pose(config_path: Path, arm: str) -> list[int]:
    from lerobot.robots import make_robot_from_config
    from lerobot.robots.omx_follower.config_omx_follower import OmxFollowerConfig

    cfg = json.loads(config_path.read_text(encoding="utf-8-sig"))
    robot = cfg.get("robot")
    if not isinstance(robot, dict):
        raise ValueError(f"{config_path.name}: robot 설정이 없습니다")
    if robot.get("type") == "bi_omx_follower" and arm in ("arm_a", "arm_b"):
        robot = robot.get(arm)
        if not isinstance(robot, dict):
            raise ValueError(f"{config_path.name}: robot.{arm} 설정이 없습니다")
    rcfg = OmxFollowerConfig(
        id=str(robot.get("id") or "omx_follower_arm"),
        port=str(robot["port"]),
        use_degrees=False,
    )
    follower = make_robot_from_config(rcfg)
    bus = follower.bus
    bus.connect()  # the handshake reads only. This pose read NEVER writes Torque_Enable: an arm a dead process left extended with torque ON is refused, not dropped
    try:
        if any(bus.read("Torque_Enable", n, normalize=False, num_retry=guarded_device.READ_RETRY) != 0 for n in (*BODY, "gripper")):
            _END["follower_torque_on"] = True
            raise FollowerTorqueOn("팔로워 토크가 켜져 있습니다 — 사람이 팔을 받친 뒤 확인")
        return [int(bus.read("Present_Position", n, normalize=False, num_retry=guarded_device.READ_RETRY)) for n in (*BODY, "gripper")]
    finally:
        bus.disconnect(disable_torque=False)  # closes the port without the default Torque_Enable write


def read_leader_pose(config_path: Path, arm: str) -> dict[str, int]:
    teleop_cfg = _load_teleop_cfg(config_path, arm)
    leader = _connect_leader(teleop_cfg)
    try:
        return _clear_wrist_roll_wrap(leader, _present_ticks(leader))
    finally:
        close_device(leader)


def check_travel(present: dict, target: dict) -> None:
    for name in BODY:
        degrees = abs(present[name] - target[name]) / TICKS_PER_DEGREE
        if degrees > MAX_TRAVEL_DEG:
            raise ValueError(f"리더 {name}이(가) {degrees:.0f}도 움직여야 합니다 (자동 이동은 {MAX_TRAVEL_DEG}도까지). "
                             "리더를 손으로 팔로워 가까이 옮긴 뒤 다시 하세요. 리더는 움직이지 않았습니다")


def check_attest(attest: str) -> None:
    parts = str(attest).split(":", 2)
    if len(parts) != 3 or parts[0] != "hands-off" or not parts[1].strip() or not parts[2].strip():
        raise ValueError("--attest 'hands-off:<who>:<iso8601>' 형식이 필요합니다")


def move_leader_home(config_path: Path, arm: str, pose_path: Path, attest: str, *, timeout_s: float = 45.0,
                     follower: list[int] | None = None, rate_deg_s: float = HOME_RATE_DEG_S,
                     accel_deg_s2: float = HOME_ACCEL_DEG_S2) -> dict:
    check_attest(attest)
    rate_deg_s, accel_deg_s2 = validate_motion_limits(rate_deg_s, accel_deg_s2)
    teleop_cfg = _load_teleop_cfg(config_path, arm)
    protect_signals()
    _END.update(torque_off_confirmed=False, restore_failures=[])  # device access starts: unconfirmed until the connect returns
    leader = _connect_leader(teleop_cfg)
    actuator = LeaderActuator(leader.bus, label=f"leader-{arm}", rate_deg_s=rate_deg_s, accel_deg_s2=accel_deg_s2)
    raised = False
    restore_failures: list[str] = []
    _END.update(torque_off_confirmed=True, restore_failures=[])
    try:
        present = _clear_wrist_roll_wrap(leader, _present_ticks(leader), returning=True)
        target = _resolve_target(pose_path, leader) if follower is None else _match_target(follower, present, leader)
        check_travel(present, target)  # before any torque: a long move is refused, not confirmed (no hands-off check exists)
        far_deg = max(abs(present[n] - target[n]) for n in BODY) / TICKS_PER_DEGREE
        timeout_s = max(timeout_s, far_deg / actuator.rate_deg_s + 15.0)
        actuator.admit(pwm=DEFAULT_PWM, current=DEFAULT_CURRENT, gains=DEFAULT_GAINS)
        actuator.enable()
        actuator.seed(present)
        deadline = time.monotonic() + timeout_s
        last = time.monotonic()
        while time.monotonic() < deadline:
            now = time.monotonic()
            elapsed = max(1.0 / 30.0, min(0.1, now - last))
            last = now
            present = _present_ticks(leader)
            lag = max(abs(present[n] - actuator.command[n]) for n in BODY) / TICKS_PER_DEGREE
            if lag > MAX_TRACK_DEG:  # measured against the last command sent, before the next one
                raise RuntimeError(f"리더 {arm} 추종 오차 {lag:.1f}도가 {MAX_TRACK_DEG}도를 넘어 정지합니다")
            actuator.check_effort(present)
            cmd = actuator.step(target, elapsed)
            actuator.write(cmd)
            if all(abs(present[n] - target[n]) <= 15 for n in BODY) and all(
                abs(actuator.command[n] - target[n]) <= 1.0 for n in BODY
            ):
                return {"ok": True, "arm": arm, "ticks": present, "start_deviation_deg": round(far_deg, 1)}
            time.sleep(1.0 / 30.0)
        raise TimeoutError(f"리더 {arm} 홈 이동 시간 초과 ({timeout_s}s)")
    except BaseException:
        raised = True
        raise
    finally:
        _END["torque_off_confirmed"] = False  # until restore() has answered
        with no_interrupts():
            close_exc = None
            try:
                restore_failures = actuator.restore()
            finally:
                try:
                    close_device(leader)
                except Exception as exc:
                    close_exc = exc
        _END.update(torque_off_confirmed=not any(f.startswith("torque OFF") for f in restore_failures),
                    restore_failures=[str(f)[:160] for f in restore_failures])
        if restore_failures and not raised:
            raise RuntimeError(f"리더 {arm} 복구 실패: {restore_failures}")
        if close_exc is not None and not raised:
            raise close_exc


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="Guarded OMX Leader Home runner")
    ap.add_argument("--config", type=Path, required=True)
    ap.add_argument("--arm", required=True, choices=("arm_a", "arm_b", "arm_s"))
    ap.add_argument("--pose", type=Path)
    ap.add_argument("--attest", default="")
    ap.add_argument("--timeout-s", type=float, default=45.0)
    ap.add_argument("--match-follower", action="store_true", help="move the Leader to the Follower's current pose (mount applied)")
    ap.add_argument("--target-follower-ticks", default="", help="5 comma-separated Follower body ticks for parallel align without opening Follower port")
    ap.add_argument("--rate-deg-s", type=float, default=HOME_RATE_DEG_S)
    ap.add_argument("--read-pose", action="store_true")
    ap.add_argument("--read-follower-pose", action="store_true")
    args = ap.parse_args(argv)
    if args.read_follower_pose:
        print(json.dumps({"ok": True, "arm": args.arm, "state": read_follower_pose(args.config, args.arm)}))
        return 0
    if args.read_pose:
        print(json.dumps({"ok": True, "arm": args.arm, "ticks": read_leader_pose(args.config, args.arm)}))
        return 0
    if args.target_follower_ticks and (args.match_follower or args.pose):
        ap.error("--target-follower-ticks cannot be combined with --match-follower or --pose")
    if not args.pose and not args.match_follower and not args.target_follower_ticks:
        ap.error("--pose is required unless --match-follower, --target-follower-ticks, --read-pose or --read-follower-pose is set")
    check_attest(args.attest)  # before any device access
    if args.target_follower_ticks:
        parts = [p.strip() for p in args.target_follower_ticks.split(",")]
        if len(parts) != 5 or any(not p.lstrip("+-").isdigit() for p in parts):
            raise ValueError("--target-follower-ticks must be 5 integers")
        follower = [int(p) for p in parts]
        if any(not 0 <= v <= 4095 for v in follower):
            raise ValueError("--target-follower-ticks values must be in 0..4095")
    else:
        follower = read_follower_pose(args.config, args.arm) if args.match_follower else None
    print(json.dumps(move_leader_home(args.config, args.arm, args.pose, args.attest, timeout_s=args.timeout_s,
                                      follower=follower, rate_deg_s=args.rate_deg_s)))
    return 0


def cli(argv=None) -> int:
    """main() with the last stdout line always a JSON verdict: a cleanup failure is never hidden behind the exception."""
    protect_signals()  # SIGTERM from the bench /stop ends the run like Ctrl-C, so the cleanup in move_leader_home runs
    try:
        return main(argv)
    except SystemExit:
        raise
    except BaseException as exc:
        traceback.print_exc()
        sys.stderr.flush()
        print(json.dumps({"ok": False, "torque_off_confirmed": _END["torque_off_confirmed"],
                          "restore_failures": _END["restore_failures"], "error": f"{type(exc).__name__}: {exc}"[:200],
                          **({"follower_torque_on": True} if _END.get("follower_torque_on") else {})}), flush=True)
        return 1


if __name__ == "__main__":
    raise SystemExit(cli())
