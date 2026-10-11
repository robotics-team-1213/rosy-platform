"""Independent, bounded evidence checks for one-step Fleet goals."""

from __future__ import annotations

import math
import re
from dataclasses import dataclass
from typing import Mapping

_STRING_LIMITS = {
    "predicate_id": 96,
    "object_id": 192,
    "destination_id": 192,
    "evidence_source": 96,
    "evidence_id": 192,
    "evidence_revision": 96,
    "producer_id": 128,
    "observation_id": 192,
    "observation_digest": 64,
    "evaluator_revision": 96,
    "action_id": 192,
    "attempt_id": 192,
    "gripper_state": 16,
    "gripper_evidence_id": 192,
    "gripper_evidence_revision": 96,
}


class GoalEvidenceError(ValueError):
    """Evidence does not satisfy the immutable Mission goal predicate."""


@dataclass(frozen=True)
class GoalPredicate:
    predicate_id: str
    condition: str
    object_id: str
    destination_id: str
    evidence_source: str

    @classmethod
    def from_mapping(cls, raw: dict) -> "GoalPredicate":
        if not isinstance(raw, dict) or set(raw) != {
            "predicate_id", "condition", "object_id", "destination_id", "evidence_source",
        }:
            raise ValueError(
                "goal predicate requires predicate_id, condition, object_id, destination_id, evidence_source"
            )
        values = {key: value for key, value in raw.items()}
        for key, value in values.items():
            if (not isinstance(value, str) or not value.strip() or value != value.strip()
                    or any(ord(char) < 32 for char in value)):
                raise ValueError(f"goal predicate {key} must be a non-empty trimmed string")
        if values["condition"] != "object_in_destination":
            raise ValueError("only object_in_destination is supported by the single-step baseline")
        if values["evidence_source"] != "camera_observation":
            raise ValueError("single-step pick-place goals require independent camera_observation evidence")
        return cls(**values)

    def to_dict(self) -> dict[str, str]:
        return {
            "predicate_id": self.predicate_id, "condition": self.condition,
            "object_id": self.object_id, "destination_id": self.destination_id,
            "evidence_source": self.evidence_source,
        }


@dataclass(frozen=True)
class GoalEvidence:
    predicate_id: str
    object_id: str
    destination_id: str
    evidence_source: str
    evidence_id: str
    evidence_revision: str
    producer_id: str
    observation_id: str
    observation_digest: str
    evaluator_revision: str
    action_id: str
    attempt_id: str
    gripper_state: str
    gripper_evidence_id: str
    gripper_evidence_revision: str
    gripper_observed_at: float
    observed_at: float
    satisfied: bool

    @classmethod
    def from_mapping(cls, raw: dict) -> "GoalEvidence":
        required = {
            "predicate_id", "object_id", "destination_id", "evidence_source",
            "evidence_id", "evidence_revision", "producer_id", "observation_id",
            "observation_digest", "evaluator_revision", "action_id", "attempt_id",
            "gripper_state", "gripper_evidence_id", "gripper_evidence_revision",
            "gripper_observed_at", "observed_at", "satisfied",
        }
        if not isinstance(raw, Mapping) or set(raw) != required:
            raise GoalEvidenceError("goal evidence has missing or unexpected fields")
        for key in required - {"observed_at", "gripper_observed_at", "satisfied"}:
            value = raw[key]
            if (not isinstance(value, str) or not value.strip() or value != value.strip()
                    or len(value) > _STRING_LIMITS[key]
                    or any(ord(char) < 32 for char in value)):
                raise GoalEvidenceError(f"goal evidence {key} is missing")
        if type(raw["satisfied"]) is not bool:
            raise GoalEvidenceError("goal evidence satisfied must be boolean")
        observed_at = _finite_timestamp(raw["observed_at"], "observed_at")
        gripper_observed_at = _finite_timestamp(raw["gripper_observed_at"], "gripper_observed_at")
        if not re.fullmatch(r"[0-9a-f]{64}", raw["observation_digest"]):
            raise GoalEvidenceError("goal observation digest must be lowercase SHA-256")
        if raw["gripper_state"] != "OPEN":
            raise GoalEvidenceError("gripper readback must confirm OPEN")
        return cls(
            predicate_id=raw["predicate_id"], object_id=raw["object_id"],
            destination_id=raw["destination_id"], evidence_source=raw["evidence_source"],
            evidence_id=raw["evidence_id"], evidence_revision=raw["evidence_revision"],
            producer_id=raw["producer_id"], observation_id=raw["observation_id"],
            observation_digest=raw["observation_digest"],
            evaluator_revision=raw["evaluator_revision"], action_id=raw["action_id"],
            attempt_id=raw["attempt_id"], gripper_state=raw["gripper_state"],
            gripper_evidence_id=raw["gripper_evidence_id"],
            gripper_evidence_revision=raw["gripper_evidence_revision"],
            gripper_observed_at=gripper_observed_at,
            observed_at=observed_at, satisfied=raw["satisfied"],
        )

    def to_dict(self) -> dict:
        return {
            "predicate_id": self.predicate_id, "object_id": self.object_id,
            "destination_id": self.destination_id, "evidence_source": self.evidence_source,
            "evidence_id": self.evidence_id, "evidence_revision": self.evidence_revision,
            "producer_id": self.producer_id, "observation_id": self.observation_id,
            "observation_digest": self.observation_digest,
            "evaluator_revision": self.evaluator_revision,
            "action_id": self.action_id, "attempt_id": self.attempt_id,
            "gripper_state": self.gripper_state,
            "gripper_evidence_id": self.gripper_evidence_id,
            "gripper_evidence_revision": self.gripper_evidence_revision,
            "gripper_observed_at": self.gripper_observed_at,
            "observed_at": self.observed_at, "satisfied": self.satisfied,
        }


def _finite_timestamp(value: object, field: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise GoalEvidenceError(f"goal evidence {field} timestamp is invalid")
    try:
        result = float(value)
    except (OverflowError, TypeError, ValueError) as exc:
        raise GoalEvidenceError(f"goal evidence {field} timestamp is invalid") from exc
    if not math.isfinite(result):
        raise GoalEvidenceError(f"goal evidence {field} timestamp is invalid")
    return result


def verify_goal(predicate: GoalPredicate, evidence: GoalEvidence, *,
                now: float, max_age_s: float) -> bool:
    if evidence.evidence_source != predicate.evidence_source:
        raise GoalEvidenceError("goal evidence source is not independent or permitted")
    if evidence.predicate_id != predicate.predicate_id:
        raise GoalEvidenceError("goal evidence predicate does not match accepted Mission predicate")
    if evidence.object_id != predicate.object_id:
        raise GoalEvidenceError("goal evidence object does not match the accepted predicate")
    if evidence.destination_id != predicate.destination_id:
        raise GoalEvidenceError("goal evidence destination does not match the accepted predicate")
    if not evidence.evidence_revision.strip():
        raise GoalEvidenceError("goal evidence revision is missing")
    if (isinstance(now, bool) or not isinstance(now, (int, float))
            or isinstance(max_age_s, bool) or not isinstance(max_age_s, (int, float))):
        raise GoalEvidenceError("goal evidence freshness parameters are invalid")
    try:
        current, max_age = float(now), float(max_age_s)
    except (TypeError, ValueError) as exc:
        raise GoalEvidenceError("goal evidence freshness parameters are invalid") from exc
    age = current - evidence.observed_at
    gripper_age = current - evidence.gripper_observed_at
    if (not math.isfinite(current) or not math.isfinite(max_age) or max_age <= 0
            or age < 0 or age > max_age or gripper_age < 0 or gripper_age > max_age):
        raise GoalEvidenceError("goal evidence is stale or from the future")
    return evidence.satisfied
