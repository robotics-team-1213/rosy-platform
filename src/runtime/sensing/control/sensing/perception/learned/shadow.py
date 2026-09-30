"""Subject: the perception/learned/shadow wire shape (D-356).

Shadow evidence has no consumer in the control path. It carries the model's
lane error next to the rule-based one so disagreement can be logged and later
used as a recording trigger and as replay-gate input (D-205)."""

from __future__ import annotations

from .runner import InferResult

SHADOW_SCHEMA = "rosy.perception.learned_shadow/1"
TOPIC = "perception/learned/shadow"


def shadow_payload(result: InferResult, *, stamp: float, rule_error: float | None) -> dict:
    ev = result.evidence
    delta = (round(ev.error - rule_error, 6)
             if ev.visible and ev.error is not None and rule_error is not None else None)
    return {
        "schema": SHADOW_SCHEMA,
        "stamp": float(stamp),
        "model_revision": result.model_revision,
        "visible": ev.visible,
        "error": ev.error,
        "confidence": ev.confidence,
        "latency_ms": round(result.latency_ms, 3),
        "class_fractions": dict(ev.class_fractions),
        "rule_error": rule_error,
        "error_delta": delta,
    }
