"""Validate a Rosy Cell proposal through an injected process compiler port.

This module owns the execution-facing submission boundary. It deliberately does
not import a palletizing implementation: the application supplies the compiler.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
import hashlib
import json
import math
import re
from typing import Protocol

from rosy.execution.api import PlanBundle

_SHA256 = re.compile(r"^[0-9a-f]{64}$")
_CANDIDATE_KEYS = {
    "kind", "recipe", "cell", "recipe_sha256", "cell_sha256", "job",
}
_TRANSFER_INPUTS = {
    "item", "pallet_id", "layer_index", "home_pose_base", "source_pose_base",
    "destination_pose_base", "source_approach_z_base_m",
    "destination_approach_z_base_m", "carry_z_base_m",
}


class CellJobCompiler(Protocol):
    """Application-provided compiler for canonical recipe and cell documents."""

    def compile(self, recipe: Mapping, cell: Mapping) -> CellJobCompilation: ...


@dataclass(frozen=True)
class CellJobCompilation:
    """Process compiler output in the small shape execution needs to verify."""

    job: Mapping
    plan_bundle: PlanBundle
    ledger_markers: tuple[Mapping, ...]
    operator_checkpoints: tuple[Mapping, ...] = ()


@dataclass(frozen=True)
class CellJobSubmission:
    """Validated ordered transfer bundle and Fleet-owned resource claims."""

    job_id: str
    workcell_id: str
    instance_id: str
    recipe_digest: str
    cell_digest: str
    process_artifact_digest: str
    job: Mapping
    plan_bundle: PlanBundle
    ledger_markers: tuple[tuple[int, str], ...]
    resources: tuple[tuple[str, str], ...]
    operator_checkpoints: tuple[Mapping, ...] = ()

    @property
    def action_kinds(self) -> tuple[str, ...]:
        return ("CELL_TRANSFER",) * len(self.plan_bundle.steps)

    def as_store_document(self) -> dict:
        """Return a JSON-ready journal payload for the Fleet persistence adapter."""
        def thaw(value):
            if isinstance(value, Mapping):
                return {key: thaw(nested) for key, nested in value.items()}
            if isinstance(value, (tuple, list)):
                return [thaw(item) for item in value]
            return value

        document = {
            "job_id": self.job_id,
            "workcell_id": self.workcell_id,
            "instance_id": self.instance_id,
            "recipe_digest": self.recipe_digest,
            "cell_digest": self.cell_digest,
            "process_artifact_digest": self.process_artifact_digest,
            "job": thaw(self.job),
            "steps": [
                {"skill_id": step.invocation.skill_id,
                 "version": step.invocation.version,
                 "inputs": thaw(step.invocation.inputs)}
                for step in self.plan_bundle.steps
            ],
            "resources": [list(resource) for resource in self.resources],
            "ledger_markers": [
                {"after_step_ordinal": ordinal, "pallet_id": pallet}
                for ordinal, pallet in self.ledger_markers
            ],
        }
        if self.operator_checkpoints:
            document["operator_checkpoints"] = [thaw(row) for row in self.operator_checkpoints]
        return document


def _canonical(value: object, *, field: str) -> str:
    try:
        return json.dumps(value, sort_keys=True, separators=(",", ":"),
                          ensure_ascii=False, allow_nan=False)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{field} must be finite JSON") from exc


def operator_checkpoint_id(recipe_digest: str, cell_digest: str, descriptor: Mapping) -> str:
    """Content identity for non-motion metadata; it grants no execution authority."""
    if (not isinstance(recipe_digest, str) or not _SHA256.fullmatch(recipe_digest)
            or not isinstance(cell_digest, str) or not _SHA256.fullmatch(cell_digest)):
        raise ValueError("operator checkpoint requires recipe/cell SHA256 digests")
    encoded = _canonical({"recipe_sha256": recipe_digest, "cell_sha256": cell_digest,
                          "checkpoint": dict(descriptor)}, field="operator checkpoint identity")
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def _operator_checkpoints(compiled: CellJobCompilation, bundle: PlanBundle) -> tuple[Mapping, ...]:
    """Reconstruct checkpoint placement from the canonical Job, not caller metadata."""
    if not isinstance(compiled.operator_checkpoints, tuple):
        raise ValueError("operator checkpoints must be a canonical tuple")
    steps = compiled.job.get("steps", ())
    has_manual_step = any(isinstance(step, Mapping) and step.get("kind") == "operator_sheet"
                          for step in steps)
    if not compiled.operator_checkpoints and not has_manual_step:
        return ()
    if not isinstance(steps, (list, tuple)) or not all(
            isinstance(step, Mapping) and "kind" in step for step in steps):
        raise ValueError("operator checkpoints require canonical Job step mappings")
    expected, completed_transfers = [], 0
    for step in steps:
        if step["kind"] == "pick":
            completed_transfers += 1
        if step["kind"] != "operator_sheet":
            continue
        if (set(step) != {"kind", "item", "pallet", "layer", "target", "approach_z", "thickness_m"}
                or step["item"] != "slip_sheet" or step["approach_z"] is not None
                or not isinstance(step["target"], Mapping)
                or set(step["target"]) != {"x", "y", "z", "yaw"}):
            raise ValueError("operator checkpoint Job step has an invalid shape")
        ordinal = completed_transfers+1
        layer = step["layer"]
        if (not 1 <= ordinal <= len(bundle.steps) or isinstance(layer, bool)
                or not isinstance(layer, int) or layer < 0):
            raise ValueError("operator checkpoint must precede an existing layer transfer")
        thickness = _finite(step["thickness_m"], "checkpoint thickness")
        if thickness <= 0:
            raise ValueError("operator checkpoint thickness must be positive")
        descriptor = {"kind": "operator_sheet", "before_transfer_ordinal": ordinal,
                      "pallet_id": _identifier(step["pallet"], "checkpoint pallet_id"), "layer_index": layer,
                      "sheet_pose_base": {_key: _finite(step["target"][_value], "checkpoint pose")
                                          for _key, _value in (
                                              ("x_m", "x"), ("y_m", "y"), ("z_m", "z"), ("yaw_rad", "yaw"))},
                      "thickness_m": thickness}
        following = bundle.steps[ordinal-1].invocation.inputs
        if (following["item"] != "box" or following["pallet_id"] != descriptor["pallet_id"]
                or following["layer_index"] != layer):
            raise ValueError("operator checkpoint does not bind the following box layer")
        expected.append({"checkpoint_id": operator_checkpoint_id(bundle.recipe_digest, bundle.cell_digest,
                                                                 descriptor), **descriptor})
    ordinals = [row["before_transfer_ordinal"] for row in expected]
    if ordinals != sorted(set(ordinals)):
        raise ValueError("operator checkpoints must be uniquely ordered by transfer boundary")
    if _canonical(list(compiled.operator_checkpoints), field="operator checkpoints") != _canonical(
            expected, field="Job operator checkpoints"):
        raise ValueError("operator checkpoint metadata differs from canonical Job binding")
    return tuple(expected)


def _identifier(value: object, field: str, *, limit: int = 192) -> str:
    if (not isinstance(value, str) or not value or value != value.strip()
            or len(value) > limit or any(ord(char) < 32 for char in value)):
        raise ValueError(f"{field} must be a non-empty trimmed identifier")
    return value


def _finite(value: object, field: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
        raise ValueError(f"{field} must be a finite number")
    return float(value)


def _pose(value: object, field: str) -> Mapping:
    if not isinstance(value, Mapping) or set(value) != {"x_m", "y_m", "z_m", "yaw_rad"}:
        raise ValueError(f"{field} must contain x_m, y_m, z_m and yaw_rad")
    return {name: _finite(value[name], f"{field}.{name}")
            for name in ("x_m", "y_m", "z_m", "yaw_rad")}


def _validate_transfer_inputs(value: Mapping) -> str:
    if set(value) != _TRANSFER_INPUTS:
        raise ValueError("pallet.transfer inputs do not match the versioned Skill contract")
    item = value["item"]
    if item not in {"box", "slip_sheet"}:
        raise ValueError("pallet.transfer item must be box or slip_sheet")
    pallet_id = _identifier(value["pallet_id"], "pallet_id")
    layer_index = value["layer_index"]
    if isinstance(layer_index, bool) or not isinstance(layer_index, int) or layer_index < 0:
        raise ValueError("layer_index must be a non-negative integer")
    _pose(value["home_pose_base"], "home_pose_base")
    source = _pose(value["source_pose_base"], "source_pose_base")
    destination = _pose(value["destination_pose_base"], "destination_pose_base")
    source_approach = _finite(value["source_approach_z_base_m"], "source_approach_z_base_m")
    destination_approach = _finite(
        value["destination_approach_z_base_m"], "destination_approach_z_base_m",
    )
    carry = _finite(value["carry_z_base_m"], "carry_z_base_m")
    if (source_approach < source["z_m"] or destination_approach < destination["z_m"]
            or carry < max(source_approach, destination_approach)):
        raise ValueError("transfer carry height must cover both target approaches")
    return pallet_id


def compile_cell_submission(candidate: Mapping, *, compiler: CellJobCompiler,
                            workcell_id: str, instance_id: str) -> CellJobSubmission:
    """Recompile and compare the submitted Job before exposing ordered transfers.

    The returned value is descriptive only. It grants no authority and performs
    no device submission.
    """
    workcell_id = _identifier(workcell_id, "workcell_id", limit=96)
    instance_id = _identifier(instance_id, "instance_id", limit=96)
    if not isinstance(candidate, Mapping) or set(candidate) != _CANDIDATE_KEYS:
        raise ValueError("cell_job candidate has an invalid envelope")
    if candidate["kind"] != "cell_job":
        raise ValueError("candidate kind must be cell_job")
    recipe, cell = candidate["recipe"], candidate["cell"]
    if not isinstance(recipe, Mapping) or not isinstance(cell, Mapping):
        raise ValueError("recipe and cell must be JSON objects")
    for name in ("recipe_sha256", "cell_sha256"):
        if not isinstance(candidate[name], str) or not _SHA256.fullmatch(candidate[name]):
            raise ValueError(f"{name} must be a lowercase SHA-256 digest")
    if len(_canonical(candidate, field="candidate").encode("utf-8")) > 64 * 1024:
        raise ValueError("cell_job candidate exceeds 64 KiB")
    if not callable(getattr(compiler, "compile", None)):
        raise ValueError("a process compiler port is required")

    compiled = compiler.compile(dict(recipe), dict(cell))
    if not isinstance(compiled, CellJobCompilation):
        raise ValueError("process compiler returned an unsupported compilation")
    if not isinstance(compiled.job, Mapping) or not isinstance(compiled.plan_bundle, PlanBundle):
        raise ValueError("process compiler returned an invalid Job or PlanBundle")
    if _canonical(candidate["job"], field="candidate Job") != _canonical(
            compiled.job, field="recompiled Job"):
        raise ValueError("candidate Job differs from the recompiled Job")
    bundle = compiled.plan_bundle
    if (bundle.recipe_digest != candidate["recipe_sha256"]
            or bundle.cell_digest != candidate["cell_sha256"]):
        raise ValueError("PlanBundle recipe digest or cell digest differs from candidate revisions")

    pallet_ids: set[str] = set()
    for step in bundle.steps:
        invocation = step.invocation
        if invocation.skill_id != "pallet.transfer":
            raise ValueError("cell Job may contain only the pallet.transfer Skill")
        if invocation.version != "1.0.0":
            raise ValueError("unsupported pallet.transfer Skill version")
        pallet_ids.add(_validate_transfer_inputs(invocation.inputs))

    markers: list[tuple[int, str]] = []
    for marker in compiled.ledger_markers:
        if not isinstance(marker, Mapping) or set(marker) != {"after_step_ordinal", "pallet_id"}:
            raise ValueError("ledger marker has an invalid shape")
        ordinal = marker["after_step_ordinal"]
        if (isinstance(ordinal, bool) or not isinstance(ordinal, int)
                or not 1 <= ordinal <= len(bundle.steps)):
            raise ValueError("ledger marker ordinal must refer to a completed transfer count")
        markers.append((ordinal, _identifier(marker["pallet_id"], "ledger pallet_id")))
    if (not markers or markers != sorted(set(markers))
            or len({ordinal for ordinal, _ in markers}) != len(markers)
            or {pallet for _, pallet in markers} != pallet_ids):
        raise ValueError("ledger markers must be ordered and cover every transferred pallet")

    digest_input = {
        "recipe_sha256": bundle.recipe_digest,
        "cell_sha256": bundle.cell_digest,
        "job": compiled.job,
    }
    job_id = hashlib.sha256(_canonical(digest_input, field="job identity").encode("utf-8")).hexdigest()
    resources = (("workcell", workcell_id),) + tuple(
        ("pallet", pallet_id) for pallet_id in sorted(pallet_ids)
    )
    return CellJobSubmission(
        job_id=job_id,
        workcell_id=workcell_id,
        instance_id=instance_id,
        recipe_digest=bundle.recipe_digest,
        cell_digest=bundle.cell_digest,
        process_artifact_digest=bundle.process_artifact_digest,
        job=dict(compiled.job),
        plan_bundle=bundle,
        ledger_markers=tuple(markers),
        resources=resources,
        operator_checkpoints=_operator_checkpoints(compiled, bundle),
    )
