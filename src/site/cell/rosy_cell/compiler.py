"""Recipe + cell config -> Job: ordered pick/place Steps in the robot base frame.

Rosy Cell submits the Job to Fleet as a Mission; Fleet dispatches the Steps to the device
(D-399 §5, D-336). The device plans, checks reachability and owns the final command; this
module never does.
"""

from __future__ import annotations

from dataclasses import dataclass

from .cell import CellConfig
from .geometry import Frame
from .recipe import Recipe
from .sequence import place_order
from .stack import StackPlan, build_stack, stack_issues


class CompileError(ValueError):
    def __init__(self, problems: list[str]) -> None:
        super().__init__("; ".join(problems))
        self.problems = tuple(problems)


@dataclass(frozen=True)
class Pose:
    x: float
    y: float
    z: float
    yaw: float


@dataclass(frozen=True)
class Step:
    kind: str  # "pick" | "place" | "pallet_done"
    item: str  # "box" | "slip_sheet" | "" for pallet_done
    pallet: str
    layer: int | None
    target: Pose | None
    approach_z: float | None


@dataclass(frozen=True)
class Job:
    recipe_hash: str
    cell_hash: str
    steps: tuple[Step, ...]


def _on_pallet(frame: Frame, x: float, y: float, z: float, yaw: float) -> Pose:
    bx, by, bz = frame.to_base((x, y, z))
    return Pose(bx, by, bz, frame.yaw_to_base(yaw))


def _transfer(src: Pose, dst: Pose, item: str, pallet: str, layer: int, clearance: float) -> list[Step]:
    return [
        Step("pick", item, pallet, layer, src, src.z + clearance),
        Step("place", item, pallet, layer, dst, dst.z + clearance),
    ]


def _check(recipe: Recipe, cell: CellConfig, tol_m: float) -> dict[str, StackPlan]:
    problems: list[str] = []
    needed = [recipe.pick_station] + ([recipe.slip_sheet_station] if recipe.slip_sheet_station else [])
    problems += [f"unknown station {s!r}" for s in needed if s not in cell.stations]
    plans: dict[str, StackPlan] = {}
    for slot in recipe.pallets:
        if slot.frame not in cell.frames:
            problems.append(f"pallet {slot.id}: unknown frame {slot.frame!r}")
        plan = build_stack(
            recipe.box,
            slot.pallet,
            recipe.layers,
            gap=recipe.gap,
            slip_sheet_thickness=recipe.slip_sheet_thickness or 0.0,
        )
        problems += [f"pallet {slot.id}: {msg}" for msg in stack_issues(plan, recipe.box, slot.pallet, tol_m=tol_m)]
        plans[slot.id] = plan
    if problems:
        raise CompileError(problems)
    return plans


def compile_job(recipe: Recipe, cell: CellConfig, *, tol_m: float) -> Job:
    plans = _check(recipe, cell, tol_m)
    clearance = cell.approach_clearance_m
    station = Pose(*cell.station_pose(recipe.pick_station))
    sheet_station = Pose(*cell.station_pose(recipe.slip_sheet_station)) if recipe.slip_sheet_station else None
    steps: list[Step] = []
    for slot in recipe.pallets:
        frame, plan = cell.frames[slot.frame], plans[slot.id]
        sheets = {s.below_layer: s for s in plan.slip_sheets}
        centre = (slot.pallet.length / 2, slot.pallet.width / 2)
        layer_ids = range(len(plan.layers))
        for n in layer_ids if recipe.mode == "palletize" else reversed(layer_ids):
            ordered = place_order(plan.layers[n], approach=recipe.approach)
            sheet = sheets.get(n)
            sheet_pose = _on_pallet(frame, *centre, sheet.z, 0.0) if sheet else None
            if recipe.mode == "palletize":
                if sheet_pose:
                    steps += _transfer(sheet_station, sheet_pose, "slip_sheet", slot.id, n, clearance)
                for b in ordered:
                    steps += _transfer(station, _on_pallet(frame, b.x, b.y, b.z_top, b.yaw), "box", slot.id, n, clearance)
            else:
                for b in reversed(ordered):
                    steps += _transfer(_on_pallet(frame, b.x, b.y, b.z_top, b.yaw), station, "box", slot.id, n, clearance)
                if sheet_pose:
                    steps += _transfer(sheet_pose, sheet_station, "slip_sheet", slot.id, n, clearance)
        steps.append(Step("pallet_done", "", slot.id, None, None, None))
    return Job(recipe.content_hash, cell.content_hash, tuple(steps))
