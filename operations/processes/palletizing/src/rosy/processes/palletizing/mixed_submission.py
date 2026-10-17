"""recipe/3 plan -> multi-arm Cell Job parts (D-781 §5, D-779 §4): per-arm pallet.transfer inputs.

The plan (mixed_plan.py) is in the cell frame. Every Step gets compiled inputs for its primary
arm and for each alternate, each in THAT arm's base frame: translate by the base (x, y), rotate
by -base yaw, yaw = cell yaw - base yaw in (-pi, pi]. The base sits at cell z 0 in the planar
cell model (mixed_cell_doc.py), so z is unchanged. Each arm picks at its own station
(``alternate_stations`` for an alternate). Numbers are rounded to 9 digits like the plan.

The other inputs mirror the single-arm compiler (compiler.py ``_transfer``, plan_bundle.py):

- ``source_pose_base``/``destination_pose_base`` are the TCP, grasp_depth below the item top face.
- the approach heights clear the item top face by the cell's ``approach_clearance_m`` (TCP z +
  grasp_depth + clearance), capped at the Step's ``carry_z``. The single-arm carry_z covers every
  top face of the whole Job; the per-Step carry_z of D-781 §3 rule 5 covers the item's hang, not
  its own top face, so the cap keeps carry >= approach. The cap only lowers a point on the
  vertical line, never the horizontal move.
- ``home_pose_base`` is the arm's taught home from the cell document.
- ``item`` is ``box`` and ``sku`` is the Step's sku (D-781 §2): the CELL_TRANSFER body carries it,
  and the owner looks the grasp geometry up by ``box:<sku>`` in the accepted recipe. The plan
  (``plan.steps[].sku``) and these inputs agree by construction.
- ``layer_index`` is the support level: 0 on the pallet, else 1 + the highest level of the boxes
  it rests on. A mixed stack has no layers; this number only names the height band.

The Job document carries the planner version, the plan digest and this module's version, so a
change to any of them changes the Job id (D-781 §5 "planner version in the digest").
"""

from __future__ import annotations

import math
from collections.abc import Mapping
from dataclasses import dataclass

from .mixed_cell import ArmBase, CellPose, Workcell
from .mixed_cell_doc import MixedCellDoc
from .mixed_plan import MixedPlan, PlanStep, pick_pose
from .mixed_planner import plan_mixed
from .mixed_recipe import MixedRecipe
from .mixed_rules import supporters

SUBMISSION_VERSION = "rosy.palletizing.mixed_submission/2"  # /2: inputs carry sku
SKILL_ID, SKILL_VERSION = "pallet.transfer", "1.0.0"
ITEM = "box"
_DIGITS = 9

Home = tuple[float, float, float, float]  # x, y, z, yaw in the arm's base frame


def _round(value: float) -> float:
    return round(value, _DIGITS) + 0.0  # + 0.0 turns -0.0 into 0.0


def yaw_in_base(cell_yaw: float, base_yaw: float) -> float:
    """cell yaw - base yaw, normalised to (-pi, pi]."""
    yaw = math.remainder(cell_yaw - base_yaw, math.tau)
    return yaw + math.tau if yaw <= -math.pi else yaw


def pose_in_base(base: ArmBase, pose: CellPose) -> dict[str, float]:
    """A cell-frame TCP pose in the arm's base frame, as pallet.transfer pose fields."""
    dx, dy = pose.x - base.x, pose.y - base.y
    c, s = math.cos(base.yaw), math.sin(base.yaw)
    return {"x_m": _round(c * dx + s * dy), "y_m": _round(-s * dx + c * dy), "z_m": _round(pose.z),
            "yaw_rad": _round(yaw_in_base(pose.yaw, base.yaw))}


def support_levels(plan: MixedPlan) -> list[int]:
    levels: list[int] = []
    for j, p in enumerate(plan.placements):
        below = supporters(p, [q for q in plan.placements[:j] if q.pallet_id == p.pallet_id])
        levels.append(1 + max(levels[q.index] for q, _ in below) if below else 0)
    return levels


def transfer_inputs(step: PlanStep, role: str, station: str, *, recipe: MixedRecipe, workcell: Workcell,
                    home: Home, layer_index: int) -> dict:
    """pallet.transfer/1.0.0 inputs of one Step for one arm, in that arm's base frame."""
    item = next(i for i in recipe.items if i.sku == step.sku)
    base = workcell.arm(role)
    pick = pick_pose(workcell, station, item.height, item.grasp_depth, step.pose_cell.yaw)
    lift = item.grasp_depth + workcell.approach_clearance_m
    hx, hy, hz, hyaw = home
    return {
        "item": ITEM,
        "sku": step.sku,
        "pallet_id": step.pallet_id,
        "layer_index": layer_index,
        "home_pose_base": {"x_m": hx, "y_m": hy, "z_m": hz, "yaw_rad": hyaw},
        "source_pose_base": pose_in_base(base, pick),
        "destination_pose_base": pose_in_base(base, step.pose_cell),
        "source_approach_z_base_m": _round(min(pick.z + lift, step.carry_z)),
        "destination_approach_z_base_m": _round(min(step.pose_cell.z + lift, step.carry_z)),
        "carry_z_base_m": _round(step.carry_z),
    }


def step_placements(recipe: MixedRecipe, workcell: Workcell, plan: MixedPlan,
                    homes: Mapping[str, Home]) -> list[dict]:
    """Every Step as a multi-arm Cell Job step: {skill_id, version, placement} (D-779 §4)."""
    levels = support_levels(plan)
    out = []
    for step in plan.steps:
        roles = ((step.arm, step.station), *zip(step.alternates, step.alternate_stations))
        actions = {role: transfer_inputs(step, role, station, recipe=recipe, workcell=workcell, home=homes[role],
                                         layer_index=levels[step.index]) for role, station in roles}
        out.append({"skill_id": SKILL_ID, "version": SKILL_VERSION, "placement": {
            "arm": step.arm, "alternates": list(step.alternates), "zone": step.zone, "coupling": step.coupling,
            "depends_on": list(step.depends_on), "actions": actions}})
    return out


def ledger_markers(plan: MixedPlan) -> list[dict]:
    """One marker per pallet, after the transfer count that includes its last Step."""
    last: dict[str, int] = {}
    for step in plan.steps:
        last[step.pallet_id] = step.index + 1
    return [{"after_step_ordinal": n, "pallet_id": p} for p, n in sorted(last.items(), key=lambda kv: kv[1])]


def job_document(recipe: MixedRecipe, cell: MixedCellDoc, plan: MixedPlan) -> dict:
    """The canonical recipe/3 Job: Rosy Cell's proposal and Fleet's recompilation compare it byte for byte."""
    return {"recipe_hash": recipe.content_hash, "cell_hash": cell.content_hash,
            "planner_version": plan.planner_version, "plan_digest": plan.digest,
            "submission_version": SUBMISSION_VERSION, "plan": plan.to_dict()}


@dataclass(frozen=True)
class MixedCellJob:
    job: dict
    arms: tuple[dict, ...]  # {role, instance_id, workcell_id} in cell order
    steps: tuple[dict, ...]
    ledger_markers: tuple[dict, ...]
    pallet_ids: tuple[str, ...]
    recipe_digest: str
    cell_digest: str


def compile_mixed_cell_job(recipe: MixedRecipe, cell: MixedCellDoc) -> MixedCellJob:
    """Plan the recipe in the cell and compile every Step for its arms. Raises PlanError/CellError."""
    workcell = cell.workcell(recipe)
    plan = plan_mixed(recipe, workcell, cell.reach(workcell))
    homes = {slot.role: tuple(_round(v) for v in slot.home) for slot in cell.arms}
    steps = step_placements(recipe, workcell, plan, homes)
    return MixedCellJob(
        job=job_document(recipe, cell, plan),
        arms=tuple({"role": s.role, "instance_id": s.instance_id, "workcell_id": s.workcell_id} for s in cell.arms),
        steps=tuple(steps), ledger_markers=tuple(ledger_markers(plan)),
        pallet_ids=tuple(sorted({s.pallet_id for s in plan.steps})),
        recipe_digest=recipe.content_hash, cell_digest=cell.content_hash)


__all__ = ["ITEM", "SUBMISSION_VERSION", "MixedCellJob", "compile_mixed_cell_job", "job_document", "ledger_markers",
           "pose_in_base", "step_placements", "support_levels", "transfer_inputs", "yaw_in_base"]
