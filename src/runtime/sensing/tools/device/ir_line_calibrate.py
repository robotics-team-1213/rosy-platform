#!/usr/bin/env python3
"""IR line calibration for the Pinky Pro (D-143, D-344 §12). Read-only.

Subscribes to ``ir_sensor/range`` only. It never publishes, never moves the
robot and never writes device config: it prints the YAML for the operator to
paste. Runbook: docs/deployment/pinky-pro-ir-line-calibration-runbook.md

  run      interactive: carpet -> left -> centre -> right, then compute
  capture  record one phase into the session JSON (repeat to redo a phase)
  compute  offline: endpoints, checks, revision digest and YAML from a session
  check    live left/right sign check with a session's (or given) endpoints

Run on the robot with the rosy-io graph up (``enable_ir:=true``)::

    source /opt/ros/jazzy/setup.bash && source /opt/rosy/current/install/setup.bash
    python3 tools/device/ir_line_calibrate.py run --session ~/rosy-ir/session.json
"""
import argparse
import json
import sys
import time
from pathlib import Path

_PKG = Path(__file__).resolve().parents[2]
if str(_PKG) not in sys.path:
    sys.path.insert(0, str(_PKG))

from control.sensing.perception.ir_calibration import (  # noqa: E402
    CHANNELS, PHASES, compute_ir_calibration, ir_side, render_config)
from control.sensing.perception.lane import IRLineCalibration, detect_ir_line  # noqa: E402

SCHEMA = "rosy.control.ir_line_calibration/1"
PROMPTS = {
    "carpet": "로봇을 맨 카펫 위에 둔다 — 세 IR 모두 테이프 밖",
    "left": "흰 테이프를 왼쪽 IR 밑에만 둔다(가운데·오른쪽은 카펫)",
    "centre": "흰 테이프를 가운데 IR 밑에만 둔다(왼쪽·오른쪽은 카펫)",
    "right": "흰 테이프를 오른쪽 IR 밑에만 둔다(왼쪽·가운데는 카펫)",
}


def load_session(path: Path) -> dict:
    if path.exists():
        data = json.loads(path.read_text(encoding="utf-8"))
        if data.get("schema") != SCHEMA:
            raise SystemExit(f"{path}: not an IR calibration session ({SCHEMA})")
        return data
    return {"schema": SCHEMA, "phases": {}}


def save_session(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=1), encoding="utf-8")


def _spin_samples(topic: str, seconds: float, on_sample=None) -> list:
    """Collect raw [left, centre, right] samples. Imports rclpy only here."""
    import rclpy
    from rclpy.qos import qos_profile_sensor_data
    from std_msgs.msg import UInt16MultiArray

    samples = []

    def callback(msg):
        values = [int(value) for value in msg.data]
        samples.append(values)
        if on_sample is not None:
            on_sample(values)

    rclpy.init()
    node = rclpy.create_node("ir_line_calibrate")
    try:
        node.create_subscription(UInt16MultiArray, topic, callback, qos_profile_sensor_data)
        deadline = time.monotonic() + seconds
        while rclpy.ok() and time.monotonic() < deadline:
            rclpy.spin_once(node, timeout_sec=0.1)
    finally:
        node.destroy_node()
        rclpy.shutdown()
    return samples


def capture(args, phase: str) -> None:
    data = load_session(args.session)
    samples = _spin_samples(args.topic, args.seconds)
    if not samples:
        raise SystemExit(f"no samples on {args.topic} in {args.seconds:g} s — "
                         "is rosy-io running with enable_ir:=true?")
    data["phases"][phase] = samples
    data.setdefault("captured_at", {})[phase] = time.strftime("%Y-%m-%dT%H:%M:%S%z")
    save_session(args.session, data)
    print(f"{phase}: {len(samples)} samples -> {args.session}")


def report(data: dict, args) -> int:
    result = compute_ir_calibration(data["phases"], min_span=args.min_span,
                                    min_samples=args.min_samples)
    print("channel   black(carpet)  white(tape)   span   noise(carpet/tape)")
    for index, name in enumerate(CHANNELS):
        carpet = result.levels["carpet"][index]
        tape = result.levels[name][index]
        print(f"{name:<8} {result.black[index]:>13.1f} {result.white[index]:>12.1f} "
              f"{abs(result.white[index] - result.black[index]):>6.1f}   "
              f"{carpet.sigma:.1f}/{tape.sigma:.1f}")
    for phase, error in result.phase_errors.items():
        print(f"  {phase:<7} decodes as {ir_side(error):<6} "
              f"({'no line' if error is None else f'error {error:+.2f}'})")
    for warning in result.warnings:
        print(f"WARNING: {warning}")
    if not result.ok:
        for error in result.errors:
            print(f"FAIL: {error}")
        print("교정 불가 — 위 원인을 고치고 해당 단계를 다시 capture 한다.")
        return 1
    print(f"\nrevision: {result.revision}\n")
    print(render_config(result))
    return 0


def cmd_run(args) -> int:
    for phase in PHASES:
        input(f"[{phase}] {PROMPTS[phase]} — 준비되면 Enter ")
        capture(args, phase)
    return report(load_session(args.session), args)


def cmd_capture(args) -> int:
    capture(args, args.phase)
    return 0


def cmd_compute(args) -> int:
    return report(load_session(args.session), args)


def cmd_check(args) -> int:
    if args.black and args.white:
        calibration = IRLineCalibration(black=tuple(args.black), white=tuple(args.white),
                                        min_span=args.min_span)
    else:
        result = compute_ir_calibration(load_session(args.session)["phases"],
                                        min_span=args.min_span, min_samples=args.min_samples)
        if not result.ok:
            raise SystemExit("session does not calibrate; run compute first")
        calibration = result.calibration
    print(f"revision {calibration.revision}")
    print("테이프를 왼쪽 → 가운데 → 오른쪽 IR 밑으로 옮기며 표시가 같은 쪽인지 본다. "
          "(left = CORE 는 오른쪽으로 비킨다)")

    def show(values):
        observation = detect_ir_line(values, calibration)
        error = None if observation is None else observation.error
        print(f"raw {values}  -> {ir_side(error):<6} "
              f"{'' if error is None else f'error {error:+.2f}'}")

    _spin_samples(args.topic, args.seconds, on_sample=show)
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    sub = parser.add_subparsers(dest="command", required=True)

    def common(p, *, live):
        p.add_argument("--session", type=Path, required=True)
        p.add_argument("--min-span", type=float, default=100.0)
        p.add_argument("--min-samples", type=int, default=20)
        if live:
            p.add_argument("--topic", default="ir_sensor/range")
            p.add_argument("--seconds", type=float, default=3.0)

    common(sub.add_parser("run"), live=True)
    capture_parser = sub.add_parser("capture")
    capture_parser.add_argument("--phase", choices=PHASES, required=True)
    common(capture_parser, live=True)
    common(sub.add_parser("compute"), live=False)
    check_parser = sub.add_parser("check")
    common(check_parser, live=True)
    check_parser.add_argument("--black", type=float, nargs=3)
    check_parser.add_argument("--white", type=float, nargs=3)
    check_parser.set_defaults(seconds=20.0)
    return parser


def main(argv=None) -> int:
    args = build_parser().parse_args(argv)
    handlers = {"run": cmd_run, "capture": cmd_capture, "compute": cmd_compute,
                "check": cmd_check}
    return handlers[args.command](args)


if __name__ == "__main__":
    sys.exit(main())
