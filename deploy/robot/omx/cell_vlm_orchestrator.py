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
_CLI_PROVIDERS = ("cli", "opencode", "codex", "claude")
_HTTP_CHAT_PROVIDERS = ("zai", "glm", "openai", "http", "vllm", "litellm", "openrouter")
_VISION_TAGS = ("vl", "vision", "4v", "gpt-4o", "claude-3", "gemini")
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


def _validate_vision_spec(spec) -> None:
    if spec is None:
        raise ValueError("a vision backend is required for VLM orchestration")
    if callable(spec):
        name = getattr(spec, "__name__", "")
        if name.startswith(("opencode:", "codex:", "claude:")):
            raise ValueError(f"text-only CLI backend {name!r} cannot inspect camera frames")
        return
    if isinstance(spec, (list, tuple)):
        items = [item for item in spec if item is not None]
        if not items:
            raise ValueError("a vision backend is required for VLM orchestration")
        for item in items:
            _validate_vision_spec(item)
        return
    if isinstance(spec, str):
        s = spec.strip()
        lower = s.lower()
        if lower.startswith(("opencode:", "codex:", "claude:")):
            raise ValueError(f"text-only CLI provider {s!r} cannot inspect camera frames")
        if lower.startswith(("zai:", "glm:", "openai:")) or lower.startswith("glm"):
            model = s.split(":", 1)[1] if ":" in s else s
            if not any(tag in model.lower() for tag in _VISION_TAGS):
                raise ValueError(f"non-vision HTTP chat model {s!r} cannot inspect camera frames")
        return
    if not isinstance(spec, dict):
        raise ValueError(f"unsupported backend spec: {spec!r}")
    if "models" in spec or "profiles" in spec:
        items = [item for item in (spec.get("models") or spec.get("profiles") or ()) if item is not None]
        if not items:
            raise ValueError("a vision backend is required for VLM orchestration")
        for item in items:
            _validate_vision_spec(item)
        if spec.get("arbiter") is not None:
            _validate_vision_spec(spec["arbiter"])
        return
    provider = str(spec.get("provider", "ollama")).lower()
    if provider in _CLI_PROVIDERS:
        raise ValueError(f"text-only CLI provider {provider!r} cannot inspect camera frames")
    if spec.get("vision") is False:
        raise ValueError("vision=False backend cannot inspect camera frames")
    if provider in _HTTP_CHAT_PROVIDERS:
        model = str(spec.get("model", "")).lower()
        if spec.get("vision") is not True and not any(tag in model for tag in _VISION_TAGS):
            raise ValueError(f"HTTP chat backend {provider}:{model or '?'} requires vision=True or a vision model")


def select_vision_backend(spec_or_fn):
    """Build or validate a vision-capable backend; reject text-only CLI and non-vision specs."""
    _validate_vision_spec(spec_or_fn)
    backend = judge_seat.from_config(spec_or_fn)
    if backend is judge_seat.rules or backend is None:
        raise ValueError("a vision backend is required for VLM orchestration")
    return backend


def _parse_last_json(text: str) -> dict | None:
    stripped = (text or "").strip()
    if not stripped:
        return None
    for line in reversed(stripped.splitlines()):
        line = line.strip()
        if line.startswith("{"):
            try:
                parsed = json.loads(line)
                if isinstance(parsed, dict):
                    return parsed
            except ValueError:
                pass
    try:
        parsed = json.loads(stripped)
        return parsed if isinstance(parsed, dict) else None
    except ValueError:
        return None


def _query_incident(client: CellJobClient, arm: str, *, poll_s: float = 0.2, timeout_s: float = 30.0) -> dict:
    try:
        started = client.start("incident_status", {"arm": arm})
        res = client.wait(started["id"], poll_s=poll_s, timeout_s=timeout_s)
    except (CellJobError, TimeoutError, OSError) as exc:
        return {"arm": arm, "held": True, "exit": None, "reason": f"incident_status failed: {exc}", "raw": None}
    parsed = _parse_last_json(res.get("log", ""))
    if res.get("exit") != 0 or parsed is None:
        return {"arm": arm, "held": True, "exit": res.get("exit"), "reason": "unreadable incident_status", "raw": parsed}
    local_held = parsed.get("local_held") is True
    fleet_held = parsed.get("fleet_held")
    unsent = parsed.get("unsent_outbox") or 0
    held = bool(local_held or fleet_held is True or (fleet_held is None and unsent > 0))
    reason = parsed.get("local_reason") or parsed.get("fleet_reason") or ("unsent outbox" if held else "")
    return {"arm": arm, "held": held, "exit": res.get("exit"), "reason": reason, "raw": parsed}


def collect_measured_facts(
    client: CellJobClient,
    arm_configs: dict[str, dict] | None = None,
    *,
    arms: tuple[str, ...] = tuple(sorted(AB_ARMS)),
    run_dry_pick: bool = True,
    poll_s: float = 0.2,
) -> dict:
    """Measure arm hold status and optional serial `auto_pick_dry_run` observations before VLM planning."""
    incidents = {arm: _query_incident(client, arm, poll_s=poll_s) for arm in arms}
    available = [arm for arm in arms if not incidents[arm]["held"]]
    dry_pick = {}
    if run_dry_pick and arm_configs:
        for arm in available:
            cfg = arm_configs.get(arm) or {}
            if not all(k in cfg for k in ("config", "catalog", "roi")):
                continue
            source, dest = cfg.get("source", "belt"), cfg.get("dest", "pallet")
            try:
                started = client.start(
                    "auto_pick_dry_run",
                    {
                        "config": cfg["config"],
                        "catalog": cfg["catalog"],
                        "roi": cfg["roi"],
                        "source": source,
                        "dest": dest,
                        "purpose": f"facts:{arm}",
                    },
                )
                res = client.wait(started["id"], poll_s=poll_s, timeout_s=60.0)
                parsed = _parse_last_json(res.get("log", "")) or {}
                attempts = parsed.get("attempts") if isinstance(parsed.get("attempts"), list) else []
                first = attempts[0] if attempts and isinstance(attempts[0], dict) else {}
                dry_pick[arm] = {
                    "exit": res.get("exit"),
                    "source": source,
                    "dest": dest,
                    "result": parsed.get("result"),
                    "observed": first.get("observed"),
                    "chosen": first.get("chosen"),
                    "refused_count": len(first.get("refused") or ()),
                }
            except (CellJobError, TimeoutError, OSError) as exc:
                dry_pick[arm] = {"source": source, "dest": dest, "error": str(exc)}
    return {"incidents": incidents, "dry_pick": dry_pick, "available_arms": available}


def _collect_frames(client: CellJobClient, views: tuple[str, ...]) -> tuple[list[str], list[str]]:
    images_b64, captured = [], []
    for view in views:
        try:
            raw = client.frame(view)
        except CellJobError as exc:
            if exc.status_code == 404:
                continue
            raise
        if not raw:
            continue
        images_b64.append(base64.b64encode(raw).decode("ascii"))
        captured.append(view)
    return images_b64, captured


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
        if proposal["action"] == "auto_pick" and arm_dry.get("observed") == 0:
            proposal.update(action="idle", site="", reason=f"vetoed auto_pick: measured 0 objects on {proposal['arm']}")
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
        out["status"] = "completed" if out["result"].get("exit") == 0 else "failed"
        summary = _parse_last_json(out["result"].get("log", ""))
        verification: dict = {
            "job_summary": {k: summary[k] for k in ("result", "attempt_id", "source", "took_one") if k in summary}
            if summary
            else None
        }
        if collect_facts and not effective_dry_run:
            verification["post_incident"] = _query_incident(client, proposal["arm"], poll_s=poll_s)
        out["verification"] = verification
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
        if (args.execute and not args.dry_run)
        else None
    )
    out = run_once(
        client,
        spec,
        arm_configs,
        operator=args.operator,
        proposer=args.proposer,
        execute=args.execute,
        person_at_switch=args.person_at_switch,
        dry_run=args.dry_run,
        approve=approve_cb,
        context=args.context,
    )
    print(json.dumps(out))
    return 0 if out["status"] in ("idle", "proposed", "dry_run_skipped", "submitted", "completed") else 1


if __name__ == "__main__":
    raise SystemExit(main())
