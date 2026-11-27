"""No held arm waits for a person (D-1079, user 2026-11-27): retry the automatic recovery of every held arm, with backoff.

A held arm stays where it stopped with torque ON (an extended arm never loses torque). This loop runs inside the cell job API
and, for each arm named in ~/.config/rosy/auto-fold.json (the D-1048 per-arm opt-in, roi and site), retries what a person used
to start:
  - a live runner hold (live.json human_hold_latched and torque_hold_commanded, its session alive): the recover_hold job
    (D-1048 addendum: look, corridor check, cell_space reservation, recover-unlatch, park-slow), principal machine:hold-retry;
  - an ended session with an open local incident hold: the D-1048 cell_auto_fold launch. The last try's per-incident marker
    is moved aside first (a try still running is waited for; a marker with no result after STALE_S is a dead try).
Backoff per arm: RETRY_S in turn, then its last value for as long as the hold lasts; reset once the arm holds nothing.

A try that loads a motor is not repeated blindly (OMX A/B review 2026-11-27: arm_a at 15:15 hit the lift PWM cap and latched an
overload on ID 12, and at 15:30 a new session pushed at rest into a following error). After a load failure (overload, strain,
pushing, stall, following error, hardware error; the incident's own fault counts) or with a latched hardware error, a motion try
needs a fresh motor-health snapshot (or an ended, all torque-OFF session's, COOLED_S after it; an ended session still holding
torque has none, so it waits) with no hardware error and every motor under COOL_C. After LOAD_FAILS_MAX load failures the
arm is not moved again until its measured pose changes by POSE_MOVED_DEG; the loop keeps auditing that it waits (no motion, no
person latch). Skipped as well: a pause file (cell-job-api/hold-retry-off or hold-retry-off-<arm>, a person working on the arm),
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
COOL_C, LOAD_FAILS_MAX, POSE_MOVED_DEG, HEALTH_MAX_AGE_S = 45.0, 2, 5.0, 30.0
CLEAR_GRACE_S = 300.0  # a hold unseen this long is gone; a shorter gap (stale live.json, session end before the incident) keeps the counts
COOLED_S = 600.0  # an ended session's last snapshot stands for a torque-OFF arm this long after it: cooled, pose unchanged
PRINCIPAL = Principal(ROLE_MACHINE, "hold-retry")
DEFAULTS_FILE = "recover-hold-defaults.json"  # cell_job_proof's {arm: {config, library, site, roi}}
PEERS = {"arm_a": ("arm_b",), "arm_b": ("arm_a",)}
LOAD_FAILURE = re.compile(r"overload|strain|push|stall|following error|hardware error|hw_error|PWM", re.I)
TICK_DEG = 360.0 / 4096


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
    folders = sorted(p for p in incidents.glob(f"*-{arm}") if p.is_dir())
    return ((read_json_dict(folders[-1] / "incident.json") or {}).get("facts") or {}) if folders else {}


def health(health_dir: Path, arm: str, now: float) -> dict | None:
    """Motor-health snapshot {"cool", "hw_ok", "pose_deg"}: a fresh one, or an ended session's with every motor torque OFF
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
                "pose_deg": [float(m["present_raw"]) * TICK_DEG for m in motors[:5]]}
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
    """Why a motion try must not start now, or None. A snapshot with a hardware error always stops it."""
    if snap is not None and not snap["hw_ok"]:
        return "HARDWARE_ERROR_LATCHED"
    if st["load_fails"] >= LOAD_FAILS_MAX:
        if snap is None or st.get("stuck_pose") is None:
            return "LOAD_FAILED_WAIT_POSE"
        if max(abs(a - b) for a, b in zip(snap["pose_deg"], st["stuck_pose"])) < POSE_MOVED_DEG:
            return "LOAD_FAILED_WAIT_POSE"
        st.update(load_fails=0, stuck_pose=None)  # moved since: a fresh situation
    if st["load_fails"] or facts.get("latched"):
        if snap is None:
            return "NO_FRESH_MOTOR_HEALTH"
        if not snap["hw_ok"]:
            return "HARDWARE_ERROR_LATCHED"
        if not snap["cool"]:
            return "MOTORS_NOT_COOL"
    return None


def tick(runner, state: dict, now: float, *, arms, observe, incident_status, launch_fold, incidents: Path,
         health_dir: Path) -> list[dict]:
    rows = []
    for arm in arms:
        st = state.setdefault(arm, {"tries": 0, "next": 0.0, "load_fails": 0, "pending": None, "stuck_pose": None, "hold": None})
        kind = needs(observe(arm), incident_status(arm))
        if kind is None:
            st.setdefault("unseen_since", now)
            if now - st["unseen_since"] >= CLEAR_GRACE_S:
                state[arm] = {"tries": 0, "next": 0.0, "load_fails": 0, "pending": None, "stuck_pose": None, "hold": None}
            continue
        st.pop("unseen_since", None)
        facts = latest_incident_facts(incidents, arm)
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
        if st["load_fails"] >= LOAD_FAILS_MAX and st.get("stuck_pose") is None and snap is not None:
            st["stuck_pose"] = snap["pose_deg"]
        if (runner.out / "hold-retry-off").exists() or (runner.out / f"hold-retry-off-{arm}").exists():
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
        st["next"] = now + RETRY_S[min(st["tries"], len(RETRY_S)) - 1]
        with runner.lock, open(runner.out / "audit.jsonl", "a", encoding="utf-8") as fh:
            fh.write(json.dumps(row) + "\n")
        rows.append(row)
    return rows


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
                 incidents=Path(omx_incident.INCIDENTS), health_dir=health_dir)
        except Exception as exc:  # noqa: BLE001  a bad pass must not end the loop; the holds stay, torque ON
            with runner.lock, open(runner.out / "audit.jsonl", "a", encoding="utf-8") as fh:
                fh.write(json.dumps({"event": "hold_retry", "error": f"{type(exc).__name__}: {str(exc)[:200]}", "time": clock()}) + "\n")
        sleep(TICK_S)
