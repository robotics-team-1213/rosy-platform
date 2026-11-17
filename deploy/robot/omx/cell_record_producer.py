#!/usr/bin/env python3
"""Read-only OMX cell producers for the Rosy Learning recording workbench (learning-recording.md).

arm_a/arm_b and the four policy cameras (top, side, each arm's wrist) as local producers of
/learning/record: the file contract `descriptor.json`, `events/<sequence>.json` (+ `.jpg`),
`latest.json` under a registered source directory. The arm producer reads only the runner's
`chunk-io/live.json` — the follower state the runner measured and the joint targets it already
sent through its guard (`target`) — in the follower's own LeRobot units (body -100..100,
gripper 0..100); radians/sim conversions stay with the exporter. The camera producer reads
only the cell's read-only viewer HTTP (`FifoCell.frame_receipt`: fresh, advancing frames).
Nothing here commands an arm: this module never opens the command FIFO and holds no device
handle; `test/test_omx_cell_record_producer.py` pins that on the AST.

Rate: the default period is 1/15 s — the two-arm policy's sim dataset FPS
(`tools/sim/omx_two_arm_world.py` FPS), so a 15 FPS recording grid aligns with the sim data.
The runner writes live.json about 10x/s (`chunk_runner`: every fps//10 ticks at fps 30), so
some arm events repeat the last row; a new sequence number is a new observation in this
contract. Cameras must actually serve fresh frames at the grid rate — a slower viewer needs a
lower session FPS.

Clocks: events are stamped with this host's `time.monotonic()` at the read (host-receive
semantics; the live row's own wall-clock `t` is kept in `reference_id`), and clock_domain is
`host-monotonic:<boot_id>` — the workbench must run on the same cell PC. reference_stage is
the contract's required value "post_guard_accepted": the reference is the target the runner
already sent. learning-recording.md's warning about the legacy live file's target as an
acceptance proof still applies — this producer feeds the learning export, not guard acceptance.

Registration layout on the cell PC (the recording config's source_root):

    <source_root>/arm_a/registration.json   {"kind": "arm", "label": "OMX arm_a follower"}
    <source_root>/arm_a/{descriptor.json, events/<seq>.json, latest.json, status.json}
    <source_root>/arm_b/...                 the same for arm_b
    <source_root>/cam_top/registration.json {"kind": "camera", "label": "OMX cell top camera"}
    <source_root>/{cam_side,cam_a_wrist,cam_b_wrist}/...

Run units (this docstring is the one record; the repo installs nothing):

    ~/.config/systemd/user/omx-record-arm@.service
      [Unit]
      Description=OMX learning recording producer (read-only) for %i
      [Service]
      ExecStart=<repo>/deploy/robot/omx/cell_record_producer.py arm --arm %i \
        --live <runner-io-dir>/live.json --config <cell-config.json> --out <source_root>/%i
      Restart=on-failure
    ~/.config/systemd/user/omx-record-camera@.service
      [Unit]
      Description=OMX learning camera recording producer (read-only) for %i
      [Service]
      ExecStart=<repo>/deploy/robot/omx/cell_record_producer.py camera --camera %i \
        --url http://127.0.0.1:<viewer-port>/%i.jpg --out <source_root>/cam_%i
      Restart=on-failure
    systemctl --user enable --now omx-record-arm@arm_a.service omx-record-camera@top.service
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import sys
import time
import uuid
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))  # arm_status_bridge, cell_act_inputs
from arm_status_bridge import JOINTS, STALE_S  # noqa: E402  the runner's joint order and staleness bound

SIM_FPS = 15  # tools/sim/omx_two_arm_world.py FPS: the recording grid this producer feeds
KEEP_EVENTS = 600  # consumed events may go; the workbench catches up at most 256 (learning-recording.md)
ARM_SCHEMA = "rosy.passive-owner-sample/1"
CAMERA_SCHEMA = "rosy.passive-camera-sample/1"
UNITS = "omx-follower-lerobot"  # body joints -100..100, gripper 0..100


def clock_domain() -> str:
    boot = Path("/proc/sys/kernel/random/boot_id")
    return "host-monotonic:" + (boot.read_text().strip() if boot.is_file() else str(uuid.uuid4()))


def _atomic(path: Path, payload: bytes) -> None:
    temporary = path.with_name(path.name + ".tmp")
    temporary.write_bytes(payload)
    os.replace(temporary, path)


class Spool:
    """The producer side of the workbench contract: event first (JPEG before its JSON), latest last."""

    def __init__(self, out: Path, descriptor: dict, label: str):
        self.out, self.descriptor = Path(out), descriptor
        self.out.mkdir(parents=True, exist_ok=True)
        (self.out / "events").mkdir(exist_ok=True)
        registration = self.out / "registration.json"
        if not registration.exists():
            _atomic(registration, json.dumps({"kind": descriptor["kind"], "label": label}).encode())
        _atomic(self.out / "descriptor.json", json.dumps(descriptor).encode())  # a restart is a new epoch
        self.sequence = -1
        for path in (self.out / "events").iterdir():
            if path.name.split(".", 1)[0].isdigit():
                self.sequence = max(self.sequence, int(path.name.split(".", 1)[0]))

    def publish(self, event: dict, *, jpeg: bytes | None = None) -> int:
        self.sequence += 1
        event["sequence"] = self.sequence
        base = self.out / "events" / str(self.sequence)
        if jpeg is not None:
            _atomic(base.with_suffix(".jpg"), jpeg)
        _atomic(base.with_suffix(".json"), json.dumps(event).encode())
        _atomic(self.out / "latest.json", json.dumps(event).encode())
        self._prune()
        return self.sequence

    def status(self, row: dict) -> dict:
        _atomic(self.out / "status.json", json.dumps({"t": round(time.time(), 3), **row}).encode())
        return {"ok": False, **row}

    def _prune(self) -> None:
        if self.sequence % 64:
            return
        cutoff = self.sequence - KEEP_EVENTS
        for path in (self.out / "events").iterdir():
            stem = path.name.split(".", 1)[0]
            if stem.isdigit() and int(stem) < cutoff:
                path.unlink(missing_ok=True)


class ArmProducer:
    """One arm: chunk-io/live.json's state and sent targets as `rosy.passive-owner-sample/1` events."""

    def __init__(self, out: Path, arm: str, *, rule: dict, identity=None, label=None, rate_hz=SIM_FPS,
                 calibration_revision="follower-default-full-range", profile_revision="unspecified",
                 clock=None):
        self.arm = arm
        self.descriptor = {
            "kind": "arm",
            "source_identity": identity or f"omx-cell:{arm}",
            "session_epoch": str(uuid.uuid4()),
            "clock_domain": (clock or clock_domain)(),
            "rate_hz": float(rate_hz),
            "owner_id": f"{arm}:chunk_runner",
            "joint_names": list(JOINTS),
            "state_units": UNITS,
            "action_units": UNITS,
            "units_note": "body joints -100..100, gripper 0..100 (LeRobot follower units)",
            "calibration_revision": calibration_revision,
            "profile_revision": profile_revision,
            "state_producer": "chunk_runner.live.json:state",
            "reference_producer": "chunk_runner.live.json:target",
            "reference_stage": "post_guard_accepted",
            "grip_rule": {"held_30mm": float(rule["held_30mm"]), "gap_mm_per_unit": float(rule["gap_mm_per_unit"])},
        }
        self.spool = Spool(out, self.descriptor, label or f"OMX {arm} follower")

    def poll(self, live: Path, *, monotonic=time.monotonic, wall=time.time) -> dict:
        """One read of the runner's live file; a published event, or the reason there is none."""
        try:
            row = json.loads(Path(live).read_text())
            t, state, target = row.get("t"), row.get("state"), row.get("target")
            if not isinstance(t, (int, float)) or not isinstance(state, list) or not isinstance(target, list):
                raise ValueError("live row lacks t/state/target")
            if len(state) != len(JOINTS) or len(target) != len(JOINTS):
                raise ValueError(f"live row is not {len(JOINTS)} joints")
            if not all(isinstance(v, (int, float)) and math.isfinite(v) for v in [*state, *target]):
                raise ValueError("live row has a non-finite joint value")
            if wall() - t > STALE_S:  # arm_status_bridge.STALE_S: the runner has stopped
                raise ValueError(f"live row is {wall() - t:.1f} s old (stale after {STALE_S} s)")
        except (OSError, ValueError, TypeError) as error:
            return self.spool.status({"reason": f"{type(error).__name__}: {error}"})
        at = monotonic()  # host-receive stamps; the live row's own wall t stays in reference_id
        event = {key: self.descriptor[key] for key in (
            "owner_id", "source_identity", "session_epoch", "clock_domain", "joint_names", "state_units",
            "action_units", "calibration_revision", "profile_revision", "reference_stage")}
        event.update(schema=ARM_SCHEMA, state_timestamp=at, reference_timestamp=at,
                     state=[float(v) for v in state], accepted_reference=[float(v) for v in target],
                     reference_id=f"{self.arm}-live-target@{t}")
        return {"ok": True, "sequence": self.spool.publish(event), "live_t": t}


class CameraProducer:
    """One camera: viewer frames (`FifoCell.frame_receipt`) as `rosy.passive-camera-sample/1` events."""

    def __init__(self, out: Path, camera: str, *, shape, identity=None, label=None, rate_hz=SIM_FPS,
                 clock=None):
        self.shape = (int(shape[0]), int(shape[1]))
        self.descriptor = {
            "kind": "camera",
            "source_identity": identity or f"omx-cell-camera:{camera}",
            "session_epoch": str(uuid.uuid4()),
            "clock_domain": (clock or clock_domain)(),
            "rate_hz": float(rate_hz),
            "shape": [3, *self.shape],
            "timestamp_semantics": "host_receive",
        }
        self.spool = Spool(out, self.descriptor, label or f"OMX cell {camera} camera")

    def poll(self, receipt: dict, *, monotonic=time.monotonic) -> dict:
        """One `frame_receipt` result; a published event, or the reason there is none."""
        try:
            image, jpeg = receipt["image"], receipt["jpeg_bytes"]
            if tuple(image.shape[:2]) != self.shape:
                raise ValueError(f"frame {tuple(image.shape[:2])} differs from frozen shape {self.shape}")
            event = {key: self.descriptor[key] for key in (
                "source_identity", "session_epoch", "clock_domain", "shape", "timestamp_semantics")}
            event.update(schema=CAMERA_SCHEMA, timestamp=monotonic(),
                         jpeg_sha256=hashlib.sha256(jpeg).hexdigest())
            return {"ok": True, "sequence": self.spool.publish(event, jpeg=jpeg),
                    "source_seq": receipt["source_seq"]}
        except (KeyError, ValueError, TypeError) as error:
            return self.spool.status({"reason": f"{type(error).__name__}: {error}"})


def _loop(step, period: float) -> None:
    try:
        while True:
            row = step()
            if not row.get("ok"):
                print(json.dumps(row), flush=True)
            time.sleep(period)
    except KeyboardInterrupt:
        print(json.dumps({"ok": True, "stopped": True}), flush=True)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest="kind", required=True)
    arm = sub.add_parser("arm", help="one arm's runner live.json -> producer spool")
    arm.add_argument("--arm", required=True, help="arm_a or arm_b")
    arm.add_argument("--live", type=Path, required=True, help="the runner's chunk-io/live.json (read only)")
    arm.add_argument("--config", type=Path, required=True,
                     help="cell config json; its arm_id/work_dir locate the arm-cal gripper rule")
    arm.add_argument("--out", type=Path, required=True, help="registered producer directory (source_root/<arm>)")
    arm.add_argument("--calibration", type=Path, help="follower calibration json; sha256 becomes calibration_revision")
    arm.add_argument("--profile-revision", default="unspecified")
    arm.add_argument("--identity", help="physical identity the stored profile will carry (default omx-cell:<arm>)")
    arm.add_argument("--label", help="registration display label (default 'OMX <arm> follower')")
    arm.add_argument("--period", type=float, default=1.0 / SIM_FPS)
    camera = sub.add_parser("camera", help="one viewer camera -> producer spool")
    camera.add_argument("--camera", required=True, help="camera name, e.g. top, side, wrist")
    camera.add_argument("--url", required=True, help="the read-only viewer HTTP URL of this camera")
    camera.add_argument("--out", type=Path, required=True, help="registered producer directory (source_root/cam_<name>)")
    camera.add_argument("--identity", help="physical identity the stored profile will carry")
    camera.add_argument("--label", help="registration display label (default 'OMX cell <name> camera')")
    camera.add_argument("--period", type=float, default=1.0 / SIM_FPS)
    args = parser.parse_args(argv)

    if args.kind == "arm":
        import cell_act_inputs  # the two-arm input 정본's own gripper rule, never a copy of it

        rule = cell_act_inputs.grip_rule(json.loads(args.config.read_text(encoding="utf-8-sig")), args.arm)
        producer = ArmProducer(args.out, args.arm, rule=rule, identity=args.identity, label=args.label,
                               rate_hz=1.0 / args.period,
                               calibration_revision=(hashlib.sha256(args.calibration.read_bytes()).hexdigest()
                                                     if args.calibration else "follower-default-full-range"),
                               profile_revision=args.profile_revision)
        print(json.dumps({"started": True, "arm": args.arm, "out": str(args.out),
                          "rate_hz": producer.descriptor["rate_hz"],
                          "grip_rule": producer.descriptor["grip_rule"]}), flush=True)
        _loop(lambda: producer.poll(args.live), args.period)
        return

    from cell_pipeline_io import FifoCell  # the read-only camera viewer; frame_receipt never touches a FIFO

    cell = FifoCell(Path("."), {args.camera: args.url})  # io unused: only the viewer HTTP is read
    first = cell.frame_receipt(args.camera)  # one fresh frame freezes the declared shape
    producer = CameraProducer(args.out, args.camera, shape=first["image"].shape[:2],
                              identity=args.identity, label=args.label, rate_hz=1.0 / args.period)
    previous = {"camera": args.camera, "source_seq": first["source_seq"],
                "source_stamp": first["source_stamp"], "etag": first["etag"]}
    print(json.dumps({"started": True, "camera": args.camera, "out": str(args.out),
                      "shape": producer.descriptor["shape"]}), flush=True)
    producer.poll(first)

    def step():
        nonlocal previous
        try:
            receipt = cell.frame_receipt(args.camera, previous=previous)
        except (OSError, ValueError, KeyError) as error:
            return producer.spool.status({"reason": f"{type(error).__name__}: {error}"})
        previous = {"camera": args.camera, "source_seq": receipt["source_seq"],
                    "source_stamp": receipt["source_stamp"], "etag": receipt["etag"]}
        return producer.poll(receipt)

    _loop(step, args.period)


if __name__ == "__main__":
    main()
