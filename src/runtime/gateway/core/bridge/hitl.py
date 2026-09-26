"""ROS-free validation for operator-assistance requests (ADR-999)."""

from __future__ import annotations

from dataclasses import dataclass
import json
import math


@dataclass(frozen=True)
class HitlRequest:
    requested: bool
    module: str
    confidence: float


def parse_hitl_request(raw: str) -> HitlRequest:
    """Parse one strict HITL request without importing ROS message types."""
    try:
        payload = json.loads(raw)
    except (TypeError, json.JSONDecodeError) as exc:
        raise ValueError("HITL request is not valid JSON") from exc
    if not isinstance(payload, dict):
        raise ValueError("HITL request must be an object")

    requested = payload.get("requested")
    module = payload.get("module")
    confidence = payload.get("confidence")
    if not isinstance(requested, bool):
        raise ValueError("requested must be boolean")
    if not isinstance(module, str) or not module.strip():
        raise ValueError("module must be a non-empty string")
    if isinstance(confidence, bool) or not isinstance(confidence, (int, float)):
        raise ValueError("confidence must be numeric")
    confidence = float(confidence)
    if not math.isfinite(confidence) or not 0.0 <= confidence <= 1.0:
        raise ValueError("confidence must be between 0 and 1")

    return HitlRequest(
        requested=requested,
        module=module.strip(),
        confidence=confidence,
    )
