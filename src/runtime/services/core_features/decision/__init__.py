"""Shared judgment library. Products supply the allowed set and the rule."""

from core_features.decision.contract import (
    ActionOption,
    DecisionRequest,
    DecisionResult,
    DecisionStatus,
)
from core_features.decision.router import constrain, route

__all__ = [
    "ActionOption",
    "DecisionRequest",
    "DecisionResult",
    "DecisionStatus",
    "constrain",
    "route",
]
