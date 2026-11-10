#!/usr/bin/env python3
"""A page on the cell PC to see and tune the arm S thresholds (rosy.omx-cell-params.v1). Local only: 127.0.0.1.

    python3 cell_params_web.py --file stack=~/cell-params-stack.json --file floor=~/cell-params-floor.json
    ssh -L 8772:127.0.0.1:8772 <cell-pc>     # from another PC, same port number

Every parameter is listed; vision thresholds and tolerances can be changed, guards and motion values cannot
(lock_reason). A save validates with cell_params, replaces the file atomically and appends the previous entries to
<file>.history.jsonl. It is refused while a session runs: a run's processes read the file at different moments, and
its attempt rows would then name values it did not use. New values apply from the next run. Run it as the user that
runs the sessions, with the same ROSY_OMX_HOME: the lock it checks is printed at start.

`--caps arm_b=caps.json [--profile arm_b=robot-profile.json]` also shows, read-only, each follower motor's servo values
and the layer that set them, as `record_session --caps --operating-profile` would use them (session_caps.servo_layers).
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import sys
import tempfile
import threading
import time
from contextlib import contextmanager
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import cell_params as prm  # noqa: E402

PAGE = Path(__file__).with_name("cell_params_web.html")
# Fail closed: a group or unit not named here stays locked, so a new guard cannot become editable by accident.
EDITABLE_GROUPS = {"objects", "track", "diagnose", "preflight", "pinch", "reach", "look", "wrist", "pivot"}
VISION_UNITS = {"lab", "px", "gray", "grey", "ratio", "deg", "mm", "count", "s", "v4l2"}
MOTION = {"wrist.probe_mm", "wrist.z_probe_mm", "wrist.servo_total_mm", "wrist.servo_iter", "wrist.cal_offset_mm",
          "wrist.tip_to_top_mm", "look.other_finger_deg", "look.other_finger_mm", "pivot.bias_reach_mm",
          "pivot.over_top_mm", "pivot.over_clear_mm", "pivot.settle_limit_s", "pivot.settle_step_s",
          # feedback gains, and the values that decide how near the jaws may come or whether a grasp goes ahead
          "reach.gain", "wrist.servo_gain", "wrist.topmap_disagree_mm", "wrist.axis_tol_deg", "look.mark_err_mm",
          "objects.split_gap_mm", "objects.split_stagger_mm", "pinch.min_gap_mm", "pinch.width_tol"}
HISTORY_SHOWN = 8
NOTE_MAX = 300


def lock_reason(name: str) -> str | None:
    """Why this page will not change a parameter, None when it may."""
    group, unit = name.split(".", 1)[0], prm.DEFAULTS[name][1]
    if group not in EDITABLE_GROUPS:
        return "안전·동작 묶음"
    if unit == "flag":
        return "단계를 켜고 끄는 값"
    if unit not in VISION_UNITS:
        return "높이·힘·관절 값"
    if "max_" in name or name in MOTION:
        return "움직임 범위·이득·틈 값"
    return None


def session_busy() -> bool:
    """True while any OMX session holds the cell lock. Reads /proc/locks: the page polls this, and taking the lock
    even briefly would make a session starting in that instant exit."""
    from joint_tune import lock_root

    try:
        inode = (lock_root() / "session.lock").stat().st_ino
    except FileNotFoundError:
        return False
    try:
        rows = Path("/proc/locks").read_text(encoding="ascii").splitlines()
    except OSError:
        return True  # unknown counts as busy: the page only refuses a save
    return any(field.endswith(f":{inode}") for row in rows for field in row.split())


def _digest(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()[:12]


class Conflict(ValueError):
    """The file changed after the page read it, or a session holds the cell."""


@contextmanager
def cell_hold():
    """Hold the cell exclusively while a save reads and replaces the file: no session starts between the check and the
    write, and a second page cannot overwrite this one."""
    # shortcut: a session starting in these milliseconds exits and must be restarted; a person pressed save, so it is
    # rare and visible. A whole-cell session ending in the same milliseconds keeps test jobs held off until the busy
    # marker expires (joint_tune.hold_test_jobs). If either ever matters, make those wait briefly for this hold.
    import fcntl

    from joint_tune import lock_root

    root = lock_root()
    root.mkdir(parents=True, exist_ok=True)
    with (root / "session.lock").open("a") as handle:
        try:
            fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            raise Conflict("세션이 실행 중이라 저장하지 않았습니다. 끝난 뒤 다시 저장하세요.") from None
        yield


class ParamFiles:
    def __init__(self, files: dict, busy=session_busy, hold=cell_hold):
        self.files = {name: Path(path).expanduser().resolve() for name, path in files.items()}
        self.busy, self.hold, self.lock = busy, hold, threading.Lock()

    def _history(self, path: Path) -> list:
        history = path.with_name(path.name + ".history.jsonl")
        if not history.exists():
            return []
        rows = []
        for line in reversed(history.read_text(encoding="utf-8").splitlines()[-HISTORY_SHOWN:]):
            try:
                rows.append(json.loads(line))
            except ValueError:  # a line torn by a crash must not hide the values
                continue
        return rows

    def _one(self, name: str, path: Path) -> dict:
        try:
            raw = path.read_bytes()
            entries = json.loads(raw.decode("utf-8-sig"))["params"]
            effective = prm.load(path)
            history = self._history(path)
        except (OSError, ValueError, KeyError, TypeError) as exc:
            return {"name": name, "error": f"{path.name}: {exc}"}
        rows = []
        for key, (default, unit, low, high) in prm.DEFAULTS.items():
            entry = entries.get(key)
            rows.append({"name": key, "group": key.split(".", 1)[0], "value": effective["values"][key],
                         "default": default, "unit": unit, "low": low, "high": high,
                         "integer": isinstance(default, int), "in_file": entry is not None,
                         "source": entry["source"] if entry else "default",
                         "evidence": entry["evidence"] if entry else "", "locked": lock_reason(key)})
        return {"name": name, "path": str(path), "file_sha": _digest(raw), "params_sha": effective["sha"],
                "rows": rows, "history": history}

    def snapshot(self) -> dict:
        return {"busy": self.busy(), "files": [self._one(name, path) for name, path in self.files.items()]}

    def save(self, body: dict) -> dict:
        name, changes, note = body.get("file"), body.get("changes"), body.get("note")
        if name not in self.files:
            raise ValueError("등록되지 않은 값 파일입니다.")
        if not isinstance(changes, dict) or not changes:
            raise ValueError("바뀐 값이 없습니다.")
        if not isinstance(note, str) or not note.strip() or len(note) > NOTE_MAX or not note.isprintable():
            raise ValueError(f"변경 근거를 한 줄로 적어 주세요({NOTE_MAX}자 이내).")
        for key in changes:
            if key not in prm.DEFAULTS:
                raise ValueError(f"{key}: 알 수 없는 값입니다.")
            if lock_reason(key):
                raise ValueError(f"{key}: 화면에서 바꿀 수 없습니다({lock_reason(key)}).")
        path = self.files[name]
        with self.lock, self.hold():
            raw = path.read_bytes()
            if _digest(raw) != body.get("base_sha"):
                raise Conflict("파일이 그사이 바뀌었습니다. 다시 불러온 뒤 저장하세요.")
            document = json.loads(raw.decode("utf-8-sig"))
            effective = prm.load(path)["values"]
            day, rows = time.strftime("%Y-%m-%d"), []
            for key, value in changes.items():
                before = document["params"].get(key)
                document["params"][key] = {"value": value, "unit": prm.DEFAULTS[key][1], "source": "tuned",
                                           "evidence": f"{day} 화면 변경 {effective[key]} -> {value}: {note.strip()}"}
                rows.append({"name": key, "from": effective[key], "to": value, "before": before})
            prm.validate(document)  # the shared rule; raises before anything is written
            after = (json.dumps(document, indent=2, ensure_ascii=False) + "\n").encode("utf-8")
            self._replace(path, after, {"at": time.strftime("%Y-%m-%dT%H:%M:%S%z"), "before_sha": _digest(raw),
                                        "after_sha": _digest(after), "note": note.strip(), "changes": rows})
        return self._one(name, self.files[name])

    @staticmethod
    def _replace(path: Path, content: bytes, row: dict) -> None:
        """History first: a crash in between leaves the old file and an extra row, never a change without a record."""
        descriptor, temporary = tempfile.mkstemp(dir=path.parent, prefix=path.name + ".")
        try:
            with os.fdopen(descriptor, "wb") as stream:
                stream.write(content)
                stream.flush()
                os.fsync(stream.fileno())
            shutil.copymode(path, temporary)
            prm.load(temporary)
            with path.with_name(path.name + ".history.jsonl").open("a", encoding="utf-8") as history:
                history.write(json.dumps(row, ensure_ascii=False) + "\n")
                history.flush()
                os.fsync(history.fileno())
            os.replace(temporary, path)
        except BaseException:
            Path(temporary).unlink(missing_ok=True)
            raise


def servo_table(name: str, caps: Path, profile: Path | None = None) -> dict:
    """One arm's servo values for the page; a file a session would refuse shows its reason instead."""
    try:
        import guarded_native
        import session_caps

        layers = session_caps.servo_layers(caps, model=session_caps.model_tuning(),
                                           robot=session_caps.robot_tuning(profile))
    except (OSError, ValueError, KeyError, TypeError, AttributeError, SystemExit) as exc:
        return {"name": name, "error": f"{caps.name}: {exc}"}
    return {"name": name, "path": str(caps), "profile": str(profile) if profile else None,
            "motors": [{"id": motor, "joint": joint, "values": layers[motor]}
                       for motor, joint in zip(layers, guarded_native.NAMES)]}


ATTEMPTS_SHOWN = 12


def attempts_table(name: str, path: Path) -> dict:
    """Recent auto-pick / tier-stacking attempts from attempts.jsonl (read-only)."""
    p = Path(path).expanduser()
    if not p.is_file():
        return {"name": name, "path": str(p), "rows": []}
    rows = []
    try:
        lines = p.read_text(encoding="utf-8", errors="replace").splitlines()
    except OSError as exc:
        return {"name": name, "path": str(p), "error": f"{p.name}: {exc}", "rows": []}
    for raw in reversed(lines[-ATTEMPTS_SHOWN:]):
        try:
            row = json.loads(raw)
        except ValueError:
            continue
        steps = [
            {"command": s.get("command"), "ok": s.get("ok"), "holding": s.get("holding"),
             "verdict": s.get("verdict"), "error": s.get("error"), "current_ma": s.get("gripper_current_ma")}
            for s in ((row.get("transfer") or {}).get("steps") or [])
        ]
        rows.append({
            "attempt_id": row.get("attempt_id"),
            "t_utc": row.get("t_utc"),
            "run_id": row.get("run_id"),
            "from": row.get("from"),
            "to": row.get("to"),
            "tier": row.get("tier"),
            "outcome": row.get("outcome"),
            "holding": row.get("holding"),
            "gripper_current_ma": row.get("gripper_current_ma"),
            "verify": row.get("verify"),
            "fail_stage": row.get("fail_stage"),
            "fail_class": row.get("fail_class"),
            "plan": row.get("plan"),
            "object": row.get("object") or (row.get("auto") or {}).get("object") or (row.get("locate") or {}).get("object"),
            "diagnosis": row.get("diagnosis"),
            "steps": steps,
        })
    return {"name": name, "path": str(p), "rows": rows}


def incidents_table(arms: list[str]) -> list[dict]:
    """Current local and Fleet hold status for each configured arm."""
    import omx_incident

    out = []
    for arm in arms:
        try:
            out.append(omx_incident.status(arm))
        except Exception as exc:
            out.append({"arm": arm, "error": f"{type(exc).__name__}: {str(exc)[:120]}"})
    return out


def clear_arm_hold(files: ParamFiles, arms: list[str], body: dict) -> dict:
    """Clear an arm's open hold via omx_incident.clear when no session is busy."""
    import omx_incident

    arm = body.get("arm")
    note = body.get("note")
    cause = body.get("cause") or None
    basis = body.get("basis") or None
    if arm not in arms:
        raise ValueError("등록되지 않은 팔입니다.")
    if not isinstance(note, str) or not note.strip() or len(note) > NOTE_MAX or not note.isprintable():
        raise ValueError(f"확인한 내용을 한 줄로 적어 주세요({NOTE_MAX}자 이내).")
    if files.busy():
        raise Conflict("세션이 실행 중이라 홀드를 해제할 수 없습니다.")
    try:
        omx_incident.clear(arm, note.strip(), cause=cause, basis=basis)
    except SystemExit as exc:
        raise ValueError(str(exc)) from None
    return omx_incident.status(arm)


def make_server(files: ParamFiles, port: int, host: str = "127.0.0.1", servo: dict | None = None,
                attempts: dict | None = None, incident_arms: list[str] | None = None):
    class Handler(BaseHTTPRequestHandler):
        def reply(self, code, value, kind="application/json"):
            body = value if isinstance(value, bytes) else json.dumps(value, ensure_ascii=False).encode()
            self.send_response(code)
            self.send_header("Content-Type", kind)
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.send_header("X-Frame-Options", "DENY")
            self.send_header("Content-Security-Policy", "default-src 'self'; style-src 'unsafe-inline'; "
                                                        "script-src 'unsafe-inline'; frame-ancestors 'none'")
            self.end_headers()
            self.wfile.write(body)

        def local(self):
            return self.headers.get("Host") in (f"127.0.0.1:{self.server.server_port}",
                                                f"localhost:{self.server.server_port}")

        def do_GET(self):
            if not self.local():
                return self.reply(403, {"error": "local cell only"})
            if self.path == "/":
                return self.reply(200, PAGE.read_bytes(), "text/html; charset=utf-8")
            if self.path == "/params.json":
                return self.reply(200, files.snapshot())
            if self.path == "/servo.json":
                return self.reply(200, [servo_table(name, *paths) for name, paths in (servo or {}).items()])
            if self.path == "/attempts.json":
                return self.reply(200, [attempts_table(name, path) for name, path in (attempts or {}).items()])
            if self.path == "/incidents.json":
                return self.reply(200, incidents_table(list(incident_arms or ())))
            self.reply(404, {"error": "not found"})

        def do_POST(self):
            # The custom header forces a CORS preflight, so another origin cannot change a value.
            if not self.local() or self.headers.get("X-Cell-Params") != "1":
                return self.reply(403, {"error": "local cell only"})
            if self.path not in ("/save", "/incidents/clear"):
                return self.reply(404, {"error": "not found"})
            try:
                length = int(self.headers.get("Content-Length", 0))
                if not 0 < length <= 65536:
                    raise ValueError("bounded JSON body required")
                body = json.loads(self.rfile.read(length))
                if not isinstance(body, dict):
                    raise ValueError("JSON object required")
                if self.path == "/incidents/clear":
                    self.reply(200, clear_arm_hold(files, list(incident_arms or ()), body))
                else:
                    self.reply(200, files.save(body))
            except Conflict as exc:
                self.reply(409, {"error": str(exc)})
            except (ValueError, OSError, KeyError, TypeError, RecursionError) as exc:
                self.reply(400, {"error": str(exc)})

        def log_message(self, *args):
            pass

    return ThreadingHTTPServer((host, port), Handler)


def parse_file(text: str) -> tuple:
    name, separator, path = text.partition("=")
    if not separator or not name or not path:
        raise argparse.ArgumentTypeError("NAME=PATH")
    return name, Path(path).expanduser()


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--file", type=parse_file, action="append", required=True, metavar="NAME=PATH")
    parser.add_argument("--caps", type=parse_file, action="append", default=[], metavar="NAME=PATH")
    parser.add_argument("--profile", type=parse_file, action="append", default=[], metavar="NAME=PATH")
    parser.add_argument("--attempts", type=parse_file, action="append", default=[], metavar="NAME=PATH")
    parser.add_argument("--incident-arm", action="append", default=[], metavar="ARM_ID")
    parser.add_argument("--port", type=int, default=8772)
    args = parser.parse_args(argv)
    files, caps, profiles, attempts = dict(args.file), dict(args.caps), dict(args.profile), dict(args.attempts)
    if (len(files) != len(args.file) or len(caps) != len(args.caps)
            or len(profiles) != len(args.profile) or len(attempts) != len(args.attempts)):
        parser.error("--file, --caps, --profile and --attempts names must differ")
    if not set(profiles) <= set(caps):
        parser.error("--profile needs a --caps of the same name")
    for path in files.values():
        try:
            prm.load(path)
        except (OSError, ValueError) as exc:
            parser.error(f"{path}: {exc}")
    server = make_server(ParamFiles(files), args.port,
                         servo={name: (path, profiles.get(name)) for name, path in caps.items()},
                         attempts=attempts, incident_arms=args.incident_arm)
    from joint_tune import lock_root

    # A page with another HOME or ROSY_OMX_HOME would watch a different lock and save during a session.
    print(f"cell params: http://127.0.0.1:{server.server_port}, session lock {lock_root() / 'session.lock'}", flush=True)
    server.serve_forever()


if __name__ == "__main__":
    main()
