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

HERE = Path(__file__).resolve().parent
if str(HERE) not in sys.path:
    sys.path.insert(0, str(HERE))

import guarded_device
from guarded_device import close_device
from joint_tune import no_interrupts, protect_signals
from leader_actuator import BODY, DEFAULT_CURRENT, DEFAULT_PWM, RATE_DEG_S, TICKS_PER_DEGREE, LeaderActuator

DEFAULT_GAINS = {n: {"p": 1200, "i": 100} for n in BODY}


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
    guarded_device.connect_passive(follower, follower=True)
    try:
        return [int(follower.bus.read("Present_Position", n, normalize=False)) for n in (*BODY, "gripper")]
    finally:
        close_device(follower)


def read_leader_pose(config_path: Path, arm: str) -> dict[str, int]:
    teleop_cfg = _load_teleop_cfg(config_path, arm)
    leader = _connect_leader(teleop_cfg)
    try:
        return _clear_wrist_roll_wrap(leader, _present_ticks(leader))
    finally:
        close_device(leader)


def move_leader_home(config_path: Path, arm: str, pose_path: Path, attest: str, *, timeout_s: float = 45.0) -> dict:
    if not str(attest).startswith("hands-off:"):
        raise ValueError("--attest 'hands-off:<who>:<iso8601>' 형식이 필요합니다")
    teleop_cfg = _load_teleop_cfg(config_path, arm)
    protect_signals()
    leader = _connect_leader(teleop_cfg)
    actuator = LeaderActuator(leader.bus, label=f"leader-{arm}")
    raised = False
    restore_failures: list[str] = []
    try:
        present = _clear_wrist_roll_wrap(leader, _present_ticks(leader), returning=True)
        target = _resolve_target(pose_path, leader)
        # the ramp is 1 degree/s: a half turn needs about 3 minutes, so the deadline follows the distance
        far_deg = max(abs(present[n] - target[n]) for n in BODY) / TICKS_PER_DEGREE
        timeout_s = max(timeout_s, far_deg / RATE_DEG_S + 15.0)
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
            actuator.check_effort(present)
            cmd = actuator.step(target, elapsed)
            actuator.write(cmd)
            if all(abs(present[n] - target[n]) <= 15 for n in BODY) and all(
                abs(actuator.command[n] - target[n]) <= 1.0 for n in BODY
            ):
                return {"ok": True, "arm": arm, "ticks": present}
            time.sleep(1.0 / 30.0)
        raise TimeoutError(f"리더 {arm} 홈 이동 시간 초과 ({timeout_s}s)")
    except BaseException:
        raised = True
        raise
    finally:
        with no_interrupts():
            close_exc = None
            try:
                restore_failures = actuator.restore()
            finally:
                try:
                    close_device(leader)
                except Exception as exc:
                    close_exc = exc
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
    ap.add_argument("--read-pose", action="store_true")
    ap.add_argument("--read-follower-pose", action="store_true")
    args = ap.parse_args(argv)
    if args.read_follower_pose:
        print(json.dumps({"ok": True, "arm": args.arm, "state": read_follower_pose(args.config, args.arm)}))
        return 0
    if args.read_pose:
        print(json.dumps({"ok": True, "arm": args.arm, "ticks": read_leader_pose(args.config, args.arm)}))
        return 0
    if not args.pose:
        ap.error("--pose is required unless --read-pose or --read-follower-pose is set")
    print(json.dumps(move_leader_home(args.config, args.arm, args.pose, args.attest, timeout_s=args.timeout_s)))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
