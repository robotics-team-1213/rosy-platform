"""Opt-in autonomous (no-approval) cell dispatch & CAS helpers for Fleet-R governance (D-1078)."""
from __future__ import annotations

import os
from typing import Any

from fastapi import HTTPException

_TRUTHY = ("1", "true", "yes", "on")


def autonomous_cell_dispatch_enabled() -> bool:
    """True only when site explicitly opts into autonomous no-approval cell dispatch."""
    return os.environ.get("ROSY_FLEET_AUTONOMOUS_CELL_DISPATCH", "").strip().lower() in _TRUTHY


def resolve_autonomous_status(
    spec: dict[str, Any], *, principal_id: str | None, principal_role: str | None,
) -> tuple[str, str | None, str | None]:
    """Return `(target_status, proposer, approval_mode)` honoring explicit `propose: true` first."""
    pid = principal_id.strip() if isinstance(principal_id, str) and principal_id.strip() else None
    proposer = pid if pid is not None else ("service" if principal_role == "service" else None)
    enabled = autonomous_cell_dispatch_enabled()
    if spec.get("propose") is True:
        return "PROPOSED", proposer, None
    req_presence = bool(spec.get("requires_presence_confirm"))
    if principal_role in ("service", "ai_observer"):
        if enabled:
            return "QUEUED", proposer, (None if req_presence else "autonomous_policy")
        return "PROPOSED", proposer, None
    return "QUEUED", proposer, ("autonomous_policy" if (enabled and not req_presence) else None)


def autonomous_approver(
    principal_id: str | None, principal_role: str | None, target_status: str, approval_mode: str | None, is_named_fn,
) -> str | None:
    """Resolve `approved_by` for a QUEUED task without weakening named-operator tracking."""
    if target_status != "QUEUED":
        return None
    if principal_role not in ("service", "ai_observer") and is_named_fn(principal_id):
        return principal_id.strip()
    if approval_mode == "autonomous_policy":
        return "autonomous_policy"
    return None


def allow_autonomous_policy_fallback(target_status: str) -> bool:
    """Allow autonomous policy -> IK fallback admission only when opted in and queued."""
    return target_status == "QUEUED" and autonomous_cell_dispatch_enabled()


def prepare_proposer_and_fallback(
    tasks: dict[str, dict], spec: dict[str, Any], *, principal_id: str | None, principal_role: str | None,
    check_limits_fn, check_fallback_fn,
) -> tuple[str, str | None, str | None, int, bool]:
    """Validate proposer fields, fallback depth, and policy fallback admission together."""
    if "propose" in spec and spec["propose"] is not None and type(spec["propose"]) is not bool:
        raise HTTPException(422, detail={"code": "INVALID_CELL_TASK_INPUT"})
    if spec.get("proposer") is not None:
        raise HTTPException(422, detail={"code": "CLIENT_PROPOSER_FORBIDDEN"})
    target_status, proposer_val, approval_mode = resolve_autonomous_status(
        spec, principal_id=principal_id, principal_role=principal_role,
    )
    depth_val = check_limits_fn(tasks, spec)
    req_named = check_fallback_fn(
        tasks, spec, role=principal_role, principal_id=principal_id, target_status=target_status,
    )
    return target_status, proposer_val, approval_mode, depth_val, req_named


def skip_claim_presence_check(task: dict[str, Any]) -> bool:
    """Skip claim-time presence confirmation when autonomous dispatch is on unless task requires it."""
    return autonomous_cell_dispatch_enabled() and not task.get("requires_presence_confirm")


def validate_cas_fields(
    expected: dict[str, Any], actual: dict[str, Any], *, ep: int, dg: int, sg: int,
    require_all: bool, require_context_sha: bool,
) -> list[str]:
    """Validate CAS context digest, readiness digest, and authority generations."""
    reasons: list[str] = []
    if require_all:
        for req_k in ("expected_dispatch_generation", "expected_stop_generation", "expected_readiness_digest"):
            if expected.get(req_k) is None:
                reasons.append(f"missing {req_k}")
        if require_context_sha and expected.get("expected_context_sha256") is None:
            reasons.append("missing expected_context_sha256")
    ecs = expected.get("expected_context_sha256")
    if ecs is not None and (type(ecs) is not str or not ecs or ecs != actual.get("context_sha256")):
        reasons.append("context_sha256 mismatch")
    erd = expected.get("expected_readiness_digest")
    if erd is not None and (type(erd) is not str or not erd or erd != actual.get("readiness_digest")):
        reasons.append("readiness_digest mismatch")
    for key, cur, label in (
        ("expected_dispatch_generation", dg, "dispatch_generation"),
        ("expected_authority_epoch", ep, "authority_epoch"),
        ("expected_stop_generation", sg, "stop_generation"),
    ):
        val = expected.get(key)
        if val is None:
            continue
        if type(val) is not int:
            reasons.append(f"invalid {label} type")
        elif val != cur:
            reasons.append(f"{label} drift (expected={val}, actual={cur})")
    return reasons
