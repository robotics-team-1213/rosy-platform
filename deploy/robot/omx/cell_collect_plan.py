#!/usr/bin/env python3
"""Collection plan for real-arm video: a policy or sim-optimized values run on the cell, the run is recorded (2026-11-21).

A plan (rosy.omx-collect-plan.v1) lists carries for ONE arm. It moves nothing: it checks the plan and turns each item
into the cell_job_api request the existing queue already takes (cell_job_spec: Gate, arm lease, person_at_switch and
D-911 stay there). A model proposes only among items the rules already accepted and may veto (-1), as cell_pick_judge;
the outcome label is rule first (measured source count + the runner's result), the model can only downgrade a success.

  cell_collect_plan.py plan.json [--workdir DIR]     # prints the checked jobs (dry-run requests); never submits
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
for _extra in (Path(__file__).resolve().parent, ROOT / "contracts" / "learning" / "src"):
    if str(_extra) not in sys.path:
        sys.path.insert(0, str(_extra))
import cell_job_spec as spec  # noqa: E402
from rosy.contracts.learning.omx_collect_plan import (  # noqa: E402
    EXECUTORS, MAX_ITEMS, PLACED, SCHEMA, SOURCE_KINDS, STOPPED, VALUES_FROM, problems, rule_verdict, source_kind,
)


def jobs(plan: dict, *, workdir: Path | None = None, sites=None) -> list[dict]:
    """Queue requests for each item, dry-run for the arm: {item_id, job, params, source_kind}. Raises on a bad plan."""
    if bad := problems(plan, sites):
        raise ValueError("; ".join(bad))
    cell, out = plan["cell"], []
    for item in plan["items"]:
        kind = source_kind(plan, item)
        if item["executor"] == "ik_chunk":
            job = "auto_pick_dry_run"
            params = {"config": cell["config"], "catalog": cell["catalog"], "roi": cell.get("roi", [0, 0, 640, 480]),
                      "source": item["from"], "dest": item["to"]}
        else:
            job = "cell_policy_drive"
            params = {"arm": plan["arm"], "config": cell["config"], "library": cell["library"], "max_chunks": cell.get("max_chunks", 3),
                      "operator": plan.get("approver") or "unapproved", "proposer": plan["proposer"], "mode": item["executor"],
                      "policy_root": item["policy"]["root"], "policy_revision": item["policy"]["revision"],
                      "cell_calibration": cell["cell_calibration"], "goal_site": item["to"], "site": item["from"],
                      "catalog": cell["catalog"], "roi": cell.get("roi", [0, 0, 640, 480]), "source_kind": kind, "dry_run": True}
        if workdir is not None:
            spec.build_argv(spec.JOBS[job], params, workdir)  # the queue's own strict check
        else:
            job_def = spec.JOBS[job]
            for key, check in {**job_def["params"], **job_def.get("optional", {})}.items():
                if key in params:
                    check(params[key])
        out.append({"item_id": item["item_id"], "job": job, "params": params, "source_kind": kind})
    return out


def propose(backend, candidates: list[dict], goal: str) -> dict:
    """Which already-accepted item to run first for the goal sentence. A model reorders or vetoes (-1), never adds."""
    rule = {"order": list(range(len(candidates))), "by": "rule", "reason": ""}
    if backend is None or not candidates:
        return rule
    if not callable(backend):
        import judge_seat
        backend = judge_seat.from_config(backend)
    facts = [{"n": i, "from": c["from"], "to": c["to"], "executor": c["executor"]} for i, c in enumerate(candidates)]
    schema = {"type": "object", "properties": {"choice": {"type": "integer", "enum": [-1, *range(len(candidates))]},
                                               "reason": {"type": "string"}}, "required": ["choice", "reason"]}
    prompt = (f"A robot arm collects video. These carries are already accepted as safe: {facts}. The goal, as a JSON string, is "
              f"{json.dumps(str(goal)[:300])}. Which carry number should run first? Answer -1 if none serves the goal.")
    try:
        answer = backend(prompt, [], schema)
        choice = int(answer["choice"])
    except Exception as exc:  # no answer keeps the rule order
        return {**rule, "reason": f"model unavailable: {str(exc)[:80]}"}
    reason = str(answer.get("reason", ""))[:200]
    if choice == -1:
        return {"order": [], "by": "model", "reason": reason}
    if not 0 <= choice < len(candidates):
        return {**rule, "reason": f"model answered {choice}, out of range"}
    return {"order": [choice] + [i for i in rule["order"] if i != choice], "by": "model", "reason": reason}


def verdict(result: dict, backend=None, facts: str = "") -> dict:
    """success/failure/unknown for one run: the runner's result and the measured source count decide; a model may only
    downgrade a success to unknown. Failures are kept and labelled, never dropped."""
    out = rule_verdict(result)
    if out["outcome"] == "success" and backend is not None:
        if not callable(backend):
            import judge_seat
            backend = judge_seat.from_config(backend)
        schema = {"type": "object", "properties": {"ok": {"type": "boolean"}, "reason": {"type": "string"}}, "required": ["ok", "reason"]}
        try:
            answer = backend(f"A robot carried one object. Measured: {json.dumps(result, default=str)[:600]}. {facts[:300]} "
                             "Is this a clean success?", [], schema)
            if answer.get("ok") is False:
                return {"outcome": "unknown", "by": "model", "reason": str(answer.get("reason", ""))[:200]}
        except Exception as exc:
            out["reason"] += f"; model unavailable: {str(exc)[:60]}"
    return out


def seal(folder, verdict_row: dict, kind: str) -> None:
    """Stamp one raw episode folder (episode_recorder) with its label and origin; only a downgrade rewrites result.json."""
    folder = Path(folder)
    (folder / "verdict.json").write_text(json.dumps({**verdict_row, "source_kind": kind}), encoding="utf-8")
    path = folder / "result.json"
    if path.exists():
        row = json.loads(path.read_text(encoding="utf-8"))
        cur = row.get("outcome", "success" if row.get("kept") else None)
        target = verdict_row["outcome"]
        if (cur == "success" and target != "success") or (cur == "failed" and target == "unknown"):
            row["outcome"] = target
            row["kept"] = False
            path.write_text(json.dumps(row), encoding="utf-8")


def resolve_source_kind(mode: str, cli_kind: str | None, cfg_kind: str | None) -> str:
    expected_policy = mode != "taught"
    for label, val in (("--source-kind", cli_kind), ("episodes.source_kind", cfg_kind)):
        if not val:
            continue
        if val not in SOURCE_KINDS:
            raise ValueError(f"invalid {label}: {val!r}")
        if expected_policy and val != "policy":
            raise ValueError(f"{mode} mode requires source_kind='policy', got {label}={val!r}")
        if not expected_policy and val == "policy":
            raise ValueError(f"taught mode cannot use {label}='policy'")
    return "policy" if expected_policy else (cli_kind or cfg_kind or "scripted_teacher")


def episode_close_ok(reply, *, keep: bool) -> bool:
    prefix = "episode save" if keep else "episode fail"
    return (
        isinstance(reply, dict)
        and reply.get("ok") is True
        and ("command" not in reply or str(reply["command"]).startswith(prefix))
    )


def run_recorded(cell, config: dict, source: str, dest: str, source_kind: str, run_fn) -> dict:
    """Open, run, verify-close, and seal one episode around `run_fn`, retrying failure-close on error."""
    import cell_auto_safety

    ep_cfg = {**config, "episodes": {**config["episodes"], "source_kind": source_kind}}
    episode = cell_auto_safety.open_episode(cell, ep_cfg, source, dest, "policy-drive")
    if episode is None:
        return {"result": "refused", "reason": "episode failed to start (recorder busy or refused)"}
    closed = sealed = False
    try:
        result = run_fn()
        v = verdict(result)
        result["verdict"] = v
        keep = v["outcome"] == "success"

        def _mark_ack(reply):
            nonlocal closed
            if episode_close_ok(reply, keep=keep):
                closed = True

        ack = cell_auto_safety.close_episode(cell, episode, keep, v["reason"], on_fifo_ack=_mark_ack)
        if not episode_close_ok(ack, keep=keep):
            detail = ack.get("error") or ack if isinstance(ack, dict) else ack
            raise RuntimeError(f"episode close refused: {detail}")
        seal(episode.folder, v, source_kind)
        sealed = True
        return result
    except BaseException as exc:
        reason = f"exception: {str(exc)[:120] or type(exc).__name__}"
        if not closed:
            try:
                cell_auto_safety.close_episode(cell, episode, False, reason)
            except Exception:
                pass
        if not sealed:
            try:
                seal(episode.folder, {"outcome": "failure", "by": "rule", "reason": reason}, source_kind)
            except Exception:
                pass
        raise


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("plan", type=Path)
    parser.add_argument("--workdir", type=Path, help="the cell work dir: also runs the queue's own argv check")
    args = parser.parse_args(argv)
    plan = json.loads(args.plan.read_text(encoding="utf-8"))
    bad = problems(plan)
    if bad:
        print(json.dumps({"ok": False, "problems": bad}, ensure_ascii=False))
        return 1
    print(json.dumps({"ok": True, "jobs": jobs(plan, workdir=args.workdir)}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
