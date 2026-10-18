"""recipe/3 Cell Jobs: Fleet recompiles a mixed plan into a multi-arm submission (D-781 §5, D-779 2-4).

A candidate whose recipe schema is ``rosy_cell.recipe/3`` does not go through
``compile_cell_submission`` (one arm, one PlanBundle). The injected process compiler's
``compile_mixed(recipe, cell)`` returns a ``MixedCellCompilation``; this module checks the
candidate envelope the same way (D-403 §3: the candidate Job equals the recompiled Job byte for
byte, the recipe and cell digests match) and builds the ``cell_arm_jobs.create`` shape. It does
not import the palletizing process (D-413): ``cell_compiler`` stays the only module that does.

The Job claims the cell's workcell, every arm owner's workcell (from the cell document's arms)
and every pallet it fills; arm and zone claims are taken per Action (D-779 §5). The job_id is
the same digest as a single-arm Job's: recipe and cell digests plus the canonical Job.
The resolver (cell_goal_evidence) then fixes one item_at_pose predicate per arm of each step,
each in that arm's base frame (``goal_predicates``), when a goal tolerance is configured.
"""

from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Mapping
from dataclasses import dataclass

MIXED_RECIPE_SCHEMA = "rosy_cell.recipe/3"
MAX_CANDIDATE_BYTES = 64 * 1024  # as compile_cell_submission
_CANDIDATE_KEYS = {"kind", "recipe", "cell", "recipe_sha256", "cell_sha256", "job"}
_SHA256 = re.compile(r"^[0-9a-f]{64}$")


@dataclass(frozen=True)
class MixedCellCompilation:
    """What the process compiler hands back for a recipe/3 candidate."""

    job: Mapping
    arms: tuple[Mapping, ...]  # {role, instance_id, workcell_id}
    steps: tuple[Mapping, ...]  # {skill_id, version, placement}
    ledger_markers: tuple[Mapping, ...]
    pallet_ids: tuple[str, ...]
    recipe_digest: str
    cell_digest: str
    process_artifact_digest: str


def _canonical(value: object, *, field: str) -> str:
    try:
        return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{field} must be finite JSON") from exc


def is_mixed(candidate: object) -> bool:
    """The candidate names a recipe/3 recipe (D-781 §1); recipe/1 and /2 keep their path."""
    return (isinstance(candidate, Mapping) and isinstance(candidate.get("recipe"), Mapping)
            and candidate["recipe"].get("schema") == MIXED_RECIPE_SCHEMA)


def compile_mixed_submission(candidate: Mapping, *, compiler, workcell_id: str, instance_id: str) -> dict:
    """Recompile a recipe/3 candidate and return the multi-arm Cell Job submission.

    ``workcell_id`` is the cell's own workcell; ``instance_id`` must be one of the cell's arm
    instances (the proposal names one; the Job runs all of them). Descriptive only: no authority.
    """
    if not isinstance(candidate, Mapping) or set(candidate) != _CANDIDATE_KEYS or candidate["kind"] != "cell_job":
        raise ValueError("cell_job candidate has an invalid envelope")
    recipe, cell = candidate["recipe"], candidate["cell"]
    if not isinstance(recipe, Mapping) or not isinstance(cell, Mapping):
        raise ValueError("recipe and cell must be JSON objects")
    for name in ("recipe_sha256", "cell_sha256"):
        if not isinstance(candidate[name], str) or not _SHA256.fullmatch(candidate[name]):
            raise ValueError(f"{name} must be a lowercase SHA-256 digest")
    if len(_canonical(candidate, field="candidate").encode("utf-8")) > MAX_CANDIDATE_BYTES:
        raise ValueError("cell_job candidate exceeds 64 KiB")
    if not callable(getattr(compiler, "compile_mixed", None)):
        raise ValueError("the process compiler does not compile recipe/3")
    compiled = compiler.compile_mixed(dict(recipe), dict(cell))
    if not isinstance(compiled, MixedCellCompilation):
        raise ValueError("process compiler returned an unsupported mixed compilation")
    if _canonical(candidate["job"], field="candidate Job") != _canonical(compiled.job, field="recompiled Job"):
        raise ValueError("candidate Job differs from the recompiled Job")
    if (compiled.recipe_digest, compiled.cell_digest) != (candidate["recipe_sha256"], candidate["cell_sha256"]):
        raise ValueError("recompiled recipe digest or cell digest differs from candidate revisions")
    arms = [dict(arm) for arm in compiled.arms]
    if len(arms) < 2:
        raise ValueError("a recipe/3 Cell Job needs a cell with two or more arms (one arm: follow-up)")
    if instance_id not in {arm["instance_id"] for arm in arms}:
        raise ValueError("instance_id must name one of the cell's arm instances")
    identity = {"recipe_sha256": compiled.recipe_digest, "cell_sha256": compiled.cell_digest, "job": compiled.job}
    job_id = hashlib.sha256(_canonical(identity, field="job identity").encode("utf-8")).hexdigest()
    resources = [["workcell", workcell_id], *(["workcell", arm["workcell_id"]] for arm in arms),
                 *(["pallet", pallet] for pallet in sorted(compiled.pallet_ids))]
    return json.loads(_canonical({
        "job_id": job_id, "workcell_id": workcell_id, "arms": arms,
        "recipe_digest": compiled.recipe_digest, "cell_digest": compiled.cell_digest,
        "process_artifact_digest": compiled.process_artifact_digest, "job": compiled.job,
        "steps": list(compiled.steps), "resources": resources, "ledger_markers": list(compiled.ledger_markers),
    }, field="multi-arm submission"))


__all__ = ["MIXED_RECIPE_SCHEMA", "MixedCellCompilation", "compile_mixed_submission", "is_mixed"]
