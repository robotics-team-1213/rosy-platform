"""Load narrowly scoped goal-evidence producer credentials from YAML."""

from __future__ import annotations

import hmac
import math
import os
import re
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Mapping

import yaml

_REQUIRED = {
    "producer_id", "token_env", "workcell_id", "predicate_id", "object_id",
    "destination_id", "evidence_source", "max_age_s", "grace_s",
    "evaluator_revisions", "valid_until",
}
_ENV_NAME = re.compile(r"^[A-Z_][A-Z0-9_]*$")
_EVIDENCE_SOURCES = frozenset({"camera_observation"})


class GoalEvidenceRegistryError(ValueError):
    """Invalid producer registry configuration."""


@dataclass(frozen=True)
class GoalEvidenceProducer:
    """One credential scoped to a workcell goal predicate and evaluator."""

    producer_id: str
    token: str = field(repr=False)
    workcell_id: str
    predicate_id: str
    object_id: str
    destination_id: str
    evidence_source: str
    max_age_s: float
    grace_s: float
    evaluator_revisions: tuple[str, ...]
    valid_until: datetime

    def is_valid_at(self, now: float) -> bool:
        return now < self.valid_until.timestamp()


@dataclass(frozen=True)
class GoalEvidenceRegistry:
    """Immutable producer snapshot; credentials never come from evidence bodies."""

    producers: tuple[GoalEvidenceProducer, ...]

    def source_for_token(self, token: str, *, now: float) -> GoalEvidenceProducer | None:
        if not isinstance(token, str) or not token:
            return None
        for producer in self.producers:
            if hmac.compare_digest(producer.token, token):
                return producer if producer.is_valid_at(now) else None
        return None

    def producer_for_scope(self, *, producer_id: str, workcell_id: str,
                           predicate_id: str, now: float) -> GoalEvidenceProducer | None:
        for producer in self.producers:
            if (producer.producer_id == producer_id
                    and producer.workcell_id == workcell_id
                    and producer.predicate_id == predicate_id
                    and producer.is_valid_at(now)):
                return producer
        return None

    def producer_for_goal(self, *, workcell_id: str, predicate_id: str,
                          now: float) -> GoalEvidenceProducer | None:
        for producer in self.producers:
            if (producer.workcell_id == workcell_id
                    and producer.predicate_id == predicate_id
                    and producer.is_valid_at(now)):
                return producer
        return None


def _nonblank(row: Mapping, key: str, index: int) -> str:
    value = row[key]
    if not isinstance(value, str) or not value.strip():
        raise GoalEvidenceRegistryError(f"producers[{index}].{key} must be a non-blank string")
    return value.strip()


def _string_list(row: Mapping, key: str, index: int) -> tuple[str, ...]:
    values = row[key]
    if (not isinstance(values, list) or not values
            or any(not isinstance(value, str) or not value.strip() for value in values)):
        raise GoalEvidenceRegistryError(
            f"producers[{index}].{key} must be a non-empty string list"
        )
    values = [value.strip() for value in values]
    if len(set(values)) != len(values):
        raise GoalEvidenceRegistryError(f"producers[{index}].{key} must not contain duplicates")
    return tuple(values)


def load_goal_evidence_registry(path: Path | str, *,
                                environ: Mapping[str, str] | None = None
                                ) -> GoalEvidenceRegistry:
    """Read non-secret scopes from YAML and resolve each token from the environment."""

    source_path = Path(path)
    try:
        config = yaml.safe_load(source_path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, yaml.YAMLError) as exc:
        raise GoalEvidenceRegistryError(
            f"cannot read goal evidence registry {source_path}: {exc}"
        ) from exc
    if (not isinstance(config, dict) or set(config) != {"producers"}
            or not isinstance(config["producers"], list) or not config["producers"]):
        raise GoalEvidenceRegistryError(
            "goal evidence registry must contain at least one producer"
        )

    env = os.environ if environ is None else environ
    producers = []
    for index, row in enumerate(config["producers"]):
        if not isinstance(row, dict):
            raise GoalEvidenceRegistryError(f"producers[{index}] must be a mapping")
        missing = _REQUIRED - row.keys()
        unknown = row.keys() - _REQUIRED
        if missing:
            raise GoalEvidenceRegistryError(
                f"producers[{index}] missing fields: {', '.join(sorted(missing))}"
            )
        if unknown:
            raise GoalEvidenceRegistryError(
                f"producers[{index}] has unknown fields: {', '.join(sorted(unknown))}"
            )

        env_name = row["token_env"]
        if not isinstance(env_name, str) or not _ENV_NAME.fullmatch(env_name):
            raise GoalEvidenceRegistryError(
                f"producers[{index}].token_env must name an uppercase environment variable"
            )
        token = env.get(env_name)
        if not isinstance(token, str) or not token:
            raise GoalEvidenceRegistryError(
                f"goal evidence token environment variable {env_name} is required"
            )
        if not isinstance(row["max_age_s"], (int, float)) or isinstance(row["max_age_s"], bool):
            raise GoalEvidenceRegistryError(f"producers[{index}].max_age_s must be a positive number")
        if not isinstance(row["grace_s"], (int, float)) or isinstance(row["grace_s"], bool):
            raise GoalEvidenceRegistryError(f"producers[{index}].grace_s must be a positive number")
        max_age_s = float(row["max_age_s"])
        grace_s = float(row["grace_s"])
        if not math.isfinite(max_age_s) or max_age_s <= 0:
            raise GoalEvidenceRegistryError(f"producers[{index}].max_age_s must be a positive number")
        if not math.isfinite(grace_s) or grace_s <= 0:
            raise GoalEvidenceRegistryError(f"producers[{index}].grace_s must be a positive number")
        evidence_source = _nonblank(row, "evidence_source", index)
        if evidence_source not in _EVIDENCE_SOURCES:
            raise GoalEvidenceRegistryError(
                f"producers[{index}].evidence_source must be one of "
                f"{', '.join(sorted(_EVIDENCE_SOURCES))}"
            )
        valid_until_raw = _nonblank(row, "valid_until", index)
        try:
            valid_until = datetime.fromisoformat(valid_until_raw.replace("Z", "+00:00"))
        except ValueError as exc:
            raise GoalEvidenceRegistryError(
                f"producers[{index}].valid_until must be an ISO-8601 timestamp"
            ) from exc
        if valid_until.tzinfo is None or valid_until.utcoffset() is None:
            raise GoalEvidenceRegistryError(
                f"producers[{index}].valid_until must include a timezone"
            )
        producers.append(GoalEvidenceProducer(
            producer_id=_nonblank(row, "producer_id", index),
            token=token,
            workcell_id=_nonblank(row, "workcell_id", index),
            predicate_id=_nonblank(row, "predicate_id", index),
            object_id=_nonblank(row, "object_id", index),
            destination_id=_nonblank(row, "destination_id", index),
            evidence_source=evidence_source,
            max_age_s=max_age_s,
            grace_s=grace_s,
            evaluator_revisions=_string_list(row, "evaluator_revisions", index),
            valid_until=valid_until,
        ))

    if len({item.producer_id for item in producers}) != len(producers):
        raise GoalEvidenceRegistryError("goal evidence producer ids must be unique")
    scopes = {(item.workcell_id, item.predicate_id) for item in producers}
    if len(scopes) != len(producers):
        raise GoalEvidenceRegistryError("producer scopes must be unique")
    if len({item.token for item in producers}) != len(producers):
        raise GoalEvidenceRegistryError("producer tokens must be unique")
    return GoalEvidenceRegistry(tuple(producers))
