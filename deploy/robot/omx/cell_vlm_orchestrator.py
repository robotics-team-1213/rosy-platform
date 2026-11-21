#!/usr/bin/env python3
"""VLM + Policy orchestrator for A/B cell arms (`arm_a`, `arm_b`) over `cell_job_api` (:8781).

Flow:
1. Measure first: check `/queue` on `cell_job_api`. If `arm_a` or `arm_b` holds the A/B space, return `idle` without
   calling the VLM.
2. Observe: fetch available camera frames (`top`, `side`, `arm_a_wrist`, `arm_b_wrist`) as base64 JPEGs; fail closed
   (`idle`) if no camera frame is available.
3. Plan (VLM): ask a vision-capable `judge_seat` backend (`ollama` or `openai_chat(vision=True)`, never text-only CLI)
   to propose `{action, arm, site, reason}`.
4. Gate & Execute: enforce `proposer != operator` (D-1024), `person_at_switch=True` (D-911), and explicit approval
   before submitting `auto_pick` (IK), `cell_policy_drive` (3-cam ACT/hybrid/taught), or `home` to `cell_job_api`.
"""
from __future__ import annotations

import argparse
import base64
import json
import sys
from pathlib import Path
from typing import Callable

sys.path.insert(0, str(Path(__file__).resolve().parent))
import judge_seat  # noqa: E402
from cell_job_client import CellJobClient, CellJobError  # noqa: E402
from cell_job_spec import AB_ARMS  # noqa: E402

AB_VIEWS = ("top", "side", "arm_a_wrist", "arm_b_wrist")
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


def select_vision_backend(spec_or_fn):
    """Build or validate a vision-capable backend; reject text-only CLI providers."""
    if callable(spec_or_fn):
        name = getattr(spec_or_fn, "__name__", "")
        if name.startswith(("opencode:", "codex:", "claude:")):
            raise ValueError(f"text-only CLI backend {name!r} cannot inspect camera frames")
        return spec_or_fn
    if isinstance(spec_or_fn, dict):
        provider = str(spec_or_fn.get("provider", "ollama")).lower()
        if provider in ("cli", "opencode", "codex", "claude"):
            raise ValueError(f"text-only CLI provider {provider!r} cannot inspect camera frames")
        if provider in ("zai", "glm", "openai", "vllm", "litellm") and spec_or_fn.get("vision") is False:
            raise ValueError("vision=False backend cannot inspect camera frames")
    backend = judge_seat.from_config(spec_or_fn)
    if backend is judge_seat.rules:
        raise ValueError("a vision backend is required for VLM orchestration")
    return backend


def _collect_frames(client: CellJobClient, views: tuple[str, ...]) -> tuple[list[str], list[str]]:
    images_b64, captured = [], []
    for view in views:
        try:
            raw = client.frame(view)
        except CellJobError as exc:
            if exc.status_code == 404:
                continue
            raise
        images_b64.append(base64.b64encode(raw).decode("ascii"))
        captured.append(view)
    return images_b64, captured


def propose_next(
    client: CellJobClient,
    backend,
    *,
    views: tuple[str, ...] = AB_VIEWS,
    context: str = "",
) -> dict:
    """Inspect queue + camera frames and return a validated high-level proposal."""
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
    images_b64, captured = _collect_frames(client, views)
    if not images_b64:
        return {
            "action": "idle",
            "arm": "arm_a",
            "site": "",
            "reason": "no camera frames available",
            "views": [],
        }
    prompt = (
        "You supervise the A/B OMX dual-arm cell (arm_a and arm_b share one workspace; only one may move at a time).\n"
        f"Attached camera views in order: {captured}.\n"
        f"Active queue: {json.dumps(q.get('active', []))}.\n"
        + (f"Operator context: {context}\n" if context else "")
        + "Choose the next safe step: 'idle' if nothing is ready or uncertain, 'auto_pick' for IK pick/place, "
        "'cell_policy_drive' for 3-camera learned policy execution, or 'home' to safely fold an arm home. "
        "For 'site': set the source site (e.g. 'belt') for 'auto_pick', the destination goal_site "
        "(e.g. 'yard:r3-s2-t1' or 'tray', or '' to use the arm config default) for 'cell_policy_drive', and '' otherwise."
    )
    reply = backend(prompt, images_b64, PROPOSAL_SCHEMA)
    if not isinstance(reply, dict) or reply.get("action") not in ACTIONS or reply.get("arm") not in AB_ARMS:
        raise ValueError(f"invalid VLM proposal: {reply!r}")
    return {
        "action": reply["action"],
        "arm": reply["arm"],
        "site": reply.get("site") or "",
        "reason": str(reply.get("reason") or ""),
        "views": captured,
    }


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
    if not operator or operator == proposer:
        raise ValueError("operator must be non-empty and differ from proposer (D-1024)")
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
        if dry_run or cfg.get("dry_run"):
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
) -> dict:
    """Run one observe -> VLM propose -> (optional) approve & execute cycle."""
    backend = select_vision_backend(backend_spec)
    proposal = propose_next(client, backend, context=context)
    if proposal["action"] == "idle":
        return {"status": "idle", "proposal": proposal}
    if not execute:
        return {"status": "proposed", "proposal": proposal}
    arm_cfg = arm_configs.get(proposal["arm"], {})
    effective_dry_run = bool(
        dry_run or (proposal["action"] == "cell_policy_drive" and arm_cfg.get("dry_run") is True)
    )
    if not effective_dry_run and not person_at_switch:
        raise ValueError("executing a moving job requires person_at_switch=True (D-911)")
    if approve is not None and not approve(proposal):
        return {"status": "rejected", "proposal": proposal}
    if effective_dry_run and proposal["action"] == "home":
        return {"status": "dry_run_skipped", "proposal": proposal, "reason": "home has no dry-run job"}
    built = build_job_params(
        proposal,
        arm_configs,
        proposer=proposer,
        operator=operator,
        person_at_switch=person_at_switch,
        dry_run=effective_dry_run,
    )
    assert built is not None
    job_name, params = built
    started = client.start(job_name, params)
    out = {"status": "submitted", "job": job_name, "id": started["id"], "proposal": proposal}
    if wait:
        out["result"] = client.wait(started["id"])
        out["status"] = "completed" if out["result"].get("exit") == 0 else "failed"
    return out


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
    out = run_once(
        client,
        spec,
        arm_configs,
        operator=args.operator,
        proposer=args.proposer,
        execute=args.execute,
        person_at_switch=args.person_at_switch,
        dry_run=args.dry_run,
        context=args.context,
    )
    print(json.dumps(out))
    return 0 if out["status"] in ("idle", "proposed", "dry_run_skipped", "submitted", "completed") else 1


if __name__ == "__main__":
    raise SystemExit(main())
