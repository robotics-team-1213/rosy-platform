"""Run a planned Fleet ACT task through `cell_policy_drive.py --policy-lease` and judge it (D-1024 3, D-1057).

The drive pushes the chunk runner a renewed 1 s lease and refuses before any motion unless the runner armed it; that refusal is
`PHYSICAL_POLICY_LEASE_OWNER_UNAVAILABLE`. If this process times out the drive is killed, its renewals stop, and the runner
holds by itself. `task_verified` is true only when the drive exited clean, the arm is folded again, the source count fell by
exactly one (`took_one`) and the destination zone was measured as this task's own slot and tier (`zone_acceptance`).
"""
from __future__ import annotations

import json
import os
from pathlib import Path
import sys
import time
from typing import Any

from cell_policy_lease import UNACKED
from cell_act_verdict import act_verdict
from cell_presence import effective_operator, presence_ok
from cell_task_act import _fail
import cell_diagnose


def execute_act_policy_task(
    handoff: dict[str, Any], plan: dict[str, Any], *, arm_id: str, wrapper: Path, cfg: Path, cat: Path,
    lease_owner: str, tools_root_fn, run_fn, last_json_fn, measured_fold_fn, fold_readback_fn, plan_home_fn,
    write_context_fn, timeout_exc, prep_dir: Path, source_clearance_fn=None,
) -> dict[str, Any]:
    task_id = handoff.get("task_id")
    cfg_data = json.loads(cfg.read_text(encoding="utf-8"))
    policy_cfg = cfg_data["act_policy"]
    rev = policy_cfg["policy_revision"].strip()
    omx_dir = Path(__file__).resolve().parent
    cat_path = cat if cat.is_file() else omx_dir / "object-catalog.example.json"
    roi, src_site, dst = plan["roi"], plan["src_site"], plan["dst"]
    cmd = [
        str(wrapper), sys.executable, str(omx_dir / "cell_policy_drive.py"),
        "--config", str(cfg), "--library", str(plan["library"]),
        "--policy-root", str(Path(policy_cfg["policy_root"].strip()).expanduser()), "--policy-revision", rev,
        "--cell-calibration", str(Path(policy_cfg["cell_calibration"].strip()).expanduser()),
        "--model-calibration", str(Path(policy_cfg["model_calibration"].strip()).expanduser()),
        "--max-chunks", str(plan["max_chunks"]), "--max-obs-age-s", str(policy_cfg.get("max_obs_age_s", 2.0)),
        "--operator", effective_operator(handoff), *(["--person-at-switch"] if presence_ok(handoff) else []),
        "--paced-chunks", "--policy-lease",
        *(["--goal-site", plan["goal_site"]] if plan.get("goal_site") else []),
        "--catalog", str(cat_path), "--roi", *(str(int(v)) for v in roi),
        "--site", src_site, "--dest-site", dst, "--task-id", plan["tid"],
    ]
    try:
        proc = run_fn(cmd, capture_output=True, text=True, timeout=300,
                      env={**os.environ, "TOOLS_ROOT": str(tools_root_fn()), "ROSY_ARM_LEASE_OWNER": lease_owner,
                           **({"ROSY_SESSION_CHUNKS": str(plan["library"]), "ROSY_SESSION_CHUNKS_STRICT": "1"} if arm_id == "arm_s" else {})})
    except timeout_exc:  # the drive is gone, so are its renewals: the runner's own watchdog holds within the ttl
        return _fail(arm_id, "SUBPROCESS_TIMEOUT", directive_id=task_id, extra_stop={"lease_watchdog": True})
    parsed = last_json_fn(proc.stdout)
    parsed = parsed if isinstance(parsed, dict) else {}
    if parsed.get("result") == "refused" and parsed.get("reason") == UNACKED:
        refused = _fail(arm_id, "PHYSICAL_POLICY_LEASE_OWNER_UNAVAILABLE", directive_id=task_id)
        if plan.get("policy_request"):
            refused["stage_result"]["policy_request"] = plan["policy_request"]
        return refused
    measured_at = time.time()
    v = act_verdict(parsed, proc.returncode, handoff, dst, fold_readback_fn=fold_readback_fn,
                    home=plan_home_fn(cfg_data), live_fold=measured_fold_fn(arm_id, prep_dir))
    fold, live_fold, folded, took_one, zone, zone_ok, verified = (
        v["fold"], v["live_fold"], v["folded"], v["took_one"], v["zone"], v["zone_ok"], v["verified"])
    source = parsed.get("source") if isinstance(parsed.get("source"), dict) else {}
    clearance = source_clearance_fn(cfg, cat_path, roi, src_site) if folded and source_clearance_fn else None
    if verified:
        write_context_fn(cfg, cfg_data, handoff, arm_id, prep_dir, dst, src_site, roi, zone, cat_path=cat_path)
    tier = handoff.get("tier")
    placement = {"verified": verified, "inside": verified, "basis": "act_policy"}
    src_meta = {"source": {**source, "roi": [int(v) for v in roi]}} if source else {}
    if zone is not None:
        verification = {**zone, "verified": bool(zone.get("verified") is True and verified),
                        "placement": placement, "policy_revision": rev, **src_meta}
    else:
        verification = {"verified": False, "basis": f"unverified: act policy {parsed.get('result') or 'failed'}",
                        "placement": placement, "policy_revision": rev, **src_meta}
    episode_ref = parsed.get("episode_ref") or parsed.get("recording_dir")
    bundle = parsed.get("failure_bundle_id")
    res_str, why_str = str(parsed.get("result") or f"act_exit_{proc.returncode}"), str(parsed.get("reason") or "")
    if not verified and res_str in ("released", "chunks_done") and not (zone_ok and took_one):
        why_str = f"{why_str} {'zone_unverified' if not zone_ok else 'took_one_unconfirmed'}".strip()
    failure = None if verified else {**cell_diagnose.classify_failure(res_str, why_str, exec_mode="act_paced"),
                                     "stratum": "human_only", "requires_human_operator": True}
    fail_keys = ({"failure_class": failure["cause"], "failure_stratum": failure["stratum"],
                  "requires_named_approval": True} if failure else {})
    stage_result = {
        "handoff_lease_id": handoff.get("handoff_lease_id"), "directive_id": task_id, "arm_id": arm_id,
        "task_verified": verified,
        "place": {"area": plan["dst_site"], "site": dst, **({"site_id": plan["goal_site"]} if plan.get("goal_site") else {}),
                  **({"tier": tier} if isinstance(tier, int) else {})},
        "verification": verification, "raw": parsed,
        **({"source_clearance": clearance} if clearance is not None else {}),
        **({"episode_ref": episode_ref} if episode_ref else {}),
        **({"failure_bundle_id": bundle} if bundle else {}),
        **fail_keys,
    }
    state_val = fold.get("state") or live_fold.get("state")
    return {
        "arm": arm_id, "events_count": 1 if parsed else 0, "measured_at": measured_at, "stage_result": stage_result,
        "stop_event": {"command": "stop", "ok": folded, "folded": folded, "readback": fold, "live": live_fold,
                       **({"state": state_val} if state_val else {})},
        "commissioning": True,
        **({"episode_ref": episode_ref} if episode_ref else {}),
        **({"failure_bundle_id": bundle} if bundle else {}),
        **({} if verified else {"error": parsed.get("result") or f"act_exit_{proc.returncode}", **fail_keys}),
    }
