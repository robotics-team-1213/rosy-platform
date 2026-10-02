"""Convert a compiled palletizing Job into transfer Skills and site ledger markers."""

from __future__ import annotations

from dataclasses import dataclass
import math

from rosy.execution.api import PlanBundle, PlanStep
from rosy.skills.api import SkillInvocation

from .cell import CellConfig, Pose
from .compiler import Job, compile_job
from .recipe import Recipe


@dataclass(frozen=True)
class PalletLedgerMarker:
    """A site-owned completion marker positioned after a count of transfer steps."""

    after_step_ordinal: int
    pallet_id: str

    def __post_init__(self) -> None:
        if (isinstance(self.after_step_ordinal, bool) or not isinstance(self.after_step_ordinal, int)
                or self.after_step_ordinal < 1):
            raise ValueError("after_step_ordinal must be a positive transfer count")
        if not isinstance(self.pallet_id, str) or not self.pallet_id or self.pallet_id != self.pallet_id.strip():
            raise ValueError("pallet_id must be a non-empty trimmed string")


@dataclass(frozen=True)
class PalletizingPlan:
    """The executable transfer plan plus non-executable, site-owned ledger markers."""

    bundle: PlanBundle
    ledger_markers: tuple[PalletLedgerMarker, ...]

    def __post_init__(self) -> None:
        if not isinstance(self.bundle, PlanBundle):
            raise ValueError("bundle must be a PlanBundle")
        if not isinstance(self.ledger_markers, tuple) or any(
            not isinstance(marker, PalletLedgerMarker) for marker in self.ledger_markers
        ):
            raise ValueError("ledger_markers must be a tuple of PalletLedgerMarker values")
        ordinals = tuple(marker.after_step_ordinal for marker in self.ledger_markers)
        if ordinals != tuple(sorted(set(ordinals))) or any(value > len(self.bundle.steps) for value in ordinals):
            raise ValueError("ledger markers must be ordered, unique and within the transfer plan")


def _pose(value: Pose | None, field: str) -> dict[str, float]:
    if value is None:
        raise ValueError(f"{field} pose is required for a transfer")
    result = {"x_m": value.x, "y_m": value.y, "z_m": value.z, "yaw_rad": value.yaw}
    for name, coordinate in result.items():
        if isinstance(coordinate, bool) or not isinstance(coordinate, (int, float)) or not math.isfinite(coordinate):
            raise ValueError(f"{field}.{name} must be a finite number")
    return result


def _height(value: float | None, field: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
        raise ValueError(f"{field} must be a finite number")
    return float(value)


def compile_plan_bundle(
    job: Job,
    recipe: Recipe,
    cell: CellConfig,
    *,
    process_artifact_digest: str,
    tol_m: float,
    verification_refs: tuple[str, ...] = (),
) -> PalletizingPlan:
    """Collapse each adjacent pick/place pair into one Skill without granting execution."""
    expected_job = compile_job(recipe, cell, tol_m=tol_m)
    if job != expected_job:
        raise ValueError("Job steps, carry_z and source hashes must match the current recipe/cell compilation")
    if not isinstance(job.steps, tuple) or not job.steps:
        raise ValueError("Job steps must be a non-empty tuple")
    carry_z = _height(job.carry_z, "Job carry_z")
    plan_steps: list[PlanStep] = []
    ledger_markers: list[PalletLedgerMarker] = []
    seen_markers: set[str] = set()
    transfer_pallets: set[str] = set()
    last_pallet: str | None = None
    index = 0

    while index < len(job.steps):
        current = job.steps[index]
        if current.kind == "pallet_done":
            if (current.item, current.layer, current.target, current.approach_z) != ("", None, None, None):
                raise ValueError("pallet_done must be a ledger marker without motion fields")
            if not plan_steps or current.pallet != last_pallet:
                raise ValueError("pallet_done must follow at least one transfer for the same pallet")
            if current.pallet in seen_markers:
                raise ValueError("each pallet may have only one pallet_done marker")
            ledger_markers.append(PalletLedgerMarker(len(plan_steps), current.pallet))
            seen_markers.add(current.pallet)
            index += 1
            continue

        if current.kind != "pick" or index + 1 >= len(job.steps):
            raise ValueError("Job motion steps must be adjacent pick/place transfer pairs")
        if not isinstance(current.pallet, str) or not current.pallet or current.pallet in seen_markers:
            raise ValueError("a transfer needs an unfinished pallet ledger entry")
        place = job.steps[index + 1]
        if place.kind != "place":
            raise ValueError("each pick must be followed by one place")
        if (current.item, current.pallet, current.layer) != (place.item, place.pallet, place.layer):
            raise ValueError("pick/place transfer identity must match item, pallet and layer")
        if current.item not in ("box", "slip_sheet"):
            raise ValueError("transfer item must be box or slip_sheet")
        if isinstance(current.layer, bool) or not isinstance(current.layer, int) or current.layer < 0:
            raise ValueError("transfer identity must include item, pallet and layer")
        source_pose = _pose(current.target, "pick target")
        destination_pose = _pose(place.target, "place target")
        source_approach = _height(current.approach_z, "pick approach_z")
        destination_approach = _height(place.approach_z, "place approach_z")
        if source_approach < source_pose["z_m"] or destination_approach < destination_pose["z_m"]:
            raise ValueError("approach_z must not be below its target pose")
        if max(source_approach, destination_approach) > carry_z:
            raise ValueError("Job carry_z must cover every transfer approach_z")

        invocation = SkillInvocation(
            "pallet.transfer",
            "1.0.0",
            {
                "item": current.item,
                "pallet_id": current.pallet,
                "layer_index": current.layer,
                "source_pose_base": source_pose,
                "destination_pose_base": destination_pose,
                "source_approach_z_base_m": source_approach,
                "destination_approach_z_base_m": destination_approach,
                "carry_z_base_m": carry_z,
            },
        )
        plan_steps.append(PlanStep(len(plan_steps), invocation))
        transfer_pallets.add(current.pallet)
        last_pallet = current.pallet
        index += 2

    if not ledger_markers or seen_markers != transfer_pallets:
        raise ValueError("every pallet with transfers must include one pallet_done ledger marker")
    bundle = PlanBundle.from_job(
        job,
        process_artifact_digest=process_artifact_digest,
        recipe_digest=recipe.content_hash,
        cell_digest=cell.content_hash,
        steps=tuple(plan_steps),
        verification_refs=verification_refs,
    )
    return PalletizingPlan(bundle, tuple(ledger_markers))
