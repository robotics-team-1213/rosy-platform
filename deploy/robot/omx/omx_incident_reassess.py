#!/usr/bin/env python3
"""D-1040: read an arm again after an incident, without moving it, so an AI assessor may clear two kinds on that read.

2026-11-17 two incidents ended with the arm folded and quiet but the session could not say so: arm_b 17:10 lost its
port to a USB hub re-enumeration while writing torque OFF, and arm_a 18:37 saw a wind-up after an orphaned session held
home for 20 min. A later read-only register read showed every motor torque OFF, no hardware error, folded.

`omx_incident.py reassess --arm arm_b --config cell-arm-b-stack.json` reads only the arm's own follower (the board map
/etc/rosy/omx-arm-boards.json; `--device` must be that path) against the arm's own plan home (its cell config, whose
arm_id must be the arm), and refuses unless no live lease and no session holds the arm and the port is free
(register_probe: fuser, exclusive open, unicast PING and READ only). It reads torque, hardware error and position of the
six motors, the cell views' stills (kept under incidents/reassess/ with their sha256) and the motor-fault records the
arm's local incidents name. `clear --reassess` sends that block, bound to each incident it clears, with the AI
assessor's clear; Fleet checks the arm and board against its manifest and decides (core_common machine_clearable).
"""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import sys
import time
import urllib.request

sys.path.insert(0, str(Path(__file__).resolve().parent))
GAP_S = 5.0  # seconds between the two reads (arm_incident.arm_incidents.SAG_GAP_S)
BODY = ("shoulder_pan", "shoulder_lift", "elbow_flex", "wrist_flex", "wrist_roll")  # follower ids 11..15
HELD_VIEWS = {"arm_a": ("top", "arm_a_wrist"), "arm_b": ("top", "arm_b_wrist"), "arm_s": ("arm_s_top", "arm_s_wrist")}


def units(raw, joint, calibration) -> float:
    """LeRobot body (-100..100) or gripper (0..100) units from a raw position."""
    cal = (calibration or {}).get(joint, {})
    lo, hi = cal.get("range_min", 0), cal.get("range_max", 4095)
    fraction = (raw - lo) / (hi - lo)
    return fraction * 100 if joint == "gripper" else fraction * 200 - 100


def viewer_fetch(viewer):
    def fetch(view):  # the site viewer answers only to its own Host name (cell_clear_check)
        request = urllib.request.Request(f"{viewer}/frame/{view}.jpg", headers={"Host": "127.0.0.1:8767"})
        with urllib.request.urlopen(request, timeout=10) as reply:
            return reply.read()
    return fetch


BOARDS = Path("/etc/rosy/omx-arm-boards.json")  # board serial -> arm, the cell's one map
CALIBRATION = Path.home() / ".cache/huggingface/lerobot/calibration/robots/omx_follower"


def follower(arm, device=None, by_id=Path("/dev/serial/by-id")) -> tuple[str, Path]:
    """(board serial, by-id path) of `arm`'s follower from the board map; SystemExit unless exactly one board maps to
    it and is plugged in, or when `device` is given and is not that path."""
    boards = json.loads(Path(os.environ.get("ROSY_OMX_ARM_BOARDS") or BOARDS).read_text(encoding="utf-8"))
    serials = [s for s, a in boards.items() if a == arm]
    paths = sorted(by_id.glob(f"*{serials[0]}*")) if len(serials) == 1 else []
    if len(paths) != 1:
        raise SystemExit(f"{arm}: {len(serials)} boards mapped, {len(paths)} plugged in; not read")
    if device is not None and Path(device) != paths[0]:
        raise SystemExit(f"{arm}: {device} is not this arm's follower ({paths[0]}); not read")
    return serials[0], paths[0]


def fault_records(arm, keep=8) -> list:
    """The motor-fault records this arm's local incidents name, as {name, fault_type, fault} (Fleet has only names)."""
    from omx_incident_fleet import INCIDENTS

    out = {}
    for incident in sorted(INCIDENTS.glob(f"*-{arm}/incident.json"))[-keep:]:
        for path in json.loads(incident.read_text())["facts"].get("fault_records") or []:
            try:
                record = json.loads(Path(path).read_text())
            except (OSError, ValueError):
                continue
            text = " ".join(str(record.get("fault") or "-").split())[:400]
            out[Path(path).name] = {"name": Path(path).name, "fault_type": str(record.get("fault_type"))[:64],
                                    "fault": text}
    return list(out.values())[-keep:]


def _observer_io(run=None, users=None, scan=None, resolve=None):
    import observer_handoff_io as oh_io

    return (
        run or oh_io.systemctl,
        users or oh_io.fuser,
        scan or oh_io.proc_holders,
        resolve or (lambda p: str(Path(p).resolve(strict=True))),
    )


def pause_observer_if_sole_holder(arm, port, *, run=None, users=None, scan=None, resolve=None,
                                  sleep=time.sleep, clock=time.monotonic, timeout_s=5.0) -> bool:
    """Stop `rosy-omx-observer@<arm>` under `session_lock(arm)` iff its MainPID is the sole holder of `port`."""
    import observer_handoff_io as oh_io

    run_fn, users_fn, scan_fn, resolve_fn = _observer_io(run, users, scan, resolve)
    resolved = resolve_fn(port)
    holders = oh_io.port_holders(resolved, users_fn, scan_fn)
    if not holders:
        return False
    unit = f"rosy-omx-observer@{arm}.service"
    if run_fn("is-active", unit).stdout.strip() != "active":
        return False
    main_pid = int(run_fn("show", "-p", "MainPID", "--value", unit).stdout.strip() or 0)
    if main_pid <= 0 or holders != {main_pid}:
        return False
    stopped = run_fn("stop", unit)
    if stopped.returncode != 0:
        raise oh_io.HandoffError(f"could not stop {unit}: {stopped.stderr.strip()}")
    deadline = clock() + timeout_s
    while oh_io.port_holders(resolved, users_fn, scan_fn):
        if clock() >= deadline:
            raise oh_io.HandoffError(f"{resolved} still held after {timeout_s:g} s")
        sleep(0.2)
    return True


def resume_observer(arm, port, *, run=None, users=None, scan=None,
                    sleep=time.sleep, clock=time.monotonic, timeout_s=5.0, resume_s=10.0):
    """Restart `rosy-omx-observer@<arm>` after `session_lock` is closed and confirm it holds `port`."""
    import observer_handoff as oh

    run_fn, users_fn, scan_fn, _ = _observer_io(run, users, scan)
    return oh.restart(arm, run=run_fn, users=users_fn, scan=scan_fn, device=str(port),
                      sleep=sleep, clock=clock, timeout_s=timeout_s, resume_s=resume_s)


def reassess(arm, config, *, device=None, fetch=None, read=None, lease_root=None, by_id=Path("/dev/serial/by-id"),
             calibration_dir=CALIBRATION, now=time.time, sleep=time.sleep, gap=GAP_S, held=True) -> dict:
    """The `remeasured` block (core_common ArmIncidentRemeasure) of `arm`'s own follower and plan home (its cell
    config). The standalone read captures held-box evidence. The legacy clear keeps its original views."""
    import cell_arm_lease
    from cell_clear_check import VIEWS
    from joint_tune import session_lock
    import omx_incident
    from omx_incident_fleet import incidents_dir

    cell = json.loads(Path(config).read_text(encoding="utf-8"))
    if arm not in VIEWS or cell.get("arm_id") != arm:
        raise SystemExit(f"{arm}: {config} is the config of {cell.get('arm_id')!r}; not read")
    serial, port = follower(arm, device, by_id)
    lease = cell_arm_lease.status(arm, lease_root).get(arm)
    if lease and lease["live"]:
        raise SystemExit(f"{arm}: lease held by {lease.get('owner')} ({lease.get('purpose') or '-'}); not read")
    home = json.loads(Path(cell["plan_path"]).expanduser().read_text(encoding="utf-8"))["home"][:len(BODY)]
    cal_file = Path(calibration_dir) / f"{arm}_follower.json"
    if not cal_file.is_file():  # review: a guessed 0..4095 range would mis-judge "folded"
        raise SystemExit(f"{arm}: no follower calibration {cal_file}; not read")
    cal = json.loads(cal_file.read_text(encoding="utf-8"))
    if held:
        jaw_cal = cal.get("gripper", {})
        lo, hi = jaw_cal.get("range_min"), jaw_cal.get("range_max")
        if type(lo) is not int or type(hi) is not int or not 0 <= lo < hi <= 4095:
            raise SystemExit(f"{arm}: no valid gripper calibration in {cal_file}; not read")
    views = zip(("top", "wrist"), HELD_VIEWS[arm]) if held else zip(VIEWS[arm], VIEWS[arm])
    fetch = fetch or viewer_fetch("http://127.0.0.1:8767")
    lock = session_lock(arm)  # SystemExit when a session holds the arm
    paused_obs = False
    try:
        try:
            if read is None:
                import register_probe
                paused_obs = pause_observer_if_sole_holder(arm, port, sleep=sleep)
                read = register_probe.collect  # refuses a port another process holds
            motors = {str(m["id"]): m for m in read(str(port))}
            first_at = now()
            sleep(gap)  # a second read under the same lock and lease: a creeping arm is not at rest
            again = {str(m["id"]): m for m in read(str(port))}
            at = now()
            if sorted(motors) != ["11", "12", "13", "14", "15", "16"] or len(home) != len(BODY):
                raise SystemExit(f"{arm}: read {sorted(motors)} against a home of {len(home)} joints; not a full read")
            if sorted(again) != sorted(motors):
                raise SystemExit(f"{arm}: the second read saw {sorted(again)}; not a full read")
            stills = {}
            for role, view in views:
                data = fetch(view)
                if data[:2] != b"\xff\xd8":
                    raise SystemExit(f"{arm}: the {view} view is not a JPEG")
                stills[role] = data
        finally:
            lock.close()
    finally:
        if paused_obs:
            resume_observer(arm, port, sleep=sleep)

    def signed(m):  # read - home per body joint, units
        return {j: round(units(m[str(11 + i)]["position_raw"], j, cal) - h, 2) for i, (j, h) in enumerate(zip(BODY, home))}
    home_err, first_err = signed(again), signed(motors)
    err = max(abs(v) for v in home_err.values())
    folder = incidents_dir() / "reassess"
    folder.mkdir(parents=True, exist_ok=True)
    stamp, frames = time.strftime("%Y%m%dT%H%M%S", time.localtime(at)), []
    for role, data in stills.items():
        (folder / f"{stamp}-{arm}-{role}.jpg").write_bytes(data)
        frames.append({"role": role, "sha256": hashlib.sha256(data).hexdigest()})
    block = {"arm": arm, "board_serial": serial, "at": round(at, 3),
             "torque_after": {m: max(int(r["torque_enabled"]), int(again[m]["torque_enabled"])) for m, r in sorted(motors.items())},
             "hardware_error": {m: max(int(r["hardware_error"]), int(again[m]["hardware_error"])) for m, r in sorted(motors.items())},
             "folded": err <= omx_incident.HOME_TOL, "max_home_err": round(err, 2),
             "home_err": home_err, "first_home_err": first_err, "first_at": round(first_at, 3),
             "stable": all(abs(home_err[j] - first_err[j]) <= 0.3 for j in BODY) and at - first_at >= gap,
             "frames": frames,
             "fault_records": fault_records(arm)}
    if held:
        first_jaw = units(motors["16"]["position_raw"], "gripper", cal)
        jaw = units(again["16"]["position_raw"], "gripper", cal)
        block.update(first_gripper_pos=first_jaw, gripper_pos=jaw,
                     stable=block["stable"] and abs(jaw - first_jaw) <= 0.3)
    (folder / f"{stamp}-{arm}.json").write_text(json.dumps({"device": str(port), **block}, indent=1))
    return block


def arguments(sub, clear_parser) -> None:
    """The `reassess` command, and `clear --reassess` with the same inputs."""
    r = sub.add_parser("reassess", help="D-1040: read a free arm's registers and stills again (no motion)")
    r.add_argument("--arm", required=True)
    clear_parser.add_argument("--reassess", action="store_true",
                              help="D-1040: read the arm again and send it with the AI assessor's clear "
                                   "(token: --token-file or $ROSY_ARM_ASSESSOR_TOKEN_FILE; --cause and --basis needed)")
    for p in (r, clear_parser):
        p.add_argument("--config", type=Path, help="the arm's own cell config (arm_id, plan_path: its folded home)")
        p.add_argument("--device", help="optional: must be the arm's follower from /etc/rosy/omx-arm-boards.json")
        p.add_argument("--viewer", default="http://127.0.0.1:8767")


def run(args, clear) -> int:
    """omx_incident main's `clear` and `reassess`; a plain clear goes to `clear` as before."""
    if args.command == "clear" and not args.reassess:
        return clear(args.arm, args.note, args.token_file, cause=args.cause, basis=args.basis)
    if not args.config:
        raise SystemExit("--config (the arm's cell config) is required to read the arm")
    token_file = args.token_file if args.command == "clear" else None
    if args.command == "clear":
        token_file = token_file or os.environ.get("ROSY_ARM_ASSESSOR_TOKEN_FILE")
        if not token_file or not args.cause or not args.basis:
            raise SystemExit("clear --reassess is the AI assessor's: its token file, --cause and --basis are required")
    block = reassess(args.arm, args.config, device=args.device, fetch=viewer_fetch(args.viewer), held=args.command == "reassess")
    print(json.dumps({"arm": args.arm, "remeasured": block}))
    if args.command == "reassess":
        return 0
    return clear(args.arm, args.note, Path(token_file), cause=args.cause, basis=args.basis, remeasured=block)
