"""No held arm waits for a person (D-1079, user 2026-11-27): retry the automatic recovery of every held arm, with backoff.

A held arm stays where it stopped with torque ON (an extended arm never loses torque). This loop runs inside the cell job API
and, for each arm named in ~/.config/rosy/auto-fold.json (the D-1048 per-arm opt-in, roi and site), retries what a person used
to start:
  - a live runner hold (live.json human_hold_latched and torque_hold_commanded, its session alive): the recover_hold job
    (D-1048 addendum: look, corridor check, cell_space reservation, recover-unlatch, park-slow), principal machine:hold-retry;
  - an ended session with an open local incident hold: the D-1048 cell_auto_fold launch. The last try's per-incident marker
    is moved aside first (a try still running is waited for; a marker with no result after STALE_S is a dead try).
Backoff per arm: RETRY_S in turn, then its last value for as long as the hold lasts; reset once the arm holds nothing.

The loop solves rather than waits (user 2026-11-27: "막는 코드가 아니라 푸는 코드"). Each try is a different way out: the fold
learns every candidate's outcome (cell_choices) and tries the next one first, and the candidates include elbow_in_then_park,
which folds the forearm in before the lift so shoulder_lift carries a shorter lever (arm_a 15:15 hit the lift PWM cap and latched
an overload on ID 12; 15:30 pushed at rest into a following error). A load or supply latch is rebooted by omx_incident at the
session end wherever the arm rests (all six torques read 0 first). What a try still waits for resolves itself: after a load
failure (overload, strain, pushing, stall, following error, hardware error; the incident's own fault counts) the motors must be
under COOL_C (a fresh snapshot, or an ended all torque-OFF session's COOLED_S after it), and an unrebooted latch waits for its
reboot. Skipped as well: a pause file (cell-job-api/hold-retry-off or hold-retry-off-<arm>, a person working on the arm),
a moving job on the arm or, for A/B, on the peer, and a home-recovery hold. Every try and every skip reason goes to
cell-job-api/audit.jsonl.
"""
from __future__ import annotations

import json
import re
import time
from pathlib import Path

from cell_job_guards import ROLE_MACHINE, Principal, read_json_dict

RETRY_S = (60.0, 120.0, 240.0, 480.0, 600.0)
TICK_S = 15.0
STALE_S = 3900.0  # longer than cell_auto_fold launch's own 3600 s bound
COOL_C, HEALTH_MAX_AGE_S = 45.0, 30.0
ROTATION, ROTATION_S = 12, 3600.0  # extended_candidate_names() once round: after that an hour between tries, still no person
CLEAR_GRACE_S = 300.0  # a hold unseen this long is gone; a shorter gap (stale live.json, session end before the incident) keeps the counts
COOLED_S = 600.0  # an ended session's last snapshot stands for a torque-OFF arm this long after it: cooled, pose unchanged
PRINCIPAL = Principal(ROLE_MACHINE, "hold-retry")
DEFAULTS_FILE = "recover-hold-defaults.json"  # cell_job_proof's {arm: {config, library, site, roi}}
PEERS = {"arm_a": ("arm_b",), "arm_b": ("arm_a",)}
LOAD_FAILURE = re.compile(r"overload|strain|push|stall|following error|hardware error|hw_error|PWM", re.I)


def needs(observation: dict, incident: dict) -> str | None:
    """What would free this arm: "live_hold", "incident", or None (nothing held, or a hold this loop does not own)."""
    live = observation.get("live") or {}
    if observation.get("session"):
        return "live_hold" if live.get("human_hold_latched") and live.get("torque_hold_commanded") else None
    if "home_recovery" in str(incident.get("fleet_reason") or "") + str(incident.get("local_reason") or ""):
        return None
    return "incident" if incident.get("local_held") else None


def _busy(runner, arm: str) -> bool:
    arms = {arm, *PEERS.get(arm, ())}
    with runner.lock:
        return any(r.get("moving") and arms & set(r.get("arms") or (r.get("arm"),)) and r["proc"].poll() is None
                   for r in runner.runs.values())


def _markers(incidents: Path, arm: str):
    for marker in sorted(incidents.glob("auto-fold-*.json")):
        if marker.name.endswith(".result.json") or ".try" in marker.name:
            continue
        row = read_json_dict(marker) or {}
        if row.get("arm") == arm and row.get("stage", "full") == "full":
            yield marker, marker.with_name(marker.name[:-5] + ".result.json"), row


def fold_running(incidents: Path, arm: str, now: float) -> bool:
    return any(not res.exists() and now - float(row.get("at") or 0) < STALE_S for _, res, row in _markers(incidents, arm))


def rotate_finished_folds(incidents: Path, arm: str, now: float) -> list[str]:
    """Move this arm's finished (or dead) fold markers aside; return their outcomes."""
    outcomes = []
    for marker, result, _ in list(_markers(incidents, arm)):
        res = read_json_dict(result) if result.exists() else {"result": "dead", "why": "no result"}
        outcomes.append(" ".join(str((res or {}).get(k) or "") for k in ("result", "why", "reason")))
        stamp = f".try{int(now)}"
        if result.exists():
            result.rename(result.with_name(result.name[:-12] + stamp + ".result.json"))
        marker.rename(marker.with_name(marker.name[:-5] + stamp + ".json"))
    return outcomes


def latest_incident_facts(incidents: Path, arm: str) -> dict:
    """The arm's latest incident facts; "latched" is emptied once omx_incident's reboot of exactly those IDs succeeded."""
    folders = sorted(p for p in incidents.glob(f"*-{arm}") if p.is_dir())
    doc = (read_json_dict(folders[-1] / "incident.json") or {}) if folders else {}
    facts = dict(doc.get("facts") or {}, incident=folders[-1].name if folders else None)
    rebooted = {str(i) for i in ((doc.get("recovery") or {}).get("rebooted") or [])}
    if facts.get("latched") and set(map(str, facts["latched"])) <= rebooted:
        facts["latched"], facts["rebooted"] = {}, sorted(rebooted)
    return facts


def health(health_dir: Path, arm: str, now: float) -> dict | None:
    """Motor-health snapshot {"cool", "hw_ok"}: a fresh one, or an ended session's with every motor torque OFF
    since COOLED_S (cool by then); None otherwise."""
    doc = read_json_dict(health_dir / f"{arm}.json") or {}
    motors = doc.get("motors")
    try:
        age = now - float(doc["observed_at"])
        cooled = (doc.get("status") == "ended" and age >= COOLED_S
                  and all(m.get("torque_enabled") is False for m in motors or ()))
        if not isinstance(motors, list) or len(motors) != 6 or not (0 <= age <= HEALTH_MAX_AGE_S or cooled):
            return None
        return {"cool": cooled or all(float(m["temperature_c"]) < COOL_C for m in motors),
                "hw_ok": all(m.get("hardware_error") == 0 and not m.get("fault") for m in motors),
                "hw_bad": sorted(str(m.get("id")) for m in motors if m.get("hardware_error") != 0 or m.get("fault")),
                "max_temp_c": max(float(m["temperature_c"]) for m in motors),
                "max_pwm_util": max(float(m.get("pwm_utilization") or 0.0) for m in motors),
                "raw": [float(m["present_raw"]) for m in motors[:5]]}
    except (KeyError, TypeError, ValueError):
        return None


def _outcome(runner, st: dict, incidents: Path, arm: str, now: float) -> None:
    """Count the finished try's load failure (live: the recover_hold job's result file; incident: read at rotation)."""
    pending = st.get("pending")
    if not pending or pending.get("kind") != "live_hold":
        return
    with runner.lock:
        run = runner.runs.get(pending.get("job_id"))
    if run is not None and run["proc"].poll() is None:
        return
    out = runner.out / f"recover-hold-{arm}.json"
    fresh = out.exists() and out.stat().st_mtime >= pending["at"] - 1.0  # an older try's file says nothing of this one
    st["pending"] = None
    res = read_json_dict(out) or {} if fresh else {}
    st["load_fails"] += bool(LOAD_FAILURE.search(" ".join(str(res.get(k) or "") for k in ("result", "why", "reason", "error"))))


def gate(st: dict, facts: dict, snap: dict | None) -> str | None:
    """What a motion try still waits for (it resolves itself: a reboot, cooling), or None."""
    if facts.get("latched") or (snap is not None and set(snap["hw_bad"]) - set(facts.get("rebooted") or ())):
        return "HARDWARE_ERROR_LATCHED"  # omx_incident reboots a load or supply latch at the session end
    if st["load_fails"]:
        if snap is None:
            return "NO_FRESH_MOTOR_HEALTH"
        if not snap["cool"]:
            return "MOTORS_NOT_COOL"
    return None


def tick(runner, state: dict, now: float, *, arms, observe, incident_status, launch_fold, incidents: Path,
         health_dir: Path, reboot=None) -> list[dict]:
    rows = []
    for arm in arms:
        st = state.setdefault(arm, {"tries": 0, "next": 0.0, "load_fails": 0, "pending": None, "hold": None})
        kind = needs(observe(arm), incident_status(arm))
        if kind is None:
            st.setdefault("unseen_since", now)
            if now - st["unseen_since"] >= CLEAR_GRACE_S:
                state[arm] = {"tries": 0, "next": 0.0, "load_fails": 0, "pending": None, "hold": None}
            continue
        st.pop("unseen_since", None)
        facts = latest_incident_facts(incidents, arm)
        done = st.get("rebooted") or {}  # {incident folder: ids}; a newer incident's latch is a new latch
        if facts.get("latched") and set(map(str, facts["latched"])) <= set(done.get(facts.get("incident"), ())):
            facts["latched"], facts["rebooted"] = {}, done[facts["incident"]]
        if st["hold"] is None:  # a new hold: the fault that made it counts as its first try
            st["hold"] = kind
            st["load_fails"] = int(any(LOAD_FAILURE.search(f"{(f or {}).get('fault') or ''} {(f or {}).get('error') or ''}") for f in facts.get("flagged") or []))
        _outcome(runner, st, incidents, arm, now)
        if now < st["next"] or _busy(runner, arm) or fold_running(incidents, arm, now):
            continue
        row = {"event": "hold_retry", "arm": arm, "kind": kind, "try": st["tries"] + 1, "time": now, "started": False}
        if kind == "incident":
            outcomes = rotate_finished_folds(incidents, arm, now)
            st["load_fails"] += sum(bool(LOAD_FAILURE.search(o)) for o in outcomes)
        snap = health(health_dir, arm, now)
        row.update({k: snap[k] for k in ("max_temp_c", "max_pwm_util")} if snap else {})
        if snap and st.get("raw"):  # what the last try changed: 0 over a run of tries is "no progress" at a glance
            row["moved_deg"] = round(max(abs(a - b) for a, b in zip(snap["raw"], st["raw"])) * 360 / 4096, 1)
        st["raw"] = snap["raw"] if snap else st.get("raw")
        paused = (runner.out / "hold-retry-off").exists() or (runner.out / f"hold-retry-off-{arm}").exists()
        if (not paused and kind == "incident" and facts.get("latched") and reboot is not None
                and not observe(arm).get("session")):  # still no session on the bus right now: clear the latch here
            row["reboot"] = res = reboot(arm, sorted(facts["latched"]))
            if set(map(str, (res or {}).get("rebooted") or ())) >= set(map(str, facts["latched"])):
                facts["rebooted"] = sorted(map(str, res["rebooted"]))
                st["rebooted"] = {facts.get("incident"): facts["rebooted"]}
                facts["latched"] = {}
        if paused:
            row["reason"] = "PAUSED"
        elif (why := gate(st, facts, snap)) is not None:
            row["reason"] = why
        elif kind == "live_hold":
            defaults = (read_json_dict(runner.out / DEFAULTS_FILE) or {}).get(arm) or {}
            params = {"arm": arm, **{k: defaults.get(k) for k in ("config", "library", "site", "roi")}}
            if any(v is None for v in params.values()):
                row["reason"] = "no_recover_params"
            else:
                res = runner.start("recover_hold", params, principal=PRINCIPAL)
                row.update(started=res.get("code") == 202, job_id=res.get("id"),
                           **({} if res.get("code") == 202 else {"reason": res.get("error_code") or res.get("error")}))
                if row["started"]:
                    st["pending"] = {"kind": kind, "job_id": res.get("id"), "at": now}
        else:
            res = launch_fold(arm)
            row.update(started=bool(res.get("started")), **({} if res.get("started") else {"reason": res.get("why")}))
        row["load_fails"] = st["load_fails"]
        st["tries"] += 1
        st["next"] = now + (ROTATION_S if st["load_fails"] >= ROTATION else RETRY_S[min(st["tries"], len(RETRY_S)) - 1])
        row["no_progress"] = st["load_fails"] >= ROTATION  # every candidate has failed once: slower, still trying
        with runner.lock, open(runner.out / "audit.jsonl", "a", encoding="utf-8") as fh:
            fh.write(json.dumps(row) + "\n")
        rows.append(row)
    return rows


def reboot_latch(arm: str, ids: list) -> dict:
    """omx_incident.reboot_latched on the arm's follower port (from its auto-fold config); it refuses unless all six read torque 0."""
    import omx_incident
    import omx_incident_auto

    conf = (json.loads(omx_incident_auto._auto_fold_config().read_text(encoding="utf-8")) or {}).get(arm) or {}
    cfg = read_json_dict(Path(conf.get("cwd", ".")).expanduser() / str(conf.get("config"))) or {}
    rec = read_json_dict(Path(str(cfg.get("record_config_path") or "-")).expanduser()) or {}
    port = cfg.get("port") or (cfg.get("follower") or {}).get("port") or rec.get("port") or (rec.get("robot") or {}).get("port")
    if not port:
        return {"refused": "no follower port in the arm's config"}
    return omx_incident.reboot_latched(str(port))([int(i) for i in ids])


def start(runner, **kwargs) -> None:
    import threading

    threading.Thread(target=run_forever, args=(runner,), kwargs=kwargs, daemon=True, name="hold-retry").start()


def run_forever(runner, *, live_max_age_s: float, session_held_fn, sleep=time.sleep, clock=time.time) -> None:
    """The cell job API's background thread; an error in one pass is audited and the loop goes on."""
    import omx_incident
    import omx_incident_auto
    from cell_job_proof import observe_factory

    observe = observe_factory(runner, live_max_age_s, session_held_fn)
    health_dir = runner.motor_health_dir or Path.home() / ".local/state/rosy/motor-health"
    state: dict = {}
    while True:
        try:
            tick(runner, state, clock(), arms=omx_incident_auto.configured_fold_arms(), observe=observe,
                 incident_status=omx_incident.status, launch_fold=omx_incident_auto.launch_auto_fold,
                 incidents=Path(omx_incident.INCIDENTS), health_dir=health_dir, reboot=reboot_latch)
        except Exception as exc:  # noqa: BLE001  a bad pass must not end the loop; the holds stay, torque ON
            with runner.lock, open(runner.out / "audit.jsonl", "a", encoding="utf-8") as fh:
                fh.write(json.dumps({"event": "hold_retry", "error": f"{type(exc).__name__}: {str(exc)[:200]}", "time": clock()}) + "\n")
        sleep(TICK_S)
