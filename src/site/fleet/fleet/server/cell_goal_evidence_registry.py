"""Credentials pinned to one simulation cell, recipe and evaluator revision."""

from dataclasses import dataclass, field
from datetime import datetime
import hmac
import math
import os
from pathlib import Path
import re

import yaml


@dataclass(frozen=True)
class CellGoalProducer:
    producer_id: str
    token: str = field(repr=False)
    workcell_id: str
    instance_id: str
    recipe_sha256: str
    cell_sha256: str
    evaluator_revisions: tuple[str, ...]
    max_age_s: float
    valid_until: datetime

    def __post_init__(self):
        for name in ("producer_id", "workcell_id", "instance_id"):
            value = getattr(self, name)
            if (not isinstance(value, str) or not value or value != value.strip() or len(value) > 128
                    or any(ord(char) < 32 for char in value)):
                raise ValueError("invalid Cell producer " + name)
        if not isinstance(self.token, str) or not self.token.strip() or len(self.token) > 4096:
            raise ValueError("Cell producer token is required")
        for name in ("recipe_sha256", "cell_sha256"):
            if not isinstance(getattr(self, name), str) or not re.fullmatch("[0-9a-f]{64}", getattr(self, name)):
                raise ValueError("Cell producer requires pinned " + name)
        if (not isinstance(self.evaluator_revisions, tuple) or not self.evaluator_revisions
                or len(set(self.evaluator_revisions)) != len(self.evaluator_revisions)
                or any(not isinstance(value, str) or not value or value != value.strip() or len(value) > 96
                       for value in self.evaluator_revisions)):
            raise ValueError("Cell producer requires evaluator revisions")
        if (isinstance(self.max_age_s, bool) or not isinstance(self.max_age_s, (float, int))
                or not math.isfinite(self.max_age_s) or not 0 < self.max_age_s <= 60):
            raise ValueError("Cell evidence freshness must be positive and at most 60 seconds")
        if (not isinstance(self.valid_until, datetime) or self.valid_until.tzinfo is None
                or self.valid_until.utcoffset() is None):
            raise ValueError("Cell producer expiry requires timezone-aware time")


@dataclass(frozen=True)
class CellGoalRegistry:
    producers: tuple[CellGoalProducer, ...]

    def __post_init__(self):
        if (not isinstance(self.producers, tuple) or not self.producers or len(self.producers) > 128
                or any(not isinstance(item, CellGoalProducer) for item in self.producers)):
            raise ValueError("Cell registry requires bounded producer entries")
        for values in ([item.producer_id for item in self.producers], [item.token for item in self.producers],
                       [(item.workcell_id, item.instance_id, item.recipe_sha256, item.cell_sha256)
                        for item in self.producers]):
            if len(values) != len(set(values)):
                raise ValueError("Cell producer identities, credentials and scopes must be unique")

    def source_for_token(self, token, *, now):
        if not isinstance(token, str) or not token or len(token) > 4096:
            return None
        return next((item for item in self.producers if hmac.compare_digest(item.token.encode(), token.encode())
                     and now < item.valid_until.timestamp()), None)


def load_cell_goal_registry(path: Path | str, *, environ=None) -> CellGoalRegistry:
    config = yaml.safe_load(Path(path).read_text(encoding="utf-8"))
    if (not isinstance(config, dict) or set(config) != {"producers"}
            or not isinstance(config["producers"], list)):
        raise ValueError("Cell producer registry requires a producers list")
    required = set(CellGoalProducer.__dataclass_fields__) - {"token"} | {"token_env"}
    entries = []
    env = os.environ if environ is None else environ
    for row in config["producers"]:
        if not isinstance(row, dict) or set(row) != required:
            raise ValueError("Cell producer registry has missing or unexpected fields")
        env_name = row["token_env"]
        if not isinstance(env_name, str) or not re.fullmatch("[A-Z_][A-Z0-9_]*", env_name):
            raise ValueError("Cell producer token_env must name an environment variable")
        expiry = row["valid_until"]
        if not isinstance(expiry, str):
            raise ValueError("Cell producer valid_until must be an ISO-8601 string")
        if not isinstance(row["evaluator_revisions"], list):
            raise ValueError("Cell producer evaluator_revisions must be a list")
        entries.append(CellGoalProducer(**{
            **{key: value for key, value in row.items()
               if key not in {"token_env", "valid_until", "evaluator_revisions"}},
            "token": env.get(env_name), "valid_until": datetime.fromisoformat(expiry.replace("Z", "+00:00")),
            "evaluator_revisions": tuple(row["evaluator_revisions"]),
        }))
    return CellGoalRegistry(tuple(entries))
