"""Per-arm non-motion upkeep checks (hold, boards, registers, cameras, light, jaws, map, monitors, TCP) for `cell_upkeep.py`."""
from __future__ import annotations

import glob
import itertools
import json
import re
import statistics
from pathlib import Path

import cell_params as prm
import cell_preflight

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


def check_hold(arm, incidents=None):
    """`incidents` None: where omx_incident keeps holds (and any an older version left in the working directory)."""
    if incidents is None:
        import omx_incident

        path = omx_incident.hold_file(arm)
    else:
        path = Path(incidents) / f"HOLD-{arm}.json"
    if path is None or not path.is_file():
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
            out.append(
                f"{side}.port {port or '(empty)'} is not connected: ping the boards (IDs 1-6 leader, 11-16 follower) and point the config at the one that answers"
            )
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
        caps = [
            f"motor {r['id']} {k}={r[k + '_raw']} (baseline {v})"
            for r in rows
            for k, v in BASELINE.items()
            if r.get(k + "_raw") is not None and r[k + "_raw"] != v
        ]
        return notes, caps

    try:
        notes, caps = problems(io.bus_read(device))
    except Exception as error:
        return row("registers", "fail", f"bus read failed: {error!r}")
    if notes:
        return row(
            "registers",
            "fail",
            "; ".join(notes)
            + ("; caps also off" if caps else "")
            + " - no write is safe; a latched hardware error is rebooted by omx_incident.py, not here",
        )
    if not caps:
        return row("registers", "ok", "torque 0, no hardware error, caps at baseline")
    if not fix:
        return row(
            "registers",
            "fail",
            f"{len(caps)} caps off baseline, e.g. {caps[0]}; rerun with --fix (torque is 0 everywhere)",
        )
    try:
        done = io.bus_fix(device, out_dir / f"{stamp}-{arm}-baseline")
        notes, caps = problems(io.bus_read(device))
    except Exception as error:
        return row("registers", "fail", f"baseline write failed: {error!r}; see {out_dir}/{stamp}-{arm}-baseline")
    if done and not notes and not caps:
        return row("registers", "fixed", "caps were off baseline; commissioning_limits.py --baseline set them, readback ok")
    return row("registers", "fail", f"baseline write did not verify: {(notes + caps)[:3]}")


def check_cameras(arm, cameras, io, fix=False, bus_free=True, usb_recover_fn=None):
    """Every configured frame answers with a JPEG."""
    if usb_recover_fn is None:
        from cell_upkeep import usb_recover as usb_recover_fn

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
            bad.append(
                f"{name}: the viewer serves no '{label}'"
                + (
                    f"; {want} is served as '{served}': use {camera['url'].replace(label + '.jpg', served + '.jpg')}"
                    if served
                    else ""
                )
            )
            continue
        role = io.roles().get(labels.get(label))
        unavailable = bool(role) and "unavailable" in io.unit_tail(role)
        if role and fix and bus_free:
            if unavailable:
                io.unit_restart(role)
                code, body = io.fetch(camera["url"])
                if code == 200 and body.startswith(b"\xff\xd8"):
                    fixed.append(f"{name}: restarted rosy-omx-camera@{role} (it held a device node a reconnect replaced)")
                    top = body if name == "top" else top
                    continue
            note = usb_recover_fn(role, io)
            code, body = io.fetch(camera["url"])
            if code == 200 and body.startswith(b"\xff\xd8"):
                fixed.append(f"{name}: {note}")
                top = body if name == "top" else top
            else:
                bad.append(f"{name}: {note}")
            continue
        if unavailable:
            bad.append(f"{name}: rosy-omx-camera@{role} reports the camera unavailable (restart it after a reconnect)")
            continue
        bad.append(f"{name} {camera['url']}: {code or 'no answer'}" + ("" if code != 200 else ", not a JPEG"))
    if bad:
        return [row("cameras", "fail", "; ".join(bad + fixed))], top
    return [
        row("cameras", "fixed", "; ".join(fixed))
        if fixed
        else row("cameras", "ok", f"{len(cameras)} answer 200 with a JPEG")
    ], top


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
        it = iter(jr.rows_of(path, lambda r: r.get("event") == "sample" and len(r.get("motors", [])) in (6, 7, 8)))
        first = next(it, None)
        if first is None or serial_tail(first["motors"][0]["usb_port"]) != tail:
            continue
        found = {value: [] for value in closed_values}
        last = None
        for r in itertools.chain([first], it):
            g = next((m for m in r["motors"] if m["joint"] == "gripper"), r["motors"][-1])
            command, present = grip_units(g["command_raw"]), grip_units(g["present_raw"])
            for value, hits in found.items():
                if (
                    last is not None
                    and abs(command - value) < 0.2
                    and abs(present - last) < 0.3
                    and abs(g["pwm"]) >= share * g["pwm_limit"]
                    and present - command > gap
                ):
                    hits.append((present, g["pwm"]))
            last = present
        bad = [
            f"closed value below the jaws' stop: target {v}, jaws stopped at {statistics.median(p for p, _ in h):.2f} "
            f"at PWM {statistics.median(w for _, w in h):.0f} ({len(h)} samples)"
            for v, h in found.items()
            if h
        ]
        return row(
            "jaw closed",
            "warn" if bad else "ok",
            "; ".join(bad) or f"no loaded-short samples at {sorted(found)} in {Path(path).name}",
        )
    return row("jaw closed", "ok", "no motor-health log for this arm: nothing to compare")


def check_jaw_open(traces, params):
    """The jaws open as wide as the newest session asked (supports 5-DOF, 6-DOF, and 7-DOF frames via `[-1]`)."""
    import jitter_replay as jr

    open_max, gap = prm.get(params, "gripper.open_max"), prm.get(params, "upkeep.jaw_gap")
    for path in sorted(traces, key=lambda p: -Path(p).stat().st_mtime):
        grip = [
            (r["sent"][-1], r["present"][-1])
            for r in jr.rows_of(path)
            if r.get("sent") and r.get("present") and len(r["sent"]) >= 6 and len(r["present"]) >= 6
        ]
        if not grip:
            continue
        max_sent, max_present = map(max, zip(*grip))  # both maxima in one pass over the trace
        want, reached = min(max_sent, open_max), max_present
        if reached < want - gap:
            return row(
                "jaw open",
                "warn",
                f"the jaws opened only to {reached:.2f} of {want:.2f} in {Path(path).name}: "
                "something limits them (linkage, cable, wedged object); a person checks before torque ON",
            )
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
    return row(
        "map",
        "warn",
        "stale: "
        + ", ".join(result["todo"])
        + "; a person at the power switch runs: cell_calibrate.py --config <cell> auto --commissioning --person-at-switch",
        motion=True,
        steps=result["todo"],
        found={
            k: v
            for k, v in result["check"].items()
            if k in ("camera_moved", "missing_map", "missing_surface", "camera_shift")
        },
    )


def check_monitors(arm, device, logs_dir, since, params, io):
    health = [p for p in sorted(glob.glob(str(logs_dir / "motor-health-*.jsonl"))) if Path(p).stat().st_mtime > since]
    traces = [p for p in sorted(glob.glob(str(logs_dir / "trace-*.jsonl"))) if Path(p).stat().st_mtime > since]
    if not health and not traces:
        return row("monitors", "ok", "no logs newer than the previous report")
    push, jitter = io.replays(health, traces, params)
    tail = serial_tail(device)
    mine = push.get(tail, {})
    shake = next(
        (v for k, v in jitter.items() if k in (tail, arm) or k == {"FF06202D": "arm_a", "FF061D2D": "arm_b"}.get(tail)),
        {},
    )
    notes = [f"wind-up {h['session']} t={h['t']}: {h['reason']}" for h in mine.get("hits", [])[:3]]
    notes += [f"jitter {f['session']} {f['joint']}: {f['reason']}" for f in shake.get("flagged", [])[:3]]
    total = len(mine.get("hits", [])) + len(shake.get("flagged", []))
    if "trace" in jitter:
        notes.append(f"unassigned trace identity; cannot clear {arm} from these logs")
    return row(
        "monitors",
        "warn" if total or "trace" in jitter else "ok",
        (f"{total} hits/flags over {len(health)} health + {len(traces)} trace logs; " + "; ".join(notes))
        if total
        else "; ".join(notes)
        if notes
        else f"no wind-up hits or jitter flags over {len(health)} health + {len(traces)} trace logs",
    )


def check_tcp(config):
    if "tcp_x_m" in config:
        return row("tcp", "ok", f"plans with {config['tcp_x_m']} m: {config.get('tcp_x_m_evidence', 'no evidence recorded')}")
    return row("tcp", "warn", f"stock {TCP_STOCK}, unmeasured (ROSY_OMX_TCP_X_M in the run script decides)")
