"""Before a real ACT drive moves the arm: the same episode, one chunk, as a dry run, plus the declared payload.

2026-11-26 arm_b: every refusal of the day (no payload declared, a 503 wrist camera, a 0.61 s observation over its
0.6 s budget, a four-row remote chunk all late, a model step faster than the 5 units/s guard) came after the home
and entry chunks had moved the arm, each costing a human hold, an incident and a person's check. The dry run takes
the same inputs, inference, window and shaping, so these refuse here with no motion.
"""
from __future__ import annotations


def preflight(runner, shadow, library_path, work, config: dict, log, kw: dict) -> dict | None:
    """None when the drive may start; else the refusal to return instead of moving."""
    from cell_envelope import _conditions, payload_check
    from cell_policy_drive import run_episode

    try:
        _facts, over = payload_check(config, _conditions(config))
    except (ValueError, TypeError, KeyError) as error:
        over = str(error)
    if over:
        return {"result": "refused", "at": 0, "reason": f"preflight: operating envelope: {over}"}
    try:
        dry = run_episode(runner, shadow, library_path, work, max_chunks=1, dry_run=True,
                          log=lambda row: log({"preflight": True, **row}), **kw)
    except (OSError, ValueError, KeyError, RuntimeError) as error:
        dry = {"result": "refused", "reason": str(error)[:200]}
    if dry.get("result") == "dry_run":
        return None
    return {"result": "refused", "at": 0, "reason": f"preflight: {dry.get('reason') or dry.get('result')}", "preflight": dry}
