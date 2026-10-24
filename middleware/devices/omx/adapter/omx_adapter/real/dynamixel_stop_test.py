"""D-858 S3 timed stop test (V-016, KAN-30) on the real Dynamixel port, and its CLI.

The arm swings joint1 a little and slowly (measurement mode: the §4 gate without the stop-test
item). Mid-swing the port is stopped exactly as an operator stop does (``port.stop``); joint1
is then sampled for a window. Measured: the time until joint1 stays slower than 0.1 rad/s,
the largest joint1 deviation from where it was at the stop, and the final joint1 speed.
Passed = within the V-016 bounds and the port reports the motion as STOPPED with the hold
written. The gate re-checks the numbers; the verdict alone never opens motion.

Absorbed from rosy-vault 9a744a3 ``device_core`` ``/arm/stop-test`` and ``auto_ready`` (V-016).
Real runs are a person's job (KAN-30). ``--dry-run`` opens nothing and only prints the gate.
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path
from typing import Callable

from .dynamixel_gates import (
    MAX_JOINT1_DEVIATION_RAD, MAX_JOINT1_VELOCITY_RAD_S, MAX_STOP_MS,
    STOP_TEST_MAX_AMPLITUDE_RAD, STOP_TEST_MAX_SPEED_RAD_S, _finite,
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


def run_stop_test(port, *, authority_epoch: int, dispatch_generation: int,
                  amplitude_rad: float = 0.1, speed_rad_s: float = 0.1, cycles: int = 1,
                  stop_after_s: float | None = None, sample_s: float = 0.01,
                  velocity_window_s: float = 0.1, window_s: float = 1.0,
                  clock: Callable[[], float] = time.monotonic,
                  sleep: Callable[[float], None] = time.sleep) -> dict:
    """Run one stop test on a rearmed port. Returns the ``stop_test`` record value plus detail.

    Speed is estimated over ``velocity_window_s`` (one encoder tick over 10 ms would read as
    0.15 rad/s). A stop counts as settled after the last sample still faster than the bound,
    so the measured time errs long, never short."""
    if not window_s * 1000 > MAX_STOP_MS or not 0 < sample_s < velocity_window_s < window_s:
        raise ValueError("need sample < velocity window < observation window, window > 500 ms")
    poses = stop_test_poses(port.present_joints(), amplitude_rad=amplitude_rad, cycles=cycles)
    receipt = port.submit_stop_test(poses, authority_epoch=authority_epoch,
                                    dispatch_generation=dispatch_generation,
                                    max_speed_rad_s=speed_rad_s)
    if not receipt.accepted:
        return {"started": False, "reason": port.last_refusal, "passed": False}
    # Mid first leg: joint1 is moving at the capped speed when the stop lands.
    deadline = clock() + (amplitude_rad / speed_rad_s / 2 if stop_after_s is None else stop_after_s)
    while clock() < deadline:
        sleep(sample_s)
    q_stop, t_stop = port.present_joints()[0], clock()
    port.stop()  # the same call an operator stop reaches (cancel -> stop)
    samples = [(t_stop, q_stop)]
    while samples[-1][0] - t_stop < window_s:
        sleep(sample_s)
        samples.append((clock(), port.present_joints()[0]))
    moving_until, speed = t_stop, 0.0
    for k, (t, q) in enumerate(samples[1:], 1):
        older = [i for i in range(k) if t - samples[i][0] >= velocity_window_s]
        j = older[-1] if older else 0
        speed = abs(q - samples[j][1]) / max(t - samples[j][0], sample_s)
        if speed > MAX_JOINT1_VELOCITY_RAD_S:
            moving_until = t
    deviation = max(abs(q - q_stop) for _, q in samples)
    snap, outcome = port.snapshot(), port.outcome or {}
    stopped = (snap["state"] == "STOPPED" and snap["last_stop_error"] is None
               and outcome.get("goal_id") == receipt.driver_goal_id
               and outcome.get("result") == "STOPPED")
    stop_ms = round((moving_until - t_stop) * 1000)
    settled = moving_until < samples[-1][0]
    passed = (stopped and settled and stop_ms <= MAX_STOP_MS
              and deviation <= MAX_JOINT1_DEVIATION_RAD and speed <= MAX_JOINT1_VELOCITY_RAD_S)
    return {"started": True, "passed": passed, "joint": "joint1", "measured_stop_ms": stop_ms,
            "joint1_deviation_rad": round(deviation, 4), "joint1_velocity_rad_s": round(speed, 4),
            "settled_in_window": settled, "stopped_mid_motion": stopped,
            "port_reason": snap["reason"], "samples": len(samples)}


def record_value(result: dict, *, config_revision: str) -> dict:
    """The ``stop_test`` item for ``CommissioningStore.save``."""
    keys = ("joint", "measured_stop_ms", "joint1_deviation_rad", "joint1_velocity_rad_s", "passed")
    return {**{k: result[k] for k in keys}, "driver": "dynamixel", "config_revision": config_revision}


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
    parser.add_argument("--speed-rad-s", type=float, default=0.1)
    parser.add_argument("--cycles", type=int, default=1)
    parser.add_argument("--dry-run", action="store_true", help="open nothing; print the gate")
    parser.add_argument("--device", help="/dev/serial/by-id/... of this arm (real run)")
    parser.add_argument("--stop-journal", type=Path, help="the arm owner's local_stop journal (real run)")
    parser.add_argument("--operator-confirmed", action="store_true",
                        help="the person at the bench rearms the stop fence at the given generation")
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
        if not 0 < args.speed_rad_s <= STOP_TEST_MAX_SPEED_RAD_S:
            raise ValueError(f"speed must lie in (0, {STOP_TEST_MAX_SPEED_RAD_S}] rad/s")
    except ValueError as exc:
        blockers.append(str(exc))
    if args.dry_run or blockers:
        print(json.dumps(report, sort_keys=True))
        return 0 if not blockers else 2
    real = (args.device, args.stop_journal, args.authority_epoch, args.dispatch_generation)
    if any(value is None for value in real) or not args.operator_confirmed:
        parser.error("a real run needs --device, --stop-journal, --authority-epoch, "
                     "--dispatch-generation and --operator-confirmed")
    from .dynamixel_port import open_real_port
    from ..local_stop import LocalStopController
    fence = LocalStopController(args.stop_journal, workcell_id=config.workcell_id,
                                instance_id=config.instance_id)
    port = open_real_port(args.device, config=config, evidence=evidence, planner=lambda grant: [],
                          stop_fence=fence, record_revision=store.revision)
    gen = (args.authority_epoch, args.dispatch_generation)
    try:
        # Bench commissioning: the owner is not driving this arm (the device opens exclusively),
        # so no Fleet dispatch reaches it; the person at the bench confirms the generation.
        # The fence still refuses with unresolved local Actions or a not-newer generation.
        fence.rearm(authority_epoch=gen[0], dispatch_generation=gen[1], operator_confirmed=True,
                    fleet_fence_current=lambda epoch, generation: (epoch, generation) == gen)
        port.rearm(authority_epoch=args.authority_epoch, dispatch_generation=args.dispatch_generation)
        result = run_stop_test(port, authority_epoch=args.authority_epoch,
                               dispatch_generation=args.dispatch_generation,
                               amplitude_rad=args.amplitude_rad, speed_rad_s=args.speed_rad_s,
                               cycles=args.cycles)
        report["result"] = result
        if result["started"]:  # failed tests are recorded too; the gate stays closed on them
            report["record_revision"] = store.save(
                {"stop_test": record_value(result, config_revision=config.calibration_revision)},
                by=args.by, config_revision=config.calibration_revision,
                joint_names=config.joint_names, expected_revision=evidence.revision)
    finally:
        port.close()
    print(json.dumps(report, sort_keys=True))
    return 0 if report.get("result", {}).get("passed") else 2


if __name__ == "__main__":
    sys.exit(main())
