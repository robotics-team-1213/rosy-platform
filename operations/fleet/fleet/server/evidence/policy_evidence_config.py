"""Load source-scoped policy-evidence permissions from non-secret site YAML."""

from __future__ import annotations

import os
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Mapping

import yaml

_REQUIRED = {
    "source_id", "token_env", "asset_kinds", "task_kinds",
    "map_id", "calibration_revision", "model_revisions",
}
_ALLOWED = _REQUIRED | {"revoked"}
_ENV_NAME = re.compile(r"^[A-Z_][A-Z0-9_]*$")
_ASSET_KINDS = frozenset({"robot", "workcell", "object"})
_TASK_KINDS = frozenset({"navigate"})


@dataclass(frozen=True)
class PolicyEvidenceSource:
    """One revocable credential and the exact evidence domain it may write."""

    source_id: str
    token: str
    asset_kinds: tuple[str, ...]
    task_kinds: tuple[str, ...]
    map_id: str
    calibration_revision: str
    model_revisions: tuple[str, ...]
    revoked: bool = False


def _string_list(row: Mapping, field: str, index: int) -> tuple[str, ...]:
    values = row[field]
    if (not isinstance(values, list) or not values
            or any(not isinstance(value, str) or not value.strip() for value in values)):
        raise ValueError(f"sources[{index}].{field} must be a non-empty string list")
    if len(set(values)) != len(values):
        raise ValueError(f"sources[{index}].{field} must not contain duplicates")
    return tuple(values)


def load_policy_evidence_sources(path: Path | str, *,
                                 environ: Mapping[str, str] | None = None
                                 ) -> list[PolicyEvidenceSource]:
    """Resolve secret values from the process environment, never from YAML."""

    source_path = Path(path)
    try:
        config = yaml.safe_load(source_path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, yaml.YAMLError) as exc:
        raise ValueError(f"cannot read policy evidence config {source_path}: {exc}") from exc
    if not isinstance(config, dict) or set(config) != {"sources"} or not isinstance(config["sources"], list):
        raise ValueError("policy evidence config must contain only a sources list")
    if not config["sources"]:
        raise ValueError("policy evidence config needs at least one source")

    env = os.environ if environ is None else environ
    sources = []
    for index, row in enumerate(config["sources"]):
        if not isinstance(row, dict):
            raise ValueError(f"sources[{index}] must be a mapping")
        missing = _REQUIRED - row.keys()
        unknown = row.keys() - _ALLOWED
        if missing:
            raise ValueError(f"sources[{index}] missing fields: {', '.join(sorted(missing))}")
        if unknown:
            raise ValueError(f"sources[{index}] has unknown fields: {', '.join(sorted(unknown))}")
        env_name = row["token_env"]
        if not isinstance(env_name, str) or not _ENV_NAME.fullmatch(env_name):
            raise ValueError(f"sources[{index}].token_env must name an uppercase environment variable")
        token = env.get(env_name)
        if not isinstance(token, str) or not token:
            raise ValueError(f"policy evidence token environment variable {env_name} is required")
        asset_kinds = _string_list(row, "asset_kinds", index)
        task_kinds = _string_list(row, "task_kinds", index)
        model_revisions = _string_list(row, "model_revisions", index)
        if not set(asset_kinds) <= _ASSET_KINDS:
            raise ValueError(f"sources[{index}].asset_kinds must be a subset of "
                             f"{', '.join(sorted(_ASSET_KINDS))}")
        if not set(task_kinds) <= _TASK_KINDS:
            raise ValueError(f"sources[{index}].task_kinds must be a subset of "
                             f"{', '.join(sorted(_TASK_KINDS))}")
        for field in ("map_id", "calibration_revision", "source_id"):
            value = row[field]
            if not isinstance(value, str) or not value.strip():
                raise ValueError(f"sources[{index}].{field} must be a non-blank string")
        revoked = row.get("revoked", False)
        if not isinstance(revoked, bool):
            raise ValueError(f"sources[{index}].revoked must be a boolean")
        sources.append(PolicyEvidenceSource(
            source_id=row["source_id"],
            token=token,
            asset_kinds=asset_kinds,
            task_kinds=task_kinds,
            map_id=row["map_id"],
            calibration_revision=row["calibration_revision"],
            model_revisions=model_revisions,
            revoked=revoked,
        ))
    if len({source.source_id for source in sources}) != len(sources):
        raise ValueError("policy evidence source ids must be unique")
    return sources
