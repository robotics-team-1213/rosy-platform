#!/usr/bin/env python3
"""VLM + Policy orchestrator for A/B cell arms (`arm_a`, `arm_b`) over `cell_job_api` (:8781).

Flow:
1. Measure first: check `/queue`, `incident_status` holds, and optional `auto_pick_dry_run` object counts before calling
   the VLM. Held arms are removed from the allowed arm set; if no arm is available, return `idle` without a VLM call.
2. Observe: fetch available camera frames (`top`, `side`, `arm_a_wrist`, `arm_b_wrist`) as base64 JPEGs; fail closed
   (`idle`) if no non-empty camera frame is available.
3. Plan (VLM): ask a vision-capable `judge_seat` backend (`ollama` or `openai_chat(vision=True)`, never text-only CLI)
   to propose `{action, arm, site, reason}` grounded on measured facts. Measurement vetoes conflicting proposals.
4. Gate, Execute & Verify: validate `proposer != operator` (D-1024) and `person_at_switch=True` (D-911) BEFORE
   requesting per-proposal approval, then submit and attach read-only `verification` (`job_summary` + `post_incident`).
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Callable

sys.path.insert(0, str(Path(__file__).resolve().parent))
import judge_seat  # noqa: E402,F401
from cell_job_client import CellJobClient  # noqa: E402
from cell_job_spec import AB_ARMS  # noqa: E402
import cell_recovery  # noqa: E402
from cell_vlm_facts import (  # noqa: E402
    AB_VIEWS,
    collect_failure_frames as _collect_failure_frames,
    collect_frames as _collect_frames,
    collect_measured_facts,
    fetch_readiness_and_failure as _fetch_readiness_and_failure,
    parse_last_json as _parse_last_json,
    query_incident as _query_incident,
    record_orchestrator_outcome as _record_outcome,
    select_vision_backend,
    verify_context_fence as _verify_context_fence,
    verify_job_outcome as _verify_job_outcome,
)

ACTIONS = ("idle", "auto_pick", "cell_policy_drive", "home")
PROPOSAL_SCHEMA = {
    "type": "object",
    "properties": {
        "action": {"type": "string", "enum": list(ACTIONS)},
        "arm": {"type": "string", "enum": sorted(AB_ARMS)},
        "site": {"type": "string"},
        "reason": {"type": "string"},
    },
    "required": ["action", "arm", "reason"],
    "additionalProperties": False,
}


def propose_next(
    client: CellJobClient,
    backend,
    *,
    views: tuple[str, ...] = AB_VIEWS,
    context: str = "",
    arm_configs: dict[str, dict] | None = None,
    collect_facts: bool = False,
    poll_s: float = 0.2,
) -> dict:
    """Inspect queue, measured facts, and camera frames, returning a validated high-level proposal."""
    q = client.queue()
    for active in q.get("active", []):
        if active.get("moving") and active.get("arm") in AB_ARMS:
            return {
                "action": "idle",
                "arm": active["arm"],
                "site": "",
                "reason": f"queue busy: {active.get('job')} on {active['arm']} (id={active.get('id')})",
                "views": [],
            }
    facts = collect_measured_facts(client, arm_configs, poll_s=poll_s) if collect_facts else None
    allowed_arms = tuple(facts["available_arms"]) if facts is not None else tuple(sorted(AB_ARMS))
    if not allowed_arms:
        return {
            "action": "idle",
            "arm": "arm_a",
            "site": "",
            "reason": "all A/B arms held or unavailable",
            "views": [],
            **({"facts": facts} if facts is not None else {}),
        }
    images_b64, captured = _collect_frames(client, views)
    if not images_b64:
        return {
            "action": "idle",
            "arm": allowed_arms[0],
            "site": "",
            "reason": "no camera frames available",
            "views": [],
            **({"facts": facts} if facts is not None else {}),
        }
    schema = {
        **PROPOSAL_SCHEMA,
        "properties": {**PROPOSAL_SCHEMA["properties"], "arm": {"type": "string", "enum": list(allowed_arms)}},
    }
    prompt = (
        "You supervise the A/B OMX dual-arm cell (arm_a and arm_b share one workspace; only one may move at a time).\n"
        f"Attached camera views in order: {captured}.\n"
        f"Active queue: {json.dumps(q.get('active', []))}.\n"
        + (f"Measured cell facts (authoritative; never claim empty if observed > 0): {json.dumps(facts)}\n" if facts else "")
        + (f"Operator context: {context}\n" if context else "")
        + f"Available arms: {list(allowed_arms)}. Choose the next safe step: 'idle' if nothing is ready or uncertain, "
        "'auto_pick' for IK pick/place, 'cell_policy_drive' for 3-camera learned policy execution, or 'home' to safely "
        "fold an arm home. For 'site': set the source site (e.g. 'beltend') for 'auto_pick', the destination "
        "goal_site (e.g. 'yard:r3-s2-t1', or '' to use the arm config default) for 'cell_policy_drive', and '' otherwise."
    )
    reply = backend(prompt, images_b64, schema)
    if not isinstance(reply, dict) or reply.get("action") not in ACTIONS or reply.get("arm") not in allowed_arms:
        raise ValueError(f"invalid VLM proposal: {reply!r}")
    proposal = {
        "action": reply["action"],
        "arm": reply["arm"],
        "site": reply.get("site") or "",
        "reason": str(reply.get("reason") or ""),
        "views": captured,
    }
    if facts is not None:
        proposal["facts"] = facts
        arm_dry = facts["dry_pick"].get(proposal["arm"]) or {}
        if proposal["action"] == "auto_pick" and (
            arm_dry.get("observed") == 0
            or arm_dry.get("error")
            or arm_dry.get("exit") not in (None, 0)
            or ("chosen" in arm_dry and arm_dry.get("chosen") is None)
        ):
            detail = arm_dry.get("error") or arm_dry.get("result") or "measured 0 usable objects"
            proposal.update(action="idle", site="", reason=f"vetoed auto_pick on {proposal['arm']}: {detail}")
    return proposal


def build_job_params(
    proposal: dict,
    arm_configs: dict[str, dict],
    *,
    proposer: str,
    operator: str,
    person_at_switch: bool,
    dry_run: bool = False,
) -> tuple[str, dict] | None:
    """Translate a VLM proposal into a guarded `(job_name, params)` for `cell_job_api`."""
    action = proposal["action"]
    if action == "idle":
        return None
    if not proposer or not operator or operator == proposer:
        raise ValueError("operator and proposer must be non-empty and distinct (D-1024)")
    arm = proposal["arm"]
    if arm not in arm_configs:
        raise ValueError(f"no arm configuration provided for {arm}")
    cfg = arm_configs[arm]
    purpose = f"vlm:{proposal['reason'][:40]}"
    base = {"arm": arm, "config": cfg["config"], "person_at_switch": bool(person_at_switch), "purpose": purpose}

    if action == "home":
        if dry_run:
            return None
        return "home", {
            **base,
            "operator": operator,
            "proposer": proposer,
            "library": cfg["library"],
            "operating_profile": cfg["operating_profile"],
        }

    if action == "auto_pick":
        source = proposal.get("site") or cfg.get("source", "belt")
        dest = cfg.get("dest", "pallet")
        if dry_run:
            return "auto_pick_dry_run", {
                "config": cfg["config"],
                "catalog": cfg["catalog"],
                "roi": cfg["roi"],
                "source": source,
                "dest": dest,
                "purpose": purpose,
            }
        return "auto_pick", {
            **base,
            "operator": operator,
            "proposer": proposer,
            "catalog": cfg["catalog"],
            "roi": cfg["roi"],
            "source": source,
            "dest": dest,
        }

    if action == "cell_policy_drive":
        mode = cfg.get("mode", "act")
        params = {
            **base,
            "library": cfg["library"],
            "max_chunks": int(cfg.get("max_chunks", 3)),
            "operator": operator,
            "proposer": proposer,
            "mode": mode,
        }
        if mode != "taught":
            params["policy_root"] = cfg["policy_root"]
            params["policy_revision"] = cfg["policy_revision"]
            params["cell_calibration"] = cfg["cell_calibration"]
        goal_site = proposal.get("site") or cfg.get("goal_site")
        if goal_site:
            params["goal_site"] = goal_site
        if dry_run or cfg.get("dry_run") is True:
            params["dry_run"] = True
            params.pop("person_at_switch", None)
        for opt_key in ("model_calibration", "n_action", "max_obs_age_s", "catalog", "roi", "site"):
            if opt_key in cfg:
                params[opt_key] = cfg[opt_key]
        return "cell_policy_drive", params

    raise ValueError(f"unsupported action {action!r}")


def run_once(
    client: CellJobClient,
    backend_spec,
    arm_configs: dict[str, dict],
    *,
    operator: str,
    proposer: str = "vlm_orchestrator",
    execute: bool = False,
    person_at_switch: bool = False,
    dry_run: bool = False,
    approve: Callable[[dict], bool] | None = None,
    wait: bool = True,
    context: str = "",
    collect_facts: bool = True,
    poll_s: float = 0.2,
    choices_path: Path | None = None,
    decisions_path: Path | None = None,
) -> dict:
    """Run one observe -> VLM propose -> (optional) validate, per-proposal approve & execute cycle."""
    backend = select_vision_backend(backend_spec)
    proposal = propose_next(client, backend, context=context, arm_configs=arm_configs, collect_facts=collect_facts, poll_s=poll_s)
    if proposal["action"] == "idle":
        return {"status": "idle", "proposal": proposal}
    if not execute:
        return {"status": "proposed", "proposal": proposal}
    arm_cfg = arm_configs.get(proposal["arm"], {})
    effective_dry_run = bool(
        dry_run or (proposal["action"] == "cell_policy_drive" and arm_cfg.get("dry_run") is True)
    )
    if effective_dry_run and proposal["action"] == "home":
        return {"status": "dry_run_skipped", "proposal": proposal, "reason": "home has no dry-run job"}
    if not effective_dry_run:
        if not person_at_switch:
            raise ValueError("executing a moving job requires person_at_switch=True (D-911)")
        if not callable(approve):
            raise ValueError("live execution requires an explicit per-proposal approve callback (D-1024)")
    built = build_job_params(
        proposal,
        arm_configs,
        proposer=proposer,
        operator=operator,
        person_at_switch=person_at_switch,
        dry_run=effective_dry_run,
    )
    assert built is not None
    if callable(approve) and not approve(proposal):
        return {"status": "rejected", "proposal": proposal}
    job_name, params = built
    started = client.start(job_name, params)
    out = {"status": "submitted", "job": job_name, "id": started["id"], "proposal": proposal}
    if wait:
        out["result"] = client.wait(started["id"], poll_s=poll_s)
        status, verification = _verify_job_outcome(
            client, job_name, proposal["arm"], out["result"],
            collect_facts=collect_facts, dry_run=effective_dry_run, poll_s=poll_s,
        )
        out["status"] = status
        out["verification"] = verification
        _record_outcome(
            proposal, status, note=str((verification.get("job_summary") or {}).get("result") or ""),
            choices_path=choices_path, decisions_path=decisions_path,
        )
    return out


def propose_fallback(
    client: CellJobClient, backend_spec, *, arm: str | None = None, views: tuple[str, ...] = AB_VIEWS,
    max_age_s: float = 5.0, request_root: Path | None = None, fallback_chain_depth: int = 0,
) -> dict:
    """Propose or escalate a post-failure fallback over `:8781` `/readiness` + `/failures/latest` with TOCTOU fencing."""
    readiness, bundle = _fetch_readiness_and_failure(client, arm=arm)
    if bundle is None:
        return {"status": "idle", "reason": "no failure bundle"}
    exp_sha = bundle.get("context_sha256")
    exp_gen = (bundle.get("generation") or {}).get("cell_state_gen")
    ok, err_code, reasons = _verify_context_fence(
        bundle, readiness, expected_sha256=exp_sha, expected_state_gen=exp_gen, max_age_s=max_age_s)
    if not ok:
        return {"status": "stale", "reason": err_code, "reasons": reasons, "bundle_id": bundle.get("bundle_id")}
    permitted = cell_recovery.permitted_fallback_verbs(bundle, fallback_chain_depth=fallback_chain_depth)
    sel_auto = cell_recovery.select_fallback(bundle, fallback_chain_depth=fallback_chain_depth)
    if sel_auto["verb"] == "escalate_human" or permitted == ["escalate_human"]:
        req = cell_recovery.escalate_to_request(bundle, selection=sel_auto, root=request_root)
        return {"status": "escalated", "verb": "escalate_human", "selection": sel_auto,
                "bundle_id": bundle.get("bundle_id"), "context_sha256": exp_sha, "request": req}
    backend = select_vision_backend(backend_spec)
    images_b64, captured = _collect_failure_frames(client, bundle, views)
    schema = {"type": "object", "required": ["verb", "reason"], "additionalProperties": False, "strict": True,
              "properties": {"verb": {"type": "string", "enum": permitted}, "reason": {"type": "string"}}}
    outcome = (bundle.get("measurement") or {}).get("outcome") or {}
    hist = bundle.get("history_and_constraints") or {}
    veto_codes = [v.get("code") for v in (hist.get("measured_vetoes") or ())]
    prompt = (
        f"Failure bundle {bundle.get('bundle_id')} arm={bundle.get('arm_id')} cause={outcome.get('attempt_cause')}.\n"
        f"Vetoes: {veto_codes}.\nAttached camera views: {captured}. Choose ONLY from permitted fallback verbs: {permitted}."
    )
    try:
        reply = backend(prompt, images_b64, schema)
    except Exception as exc:
        reply = {"verb": "escalate_human", "reason": f"VLM fallback error: {exc}"}
    if not isinstance(reply, dict) or reply.get("verb") not in permitted:
        reply = {"verb": "escalate_human", "reason": f"invalid VLM fallback reply: {reply!r}"}
    readiness2, latest2 = _fetch_readiness_and_failure(client, arm=arm)
    ok2, err_code2, reasons2 = _verify_context_fence(
        bundle, readiness2, expected_sha256=exp_sha, expected_state_gen=exp_gen, max_age_s=max_age_s)
    if not ok2 or latest2 is None or latest2.get("bundle_id") != bundle.get("bundle_id") or latest2.get("context_sha256") != exp_sha:
        return {"status": "stale", "reason": err_code2 or "STALE_FAILURE_CONTEXT",
                "reasons": reasons2 or ["failure bundle changed during VLM call"], "bundle_id": bundle.get("bundle_id")}
    sel = cell_recovery.select_fallback(bundle, proposed_verb=reply["verb"], fallback_chain_depth=fallback_chain_depth)
    out = {"status": "escalated" if sel["escalate"] else "proposed", "verb": sel["verb"], "selection": sel,
           "proposal": {"verb": sel["verb"], "reason": str(reply.get("reason") or ""), "views": captured},
           "bundle_id": bundle.get("bundle_id"), "context_sha256": exp_sha}
    if sel["escalate"]:
        out["request"] = cell_recovery.escalate_to_request(
            bundle, selection=sel, reason=str(reply.get("reason") or ""), root=request_root)
    return out


def _prompt_approval(proposal: dict, *, operator: str, proposer: str) -> bool:
    print(json.dumps({"proposer": proposer, "operator": operator, "proposal": proposal}, ensure_ascii=False), file=sys.stderr)
    try:
        ans = input(f"Approve {proposal['action']} on {proposal['arm']} as {operator}? [y/N]: ")
    except (EOFError, OSError, KeyboardInterrupt):
        return False
    return ans.strip().lower() in ("y", "yes")


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--url", help="cell-job-api base URL")
    ap.add_argument("--arm-configs", type=Path, required=True, help="JSON mapping arm_a/arm_b -> job params")
    ap.add_argument("--vlm-provider", default="ollama")
    ap.add_argument("--vlm-url", default="http://127.0.0.1:11434")
    ap.add_argument("--vlm-model", default="qwen3-vl:8b-instruct")
    ap.add_argument("--operator", required=True)
    ap.add_argument("--proposer", default="vlm_orchestrator")
    ap.add_argument("--execute", action="store_true")
    ap.add_argument("--person-at-switch", action="store_true")
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--context", default="")
    args = ap.parse_args(argv)

    arm_configs = json.loads(args.arm_configs.read_text(encoding="utf-8"))
    client = CellJobClient(args.url)
    spec = {"provider": args.vlm_provider, "url": args.vlm_url, "model": args.vlm_model, "vision": True}
    approve_cb = (
        (lambda p: _prompt_approval(p, operator=args.operator, proposer=args.proposer))
        if (args.execute and not args.dry_run) else None
    )
    out = run_once(
        client, spec, arm_configs, operator=args.operator, proposer=args.proposer,
        execute=args.execute, person_at_switch=args.person_at_switch,
        dry_run=args.dry_run, approve=approve_cb, context=args.context,
    )
    print(json.dumps(out))
    return 0 if out["status"] in ("idle", "proposed", "dry_run_skipped", "submitted", "completed") else 1


if __name__ == "__main__":
    raise SystemExit(main())
