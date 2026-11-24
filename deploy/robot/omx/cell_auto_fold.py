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
    from cell_recovery_plan import STEP_MAX, chunk_jog_commands, interpolate_pose

    yield "park", [], plan(state)
    for d in PAN_DETOURS:
        moved = [state[0] + d, *state[1:]]
        segs = [moved] if abs(d) <= STEP_MAX else interpolate_pose(state, moved, max_step=STEP_MAX)
        yield f"pan{d:+g}", chunk_jog_commands("shoulder_pan.pos", d), [state, *segs, *plan(moved)]


def recover(cell, home, closed, *, plan, look, reserve, release, release_and_rise, low, log=lambda row: None, order=None,
            release_unmoved: bool = False, moved_out: list | None = None, advisor=None, load_check=None,
            bounds=None, tcp_x_m: float | None = None, clear_z_m: float = 0.10, extended_detours: bool = False,
            sleep=time.sleep) -> dict:
    """Fold the held arm home or hold it where it is; never moves without a clear, reserved corridor. order(names)
    gives the candidates' try order (learned outcomes); the set of candidates is never changed by it."""
    from cell_recovery_plan import build_candidates, classify_situation, run_detour_jogs

    steps, known, moved = [], {"state": None}, {"yes": False}  # known: last state seen; moved: any release/jog/park sent

    def mark_moved():
        moved["yes"] = True
        if moved_out is not None:
            moved_out.append(True)

    def note(row):
        steps.append(row)
        log(row)

    def hold(reason, is_holding: bool = False, **extra):
        # resting at home: end the session in place (torque OFF), nothing hangs out. The pose is read again right before
        # the stop (review N1: seconds of corridor checks may pass after the last read). Never drop a held load!
        if not is_holding and at_rest(known["state"], home) and at_rest(_ok_state(cell.act("state")), home):
            if (stopped := cell.act("stop now")).get("ok") is True:
                return {"schema": SCHEMA, "result": "held", "reason": reason, "steps": steps, "hold_ok": None, "ended": "stop_now", **extra}
        if release_unmoved and not moved["yes"] and not is_holding:
            if (stopped := cell.act("stop now")).get("ok") is True:
                return {"schema": SCHEMA, "result": "held", "reason": reason, "steps": steps, "hold_ok": None, "ended": "stop_now", "unmoved": True, **extra}
        held = cell.act("human-hold")
        return {"schema": SCHEMA, "result": "held", "reason": reason, "steps": steps, "hold_ok": held.get("ok"), **extra}

    status = cell.act("state")
    state = _ok_state(status)
    target = status.get("target") if isinstance(status.get("target"), list) and len(status["target"]) >= 6 else state
    known["state"] = state
    if state is None:
        return hold("STATE_UNREADABLE")
    if folded(state, home):
        return {"schema": SCHEMA, "result": "folded", "candidate": "already_home", "state": state, "steps": steps, "corridor": None}
    is_low = bool(low(state))
    if holding(state, target, closed):
        if not is_low:
            return hold("HOLDING_HIGH", is_holding=True)
        rise_lane = [state, [state[0], state[1] - RISE_UNITS, *state[2:]]]
        if not look(rise_lane).get("clear") or not reserve(rise_lane).get("ok"):
            release()
            return hold("RISE_BLOCKED", is_holding=True)
        known["state"] = None
        mark_moved()
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
        is_low = bool(low(state))

    situation = classify_situation(state, target, home, closed, low_ok=is_low, is_holding=False)
    tries = (build_candidates(list(target[:6]), home, closed, plan, bounds=bounds, tcp_x_m=tcp_x_m,
                              clear_z_m=clear_z_m, situation=situation, extended=True)
             if extended_detours else list(candidates(list(target[:6]), plan)))  # the runner parks from its held target
    if order is not None:
        rank = {name: i for i, name in enumerate(order([name for name, _, _ in tries]))}
        tries.sort(key=lambda c: (0 if situation == "low_open_jaws" and c[0].startswith("lift_") else 1, rank.get(c[0], len(rank))))

    def _try_candidate(name, before, frames):
        verdict = look(frames)
        note({"step": "check", "candidate": name, "clear": verdict.get("clear"), "low": len(verdict.get("low") or []),
              "high": len(verdict.get("high") or []), "off_map": verdict.get("off_map"), "off_surface": verdict.get("off_surface")})
        if not verdict.get("clear"):
            return None
        if load_check is not None:
            lc = load_check(frames)
            note({"step": "load_check", "candidate": name, "ok": lc.get("ok"), "verdict": lc.get("verdict")})
            if not lc.get("ok"):
                return None
        if not (booked := reserve(frames)).get("ok"):
            note({"step": "reserve", "candidate": name, "refused": booked.get("reason")})
            return None
        known["state"] = None  # from the first command the arm is no longer where it was read
        mark_moved()
        try:
            ok_jog, err_reason, err_ack = run_detour_jogs(cell, list(before), settle_tol=SETTLE_TOL, sleep=sleep)
            if not ok_jog:
                return hold(err_reason or "DETOUR_REFUSED", candidate=name, error=(err_ack or {}).get("error"))
            parked = cell.act("park")
        finally:
            release()
        at = known["state"] = _ok_state(parked)
        note({"step": "park", "candidate": name, "ok": parked.get("ok"), "settled": parked.get("settled"),
              "error": parked.get("error"), "contact": parked.get("contact")})
        if parked.get("ok") is True and parked.get("settled") is True and at is not None and folded(at, home):
            return {"schema": SCHEMA, "result": "folded", "candidate": name, "state": at, "steps": steps, "corridor": verdict}
        return hold("PARK_NOT_HOME", candidate=name, error=parked.get("error"))

    for name, before, frames in tries:
        if (outcome := _try_candidate(name, before, frames)) is not None:
            return outcome
    if advisor is not None:
        try:
            adv = advisor({"state": state, "target": list(target[:6]), "home": list(home), "closed": closed,
                           "holding": False, "low": bool(is_low or low(list(target[:6]))),
                           "situation": situation, "blocked": list(steps)})
        except Exception as exc:
            adv = {"audit": {"ok": False, "error": f"{type(exc).__name__}: {str(exc)[:120]}"}}
        note({"step": "advisor", **(adv.get("audit") or {})})
        if (cand := adv.get("candidate") if isinstance(adv, dict) else None) is not None and (outcome := _try_candidate(*cand)) is not None:
            return outcome
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
    if not path or name in (None, "already_home") or str(name).startswith("advisor:"):
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
    from cell_recovery_plan import wait_session_json

    sess, why = wait_session_json(cwd / "session.json", arm, started, sleep)
    if sess is None:
        return done({"result": "not_cleared", "why": why}, cand)
    torque = sess.get("torque_after") or {}
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
    import cell_params as prm
    import cell_pipeline as cp
    import cell_pivot
    import cell_place_fit
    import cell_recovery_plan as crp
    import cell_space
    import cell_unwedge
    import omx_tcp
    from cell_observe import predicted_pixel
    from omx_adapter.chunk_library import NAMES, park_path

    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--arm", required=True, help="the arm this session holds (its space reservation key)")
    ap.add_argument("--config", type=Path, required=True, help="the arm's cell-auto config (io, cameras, sites)")
    ap.add_argument("--library", type=Path, required=True, help="the arm's reviewed chunk library (home, transit)")
    ap.add_argument("--site", required=True, help="the surface whose map the corridor is checked on")
    ap.add_argument("--roi", nargs=4, type=int, required=True)
    ap.add_argument("--out", type=Path, required=True, help="result JSON")
    ap.add_argument("--supervised", action="store_true", help="bench operator recovery (no held incident id)")
    ap.add_argument("--vlm-url", help="optional AI-PC vision endpoint URL for tier-2 recovery proposals")
    ap.add_argument("--vlm-model", default="qwen3-vl:8b-instruct")
    ap.add_argument("--vlm-provider", default="ollama")
    ap.add_argument("--vlm-timeout", type=float, default=15.0)
    args = ap.parse_args(argv)
    if not args.supervised and not os.environ.get("ROSY_RECOVERY_INCIDENT"):
        ap.error("ROSY_RECOVERY_INCIDENT is required: this tool only folds an arm a held incident names")
    arm, cell, space, home, choices_path, moved_out = args.arm, None, None, [], None, []
    try:
        config = cell_place_fit.with_tiers(json.loads(args.config.read_text(encoding="utf-8")))[0]
        params = config["params"] = prm.load(config.get("params_path"))["values"]
        calibration, library = json.loads(Path(config["calibration_path"]).expanduser().read_text()), json.loads(args.library.read_text())
        home, closed = library["chunks"]["home"][-1], float(library["gripper_closed"])
        transit = {NAMES.index(k): float(v) for k, v in library.get("transit", {}).items()} or None
        cell = cp.FifoCell(Path(config["io"]).expanduser(), config["cameras"])
        space = cell_space.Space(Path(config.get("space_dir", "~/rosy-omx/space")).expanduser())
        to_px = lambda p: predicted_pixel(config, calibration, args.site, p)  # noqa: E731
        tcp_x_m, clear_z_m = omx_tcp.config_tcp(config) or library.get("tcp_x_m"), prm.get(params, "corridor.clear_z_m", cell_corridor.CLEAR_Z_M)
        bounds = crp.joint_bounds(config)
        choices_path = Path(config.get("work_dir") or ".") / f"auto-fold-choices-{arm}.json"
        choices = cell_choices.Choices(choices_path)
        for name in crp.extended_candidate_names():
            choices.offer(CHOICE, name, "D-1048")
        choices.save()
        plan = lambda s: park_path(list(s), home, closed, library["fps"], transit, library.get("transit_speed", 0.85))  # noqa: E731
        low = lambda s: crp.fk_z(s, tcp_x_m=tcp_x_m) < clear_z_m  # noqa: E731
        look = crp.build_multi_site_look(cell, config, calibration, args.site, args.roi, params, to_px, tcp_x_m)
        load_check = crp.make_load_checker(config, library, params)
        advisor = None
        if args.vlm_url:
            from cell_recovery_advisor import make_advisor
            spec = {"provider": args.vlm_provider, "url": args.vlm_url, "model": args.vlm_model, "vision": True}
            cam_views = tuple(k for k in ("top", "side", f"{arm}_wrist", "wrist") if k in (config.get("cameras") or {})) or ("top", "side", "wrist")
            advisor = make_advisor(spec, cell, home=home, plan=plan, bounds=bounds, tcp_x_m=tcp_x_m,
                                   clear_z_m=clear_z_m, views=cam_views, timeout_s=args.vlm_timeout, propose_only=not args.supervised)

        def reserve(frames):
            r = cell_corridor.runs([cell_pivot.joints_tcp(f, tcp_x_m=tcp_x_m)[:3] for f in frames])
            lane = cell_corridor.corridor(r[0] + r[1], to_px, (args.roi[3] - args.roi[1], args.roi[2] - args.roi[0]),
                                          args.roi, prm.get(params, "corridor.half_width_mm", cell_corridor.HALF_WIDTH_MM))
            return space.reserve(arm, lane, ttl_s=300.0)

        result = recover(cell, home, closed, plan=plan, look=look, reserve=reserve, release=lambda: space.release(arm),
                         release_and_rise=cell_unwedge.release_and_rise, low=low, order=lambda n: choices.ranked(CHOICE, n),
                         release_unmoved=args.supervised, moved_out=moved_out, advisor=advisor, load_check=load_check,
                         bounds=bounds, tcp_x_m=tcp_x_m, clear_z_m=clear_z_m, extended_detours=True)
    except Exception as exc:  # whatever broke, keep torque ON if moved; else stop now when supervised
        err = f"ERROR: {type(exc).__name__}: {str(exc)[:160]}"
        if space is not None:
            space.release(arm)
        if cell is None:
            result = {"schema": SCHEMA, "result": "held", "reason": err, "hold_ok": None,
                      **({"unmoved": True} if args.supervised else {}), "steps": []}
        else:
            stopped = cell.act("stop now") if args.supervised and not moved_out else {}
            if stopped.get("ok") is True:
                result = {"schema": SCHEMA, "result": "held", "reason": err, "hold_ok": None, "ended": "stop_now", "unmoved": True, "steps": []}
            else:
                result = {"schema": SCHEMA, "result": "held", "reason": err, "hold_ok": cell.act("human-hold").get("ok"), "steps": []}
    result["incident_id"] = None if args.supervised else os.environ["ROSY_RECOVERY_INCIDENT"]
    result["home"], result["supervised"] = list(home), bool(args.supervised)
    if choices_path is not None:
        result["choices_path"] = str(choices_path)
    if result["result"] == "folded":
        result["stop"] = cell.act("stop")  # at home: the runner's stop folds nothing more and turns torque OFF
    args.out.write_text(json.dumps(result, default=str, indent=1))
    print(json.dumps({k: result.get(k) for k in ("result", "reason", "candidate")}))
    return 0 if result["result"] == "folded" else 3


if __name__ == "__main__":
    raise SystemExit(main())
