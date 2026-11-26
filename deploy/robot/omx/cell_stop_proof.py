"""D-1077: the stop-capability proof that replaces a declared person at the switch (D-911 4, D-1024 L3).

The runner measures it right before a moving job starts. A request value cannot make it: `person_at_switch` in a request is
dropped and only recorded. A proof binds one job id, its arms and a time, is never reused, and is written to audit.jsonl.
Recovery jobs (`recovery=True`) already have the hold latched, so a latch, fault or unfolded arm does not fail them.
shortcut: a cold arm (no fresh live.json, no session) is proved by the passive motor-health snapshot only; a library home
is checked by the drive in its own pre-settle step, not here.
"""
from __future__ import annotations

import json
import math
import time
from pathlib import Path
from typing import Any, Callable

_MINTED: set[tuple[str, float]] = set()  # proofs this process measured: a dict from a file or a request is not one

from cell_job_peer_health import live_folded

SCHEMA = "rosy.stop-proof.v1"
MAX_AGE_S = 30.0  # a proof older than this at use is not one
CODES = ("STOP_PROOF_FLEET_BLOCKED", "STOP_PROOF_LIVE_STALE", "STOP_PROOF_FAULT", "STOP_PROOF_LATCH", "STOP_PROOF_CONTACT",
         "STOP_PROOF_NOT_SETTLED", "STOP_PROOF_NOT_FOLDED", "STOP_PROOF_ARM_STATE_UNKNOWN", "STOP_PROOF_NO_REMOTE_STOP")


def _fresh(live: dict | None, now: float, max_age_s: float) -> bool:
    t = live.get("t") if isinstance(live, dict) else None
    return isinstance(t, (int, float)) and not isinstance(t, bool) and math.isfinite(float(t)) and -2.0 <= now - float(t) <= max_age_s


def check_arm(live: dict | None, *, now: float, max_age_s: float, session: bool, cold_folded: bool, fleet: dict,
              recovery: bool = False) -> tuple[str | None, str, bool]:
    """(code or None, basis, remote_stop) for one arm from what was just observed."""
    if fleet.get("blocked"):
        return "STOP_PROOF_FLEET_BLOCKED", "fleet", False
    online = bool(fleet.get("online"))
    if not _fresh(live, now, max_age_s):
        if session:
            return "STOP_PROOF_LIVE_STALE", "live", online  # a session claims the arm but publishes nothing fresh
        if not cold_folded:
            return "STOP_PROOF_ARM_STATE_UNKNOWN", "none", online
        return (None if online else "STOP_PROOF_NO_REMOTE_STOP"), "motor_health_folded", online
    fault = str(live.get("fault") or "")
    if live.get("contact") or fault.startswith("contact"):
        return "STOP_PROOF_CONTACT", "live", True  # a contact hold is a person's to clear, recovery included
    if (fault and not (recovery and fault.startswith("human hold"))) or (live.get("interrupt") and not recovery):
        return "STOP_PROOF_FAULT", "live", True
    if not recovery and live.get("human_hold_latched"):
        return "STOP_PROOF_LATCH", "live", True
    if live.get("chunk") is not None or live.get("settled") is False:
        return "STOP_PROOF_NOT_SETTLED", "live", True
    if not recovery and not (live_folded(live) is True or live.get("at_home") is True):
        return "STOP_PROOF_NOT_FOLDED", "live", True
    return None, "live", True  # a fresh runner publishing live.json takes the local human-hold command


def measure(job_id: str, arms: tuple[str, ...], observe: Callable[[str], dict[str, Any]], *, now: float | None = None,
            max_age_s: float = 15.0, recovery: bool = False) -> dict[str, Any]:
    """Measure every arm. `observe(arm)` returns {live, session, cold_folded, fleet}; the first failure names the code."""
    now = time.time() if now is None else now
    proof: dict[str, Any] = {"schema": SCHEMA, "job_id": job_id, "arms": list(arms), "at": now, "ok": True, "code": None,
                              "reason": None, "basis": {}, "fleet_online": False, "recovery": recovery}
    if not arms:
        return {**proof, "ok": False, "code": "STOP_PROOF_ARM_STATE_UNKNOWN", "reason": "no arm to prove"}
    for arm in arms:
        obs = observe(arm)
        fleet = obs.get("fleet") or {}
        code, basis, _remote = check_arm(obs.get("live"), now=now, max_age_s=max_age_s, session=bool(obs.get("session")),
                                         cold_folded=bool(obs.get("cold_folded")), fleet=fleet, recovery=recovery)
        proof["basis"][arm] = basis
        proof["fleet_online"] = proof["fleet_online"] or bool(fleet.get("online"))
        if code is not None:
            return {**proof, "ok": False, "code": code, "reason": f"{arm}: {fleet.get('reason') or code.removeprefix('STOP_PROOF_').lower()}"}
    _MINTED.add((job_id, now))
    return proof


def session_proof(cell, job_id: str, arm: str, *, max_age_s: float = 15.0) -> dict[str, Any]:
    """The drive's own measurement from the running session's live.json. Fleet is the job API's check, so it is not asked again.
    shortcut: `at_home` is taken as true because cell_policy_pre_home refuses an arm off home before any command; upgrade
    when the live row carries a library-home verdict."""
    live = cell.policy_state() if hasattr(cell, "policy_state") else None
    obs = {"live": {**live, "at_home": True} if isinstance(live, dict) else None, "session": True, "cold_folded": False, "fleet": {}}
    return measure(job_id, (arm,), lambda _arm: obs, max_age_s=max_age_s)


def verify(proof: Any, *, job_id: str | None = None, arms: tuple[str, ...] | None = None, now: float | None = None,
           local: bool = False) -> bool:
    """A passing proof of this schema, fresh, and (when given) for exactly this job and these arms. `local`: this process measured it."""
    now = time.time() if now is None else now
    return (isinstance(proof, dict) and (not local or ((proof.get("job_id"), proof.get("at")) in _MINTED and proof.get("recovery") is not True)) and proof.get("schema") == SCHEMA and proof.get("ok") is True
            and isinstance(proof.get("at"), (int, float)) and not isinstance(proof.get("at"), bool) and -2.0 <= now - proof["at"] <= MAX_AGE_S
            and (job_id is None or proof.get("job_id") == job_id) and (arms is None or tuple(proof.get("arms") or ()) == tuple(arms)))


def audit_proof(out_dir: Path, proof: dict, *, ignored_person: Any = None, job: str = "", principal: str = "") -> None:
    """One audit.jsonl row, for a pass and for a refusal; a request's person_at_switch is recorded here and nowhere else."""
    row = {"id": proof["job_id"], "event": "stop_proof" if proof["ok"] else "stop_proof_refused", "job": job, "principal": principal,
           "time": time.time(), "person_at_switch_ignored": ignored_person, **proof}
    with open(Path(out_dir) / "audit.jsonl", "a", encoding="utf-8") as fh:
        fh.write(json.dumps(row) + "\n")
