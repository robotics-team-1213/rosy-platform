#!/usr/bin/env python3
"""CLI, fail-closed safety-fence, and folded-at-home helpers for `cell_auto_fold.py` (D-1048)."""
from __future__ import annotations

import argparse
import json
import math
import os
from pathlib import Path
import re
import subprocess
import sys
import threading
import time
from typing import Any, Callable


SCHEMA = "rosy.omx-auto-fold.v1"
CHOICE = "auto_fold.candidate"  # cell_choices name the candidates compete under
LIFT_FAR = 50.0  # shoulder_lift units past home: the forearm lever that latched shoulder_lift on 2026-11-27
# A load joint overloaded/pushing/stalled: resting on something (15:15, 15:30); other contact (16:51 wrist) is its own bucket.
SUPPORTED = re.compile(r"pushing at rest|(shoulder_lift|elbow_flex).*(overload|push|stall)|(overload|push|stall).*(shoulder_lift|elbow_flex)", re.I)
CONTACT = re.compile(r"contact|overload|push|stall", re.I)


def fold_context(state, home, hold_reason: str | None = None) -> str:
    """The coarse situation (4 buckets) whose own record orders the candidates: the hold's reason says the arm is supported
    or not (no PWM threshold yet: fk_z was 'low' even at home), lift near or far."""
    reason = str(hold_reason or "")
    support = "supported" if SUPPORTED.search(reason) else "contact" if CONTACT.search(reason) else "unknown-support"
    return f"{support}/{'far' if abs(float(state[1]) - float(home[1])) > LIFT_FAR else 'near'}"


def start_record(state, status: dict, hold_reason: str | None) -> dict:
    """What the fold started from, a record only (nothing decides on it): joints, measured PWM, the hold's reason."""
    health = status.get("health") if isinstance(status.get("health"), dict) else {}
    return {"state_start": [round(float(v), 2) for v in state[:6]], "start_pwm": health.get("pwm"), "hold_reason": hold_reason}


def evidence(result: dict, home, torque_after: dict, incident_id: str, taken_at: float, *,
             hardware_error_after: dict | None = None, caps_restored_after: bool | None = None) -> dict:
    """What core_common.clearable_after_fold reads: the measured fold, home, torque after the session, the check, and
    the incident it was taken for (Fleet refuses it for any other)."""
    corridor = result.get("corridor") or {}
    out = {"kind": "auto_fold", "schema": SCHEMA, "incident_id": incident_id, "taken_at": round(taken_at, 3),
           "candidate": result.get("candidate"), "folded_state": result["state"], "home": list(home),
           "torque_after": torque_after,
           "corridor_clear": corridor.get("clear") if corridor else result.get("candidate") == "already_home",
           "steps": len(result.get("steps") or [])}
    if hardware_error_after is not None:
        out["hardware_error_after"] = hardware_error_after
    if caps_restored_after is not None:
        out["caps_restored_after"] = caps_restored_after
    return out


def _learn(result: dict, ok: bool) -> None:
    """Record how the tried candidate did in the arm's cell_choices file (main named it); nothing moved: nothing recorded."""
    path, name = result.get("choices_path"), result.get("candidate")
    if not path or name in (None, "already_home") or str(name).startswith("advisor:"):
        return
    try:
        from cell_choices import Choices

        choices = Choices(Path(path))
        note = str(result.get("reason") or result.get("result"))
        choices.outcome(CHOICE, name, ok, note=note)
        if result.get("context"):  # the same try under its situation too (ranked_in_context)
            choices.offer(f"{CHOICE}@{result['context']}", name, "D-1048")
            choices.outcome(f"{CHOICE}@{result['context']}", name, ok, note=note)
        choices.save()
    except (SystemExit, Exception):  # a lost learning row never changes the outcome
        pass


def expiry_error(expires_at: Any, *, required: bool, now_t: float) -> str | None:
    if expires_at is None:
        return "SAFE_HOME_EXPIRY_MISSING" if required else None
    if isinstance(expires_at, bool) or not isinstance(expires_at, (int, float)):
        return "SAFE_HOME_EXPIRY_INVALID"
    try:
        exp_f = float(expires_at)
    except (TypeError, ValueError, OverflowError):
        return "SAFE_HOME_EXPIRY_INVALID"
    if not math.isfinite(exp_f):
        return "SAFE_HOME_EXPIRY_INVALID"
    if now_t > exp_f:
        return "SAFE_HOME_EXPIRED"
    return None


def _safety_fence_error(args) -> str | None:
    if args.expires_at is not None:
        exp_err = expiry_error(args.expires_at, required=True, now_t=time.time())
        if exp_err is not None:
            return exp_err
    if args.safety_fence is not None or args.stop_generation is not None:
        fence_path = Path(args.safety_fence) if (args.safety_fence and args.safety_fence.strip()) else None
        if fence_path is None or not fence_path.is_file():
            return "SAFETY_FENCE_MISSING"
        try:
            fence = json.loads(fence_path.read_text(encoding="utf-8"))
            upd = fence.get("updated_at") if isinstance(fence, dict) else None
            sg = fence.get("stop_generation") if isinstance(fence, dict) else None
            if not isinstance(fence, dict) or type(fence.get("human_hold")) is not bool:
                return "SAFETY_FENCE_UNREADABLE"
            if fence["human_hold"]:
                return "HUMAN_HOLD_ACTIVE"
            if isinstance(upd, bool) or not isinstance(upd, (int, float)) or not math.isfinite(upd) or not (-5.0 <= (time.time() - upd) <= 15.0):
                return "SAFETY_FENCE_STALE"
            if type(sg) is not int or args.stop_generation is None or sg != args.stop_generation:
                return "STOP_GENERATION_PREEMPTED"
        except Exception:
            return "SAFETY_FENCE_UNREADABLE"
    fleet_requested = (getattr(args, "stage", "full") != "full") or (args.safety_fence is not None) or (args.stop_generation is not None)
    if fleet_requested and args.expires_at is None:
        return "SAFE_HOME_EXPIRY_MISSING"
    return None


def resolve_folded_at_home(
    cell, state: list, *, stage: str, latched: dict, is_holding: bool,
    steps: list, note_fn, hold_fn, ensure_unlatch_fn, schema: str,
) -> dict | None:
    """Return outcome when arm is already folded at home, or None to continue into release-and-lift recovery."""
    if stage == "park_only" and is_holding:
        return hold_fn("STILL_HOLDING_BEFORE_PARK", is_holding=True)
    if stage == "release_and_lift":
        if is_holding:
            return None
        held = cell.act("human-hold")
        if held.get("ok") is not True:
            return {"schema": schema, "result": "held", "reason": "HOLD_AFTER_LIFT_FAILED",
                    "candidate": "release_and_lift", "hold_ok": held.get("ok"), "steps": steps}
        return {"schema": schema, "result": "risen_for_visual_verify", "candidate": "release_and_lift",
                "state": state, "hold_ok": True, "steps": steps, "corridor": None}
    if latched["active"]:
        if is_holding:
            return hold_fn("HOLDING_AT_HOME", is_holding=True)
        ok_u, err_u = ensure_unlatch_fn(cell, latched, note_fn)
        if not ok_u:
            return hold_fn("UNLATCH_REFUSED", error=err_u)
    elif is_holding:
        return hold_fn("HOLDING_AT_HOME", is_holding=True)
    return {"schema": schema, "result": "folded", "candidate": "already_home", "state": state, "steps": steps,
            "corridor": None, **({"unlatched_live_hold": True} if latched["started"] else {})}


def write_req_result(incidents_dir: Path, request_id: str | None, arm: str, stage: str, out: dict[str, Any]) -> None:
    if not request_id:
        return
    res = str(out.get("result") or "")
    outcome = ("completed" if res in ("folded", "cleared", "parked_for_visual_verify")
               else "risen_for_visual_verify" if res == "risen_for_visual_verify"
               else "held_guard_tripped" if res == "held"
               else "skipped" if res == "skipped"
               else "failed")
    payload = {"request_id": request_id, "arm": arm, "stage": stage, "outcome": outcome,
               "detail": out.get("why"), "result": out}
    target = incidents_dir / f"auto-fold-req-{request_id}.result.json"
    target.parent.mkdir(parents=True, exist_ok=True)
    tmp = target.with_name(f"{target.name}.{os.getpid()}.tmp")
    tmp.write_text(json.dumps(payload, default=str), encoding="utf-8")
    os.replace(tmp, target)


class FencedCell:
    """Guard both `act()` and `checked()` with a session-wide safety-fence watcher through settling."""

    def __init__(self, cell, fence_check: Callable[[], str | None], *, poll_s: float = 0.05):
        self._cell, self._fence_check, self._poll_s = cell, fence_check, poll_s
        self.tripped_reason: str | None = None
        self._lock = threading.Lock()
        self._done = threading.Event()
        self._watcher: threading.Thread | None = None

    def __enter__(self) -> "FencedCell":
        return self

    def __exit__(self, *_exc) -> None:
        self.close()

    def close(self) -> None:
        self._done.set()
        if self._watcher is not None:
            self._watcher.join(timeout=1.0)

    def __getattr__(self, name: str):
        return getattr(self._cell, name)

    def _ensure_watcher(self) -> None:
        with self._lock:
            if self._watcher is not None:
                return

            def _watch() -> None:
                while not self._done.wait(self._poll_s):
                    watch_err = self._fence_check()
                    if watch_err is not None:
                        self.tripped_reason = watch_err
                        try:
                            self._cell.act("human-hold")
                        except Exception:
                            pass
                        return

            self._watcher = threading.Thread(target=_watch, daemon=True)
            self._watcher.start()

    def _guard_motion(self, call_fn: Callable[[], dict]) -> dict:
        err = self.tripped_reason or self._fence_check()
        if err is not None:
            self.tripped_reason = err
            return {"ok": False, "error": err, "fence_tripped": True}
        self._ensure_watcher()
        res = call_fn()
        if self.tripped_reason is not None:
            return {"ok": False, "error": self.tripped_reason, "fence_tripped": True, "motion_reply": res}
        return res

    def act(self, command: str, *args, **kwargs) -> dict:
        if command in ("state", "human-hold", "stop now") or command.startswith(("human-hold ", "stop ")):
            return self._cell.act(command, *args, **kwargs)
        return self._guard_motion(lambda: self._cell.act(command, *args, **kwargs))

    def checked(self, command: str, assessment: dict, *args, **kwargs) -> dict:
        return self._guard_motion(lambda: self._cell.checked(command, assessment, *args, **kwargs))


BOUND_INCIDENT_OPTION = "--expected-incident-id"


def bound_hold_matches(link, incident_id):
    from core_common.protocol.arm_incident.home_recovery import HOME_RECOVERY_REASON
    try:
        current = link.hold()
        return (current.held is True and current.reason == HOME_RECOVERY_REASON
                and list(current.incident_ids) == [incident_id])
    except (AttributeError, RuntimeError, ValueError, OSError):
        return False


def run_cli_main(argv: list[str] | None, *, launch_fn: Callable[..., dict], recover_fn: Callable[..., dict],
                 candidate_names_fn: Callable[[], list[str]], choice_key: str, schema: str) -> int:
    del candidate_names_fn, choice_key
    args_list = list(sys.argv[1:] if argv is None else argv)
    if args_list[:1] == ["launch"]:
        lp = argparse.ArgumentParser(prog="cell_auto_fold.py launch")
        lp.add_argument("--arm", required=True)
        lp.add_argument("--config-file", type=Path, required=True)
        lp.add_argument("--stage", choices=("full", "release_and_lift", "park_only"), default="full")
        lp.add_argument(BOUND_INCIDENT_OPTION)
        lp.add_argument("--request-id", default=None)
        lp.add_argument("--expires-at", type=float, default=None)
        lp.add_argument("--stop-generation", type=int, default=None)
        lp.add_argument("--safety-fence", default=None)
        opts = lp.parse_args(args_list[1:])
        print(json.dumps(launch_fn(opts.arm, opts.config_file, stage=opts.stage,
                                   request_id=opts.request_id, expires_at=opts.expires_at,
                                   **({"expected_incident_id": opts.expected_incident_id} if opts.expected_incident_id is not None else {}),
                                   stop_generation=opts.stop_generation, safety_fence=opts.safety_fence), default=str))
        return 0

    from chunk_runner_recover import run_fold_session_cli

    ap = argparse.ArgumentParser(description="Fold a held arm home on its own (D-1048).")
    ap.add_argument("--arm", required=True)
    ap.add_argument("--config", type=Path, required=True)
    ap.add_argument("--library", type=Path, required=True)
    ap.add_argument("--site", required=True)
    ap.add_argument("--roi", nargs=4, type=int, required=True)
    ap.add_argument("--out", type=Path, required=True)
    ap.add_argument("--stage", choices=("full", "release_and_lift", "park_only"), default="full")
    ap.add_argument("--expires-at", type=float, default=None)
    ap.add_argument("--stop-generation", type=int, default=None)
    ap.add_argument("--safety-fence", default=None)
    ap.add_argument(BOUND_INCIDENT_OPTION)
    ap.add_argument("--supervised", action="store_true")
    ap.add_argument("--commissioning", action="store_true", help="trial the exact incident-bound cargo placement")
    ap.add_argument("--person-at-switch", action="store_true", help="confirm a person is at the power switch for this trial")
    ap.add_argument("--unlatch-hold", action="store_true")
    ap.add_argument("--vlm-url")
    ap.add_argument("--vlm-model", default="qwen3-vl:8b-instruct")
    ap.add_argument("--vlm-provider", default="ollama")
    ap.add_argument("--vlm-config", type=Path)
    ap.add_argument("--vlm-timeout", type=float, default=25.0)
    args = ap.parse_args(args_list)
    if args.commissioning != args.person_at_switch:
        ap.error("--commissioning and --person-at-switch require each other")
    if args.commissioning and (not args.expected_incident_id or args.stage != "full" or args.supervised
                               or args.unlatch_hold or not args.safety_fence or args.stop_generation is None
                               or args.expires_at is None):
        ap.error("placement commissioning requires a fenced, incident-bound full command")
    if args.expected_incident_id is not None:
        import omx_incident
        if (args.supervised or args.expected_incident_id != os.environ.get("ROSY_RECOVERY_INCIDENT")
                or not bound_hold_matches(omx_incident.link_for(args.arm), args.expected_incident_id)):
            args.out.write_text(json.dumps({"result": "held", "reason": "HOME_RECOVERY_INCIDENT_MISMATCH",
                                            "incident_id": args.expected_incident_id}))
            return 3
    if not args.supervised and not os.environ.get("ROSY_RECOVERY_INCIDENT"):
        ap.error("ROSY_RECOVERY_INCIDENT is required: this tool only folds an arm a held incident names")

    def _guarded_recover(cell, home, closed, **kw):
        fence_bad = _safety_fence_error(args)
        if fence_bad is not None:
            can_stop = bool(args.supervised and not args.unlatch_hold and not kw.get("moved_out") and not kw.get("latched_out"))
            stopped = cell.act("stop now") if can_stop else {}
            if stopped.get("ok") is True:
                return {"schema": schema, "result": "held", "reason": fence_bad, "hold_ok": None,
                        "ended": "stop_now", "unmoved": True, "steps": []}
            return {"schema": schema, "result": "held", "reason": fence_bad,
                    "hold_ok": cell.act("human-hold").get("ok"), "steps": []}
        with FencedCell(cell, lambda: _safety_fence_error(args)) as fenced:
            placement = None
            if args.expected_incident_id is not None:
                from cell_bound_home_placement import before_bound_home
                from cell_recovery_placement import place_nearest
                from cell_recovery_placement_context import load_context
                from cell_recovery_placement_journal import PlacementJournal
                from cell_recovery_placement_live import build_backend
                from omx_incident_fleet import incidents_dir
                import sqlite3

                kw["require_empty_gripper"] = True
                directory = incidents_dir()
                try:
                    placement = before_bound_home(
                        args, fenced, closed, kw, PlacementJournal(directory, args.arm), directory,
                        load_context=load_context, build_backend=build_backend, place_nearest=place_nearest)
                except (sqlite3.Error, OSError, ValueError) as exc:
                    placement = {"result": "held", "reason": f"PLACEMENT_UNAVAILABLE: {exc}"}
                if placement is not None and placement.get("result") != "placed":
                    return {"schema": schema, **placement, "result": "held",
                            "hold_ok": fenced.act("human-hold").get("ok"), "steps": placement.get("steps", [])}
            out = recover_fn(fenced, home, closed, stage=args.stage, **kw)
            if placement is not None:
                out["placement"] = placement
            if fenced.tripped_reason is not None:
                if out.get("result") != "held":
                    held = cell.act("human-hold")
                    return {"schema": schema, "result": "held", "reason": fenced.tripped_reason,
                            "hold_ok": held.get("ok"), "steps": out.get("steps") or []}
                out["reason"] = fenced.tripped_reason
        return out

    rc = run_fold_session_cli(args, _guarded_recover, schema)
    if rc == 3 and args.out.is_file():
        try:
            if json.loads(args.out.read_text(encoding="utf-8")).get("result") == "risen_for_visual_verify":
                return 0
        except Exception:
            pass
    return rc


def run_launch_command(
    script_path: Path, arm: str, conf: dict[str, Any], *, stage: str, out: Path, cwd: Path,
    incident: str, marker: Path, expires_at: float | None, stop_generation: int | None,
    safety_fence: str | None, run: Callable[..., Any] | None, sleep: Callable[[float], Any],
    now: Callable[[], float], require_expiry: bool = False, expected_incident_id: str | None = None,
) -> dict[str, Any] | None:
    """Invoke auto-fold subprocess with lock retries; return early skip/failure payload or None once `out` exists."""
    req_exp = bool(require_expiry or (stage != "full") or (safety_fence is not None) or (stop_generation is not None))
    exp_err = expiry_error(expires_at, required=req_exp, now_t=now())
    if exp_err is not None:
        marker.unlink(missing_ok=True)
        return {"result": "skipped", "why": exp_err}
    command = [
        conf["wrapper"], sys.executable, str(script_path), "--arm", arm, "--config", conf["config"],
        "--library", conf["library"], "--site", conf["site"], "--roi", *map(str, conf["roi"]),
        "--stage", stage, "--out", str(out),
    ]
    if expected_incident_id is not None:
        command += [BOUND_INCIDENT_OPTION, expected_incident_id]
    if expires_at is not None:
        command += ["--expires-at", f"{float(expires_at):.3f}"]
    if stop_generation is not None:
        command += ["--stop-generation", str(int(stop_generation))]
    if safety_fence:
        command += ["--safety-fence", str(safety_fence)]
    env = {**os.environ, "ROSY_RECOVERY_INCIDENT": incident, "ROSY_SESSION_CHUNKS": str((Path(cwd) / Path(conf["library"]).expanduser()).resolve())}
    proc = None
    for _ in range(12):  # the session that held the arm may still be ending: its lock frees within a minute
        exp_err = expiry_error(expires_at, required=req_exp, now_t=now())
        if exp_err is not None:
            marker.unlink(missing_ok=True)
            return {"result": "skipped", "why": exp_err}
        # no short timeout: killing the wrapper mid-fold would leave the arm out on its reach
        proc = (run or subprocess.run)(command, cwd=cwd, env=env, timeout=3600, capture_output=True, text=True)
        if "session lock is held" not in (proc.stdout or "") + (proc.stderr or ""):
            break
        sleep(5)
    if not out.is_file():
        output = ((proc.stdout or "") + (proc.stderr or "")) if proc is not None else "no process run"
        if "session lock is held" in output:
            marker.unlink(missing_ok=True)
        return {"result": "failed", "why": output[-300:]}
    return None
