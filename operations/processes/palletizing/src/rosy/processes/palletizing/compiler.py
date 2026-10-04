"""Recipe + cell config -> Job: ordered pick/place Steps in the robot base frame.

Rosy Cell submits the Job to Fleet as a Mission; Fleet dispatches the Steps to the device
(D-399 §5, D-336). The device plans, checks reachability and owns the final command; this
module never does.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass

from .cell import CellConfig, Pose
from .geometry import Frame
from .recipe import Recipe
from .sequence import place_order
from .stack import StackPlan, build_stack, stack_issues


class CompileError(ValueError):
    def __init__(self, problems: list[str]) -> None:
        super().__init__("; ".join(problems))
        self.problems = tuple(problems)


@dataclass(frozen=True)
class Step:
    kind: str  # "pick" | "place" | "pallet_done"
    item: str  # "box" | "slip_sheet" | "" for pallet_done
    pallet: str
    layer: int | None
    target: Pose | None
    approach_z: float | None


@dataclass(frozen=True)
class OperatorSheetStep(Step):
    """A human operation in the canonical Job, never a robot motion instruction."""
    thickness_m: float


@dataclass(frozen=True)
class Job:
    recipe_hash: str
    cell_hash: str
    carry_z: float  # base-frame height every horizontal move is flown at
    steps: tuple[Step, ...]


def job_document(job: Job) -> dict:
    """The canonical JSON form of a Job. A Rosy Cell proposal and Fleet's recompilation both use
    it, so their comparison is byte-exact (D-403 §3)."""
    return {"recipe_hash": job.recipe_hash, "cell_hash": job.cell_hash, "carry_z": job.carry_z,
            "steps": [asdict(step) for step in job.steps]}


def _on_pallet(frame: Frame, x: float, y: float, z: float, yaw: float) -> Pose:
    bx, by, bz = frame.to_base((x, y, z))
    return Pose(bx, by, bz, frame.yaw_to_base(yaw))


def _transfer(src: Pose, dst: Pose, item: str, pallet: str, layer: int, clearance: float,
              depth: float = 0.0) -> list[Step]:
    """src/dst are the item's top face. The Step target is the TCP grasp height, depth below
    the top (C3b B1); approach_z clears the top face by the clearance."""
    def tcp(top: Pose) -> Pose:
        return Pose(top.x, top.y, top.z - depth, top.yaw)

    return [
        Step("pick", item, pallet, layer, tcp(src), src.z + clearance),
        Step("place", item, pallet, layer, tcp(dst), dst.z + clearance),
    ]


def _check(recipe: Recipe, cell: CellConfig, tol_m: float) -> dict[str, StackPlan]:
    problems: list[str] = []
    needed = [recipe.pick_station] + ([recipe.slip_sheet_station] if recipe.slip_sheet_station else [])
    problems += [f"unknown station {s!r}" for s in needed if s not in cell.stations]
    plans: dict[str, StackPlan] = {}
    for slot in recipe.pallets:
        if slot.frame not in cell.frames:
            problems.append(f"pallet {slot.id}: unknown frame {slot.frame!r}")
        else:
            # far-first order needs the robot outside the pallet; inside, "far" has no safe meaning
            rx, ry, _ = cell.frames[slot.frame].from_base((0.0, 0.0, 0.0))
            if 0 <= rx <= slot.pallet.length and 0 <= ry <= slot.pallet.width:
                problems.append(f"pallet {slot.id}: robot base lies inside the pallet footprint")
        plan = build_stack(
            recipe.box,
            slot.pallet,
            recipe.layers,
            gap=recipe.gap,
            slip_sheet_thickness=recipe.slip_sheet_thickness or 0.0,
        )
        problems += [f"pallet {slot.id}: {msg}" for msg in stack_issues(plan, recipe.box, slot.pallet, tol_m=tol_m)]
        plans[slot.id] = plan
    # The fingertips reach fingertip_overhang_m below the TCP; a grasp deeper than
    # height - overhang would put them below the box bottom, into the surface it lands on.
    if recipe.box.grasp_depth > recipe.box.height - cell.fingertip_overhang_m + 1e-12:
        problems.append(f"box grasp_depth {recipe.box.grasp_depth:.4f} puts the fingertips "
                        f"({cell.fingertip_overhang_m:.4f} below the TCP) below the box bottom")
    if problems:
        raise CompileError(problems)
    return plans


def carry_z(recipe: Recipe, cell: CellConfig, *, tol_m: float) -> float:
    """Highest surface over the whole Job + held-item hang below the TCP + approach clearance (D-402 §6).

    The hang is box height - grasp_depth (the TCP grasps grasp_depth below the box top, C3b
    B1), or a robot-handled slip-sheet thickness if larger (a sheet is taken at its top face).

    Surfaces: the top of every pallet's full stack (all four footprint corners, so a tilted frame is
    covered) and every station pose the recipe uses. Home is not an obstacle and is not included.
    Runs the same checks as compile_job, so it raises CompileError for an unusable recipe/cell pair.
    """
    return _carry_z(recipe, cell, _check(recipe, cell, tol_m))


def _carry_z(recipe: Recipe, cell: CellConfig, plans: dict[str, StackPlan]) -> float:
    tops: list[float] = []
    for slot in recipe.pallets:
        frame, plan = cell.frames[slot.frame], plans[slot.id]
        for x in (0.0, slot.pallet.length):
            for y in (0.0, slot.pallet.width):
                tops.append(frame.to_base((x, y, plan.height))[2])
    stations = [recipe.pick_station] + ([recipe.slip_sheet_station] if recipe.slip_sheet_station else [])
    tops += [cell.station_pose(s)[2] for s in stations]
    sheet_hang = (recipe.slip_sheet_thickness or 0.0) if recipe.slip_sheet_handling == "robot" else 0.0
    hang = max(recipe.box.height - recipe.box.grasp_depth, sheet_hang,
               cell.fingertip_overhang_m)
    return max(tops) + hang + cell.approach_clearance_m


def compile_job(recipe: Recipe, cell: CellConfig, *, tol_m: float) -> Job:
    plans = _check(recipe, cell, tol_m)
    clearance = cell.approach_clearance_m
    depth = recipe.box.grasp_depth
    station = Pose(*cell.station_pose(recipe.pick_station))
    sheet_station = Pose(*cell.station_pose(recipe.slip_sheet_station)) if recipe.slip_sheet_station else None
    steps: list[Step] = []
    # depalletize is the exact reverse: last pallet filled is emptied first; pallet_done follows each emptied pallet
    slots = recipe.pallets if recipe.mode == "palletize" else tuple(reversed(recipe.pallets))
    for slot in slots:
        frame, plan = cell.frames[slot.frame], plans[slot.id]
        sheets = {s.below_layer: s for s in plan.slip_sheets}
        centre = (slot.pallet.length / 2, slot.pallet.width / 2)
        layer_ids = range(len(plan.layers))
        for n in layer_ids if recipe.mode == "palletize" else reversed(layer_ids):
            ordered = place_order(plan.layers[n], frame)
            sheet = sheets.get(n)
            sheet_pose = _on_pallet(frame, *centre, sheet.z, 0.0) if sheet else None
            if recipe.mode == "palletize":
                if sheet_pose:
                    if recipe.slip_sheet_handling == "operator":
                        steps.append(OperatorSheetStep("operator_sheet", "slip_sheet", slot.id, n,
                                                       sheet_pose, None, recipe.slip_sheet_thickness))
                    else:
                        steps += _transfer(sheet_station, sheet_pose, "slip_sheet", slot.id, n, clearance)
                for b in ordered:
                    steps += _transfer(station, _on_pallet(frame, b.x, b.y, b.z_top, b.yaw), "box", slot.id, n,
                                       clearance, depth)
            else:
                for b in reversed(ordered):
                    steps += _transfer(_on_pallet(frame, b.x, b.y, b.z_top, b.yaw), station, "box", slot.id, n,
                                       clearance, depth)
                if sheet_pose:
                    steps += _transfer(sheet_pose, sheet_station, "slip_sheet", slot.id, n, clearance)
        steps.append(Step("pallet_done", "", slot.id, None, None, None))
    ceiling = _carry_z(recipe, cell, plans)
    # carry_z covers every surface a step touches, so a violation means a defect in the compiler itself
    problems = [
        f"{s.kind} {s.item} on pallet {s.pallet}: approach_z {s.approach_z:.3f} above carry_z {ceiling:.3f}"
        for s in steps
        if s.approach_z is not None and s.approach_z > ceiling
    ]
    if problems:
        raise CompileError(problems)
    return Job(recipe.content_hash, cell.content_hash, ceiling, tuple(steps))
