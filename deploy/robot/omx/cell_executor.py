#!/usr/bin/env python3
"""Which executor runs one carry segment, chosen by outcomes (VLA pipeline handoff 2026-11-13, slice 3).

The cell_choices ledger picks among executors approved for the real arm; a model never picks. A guard,
fault or lock stop leaves the execution record "stopped" and the ledger untouched (no retry pressure)."""
from __future__ import annotations

EXECUTOR_CANDIDATES = ("ik_chunk", "smolvla", "act_policy")
APPROVED_REAL_EXECUTORS = frozenset({"ik_chunk"})  # D-911: new motion paths need a person's approval.
PURPOSE = "pick_place"


def choose(choices, segment: int) -> tuple[dict, dict]:
    """(ledger choice, execution record) for one segment; refuses when no approved executor is left."""
    allowed = [executor for executor in EXECUTOR_CANDIDATES if executor in APPROVED_REAL_EXECUTORS]
    choice = choices.best_contextual(f"exec.{PURPOSE}", allowed=allowed)
    if choice["value"] != "ik_chunk":
        raise RuntimeError("no approved executor for the real arm")
    return choice, {"segment": segment, "purpose": PURPOSE, "executor": choice["value"],
                    "candidates": allowed, "propensity": choice["propensity"], "outcome": "stopped"}


def outcome(choices, record: dict, choice: dict, ok: bool, note: str) -> None:
    """The segment ran to an end the arm itself reached: count it for its executor."""
    record["outcome"] = "succeeded" if ok else "failed"
    choices.outcome_contextual(f"exec.{PURPOSE}", choice["value"], ok, propensity=choice["propensity"], note=note)
    choices.save()


def record_act_outcome(choices, task_id: str | None, ok: bool, note: str, *, failure_class: str | None = None) -> dict:
    """Record a supervised `act_policy` execution outcome without altering approved real IK selection."""
    rec = {"task_id": task_id, "executor": "act_policy", "outcome": "succeeded" if ok else "failed",
           **({"failure_class": failure_class} if failure_class else {})}
    if choices is not None:
        key = "exec.act_policy"
        choices.offer(key, "act_policy", "supervised_act")
        choices.outcome_contextual(key, "act_policy", ok, propensity=1.0, note=str(note or failure_class or "")[:200])
        choices.save()
    return rec
