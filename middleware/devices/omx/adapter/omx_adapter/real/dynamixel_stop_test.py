"""D-858 S3 timed stop test (V-016, KAN-30) on the real Dynamixel port, and its CLI.

The arm swings joint1 a little and slowly (measurement mode: the §4 gate without the stop-test
item). Mid-swing the port is stopped exactly as an operator stop does (``port.stop``); joint1
is then sampled for a window. Measured: joint1 speed just before the stop (it must really be
moving), the time until joint1 is measured still (0.03 rad/s), the largest joint1 deviation
from where it was at the stop, and the final joint1 speed.
Passed = within the V-016 bounds and the port reports the motion as STOPPED with the hold
written. The gate re-checks the numbers; the verdict alone never opens motion.

Absorbed from rosy-vault 9a744a3 ``device_core`` ``/arm/stop-test`` and ``auto_ready`` (V-016).
Real runs are a person's job (KAN-30). ``--dry-run`` opens nothing and only prints the gate.
"""
from __future__ import annotations

import argparse
import json
import socket
import sys
import time
from pathlib import Path
from typing import Callable

from .dynamixel_gates import (
    JOINT1_STILL_RAD_S, MAX_JOINT1_DEVIATION_RAD, MAX_JOINT1_VELOCITY_RAD_S, MAX_STOP_MS,
    STOP_TEST_MAX_AMPLITUDE_RAD, STOP_TEST_MAX_SPEED_RAD_S, STOP_TEST_MIN_PRE_STOP_RAD_S,
    STOP_TEST_MIN_SPEED_RAD_S, _finite,
)


def stop_test_poses(present: list[float], *, amplitude_rad: float, cycles: int) -> list[list[float]]:
    """joint1 out, back, the other way, back; ``cycles`` times, from where the arm is."""
    if not (_finite(amplitude_rad) and 0 < amplitude_rad <= STOP_TEST_MAX_AMPLITUDE_RAD):
        raise ValueError(f"amplitude must lie in (0, {STOP_TEST_MAX_AMPLITUDE_RAD}] rad")
    if type(cycles) is not int or not 1 <= cycles <= 5:
        raise ValueError("cycles must be 1..5")
    out_, in_ = list(present), list(present)
    out_[0] += amplitude_rad
    in_[0] -= amplitude_rad
    return [list(q) for _ in range(cycles) for q in (out_, present, in_, present)]


def _speed(samples: list[tuple[float, float]], window_s: float) -> float:
    """joint1 speed at the last sample over at least ``window_s`` (or all samples if shorter)."""
    t, q = samples[-1]
    older = [i for i in range(len(samples) - 1) if t - samples[i][0] >= window_s]
    t0, q0 = samples[older[-1] if older else 0]
    return abs(q - q0) / (t - t0) if t > t0 else 0.0


def run_stop_test(port, *, authority_epoch: int, dispatch_generation: int,
                  amplitude_rad: float = 0.1, speed_rad_s: float = STOP_TEST_MAX_SPEED_RAD_S,
                  cycles: int = 1, stop_after_s: float | None = None, sample_s: float = 0.01,
                  velocity_window_s: float = 0.1, window_s: float = 1.0,
                  clock: Callable[[], float] = time.monotonic,
                  sleep: Callable[[float], None] = time.sleep) -> dict:
    """Run one stop test on a rearmed port. Returns the ``stop_test`` record value plus detail.

    Speed is measured on joint1 over ``velocity_window_s`` (one encoder tick over 10 ms would
    read as 0.15 rad/s). The arm must be measured moving at >= 0.12 rad/s just before the stop;
    the stop time ends at the last sample still faster than the "still" speed (0.03 rad/s), so
    it errs long, never short. A stop that never lands keeps the commanded speed and fails."""
    if not window_s * 1000 > MAX_STOP_MS or not 0 < sample_s < velocity_window_s < window_s:
        raise ValueError("need sample < velocity window < observation window, window > 500 ms")
    if not (_finite(speed_rad_s) and STOP_TEST_MIN_SPEED_RAD_S <= speed_rad_s <= STOP_TEST_MAX_SPEED_RAD_S):
        raise ValueError(f"speed must lie in [{STOP_TEST_MIN_SPEED_RAD_S}, {STOP_TEST_MAX_SPEED_RAD_S}] rad/s")
    poses = stop_test_poses(port.present_joints(), amplitude_rad=amplitude_rad, cycles=cycles)
    receipt = port.submit_stop_test(poses, authority_epoch=authority_epoch,
                                    dispatch_generation=dispatch_generation,
                                    max_speed_rad_s=speed_rad_s)
    if not receipt.accepted:
        return {"started": False, "reason": port.last_refusal, "passed": False}
    # Mid first leg: joint1 is moving at the capped speed when the stop lands.
    run_s = amplitude_rad / speed_rad_s / 2 if stop_after_s is None else stop_after_s
    if run_s < velocity_window_s:
        raise ValueError("stop after at least one velocity window of motion")
    before = [(clock(), port.present_joints()[0])]
    deadline = before[0][0] + run_s
    while clock() < deadline:
        sleep(sample_s)
        before.append((clock(), port.present_joints()[0]))
    pre_stop = _speed(before, velocity_window_s)
    q_stop, t_stop = before[-1][1], before[-1][0]
    port.stop()  # the same call an operator stop reaches (cancel -> stop)
    samples = [(t_stop, q_stop)]
    moving_until, speed = t_stop, pre_stop
    while samples[-1][0] - t_stop < window_s:
        sleep(sample_s)
        samples.append((clock(), port.present_joints()[0]))
        speed = _speed(samples, velocity_window_s)
        if speed > JOINT1_STILL_RAD_S:
            moving_until = samples[-1][0]
    deviation = max(abs(q - q_stop) for _, q in samples)
    snap, outcome = port.snapshot(), port.outcome or {}
    stopped = (snap["state"] == "STOPPED" and snap["last_stop_error"] is None
               and outcome.get("goal_id") == receipt.driver_goal_id
               and outcome.get("result") == "STOPPED")
    stop_ms = round((moving_until - t_stop) * 1000)
    settled = moving_until < samples[-1][0]  # measured still, not only the software state
    passed = (stopped and settled and pre_stop >= STOP_TEST_MIN_PRE_STOP_RAD_S
              and stop_ms <= MAX_STOP_MS and deviation <= MAX_JOINT1_DEVIATION_RAD
              and speed <= MAX_JOINT1_VELOCITY_RAD_S)
    return {"started": True, "passed": passed, "joint": "joint1", "measured_stop_ms": stop_ms,
            "joint1_deviation_rad": round(deviation, 4), "joint1_velocity_rad_s": round(speed, 4),
            "pre_stop_velocity_rad_s": round(pre_stop, 4), "settled_in_window": settled,
            "stopped_mid_motion": stopped, "port_reason": snap["reason"], "samples": len(samples)}


def record_value(result: dict, *, config_revision: str) -> dict:
    """The ``stop_test`` item for ``CommissioningStore.save``."""
    keys = ("joint", "measured_stop_ms", "joint1_deviation_rad", "joint1_velocity_rad_s",
            "pre_stop_velocity_rad_s", "passed")
    return {**{k: result[k] for k in keys}, "driver": "dynamixel", "config_revision": config_revision}


def owner_running(socket_path: Path) -> bool:
    """A live owner socket for this arm instance (D-858 §3: one writer per arm)."""
    if not hasattr(socket, "AF_UNIX") or not Path(socket_path).exists():
        return False
    with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as probe:
        probe.settimeout(1.0)
        try:
            probe.connect(str(socket_path))
        except OSError:
            return False  # a stale socket file of a stopped owner
    return True


def _config(path: Path):
    from ..command_owner import ArmCommandConfig
    return ArmCommandConfig(**json.loads(path.read_text(encoding="utf-8")))


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--record-root", type=Path, required=True)
    parser.add_argument("--owner-config", type=Path, required=True,
                        help="JSON of ArmCommandConfig fields for this arm (enabled, limits)")
    parser.add_argument("--by", required=True, help="name of the person running the test")
    parser.add_argument("--amplitude-rad", type=float, default=0.1)
    parser.add_argument("--speed-rad-s", type=float, default=STOP_TEST_MAX_SPEED_RAD_S)
    parser.add_argument("--cycles", type=int, default=1)
    parser.add_argument("--dry-run", action="store_true", help="open nothing; print the gate")
    parser.add_argument("--device", help="/dev/serial/by-id/... of this arm (real run)")
    parser.add_argument("--stop-journal", type=Path, help="the arm owner's local_stop journal (real run)")
    parser.add_argument("--operator-confirmed", action="store_true",
                        help="the person at the bench rearms the stop fence at the given generation")
    parser.add_argument("--owner-socket", type=Path,
                        help="this arm instance's owner socket; a live owner refuses the run")
    parser.add_argument("--authority-epoch", type=int)
    parser.add_argument("--dispatch-generation", type=int)
    args = parser.parse_args(argv)
    from .commissioning_record import CommissioningStore, load_motion_evidence
    config = _config(args.owner_config)
    store = CommissioningStore(args.record_root, workcell_id=config.workcell_id,
                               instance_id=config.instance_id)
    evidence = load_motion_evidence(store, config)
    blockers = evidence.blockers(config_revision=config.calibration_revision, include_stop_test=False)
    report = {"dry_run": args.dry_run, "record_revision": evidence.revision,
              "measurement_gate_blockers": blockers,
              "rules": {"amplitude_rad": args.amplitude_rad, "speed_rad_s": args.speed_rad_s,
                        "cycles": args.cycles, "max_stop_ms": MAX_STOP_MS,
                        "max_joint1_deviation_rad": MAX_JOINT1_DEVIATION_RAD,
                        "max_joint1_velocity_rad_s": MAX_JOINT1_VELOCITY_RAD_S}}
    try:
        stop_test_poses([0.0] * len(config.joint_names), amplitude_rad=args.amplitude_rad,
                        cycles=args.cycles)
        if not STOP_TEST_MIN_SPEED_RAD_S <= args.speed_rad_s <= STOP_TEST_MAX_SPEED_RAD_S:
            raise ValueError(f"speed must lie in [{STOP_TEST_MIN_SPEED_RAD_S}, "
                             f"{STOP_TEST_MAX_SPEED_RAD_S}] rad/s")
    except ValueError as exc:
        blockers.append(str(exc))
    if args.dry_run or blockers:
        print(json.dumps(report, sort_keys=True))
        return 0 if not blockers else 2
    real = (args.device, args.stop_journal, args.owner_socket, args.authority_epoch,
            args.dispatch_generation)
    if any(value is None for value in real) or not args.operator_confirmed:
        parser.error("a real run needs --device, --stop-journal, --owner-socket, --authority-epoch, "
                     "--dispatch-generation and --operator-confirmed")
    if owner_running(args.owner_socket):
        parser.error("this arm's owner is running; stop the owner service before a bench stop test")
    from .dynamixel_port import open_real_port
    from ..local_stop import LocalStopController
    fence = LocalStopController(args.stop_journal, workcell_id=config.workcell_id,
                                instance_id=config.instance_id)
    port = open_real_port(args.device, config=config, store=store, planner=lambda grant: [],
                          stop_fence=fence)
    gen = (args.authority_epoch, args.dispatch_generation)
    try:
        # Bench commissioning: the owner is not running (checked above; the device also opens
        # exclusively), so no Fleet dispatch reaches this arm and the person at the bench confirms
        # the generation. The fence still refuses with unresolved local Actions or a not-newer
        # generation. The stop source column only knows fleet/operator values, so the bench
        # rearm is told apart by its reason instead of a new schema value.
        fence.rearm(authority_epoch=gen[0], dispatch_generation=gen[1], operator_confirmed=True,
                    fleet_fence_current=lambda epoch, generation: (epoch, generation) == gen,
                    reason="BENCH_COMMISSIONING_REARM")
        port.rearm(authority_epoch=gen[0], dispatch_generation=gen[1])
        result = run_stop_test(port, authority_epoch=gen[0], dispatch_generation=gen[1],
                               amplitude_rad=args.amplitude_rad, speed_rad_s=args.speed_rad_s,
                               cycles=args.cycles)
        report["result"] = result
        if result["started"]:  # failed tests are recorded too; the gate stays closed on them
            report["record_revision"] = store.save(
                {"stop_test": record_value(result, config_revision=config.calibration_revision)},
                by=args.by, config_revision=config.calibration_revision,
                joint_names=config.joint_names, expected_revision=port.evidence.revision)
    finally:
        port.stop("BENCH_STOP_TEST_DONE")  # leave the fence tripped: the owner needs a person rearm
        port.close()
    print(json.dumps(report, sort_keys=True))
    return 0 if report.get("result", {}).get("passed") else 2


if __name__ == "__main__":
    sys.exit(main())
