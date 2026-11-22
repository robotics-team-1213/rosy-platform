#!/usr/bin/env python3
"""Fold a held, extended arm home on its own, around what is in the way (D-1048).

User 2026-11-19: "팔을 뻗은 채 멈춘 사고는 안전하게 접어야지. 접는 경로에 문제가 있다면 이를 피해서 하는 플래닝을 하게 하면
되잖아." An incident that held the arm away from home (a contact or strain hold, a link failure mid-carry, jaws on a box)
no longer waits for a person when the cell can see a free way home:

1. jaws on something (told to close, stopped wider than the empty close): only with the TCP low (below clear_z, where a
   carry grips and places) and its short rise checked, cell_unwedge.release_and_rise lets go and rises first; jaws on a box
   up high stay with a person (letting go there drops it);
2. candidates, first clear one wins: the runner's own park path (rise, turn at transit height, descend) from where the
   arm stands, then the same after a shoulder_pan detour of +-5 / +-10 units. Each is checked before anything moves:
   its frames through FK into the top view, cell_corridor.check (low runs: any blob; high runs: unknown blobs such as a
   hand or the other arm), and the corridor reserved in cell_space against the other arm's live reservation;
3. nothing clear (or any error): human-hold where it stands, torque ON (an extended arm never loses torque), and the
   hold stays. With the hold latched the runner's own idle park is refused and it keeps torque (chunk_runner_settle).

Every motion is the runner's guarded command (park, jog): its speed limit, following-error, strain and contact holds
apply unchanged. Success is measured: park settled within SETTLE_TOL of home. The evidence (folded state, home, the
corridor verdict, torque after the session ends) goes with the assessor's clear (core_common clearable_after_fold).
"""
from __future__ import annotations

import json
import math
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

SCHEMA = "rosy.omx-auto-fold.v1"
PAN_DETOURS = (5.0, -5.0, 10.0, -10.0)
SETTLE_TOL = 3.0  # chunk_runner.SETTLE_TOL (kept here so the plan is testable without the runner)
HOLDING_MARGIN = 4.0  # jaws stopped this far above their closing command are on something (cell_transfer.STILL_HOLDING_UNITS)
REST_TOL = 8.0  # a hold this near home (all five body joints) ends the session instead of holding torque
CHOICE = "auto_fold.candidate"  # cell_choices name the candidates compete under
RISE_UNITS = 12.0  # cell_unwedge.CLEAR: release_and_rise lifts shoulder_lift this far


def _ok_state(status) -> list | None:
    state = status.get("state") if isinstance(status, dict) else None
    if status.get("ok") is not True or not isinstance(state, list) or len(state) < 6 \
            or any(type(v) not in (int, float) or not math.isfinite(v) for v in state[:6]):
        return None
    return list(state[:6])


def holding(state, target, closed: float) -> bool:
    """Told to close (target at the empty close) and stopped wider: something is in the jaws. An open approach is not."""
    return target[5] <= closed + 1.0 and state[5] > target[5] + HOLDING_MARGIN


def folded(state, home) -> bool:
    return all(abs(a - b) <= SETTLE_TOL for a, b in zip(state[:5], home[:5]))


def candidate_names():
    return ["park", *(f"pan{d:+g}" for d in PAN_DETOURS)]


def at_rest(state, home) -> bool:
    return state is not None and all(abs(a - b) <= REST_TOL for a, b in zip(state[:5], home[:5]))


def candidates(state, plan):
    """(name, commands before the park, frames the arm would sweep) in the order they are tried."""
    yield "park", [], plan(state)
    for d in PAN_DETOURS:
        moved = [state[0] + d, *state[1:]]
        yield f"pan{d:+g}", [f"jog shoulder_pan.pos {d}"], [state, moved, *plan(moved)]


def recover(cell, home, closed, *, plan, look, reserve, release, release_and_rise, low, log=lambda row: None, order=None) -> dict:
    """Fold the held arm home or hold it where it is; never moves without a clear, reserved corridor. order(names)
    gives the candidates' try order (learned outcomes); the set of candidates is never changed by it."""
    steps, known = [], {"state": None}  # known: the last state seen, None once the arm may have moved unseen

    def note(row):
        steps.append(row)
        log(row)

    def hold(reason, is_holding: bool = False, **extra):
        # resting at home: end the session in place (torque OFF), nothing hangs out. The pose is read again right before
        # the stop (review N1: seconds of corridor checks may pass after the last read). Never drop a held load!
        if not is_holding and at_rest(known["state"], home) and at_rest(_ok_state(cell.act("state")), home):
            stopped = cell.act("stop now")
            if stopped.get("ok") is True:
                return {"schema": SCHEMA, "result": "held", "reason": reason, "steps": steps, "hold_ok": None,
                        "ended": "stop_now", **extra}
        held = cell.act("human-hold")
        return {"schema": SCHEMA, "result": "held", "reason": reason, "steps": steps, "hold_ok": held.get("ok"), **extra}

    status = cell.act("state")
    state = _ok_state(status)
    target = status.get("target") if isinstance(status.get("target"), list) and len(status["target"]) >= 6 else state
    known["state"] = state
    if state is None:
        return hold("STATE_UNREADABLE")
    if folded(state, home):
        return {"schema": SCHEMA, "result": "folded", "candidate": "already_home", "state": state, "steps": steps,
                "corridor": None}
    if holding(state, target, closed):
        if not low(state):
            return hold("HOLDING_HIGH", is_holding=True)
        risen = [state[0], state[1] - RISE_UNITS, *state[2:]]
        rise_lane = [state, risen]
        if not look(rise_lane).get("clear") or not reserve(rise_lane).get("ok"):
            release()
            return hold("RISE_BLOCKED", is_holding=True)
        known["state"] = None
        try:
            freed = release_and_rise(cell)
        finally:
            release()
        note({"step": "release_and_rise", **{k: freed.get(k) for k in ("result", "at", "error", "jaws", "lags")}})
        if freed.get("result") != "risen":
            return hold("RELEASE_STUCK")
        status = cell.act("state")
        state = known["state"] = _ok_state(status)
        if state is None:
            return hold("STATE_UNREADABLE")
        target = status.get("target") if isinstance(status.get("target"), list) and len(status["target"]) >= 6 else state
    tries = list(candidates(list(target[:6]), plan))  # the runner parks from its held target
    if order is not None:
        rank = {name: i for i, name in enumerate(order([name for name, _, _ in tries]))}
        tries.sort(key=lambda c: rank.get(c[0], len(rank)))
    for name, before, frames in tries:
        verdict = look(frames)
        note({"step": "check", "candidate": name, "clear": verdict.get("clear"),
              "low": len(verdict.get("low") or []), "high": len(verdict.get("high") or []),
              "off_map": verdict.get("off_map"), "off_surface": verdict.get("off_surface")})
        if not verdict.get("clear"):
            continue
        booked = reserve(frames)
        if not booked.get("ok"):
            note({"step": "reserve", "candidate": name, "refused": booked.get("reason")})
            continue
        known["state"] = None  # from the first command the arm is no longer where it was read
        try:
            for command in before:
                moved = cell.act(command)
                if moved.get("ok") is not True:
                    return hold("DETOUR_REFUSED", candidate=name, error=moved.get("error"))
            parked = cell.act("park")
        finally:
            release()
        at = known["state"] = _ok_state(parked)
        note({"step": "park", "candidate": name, "ok": parked.get("ok"), "settled": parked.get("settled"),
              "error": parked.get("error"), "contact": parked.get("contact")})
        if parked.get("ok") is True and parked.get("settled") is True and at is not None and folded(at, home):
            return {"schema": SCHEMA, "result": "folded", "candidate": name, "state": at, "steps": steps,
                    "corridor": verdict}
        return hold("PARK_NOT_HOME", candidate=name, error=parked.get("error"))
    return hold("ALL_PATHS_BLOCKED")


def evidence(result: dict, home, torque_after: dict, incident_id: str, taken_at: float) -> dict:
    """What core_common.clearable_after_fold reads: the measured fold, home, torque after the session, the check, and
    the incident it was taken for (Fleet refuses it for any other)."""
    corridor = result.get("corridor") or {}
    return {"kind": "auto_fold", "schema": SCHEMA, "incident_id": incident_id, "taken_at": round(taken_at, 3),
            "candidate": result.get("candidate"), "folded_state": result["state"], "home": list(home),
            "torque_after": torque_after,
            "corridor_clear": corridor.get("clear") if corridor else result.get("candidate") == "already_home",
            "steps": len(result.get("steps") or [])}


def _learn(result: dict, ok: bool) -> None:
    """Record how the tried candidate did in the arm's cell_choices file (main named it); nothing moved: nothing recorded."""
    path, name = result.get("choices_path"), result.get("candidate")
    if not path or name in (None, "already_home"):
        return
    try:
        from cell_choices import Choices

        choices = Choices(Path(path))
        choices.outcome(CHOICE, name, ok, note=str(result.get("reason") or result.get("result")))
        choices.save()
    except (SystemExit, Exception):  # a lost learning row never changes the outcome
        pass


def launch(arm: str, conf_file, *, link=None, run=None, sleep=time.sleep, now=time.time, clear=None) -> dict:
    """omx_incident starts this after a held incident it could not clear: one try per incident. Opens the arm's session
    through its wrapper as a recovery session for that incident alone, folds (main), waits for the session's own end
    (torque OFF confirmed in session.json) and clears that incident with the evidence. Anything short leaves the hold."""
    import os
    import subprocess

    import omx_incident
    import omx_incident_auto

    conf = json.loads(Path(conf_file).read_text(encoding="utf-8"))[arm]
    link = link or omx_incident.link_for(arm)
    ids = list(link.hold().incident_ids) if link is not None else []
    if len(ids) != 1:
        return {"result": "skipped", "why": f"{len(ids)} open incidents (one is folded at a time)"}
    incident = ids[0]
    marker = Path(omx_incident.INCIDENTS) / f"auto-fold-{incident}.json"
    if marker.exists():
        return {"result": "skipped", "why": "already tried for this incident"}
    marker.parent.mkdir(parents=True, exist_ok=True)
    try:  # one try per incident, claimed atomically
        fd = os.open(marker, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
    except FileExistsError:
        return {"result": "skipped", "why": "already tried for this incident"}
    with os.fdopen(fd, "w") as stream:
        stream.write(json.dumps({"incident_id": incident, "arm": arm, "at": now()}))
    out, cwd = marker.with_name(f"auto-fold-{incident}.result.json"), Path(conf["cwd"]).expanduser()
    command = [conf["wrapper"], sys.executable, str(Path(__file__).resolve()), "--arm", arm, "--config", conf["config"],
               "--library", conf["library"], "--site", conf["site"], "--roi", *map(str, conf["roi"]), "--out", str(out)]
    env = {**os.environ, "ROSY_RECOVERY_INCIDENT": incident}
    started = now()

    def done(out: dict, candidate=None) -> dict:
        omx_incident_auto.note_event({"kind": "auto_fold", "arm": arm, "incident_id": incident, "result": out["result"],
                                      "why": out.get("why"), "candidate": candidate})
        return out

    for _ in range(12):  # the session that held the arm may still be ending: its lock frees within a minute
        # no short timeout: killing the wrapper mid-fold would leave the arm out on its reach
        proc = (run or subprocess.run)(command, cwd=cwd, env=env, timeout=3600, capture_output=True, text=True)
        if "session lock is held" not in (proc.stdout or "") + (proc.stderr or ""):
            break
        sleep(5)
    if not out.is_file():
        output = ((proc.stdout or "") + (proc.stderr or ""))
        if "session lock is held" in output:
            marker.unlink(missing_ok=True)
        return done({"result": "failed", "why": output[-300:]})
    result = json.loads(out.read_text())
    cand = result.get("candidate")
    _learn(result, result.get("result") == "folded")
    if result.get("result") != "folded":
        return done({"result": "held", "why": result.get("reason")}, cand)
    session = cwd / "session.json"
    for _ in range(36):  # the stop ends the recovery session; record_session writes torque_after when it has
        if session.is_file() and session.stat().st_mtime >= started - 2.0:  # file-time granularity; old sessions are minutes old
            try:
                sess = json.loads(session.read_text())
            except (OSError, ValueError):
                sess = None
            if isinstance(sess, dict):
                prof = sess.get("operating_profile")
                chunks_io = (sess.get("chunks") or {}).get("io") if isinstance(sess.get("chunks"), dict) else None
                io_tag = chunks_io.rstrip("/").rsplit("-", 1)[-1] if isinstance(chunks_io, str) else ""
                sess_arm = (
                    (sess.get("arm") if isinstance(sess.get("arm"), str) and sess.get("arm") else None)
                    or (prof.get("instance_id") if isinstance(prof, dict) and prof.get("instance_id") else None)
                    or (sess.get("motor_health_owner") if isinstance(sess.get("motor_health_owner"), str) and sess.get("motor_health_owner") else None)
                    or (f"arm_{io_tag}" if io_tag in ("a", "b", "s") else None)
                )
                real_record = any(k in sess for k in ("arm", "operating_profile", "motor_health_owner", "chunks", "config"))
                if sess_arm == arm or (not real_record and sess_arm is None and "torque_after" in sess):
                    break
        sleep(5)
    else:
        return done({"result": "not_cleared", "why": "the recovery session did not report its end (no fresh session.json)"}, cand)
    try:
        torque = json.loads(session.read_text()).get("torque_after") or {}
    except (OSError, ValueError):
        return done({"result": "not_cleared", "why": "session.json unreadable"}, cand)
    proof = evidence(result, result["home"], torque, incident, now())
    note = f"automatic fold (D-1048): {result.get('candidate')}, home within {SETTLE_TOL} units, torque OFF"
    try:
        (clear or omx_incident.clear)(arm, note, omx_incident_auto.assessor_token_file(), link, cause="unknown",
                                      basis="measured", recovery=proof, only=incident)
        return done({"result": "cleared", "incident_id": incident, "evidence": proof}, cand)
    except (SystemExit, Exception) as exc:  # Fleet refused or unreachable: the hold stays
        return done({"result": "not_cleared", "why": f"{type(exc).__name__}: {str(exc)[:200]}", "evidence": proof}, cand)


def main(argv=None) -> int:
    """Run inside the arm's session wrapper (ROSY_RECOVERY_INCIDENT names the one held incident it may open with);
    `launch --arm A --config-file F` is how omx_incident starts it."""
    import argparse
    import os

    argv = list(sys.argv[1:] if argv is None else argv)
    if argv[:1] == ["launch"]:
        lp = argparse.ArgumentParser(prog="cell_auto_fold.py launch")
        lp.add_argument("--arm", required=True)
        lp.add_argument("--config-file", type=Path, required=True)
        opts = lp.parse_args(argv[1:])
        print(json.dumps(launch(opts.arm, opts.config_file), default=str))
        return 0

    import cell_choices
    import cell_corridor
    import cell_objects
    import cell_params as prm
    import cell_pipeline as cp
    import cell_pivot
    import cell_place_fit
    import cell_space
    import cell_unwedge
    from cell_observe import predicted_pixel
    from omx_adapter.chunk_library import NAMES, park_path

    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--arm", required=True, help="the arm this session holds (its space reservation key)")
    ap.add_argument("--config", type=Path, required=True, help="the arm's cell-auto config (io, cameras, sites)")
    ap.add_argument("--library", type=Path, required=True, help="the arm's reviewed chunk library (home, transit)")
    ap.add_argument("--site", required=True, help="the surface whose map the corridor is checked on")
    ap.add_argument("--roi", nargs=4, type=int, required=True)
    ap.add_argument("--out", type=Path, required=True, help="result JSON")
    args = ap.parse_args(argv)
    if not os.environ.get("ROSY_RECOVERY_INCIDENT"):
        ap.error("ROSY_RECOVERY_INCIDENT is required: this tool only folds an arm a held incident names")
    config = cell_place_fit.with_tiers(json.loads(args.config.read_text(encoding="utf-8")))[0]
    params = config["params"] = prm.load(config.get("params_path"))["values"]
    calibration = json.loads(Path(config["calibration_path"]).expanduser().read_text())
    library = json.loads(args.library.read_text())
    home = library["chunks"]["home"][-1]
    closed = float(library["gripper_closed"])  # what the runner's park closes to (chunk_runner_commands park)
    transit = {NAMES.index(k): float(v) for k, v in library.get("transit", {}).items()} or None  # as the runner keys it
    site = config["sites"][args.site]
    cell = cp.FifoCell(Path(config["io"]).expanduser(), config["cameras"])
    space = cell_space.Space(Path(config.get("space_dir", "~/rosy-omx/space")).expanduser())
    arm = args.arm
    to_px = lambda p: predicted_pixel(config, calibration, args.site, p)  # noqa: E731
    booked = {}
    choices_path = Path(config.get("work_dir") or ".") / f"auto-fold-choices-{arm}.json"
    choices = cell_choices.Choices(choices_path)
    for name in candidate_names():
        choices.offer(CHOICE, name, "D-1048")
    choices.save()  # launch records the outcome into this file

    def plan(state):  # the runner's park: park_path(target, home[-1], gripper_closed, fps, transit, transit_speed)
        return park_path(list(state), home, closed, library["fps"], transit, library.get("transit_speed", 0.85))

    def low(state):
        return cell_pivot.joints_tcp(state)[2] < prm.get(params, "corridor.clear_z_m", cell_corridor.CLEAR_Z_M)

    def look(frames):
        img = cell.frame("top")
        mask = cell_objects.foreground(img, args.roi, params=params, surface_px=site.get("surface_px"),
                                       surface_lab=site.get("surface_lab"))
        return cell_corridor.check([cell_pivot.joints_tcp(f)[:3] for f in frames], mask, args.roi, to_px,
                                   params=params, surface_px=site.get("surface_px"))

    def reserve(frames):
        lane = cell_corridor.corridor(cell_corridor.runs([cell_pivot.joints_tcp(f)[:3] for f in frames])[0]
                                      + cell_corridor.runs([cell_pivot.joints_tcp(f)[:3] for f in frames])[1],
                                      to_px, (args.roi[3] - args.roi[1], args.roi[2] - args.roi[0]), args.roi,
                                      prm.get(params, "corridor.half_width_mm", cell_corridor.HALF_WIDTH_MM))
        booked["mask"] = lane
        return space.reserve(arm, lane, ttl_s=300.0)  # a transit park with a detour fits well inside

    try:
        result = recover(cell, home, closed, plan=plan, look=look, reserve=reserve, release=lambda: space.release(arm),
                         release_and_rise=cell_unwedge.release_and_rise, low=low,
                         order=lambda names: choices.ranked(CHOICE, names))
    except Exception as exc:  # whatever broke, the arm stays where it is with torque ON
        held = cell.act("human-hold")
        space.release(arm)
        result = {"schema": SCHEMA, "result": "held", "reason": f"ERROR: {type(exc).__name__}: {str(exc)[:160]}",
                  "hold_ok": held.get("ok"), "steps": []}
    result["incident_id"], result["home"] = os.environ["ROSY_RECOVERY_INCIDENT"], list(home)
    result["choices_path"] = str(choices_path)
    if result["result"] == "folded":
        result["stop"] = cell.act("stop")  # at home: the runner's stop folds nothing more and turns torque OFF
    args.out.write_text(json.dumps(result, default=str, indent=1))
    print(json.dumps({k: result.get(k) for k in ("result", "reason", "candidate")}))
    return 0 if result["result"] == "folded" else 3


if __name__ == "__main__":
    raise SystemExit(main())
