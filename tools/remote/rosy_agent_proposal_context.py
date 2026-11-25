"""Validate Fleet proposal lineage against the cell's saved failure context."""
from __future__ import annotations

from collections.abc import Callable
from typing import Any


def validate_proposal_args(args: dict[str, Any]) -> str | None:
    if (args.get("fallback_verb") == "propose_ik_fallback_for_policy"
            and not args.get("fallback_from_task_id", "").strip()):
        return "fallback_from_task_id: original Fleet task required for policy fallback"
    if args.get("fallback_verb") and not args.get("failure_bundle_id"):
        return "failure_bundle_id: required for fallback proposals"
    if args.get("failure_bundle_id") and not (
        args.get("expected_context_sha256") and args.get("expected_readiness_digest")
    ):
        return "expected_context_sha256 and expected_readiness_digest are required for failure context"
    return None


def check_proposal_context(
    proposal: dict[str, Any], read_context: Callable[[str], dict[str, Any]],
) -> dict[str, Any] | None:
    bundle_id = proposal.get("failure_bundle_id")
    if not bundle_id:
        return None
    arm_id = proposal.get("arm_id")
    if not isinstance(arm_id, str) or not arm_id.strip():
        return {"ok": False, "status": 400, "error_code": "INVALID_ARGS",
                "detail": "arm_id: required for failure context"}
    response = read_context(bundle_id)
    if not response.get("ok"):
        return response
    bundle = response.get("data")
    if isinstance(bundle, dict):
        freshness = bundle.get("freshness")
        correlation = bundle.get("correlation")
        parent_id = proposal.get("fallback_from_task_id")
        digest = proposal["expected_context_sha256"]
        if (
            isinstance(freshness, dict) and freshness.get("still_valid_for_action") is True
            and bundle.get("bundle_id") == bundle_id
            and bundle.get("context_sha256") == digest
            and proposal.get("failure_context_sha256", digest) == digest
            and bundle.get("cell_id") == proposal["cell_id"]
            and bundle.get("arm_id") == arm_id
            and (not parent_id or (isinstance(correlation, dict) and correlation.get("fleet_task_id") == parent_id))
        ):
            history = bundle.get("history_and_constraints")
            menu = history.get("allowed_fallback_menu") if isinstance(history, dict) else None
            if (verb := proposal.get("fallback_verb")) and not (
                isinstance(menu, list) and any(
                    isinstance(item, dict) and item.get("verb") == verb and item.get("preconditions_met") is True
                    for item in menu
                )
            ):
                return {"ok": False, "status": 403, "error_code": "VERB_NOT_ALLOWED",
                        "detail": "The cell did not confirm the requested fallback verb."}
            return None
    return {"ok": False, "status": 409, "error_code": "STALE_FAILURE_CONTEXT",
            "detail": "The cell did not confirm the same actionable failure context. Diagnose again."}
