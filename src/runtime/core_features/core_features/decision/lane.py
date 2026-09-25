"""lane_recovery chooses FOLLOW or STOP. It does not compute a velocity."""

from __future__ import annotations

from core_features.decision.contract import ActionOption, DecisionRequest

FOLLOW = "FOLLOW"
STOP = "STOP"

LANE_ACTIONS = (
    ActionOption(FOLLOW, motion=True),
    ActionOption(STOP, motion=False),
)


def lane_recovery_rule(request: DecisionRequest, _allowed: tuple[ActionOption, ...]) -> str:
    context = request.context
    age_s = context.get("age_s")
    try:
        confidence = float(context.get("confidence", 0.0))
        min_confidence = float(context.get("min_confidence", 1.0))
        stale_after_s = float(context.get("stale_after_s", 0.0))
        age = None if age_s is None else float(age_s)
    except (TypeError, ValueError):
        return STOP
    tracking = (
        bool(context.get("source_matches"))
        and age is not None
        and 0.0 <= age <= stale_after_s
        and bool(context.get("visible"))
        and confidence >= min_confidence
    )
    return FOLLOW if tracking else STOP
