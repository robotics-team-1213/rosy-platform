"""D-1077: the cell job API's side of the stop proof (measure before a moving job starts) and the one automatic recover_hold.

Split from cell_job_api (400-line rule). `prove_job` returns (proof, None) or (None, refusal); a job that never needed a person
(dry run, reviewed, recovery) gets (None, None). `auto_recover_once` follows a no-move refusal that says next=recover_hold.
"""
from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any

import cell_arm_lease
import cell_stop_proof
from cell_job_guards import ROLE_HUMAN, ROLE_MACHINE, Principal, read_json_dict
from cell_job_peer_health import passive_motor_health_folded
from cell_job_readiness import parse_structured_result

RECOVER_WINDOW_S = 10.0  # the reap thread runs right after the process exits; the log's last write is its exit time
DEFAULTS_FILE = "recover-hold-defaults.json"  # {arm: {"site": ..., "roi": [...], "config": ..., "library": ...}} when the failed job has none


def _just_ended(log: Path, window_s: float = RECOVER_WINDOW_S) -> bool:
    try:
        return 0.0 <= time.time() - Path(log).stat().st_mtime <= window_s
    except OSError:
        return False


def needs_proof(job: dict, params: dict, moving: bool) -> bool:
    """The jobs that used to need person_at_switch: moving, not reviewed, not a recovery of a held arm."""
    reviewed = bool(job.get("reviewed_only")) or (params.get("reviewed_auto") is True and "reviewed_auto" in (job.get("optional") or ()))
    return moving and not reviewed and not job.get("attach_live_hold") and not job.get("recovery_home")


def observe_factory(runner, live_max_age_s: float, session_held_fn):
    def observe(arm: str) -> dict[str, Any]:
        lease = read_json_dict(runner.lease_dir / f"{arm}.json")
        health = runner.motor_health_dir if runner.motor_health_dir is not None else Path.home() / ".local/state/rosy/motor-health"
        return {"live": read_json_dict(runner.workdir / f"chunk-io-{arm.split('_')[-1]}" / "live.json"),
                "session": bool(session_held_fn(arm, runner.lock_dir)) or bool(lease and cell_arm_lease.live(lease)),
                "cold_folded": passive_motor_health_folded(arm, health, max_age_s=live_max_age_s, read_json_fn=read_json_dict,
                                                           calibration_dir=runner.calibration_dir),
                "fleet": runner._check_fleet_safety(arm)}
    return observe


def prove_job(runner, jid: str, name: str, job: dict, arms: tuple[str, ...], params: dict, moving: bool, ignored: Any,
              principal: Principal, *, live_max_age_s: float, session_held_fn) -> tuple[dict | None, dict | None]:
    if not needs_proof(job, params, moving):
        return None, None
    proof = cell_stop_proof.measure(jid, arms, observe_factory(runner, live_max_age_s, session_held_fn), max_age_s=live_max_age_s)
    cell_stop_proof.audit_proof(runner.out, proof, ignored_person=ignored, job=name, principal=f"{principal.role}:{principal.principal_id}")
    if proof["ok"]:
        return proof, None
    return None, {"code": 409, "error_code": proof["code"], "error": f"no stop-capability proof: {proof['reason']}", "stop_proof": proof}


def auto_recover_once(runner, jid: str, run: dict, *, live_max_age_s: float, session_held_fn) -> dict | None:
    """After a moving job ends with next=recover_hold, run recover_hold on the same arm once, if a recovery proof passes.
    Only for a job a human principal started (a machine token never gains recover_hold this way); never raises: the job's own
    audit row must still be written."""
    try:
        return _auto_recover(runner, jid, run, live_max_age_s, session_held_fn)
    except Exception as exc:
        run["auto_recover"] = {"event": "auto_recover", "id": jid, "started": False, "reason": f"error: {exc}"}
        return run["auto_recover"]


def _auto_recover(runner, jid: str, run: dict, live_max_age_s: float, session_held_fn) -> dict | None:
    if not run.get("moving") or run["job"] == "recover_hold" or run.get("arm") is None or run.get("auto_recover") is not None:
        return None
    result = parse_structured_result(run["log"])[0]
    if not isinstance(result, dict) or result.get("next") != "recover_hold":
        return None
    # the latch to clear is the one this job's own refusal sent; a hold a person asks for later is indistinguishable in live.json,
    # so only the moments right after the job ended count, and a refusal that kept no hold has nothing to clear
    if result.get("hold_kept") is not True or not result.get("reason_code") or not _just_ended(run["log"]):
        return None
    arm = run["arm"]
    out: dict[str, Any] = {"event": "auto_recover", "id": jid, "arm": arm, "started": False, "time": time.time()}
    run["auto_recover"] = out  # set first: a second pass over this run cannot start another
    defaults = (read_json_dict(runner.out / DEFAULTS_FILE) or {}).get(arm) or {}
    params = {"arm": arm, **{k: run["params"].get(k) or defaults.get(k) for k in ("config", "library", "site", "roi")}}
    principal = Principal(run.get("principal_role", ROLE_HUMAN), run.get("principal_id", ROLE_HUMAN))
    if principal.role == ROLE_MACHINE:
        out["reason"] = "machine_principal"
    elif any(v is None for v in params.values()):
        out["reason"] = "no_recover_params"
    else:
        proof = cell_stop_proof.measure(f"{jid}-recover", (arm,), observe_factory(runner, live_max_age_s, session_held_fn),
                                        max_age_s=live_max_age_s, recovery=True)
        cell_stop_proof.audit_proof(runner.out, proof, job="recover_hold", principal=f"{principal.role}:{principal.principal_id}")
        if not proof["ok"]:
            out["reason"] = proof["code"]
        else:
            res = runner.start("recover_hold", params, principal=principal)
            out.update(started=res.get("code") == 202, recover_job_id=res.get("id"), http_code=res.get("code"),
                       **({} if res.get("code") == 202 else {"reason": res.get("error_code") or res.get("error")}))
    with runner.lock, open(runner.out / "audit.jsonl", "a", encoding="utf-8") as fh:
        fh.write(json.dumps(out) + "\n")
    return out
