#!/usr/bin/env python3
"""One upkeep pass over every arm of the OMX cell: what went wrong by hand on 2026-11-03/04, as checks.

  cell_upkeep.py upkeep-arms.json [--fix] [--out upkeep] [--incidents incidents] [--since EPOCH]

The manifest maps an arm name to {"cell": <cell config>, "record": <record config>, "chunks": <chunk library>}
(paths relative to the manifest). Per arm, in this order: held (incidents/HOLD-<arm>.json), boards (record config
robot.port / teleop.port exist), bus ownership (no record_session.py for the arm, per-arm lock free), follower
registers (torque 0, no hardware error, caps at the commissioning baseline), cameras (200 + JPEG, top light gate),
jaw closed value against the latest motor-health log, the jaw opening against the newest session trace, the calibration map (read-only cell_calibrate.check), the
after-session monitors (push_replay, jitter_replay) over the logs newer than the previous report, and the planning TCP.

No motion, ever. With --fix the only write is `commissioning_limits.py --baseline`, and only when every follower
motor reads torque 0 with no hardware error and nothing owns the bus. A latched hardware error is reported, not
rebooted (omx_incident.py owns that). Each arm's report goes to <out>/<stamp>-<arm>.json; exit 0 only when every arm is ready.
Verdicts: ready | needs_motion_step (only the supervised cell_calibrate steps are left) | needs_person.
"""
from __future__ import annotations

import argparse
import glob
import json
import re
import statistics
import subprocess
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import cell_params as prm  # noqa: E402
import cell_preflight  # noqa: E402

TCP_STOCK = 0.09193
BAD = ("fail", "warn", "skipped")


def grip_units(raw):
    """LeRobot's gripper value (RANGE_0_100). shortcut: assumes the arm's calibration range 0..4095 (arm_a, arm_b
    2026-11-03); read the calibration file's range_min/max when an arm is calibrated differently."""
    return raw * 100 / 4095


def serial_tail(device) -> str:
    """The USB serial tail motor-health logs name an arm by (the same cut push_replay and jitter_replay use)."""
    return str(device).rsplit("_", 1)[-1].split("-")[0][-8:]


def row(check, status, detail, **extra):
    return {"check": check, "status": status, "detail": detail, **extra}


# ---- hardware seams: the defaults touch the machine, tests pass fakes -------------------------------------------

def fetch_url(url):
    """(HTTP status, body); status 0 when nothing answers."""
    try:
        with urllib.request.urlopen(url, timeout=5) as response:
            return response.status, response.read()
    except urllib.error.HTTPError as error:
        return error.code, b""
    except OSError:
        return 0, b""


def decode_frame(body, gray=False):
    import cv2
    import numpy as np

    return cv2.imdecode(np.frombuffer(body, np.uint8), cv2.IMREAD_GRAYSCALE if gray else cv2.IMREAD_COLOR)


def bus_read(device):
    from register_probe import open_readonly_port, read_motors

    with open_readonly_port(device) as port:
        return read_motors(port, allow_fault=True)


def bus_fix(device, out):
    import commissioning_limits

    out.parent.mkdir(parents=True, exist_ok=True)
    return commissioning_limits.main(["--device", str(device), "--baseline", "--output", str(out)]) == 0


def viewer_labels() -> dict:
    """label -> topic the camera viewer serves at /frame/<label>.jpg (omx-camera-view.env ROSY_VIEW_ARGS)."""
    env = Path.home() / ".config/rosy/omx-camera-view.env"
    return dict(re.findall(r"--camera-topic\s+(\w+)=(\S+?)(?=[\s\"]|$)", env.read_text())) if env.exists() else {}


def camera_roles() -> dict:
    """topic -> registry role (its preview unit is rosy-omx-camera@<role>)."""
    path = Path.home() / ".config/rosy/omx-cameras.json"
    return {c["topic"]: c["role"] for c in json.loads(path.read_text())["cameras"]} if path.exists() else {}


def unit_tail(role) -> str:
    return subprocess.run(["journalctl", "--user", "-u", f"rosy-omx-camera@{role}", "-n", "1", "-o", "cat", "--no-pager"],
                          capture_output=True, text=True).stdout


def unit_restart(role) -> None:
    subprocess.run(["systemctl", "--user", "restart", f"rosy-omx-camera@{role}"], check=True)
    time.sleep(8)  # the preview republishes within a few seconds (2026-11-04)


def sessions():
    """Command lines of every running record_session.py: a `--io chunk-io` one is the runner that owns the bus."""
    text = subprocess.run(["ps", "-eo", "args"], capture_output=True, text=True).stdout
    return [line for line in text.splitlines() if "record_session.py" in line]


def lock_free(arm) -> bool:
    """The cell lock (shared, as an arm session takes it) and the arm's own lock can both be taken now."""
    import fcntl

    from joint_tune import lock_root

    ok = True
    for name, mode in (("session.lock", fcntl.LOCK_SH), (f"session-{arm}.lock", fcntl.LOCK_EX)):
        path = lock_root() / name
        if not path.exists():
            continue
        with path.open("a") as handle:
            try:
                fcntl.flock(handle, mode | fcntl.LOCK_NB)
            except BlockingIOError:
                ok = False
    return ok


def calibrate_check(config, calibration, frame, params):
    import cell_calibrate as cc

    found = cc.check(config, calibration, [], frame, params)
    return {"check": found, "todo": cc.stale(found)}


def replays(health, traces, params):
    import jitter_replay
    import push_replay

    return push_replay.replay(health, params), jitter_replay.replay(traces, health, params)


class Io:
    def __init__(self, **seams):
        self.fetch, self.decode, self.bus_read, self.bus_fix = fetch_url, decode_frame, bus_read, bus_fix
        self.sessions, self.lock_free, self.calibrate, self.replays = sessions, lock_free, calibrate_check, replays
        self.labels, self.roles, self.unit_tail, self.unit_restart = viewer_labels, camera_roles, unit_tail, unit_restart
        for name, fn in seams.items():
            if not hasattr(self, name):
                raise TypeError(f"unknown seam {name}")
            setattr(self, name, fn)


# ---- checks ------------------------------------------------------------------------------------------------------

def check_hold(arm, incidents):
    path = Path(incidents) / f"HOLD-{arm}.json"
    if not path.is_file():
        return row("hold", "ok", "no hold")
    try:
        reason = json.loads(path.read_text())["reason"]
    except (ValueError, KeyError, OSError):
        reason = "unreadable hold file"
    return row("hold", "fail", f"HOLD-{arm}.json: {reason}")


def check_boards(record):
    out = []
    for side in ("robot", "teleop"):
        port = (record.get(side) or {}).get("port")
        if not port or not Path(port).exists():
            out.append(f"{side}.port {port or '(empty)'} is not connected: ping the boards (IDs 1-6 leader, 11-16 follower) and point the config at the one that answers")
    return row("boards", "fail", "; ".join(out)) if out else row("boards", "ok", "robot and teleop ports exist")


def bus_owner(arm, io):
    for line in io.sessions():
        named = re.search(r"--arm[ =](\S+)", line)
        if not named or named.group(1) == arm:
            return f"record_session.py running: {line.strip()[:120]}"
    return None if io.lock_free(arm) else f"session lock for {arm} is held"


def check_registers(arm, device, io, fix, out_dir, stamp):
    from joint_tune import BASELINE

    def problems(rows):
        notes = [f"motor {r['id']} torque ON" for r in rows if r["torque_enabled"]]
        notes += [f"motor {r['id']} hardware_error {r['hardware_error']}" for r in rows if r["hardware_error"]]
        caps = [f"motor {r['id']} {k}={r[k + '_raw']} (baseline {v})" for r in rows for k, v in BASELINE.items()
                if r.get(k + "_raw") is not None and r[k + "_raw"] != v]
        return notes, caps

    try:
        notes, caps = problems(io.bus_read(device))
    except Exception as error:  # a busy or absent port is a finding, not a crash
        return row("registers", "fail", f"bus read failed: {error!r}")
    if notes:
        return row("registers", "fail", "; ".join(notes) + ("; caps also off" if caps else "")
                   + " - no write is safe; a latched hardware error is rebooted by omx_incident.py, not here")
    if not caps:
        return row("registers", "ok", "torque 0, no hardware error, caps at baseline")
    if not fix:
        return row("registers", "fail", f"{len(caps)} caps off baseline, e.g. {caps[0]}; rerun with --fix (torque is 0 everywhere)")
    try:
        done = io.bus_fix(device, out_dir / f"{stamp}-{arm}-baseline")
        notes, caps = problems(io.bus_read(device))
    except Exception as error:
        return row("registers", "fail", f"baseline write failed: {error!r}; see {out_dir}/{stamp}-{arm}-baseline")
    if done and not notes and not caps:
        return row("registers", "fixed", "caps were off baseline; commissioning_limits.py --baseline set them, readback ok")
    return row("registers", "fail", f"baseline write did not verify: {(notes + caps)[:3]}")


def check_cameras(arm, cameras, io, fix=False, bus_free=True):
    """Every configured frame answers with a JPEG. Two failures of 2026-11-04 are told apart: a label the viewer does
    not serve (arm_a's wrist is `front`, not `arm_a_wrist`: the config is wrong and the right URL is named) and a
    preview unit still polling a device node a reconnect replaced ("selected camera is unavailable": restarted with
    --fix when no session runs)."""
    bad, fixed, top = [], [], None
    for name, camera in cameras.items():
        code, body = io.fetch(camera["url"])
        if code == 200 and body.startswith(b"\xff\xd8"):
            top = body if name == "top" else top
            continue
        label, labels = Path(camera["url"]).stem, io.labels()
        if labels and label not in labels:
            want = f"/{arm}_{name}_camera/image_raw"
            served = next((k for k, v in labels.items() if v == want), None)
            bad.append(f"{name}: the viewer serves no '{label}'" + (
                f"; {want} is served as '{served}': use {camera['url'].replace(label + '.jpg', served + '.jpg')}" if served else ""))
            continue
        role = io.roles().get(labels.get(label))
        if role and "unavailable" in io.unit_tail(role):
            if fix and bus_free:
                io.unit_restart(role)
                code, body = io.fetch(camera["url"])
                if code == 200 and body.startswith(b"\xff\xd8"):
                    fixed.append(f"{name}: restarted rosy-omx-camera@{role} (it held a device node a reconnect replaced)")
                    top = body if name == "top" else top
                    continue
            bad.append(f"{name}: rosy-omx-camera@{role} reports the camera unavailable (restart it after a reconnect)")
            continue
        bad.append(f"{name} {camera['url']}: {code or 'no answer'}" + ("" if code != 200 else ", not a JPEG"))
    if bad:
        return [row("cameras", "fail", "; ".join(bad + fixed))], top
    return [row("cameras", "fixed", "; ".join(fixed)) if fixed
            else row("cameras", "ok", f"{len(cameras)} answer 200 with a JPEG")], top


def check_light(top, params, io):
    gray = io.decode(top, gray=True) if top else None
    if gray is None:
        return row("light top", "skipped", "no top frame")
    _, ok, why = cell_preflight.lights({"top": gray}, params)[0]
    return row("light top", "ok" if ok else "fail", why)


def check_jaws(arm, device, closed_values, health_logs, params):
    import jitter_replay as jr

    tail, gap, share = serial_tail(device), prm.get(params, "upkeep.jaw_gap"), prm.get(params, "windup.jaw_pwm")
    for path in sorted(health_logs, key=lambda p: -Path(p).stat().st_mtime):
        first = next(iter(jr.rows_of(path, lambda r: r.get("event") == "sample" and len(r.get("motors", [])) == 6)), None)
        if first is None or serial_tail(first["motors"][0]["usb_port"]) != tail:
            continue
        found = {value: [] for value in closed_values}
        last = None
        for r in jr.rows_of(path, lambda r: r.get("event") == "sample" and len(r.get("motors", [])) == 6):
            g = next(m for m in r["motors"] if m["joint"] == "gripper")
            command, present = grip_units(g["command_raw"]), grip_units(g["present_raw"])
            for value, hits in found.items():
                if (last is not None and abs(command - value) < 0.2 and abs(present - last) < 0.3
                        and abs(g["pwm"]) >= share * g["pwm_limit"] and present - command > gap):
                    hits.append((present, g["pwm"]))
            last = present
        bad = [f"closed value below the jaws' stop: target {v}, jaws stopped at {statistics.median(p for p, _ in h):.2f} "
               f"at PWM {statistics.median(w for _, w in h):.0f} ({len(h)} samples)" for v, h in found.items() if h]
        return row("jaw closed", "warn" if bad else "ok", "; ".join(bad) or f"no loaded-short samples at {sorted(found)} in {Path(path).name}")
    return row("jaw closed", "ok", "no motor-health log for this arm: nothing to compare")


def check_jaw_open(traces, params):
    """The jaws open as wide as the newest session asked. 2026-11-04: after a wind-up arm_b's jaws stopped at 53.9
    against 58.6 sent (61.2 at 03:00) while the frames and the VLM saw nothing; a hold was cleared on them."""
    import jitter_replay as jr

    open_max, gap = prm.get(params, "gripper.open_max"), prm.get(params, "upkeep.jaw_gap")
    for path in sorted(traces, key=lambda p: -Path(p).stat().st_mtime):
        grip = [(r["sent"][5], r["present"][5]) for r in jr.rows_of(path) if r.get("sent") and r.get("present")]
        if not grip:
            continue
        want, reached = min(max(s for s, _ in grip), open_max), max(p for _, p in grip)
        if reached < want - gap:
            return row("jaw open", "warn", f"the jaws opened only to {reached:.2f} of {want:.2f} in {Path(path).name}: "
                                           "something limits them (linkage, cable, wedged object); a person checks before torque ON")
        return row("jaw open", "ok", f"opened to {reached:.2f} (asked {want:.2f}) in {Path(path).name}")
    return row("jaw open", "ok", "no session trace for this arm: nothing to compare")


def check_map(config, params, top, io):
    if top is None:
        return row("map", "skipped", "no top frame")
    calibration_path = Path(config["calibration_path"]).expanduser()
    config = dict(config, calibration_path=str(calibration_path), params=params)
    if calibration_path.exists():
        calibration = json.loads(calibration_path.read_text())
    else:
        import cell_calibration

        calibration = {"schema": cell_calibration.SCHEMA, "sites": {}}
    result = io.calibrate(config, calibration, io.decode(top), params)
    if not result["todo"]:
        return row("map", "ok", "map, camera pose and surfaces agree")
    return row("map", "warn", "stale: " + ", ".join(result["todo"]) + "; a person at the power switch runs: cell_calibrate.py --config <cell> auto --commissioning --person-at-switch",
               motion=True, steps=result["todo"],
               found={k: v for k, v in result["check"].items() if k in ("camera_moved", "missing_map", "missing_surface", "camera_shift")})


def check_monitors(arm, device, logs_dir, since, params, io):
    health = [p for p in sorted(glob.glob(str(logs_dir / "motor-health-*.jsonl"))) if Path(p).stat().st_mtime > since]
    traces = [p for p in sorted(glob.glob(str(logs_dir / "trace-*.jsonl"))) if Path(p).stat().st_mtime > since]
    if not health and not traces:
        return row("monitors", "ok", "no logs newer than the previous report")
    push, jitter = io.replays(health, traces, params)
    tail = serial_tail(device)
    mine = push.get(tail, {})
    shake = next((v for k, v in jitter.items() if k in (tail, arm) or k == {"FF06202D": "arm_a", "FF061D2D": "arm_b"}.get(tail)), {})
    notes = [f"wind-up {h['session']} t={h['t']}: {h['reason']}" for h in mine.get("hits", [])[:3]]
    notes += [f"jitter {f['session']} {f['joint']}: {f['reason']}" for f in shake.get("flagged", [])[:3]]
    total = len(mine.get("hits", [])) + len(shake.get("flagged", []))
    return row("monitors", "warn" if total else "ok",
               (f"{total} hits/flags over {len(health)} health + {len(traces)} trace logs; " + "; ".join(notes)) if total
               else f"no wind-up hits or jitter flags over {len(health)} health + {len(traces)} trace logs")


def check_tcp(config):
    if "tcp_x_m" in config:
        return row("tcp", "ok", f"plans with {config['tcp_x_m']} m: {config.get('tcp_x_m_evidence', 'no evidence recorded')}")
    # an unmeasured jaw put arm_b's tips 18 mm above every planned height (2026-11-03): not ready until measured
    return row("tcp", "warn", f"stock {TCP_STOCK}, unmeasured (ROSY_OMX_TCP_X_M in the run script decides)")


# ---- one arm, the run ---------------------------------------------------------------------------------------------

def rel(base, path):
    return str(Path(path).expanduser() if Path(path).expanduser().is_absolute() else base / path)


def previous_report(out_dir, arm):
    times = [p.stat().st_mtime for p in out_dir.glob(f"*-{arm}.json")]
    return max(times, default=0.0)


def upkeep_arm(arm, spec, fix, io, out_dir, incidents, stamp, since=None):
    base = Path(spec.get("_base", "."))
    cell = json.loads(Path(rel(base, spec["cell"])).read_text(encoding="utf-8"))
    record = json.loads(Path(rel(base, spec["record"])).read_text(encoding="utf-8"))
    library = json.loads(Path(rel(base, spec["chunks"])).read_text(encoding="utf-8"))
    cell_dir = Path(rel(base, spec["cell"])).parent
    params = prm.load(rel(cell_dir, cell["params_path"]) if cell.get("params_path") else None)["values"]
    device = (record.get("robot") or {}).get("port") or ""
    checks = [check_hold(arm, incidents), check_boards(record)]
    owner = bus_owner(arm, io)
    if owner:
        checks.append(row("bus ownership", "skipped", owner + "; register checks skipped, wait for the session"))
        checks.append(row("registers", "skipped", "bus is owned"))
    else:
        checks.append(row("bus ownership", "ok", "no record_session.py, lock free"))
        checks.append(check_registers(arm, device, io, fix, out_dir, stamp) if Path(device).exists()
                      else row("registers", "skipped", "follower board missing"))
    cameras, top = check_cameras(arm, cell.get("cameras", {}), io, fix, bus_free=owner is None)
    checks += cameras + [check_light(top, params, io)]
    logs_dir = Path(rel(base, spec["record"])).parent
    closed = {float(library["gripper_closed"])} if library.get("gripper_closed") is not None else set()
    plan_path = cell.get("plan_path")
    if plan_path and Path(plan_path).expanduser().exists():
        closed.add(float(json.loads(Path(plan_path).expanduser().read_text())["grip_closed"]))
    checks.append(check_jaws(arm, device, closed, glob.glob(str(logs_dir / "motor-health-*.jsonl")), params))
    checks.append(check_jaw_open(glob.glob(str(logs_dir / f"trace-{arm}-*.jsonl")), params))
    checks.append(check_map(cell, params, top, io))
    checks.append(check_monitors(arm, device, logs_dir, previous_report(out_dir, arm) if since is None else since, params, io))
    checks.append(check_tcp(cell))
    bad = [c for c in checks if c["status"] in BAD]
    verdict = "ready" if not bad else "needs_motion_step" if all(c.get("motion") for c in bad) else "needs_person"
    return {"arm": arm, "stamp": stamp, "at": time.time(), "verdict": verdict, "fix": fix, "checks": checks}


def run(arms: dict, fix: bool = False, *, io: Io | None = None, out_dir="upkeep", incidents="incidents", since=None,
        stamp=None) -> dict:
    """{arm: report}; each report is also written to <out_dir>/<stamp>-<arm>.json."""
    io, out_dir, reports = io or Io(), Path(out_dir), {}
    stamp = stamp or time.strftime("%Y%m%dT%H%M%S")
    out_dir.mkdir(parents=True, exist_ok=True)
    for arm, spec in arms.items():
        if not re.fullmatch(r"[A-Za-z0-9_-]{1,32}", arm):
            raise ValueError(f"arm name {arm!r} is not a plain name")
        reports[arm] = upkeep_arm(arm, spec, fix, io, out_dir, incidents, stamp, since)
        (out_dir / f"{stamp}-{arm}.json").write_text(json.dumps(reports[arm], indent=1, default=str))
    return reports


def summary(reports) -> str:
    lines = []
    for arm, report in reports.items():
        lines.append(f"== {arm}: {report['verdict']}")
        lines += [f"   {c['status']:7s} {c['check']}: {c['detail']}" for c in report["checks"]]
    return "\n".join(lines)


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("manifest", type=Path)
    ap.add_argument("--fix", action="store_true", help="lower raised follower caps (torque 0 everywhere, bus free)")
    ap.add_argument("--out", default="upkeep")
    ap.add_argument("--incidents", default="incidents")
    ap.add_argument("--since", type=float, help="replay logs newer than this epoch (default: the previous report)")
    args = ap.parse_args(argv)
    arms = json.loads(args.manifest.read_text(encoding="utf-8"))
    for spec in arms.values():
        spec["_base"] = str(args.manifest.resolve().parent)
    reports = run(arms, args.fix, out_dir=args.out, incidents=args.incidents, since=args.since)
    print(summary(reports))
    return 0 if all(r["verdict"] == "ready" for r in reports.values()) else 1


if __name__ == "__main__":
    sys.exit(main())
