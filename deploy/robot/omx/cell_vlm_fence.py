"""TOCTOU failure-context fence and fail-closed post-job outcome verification for VLM orchestration."""
from __future__ import annotations

import math
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import cell_failure_context as cfc  # noqa: E402
from cell_job_client import CellJobClient, CellJobError  # noqa: E402


def _finite_float(val) -> float | None:
    if isinstance(val, bool) or not isinstance(val, (int, float)):
        return None
    f = float(val)
    return f if math.isfinite(f) else None


def _valid_gen(val) -> int | None:
    return val if isinstance(val, int) and not isinstance(val, bool) and val >= 0 else None


def verify_context_fence(
    bundle: dict | None,
    readiness: dict | None,
    *,
    expected_sha256: str | None = None,
    expected_state_gen: int | None = None,
    now_s: float | None = None,
    max_age_s: float | None = None,
) -> tuple[bool, str | None, list[str]]:
    """Verify bundle + readiness freshness, holds, and `cell_state_gen` continuity (TOCTOU fence)."""
    if not isinstance(bundle, dict) or not isinstance(readiness, dict):
        return False, "STALE_FAILURE_CONTEXT", ["missing failure bundle or readiness"]
    if readiness.get("schema") != "rosy.cell-readiness.v1":
        return False, "STALE_FAILURE_CONTEXT", [f"unexpected readiness schema: {readiness.get('schema')!r}"]
    now = time.time() if now_s is None else _finite_float(now_s)
    obs = _finite_float(readiness.get("observed_at"))
    r_max = _finite_float(readiness.get("max_age_s", 5.0))
    req_max = _finite_float(max_age_s) if max_age_s is not None else r_max
    if now is None or obs is None or r_max is None or r_max <= 0.0 or req_max is None or req_max <= 0.0:
        return False, "STALE_FAILURE_CONTEXT", ["invalid readiness timing"]
    limit = min(req_max, r_max, 5.0)
    if now - obs > limit or obs - now > 1.0:
        return False, "STALE_FAILURE_CONTEXT", ["stale readiness snapshot"]

    arms = readiness.get("arms")
    if not isinstance(arms, dict):
        return False, "STALE_FAILURE_CONTEXT", ["missing readiness arms map"]
    target_arm = str(bundle.get("arm_id") or "")
    target_info = arms.get(target_arm)
    if not isinstance(target_info, dict):
        return False, "STALE_FAILURE_CONTEXT", [f"missing readiness state for {target_arm or 'arm'}"]

    cur_gen = _valid_gen(readiness.get("cell_state_gen"))
    raw_exp_gen = (bundle.get("generation") or {}).get("cell_state_gen") if expected_state_gen is None else expected_state_gen
    exp_gen = _valid_gen(raw_exp_gen)
    raw_exp_sha = bundle.get("context_sha256") if expected_sha256 is None else expected_sha256
    if cur_gen is None or exp_gen is None or not isinstance(raw_exp_sha, str) or not raw_exp_sha:
        return False, "STALE_FAILURE_CONTEXT", ["missing or invalid cell_state_gen or context_sha256"]

    active_holds = tuple(
        a for a, info in arms.items()
        if isinstance(info, dict) and (info.get("incident_held") or info.get("fault") or info.get("human_hold_latched"))
    )
    ok, code, reasons = cfc.check_fence(
        bundle,
        expected_context_sha256=raw_exp_sha,
        expected_cell_state_gen=exp_gen,
        current_cell_state_gen=cur_gen,
        now_s=now,
        active_holds=active_holds,
        max_age_s=limit,
    )
    for bl in (str(r) for r in (readiness.get("blocking_refusals") or ())):
        if (
            bl in ("whole_cell_lock_held", "depth_lock_held")
            or bl.startswith(("fleet_safety:", "session_lock:"))
            or bl.endswith((":incident_held", ":fault", ":human_hold_latched"))
        ):
            reasons.append(f"readiness refusal: {bl}")
    if target_info.get("dirty") is True:
        reasons.append(f"{target_arm}:dirty")
    if target_info.get("active_job_id"):
        reasons.append(f"{target_arm}:active_job_id={target_info.get('active_job_id')}")
    if isinstance(target_info.get("fleet_safety"), dict) and target_info["fleet_safety"].get("blocked") is True:
        reasons.append(f"{target_arm}:fleet_safety_blocked")
    if target_info.get("session_lock_held") and target_info.get("folded") is not True:
        reasons.append(f"{target_arm}:session_lock_held while not folded")
    if target_arm in ("arm_a", "arm_b"):
        peer = "arm_b" if target_arm == "arm_a" else "arm_a"
        peer_info = arms.get(peer)
        if isinstance(peer_info, dict):
            if peer_info.get("incident_held") or peer_info.get("fault") or peer_info.get("human_hold_latched") or peer_info.get("active_job_id"):
                reasons.append(f"peer {peer} busy/held/faulted")
            if isinstance(peer_info.get("fleet_safety"), dict) and peer_info["fleet_safety"].get("blocked") is True:
                reasons.append(f"peer {peer}:fleet_safety_blocked")
            if peer_info.get("session_lock_held") and peer_info.get("folded") is not True:
                reasons.append(f"peer {peer}:session_lock_held while not folded")
    if reasons:
        return False, "STALE_FAILURE_CONTEXT", reasons
    return ok, code, reasons


def verify_job_outcome(
    client: CellJobClient,
    job_name: str,
    arm: str,
    result: dict,
    *,
    collect_facts: bool = True,
    dry_run: bool = False,
    poll_s: float = 0.2,
    readiness_after: dict | None = None,
) -> tuple[str, dict]:
    """Verify completed job telemetry fail-closed; never equate bare `exit == 0` with success."""
    import cell_vlm_facts as _vf

    summary = result.get("structured_result") if isinstance(result.get("structured_result"), dict) else _vf.parse_last_json(result.get("log", ""))
    job_summary = (
        {k: summary[k] for k in ("result", "attempt_id", "source", "took_one") if k in summary}
        if summary
        else None
    )
    verification: dict = {"job_summary": job_summary}
    failure_reasons: list[str] = []
    if result.get("exit") != 0:
        failure_reasons.append(f"exit={result.get('exit')}")
    elif not dry_run:
        if summary is None:
            failure_reasons.append("missing structured job summary")
        else:
            if summary.get("ok") is False:
                failure_reasons.append("ok=False")
            res_val = summary.get("result")
            if job_name == "auto_pick" and res_val != "placed":
                failure_reasons.append(f"auto_pick result={res_val!r}")
            elif job_name in ("cell_policy_drive", "cell_policy_run") and res_val not in ("released", "chunks_done", "placed"):
                failure_reasons.append(f"policy_drive result={res_val!r}")
            elif res_val is not None and str(res_val).startswith(("stopped", "held", "refused", "aborted", "fault")):
                failure_reasons.append(f"non-success result={res_val!r}")
            if summary.get("parked") is False:
                failure_reasons.append("parked=False")
            if job_name in ("auto_pick", "cell_policy_drive", "cell_policy_run"):
                if summary.get("took_one") is not True:
                    failure_reasons.append(f"took_one={summary.get('took_one')!r}")
            elif job_name != "home" and summary.get("took_one") is False:
                failure_reasons.append("took_one=False")
            zv = summary.get("zone_verification")
            if isinstance(zv, dict) and zv.get("verified") is False:
                failure_reasons.append("zone_verification.verified=False")
    if not dry_run:
        post_inc = _vf.query_incident(client, arm, poll_s=poll_s)
        verification["post_incident"] = post_inc
        if post_inc.get("held") is True:
            failure_reasons.append(f"post_incident held: {post_inc.get('reason')}")
        if readiness_after is None:
            try:
                readiness_after = client.readiness()
            except (CellJobError, TimeoutError, OSError):
                readiness_after = None
        arm_st = (readiness_after.get("arms") or {}).get(arm) if isinstance(readiness_after, dict) and isinstance(readiness_after.get("arms"), dict) else None
        if not isinstance(arm_st, dict):
            failure_reasons.append(f"missing post-job readiness for {arm}")
        else:
            if arm_st.get("folded") is not True:
                failure_reasons.append(f"arm folded={arm_st.get('folded')!r} after job")
            if arm_st.get("incident_held") is True:
                failure_reasons.append("arm incident_held=True after job")
            if arm_st.get("fault"):
                failure_reasons.append(f"arm fault={arm_st.get('fault')}")
            if arm_st.get("human_hold_latched") is True:
                failure_reasons.append("human_hold_latched=True")
    if failure_reasons:
        verification["failure_reasons"] = failure_reasons
        return "failed", verification
    return "completed", verification
