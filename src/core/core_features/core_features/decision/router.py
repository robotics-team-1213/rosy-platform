"""Local decision route. Hard constraints, then one rule. No network and no actuator."""

from __future__ import annotations

from collections.abc import Callable

from core_features.decision.contract import (
    ActionOption,
    DecisionRequest,
    DecisionResult,
    DecisionStatus,
)

Rule = Callable[[DecisionRequest, tuple[ActionOption, ...]], str | None]

_MOTION_BLOCKED = frozenset({"SAFE_STOP", "EMERGENCY"})


def constrain(request: DecisionRequest) -> tuple[ActionOption, ...]:
    actions = request.allowed_actions
    if request.safety_state in _MOTION_BLOCKED or request.mode == "MANUAL":
        actions = tuple(action for action in actions if not action.motion)
    return actions


def _fallback(request: DecisionRequest, allowed_ids: set[str]) -> str | None:
    if request.fallback_action in allowed_ids:
        return request.fallback_action
    return None


def _result(
    request: DecisionRequest,
    status: DecisionStatus,
    selected: str | None,
    allowed_ids: set[str],
    reason: str,
) -> DecisionResult:
    fallback = None if status is DecisionStatus.DECIDED else _fallback(request, allowed_ids)
    return DecisionResult(request.decision_id, status, selected, fallback, reason)


def route(request: DecisionRequest, rule: Rule | None) -> DecisionResult:
    allowed = constrain(request)
    allowed_ids = {action.id for action in allowed}
    if request.snapshot_age_ms > request.max_age_ms:
        return _result(request, DecisionStatus.STALE_INPUT, None, allowed_ids, "STALE_SNAPSHOT")
    if request.elapsed_ms > request.deadline_ms:
        return _result(request, DecisionStatus.TIMEOUT, None, allowed_ids, "DEADLINE")
    if rule is None:
        return _result(request, DecisionStatus.NO_PROVIDER, None, allowed_ids, "NO_PROVIDER")
    try:
        choice = rule(request, allowed)
    except Exception:
        return _result(request, DecisionStatus.ERROR, None, allowed_ids, "RULE_ERROR")
    if choice is None:
        return _result(request, DecisionStatus.ABSTAINED, None, allowed_ids, "UNRESOLVED")
    if choice not in allowed_ids:
        return _result(request, DecisionStatus.INVALID, None, allowed_ids, "OUTSIDE_ALLOWED_SET")
    return _result(request, DecisionStatus.DECIDED, choice, allowed_ids, "RULE")
