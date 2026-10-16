"""Mixed plan output: Steps with arm, zone and the order they must keep (D-781 §4-5).

The greedy placement order is the reference order. A Step depends only on
- the boxes it rests on (support),
- earlier boxes whose lowering or finger volume it would sit in (finger clearance / approach),
- the previous Step of the same arm (one arm does its Steps in reference order).
Every dependency points to an earlier index, so the graph is acyclic by construction. Steps in
different zones with none of these relations can run on two arms at once.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from types import MappingProxyType

from .mixed_cell import CellPose, Workcell
from .mixed_recipe import MixedRecipe
from .mixed_rules import Placed, in_approach, supporters
from .recipe import content_hash

_DIGITS = 9


class PlanError(ValueError):
    def __init__(self, problems: list[str]) -> None:
        super().__init__("; ".join(problems))
        self.problems = tuple(problems)


@dataclass(frozen=True)
class Assignment:
    arm: str
    alternates: tuple[str, ...]
    zone: str | None
    station: str
    pose: CellPose
    arm_distance: float


@dataclass(frozen=True)
class PlanStep:
    index: int
    role: str  # "place" in the first version
    sku: str
    pallet_id: str
    pose_cell: CellPose  # TCP at release: item centre, grasp_depth below its top face
    arm: str
    alternates: tuple[str, ...]
    zone: str | None
    coupling: str  # "independent" until coordinated Steps exist (D-780)
    depends_on: tuple[int, ...]
    carry_z: float  # cell-frame height of the horizontal move for this Step (D-402 §6)
    station: str  # where the item is picked

    def to_dict(self) -> dict:
        p = self.pose_cell
        return {
            "index": self.index,
            "role": self.role,
            "sku": self.sku,
            "pallet_id": self.pallet_id,
            "pose_cell": {k: round(v, _DIGITS) for k, v in (("x", p.x), ("y", p.y), ("z", p.z), ("yaw", p.yaw))},
            "arm": self.arm,
            "alternates": list(self.alternates),
            "zone": self.zone,
            "coupling": self.coupling,
            "depends_on": list(self.depends_on),
            "carry_z": round(self.carry_z, _DIGITS),
            "station": self.station,
        }


@dataclass(frozen=True)
class MixedPlan:
    recipe_hash: str
    planner_version: str
    steps: tuple[PlanStep, ...]
    feed_order: Mapping[str, tuple[tuple[int, str], ...]]  # station -> (step index, sku) in pick order
    placements: tuple[Placed, ...]  # pallet-frame boxes, same order as steps

    def to_dict(self) -> dict:
        return {
            "recipe_hash": self.recipe_hash,
            "planner_version": self.planner_version,
            "steps": [s.to_dict() for s in self.steps],
            "feed_order": {k: [list(e) for e in v] for k, v in sorted(self.feed_order.items())},
        }

    @property
    def digest(self) -> str:
        return content_hash(self.to_dict())


def dependencies(order: Sequence[Placed], arms: Sequence[str], workcell: Workcell) -> list[tuple[int, ...]]:
    finger = workcell.finger
    out: list[tuple[int, ...]] = []
    last_of_arm: dict[str, int] = {}
    for j, p in enumerate(order):
        earlier = [q for q in order[:j] if q.pallet_id == p.pallet_id]
        deps = {q.index for q, _ in supporters(p, earlier)}
        deps |= {q.index for q in earlier if in_approach(q, p, finger)}
        blocked = [q.index for q in earlier if in_approach(p, q, finger)]
        if blocked:  # the planner never lowers an item through a box already there
            raise PlanError([f"step {j} ({p.sku}) is lowered through earlier steps {blocked}"])
        if arms[j] in last_of_arm:
            deps.add(last_of_arm[arms[j]])
        last_of_arm[arms[j]] = j
        out.append(tuple(sorted(deps)))
    return out


def carry_heights(order: Sequence[Placed], recipe: MixedRecipe, workcell: Workcell,
                  stations: Sequence[str]) -> list[float]:
    """Per Step: highest surface so far (pallet tops, boxes already placed, its pick station)
    + the held item's hang below the TCP + the approach clearance (D-781 §3 rule 5)."""
    pallet_z = [workcell.pallet_origins[s.id][2] for s in recipe.pallets]
    heights = []
    for j, p in enumerate(order):
        tops = pallet_z + [workcell.pallet_origins[q.pallet_id][2] + q.top for q in order[:j]]
        tops.append(workcell.stations[stations[j]][2])
        hang = max(p.h - p.grasp_depth, workcell.finger.overhang_m)
        heights.append(max(tops) + hang + workcell.approach_clearance_m)
    return heights


def build_plan(recipe: MixedRecipe, workcell: Workcell, order: Sequence[Placed],
               assignments: Sequence[Assignment], planner_version: str) -> MixedPlan:
    arms = [a.arm for a in assignments]
    deps = dependencies(order, arms, workcell)
    carry = carry_heights(order, recipe, workcell, [a.station for a in assignments])
    steps = tuple(
        PlanStep(j, "place", p.sku, p.pallet_id, a.pose, a.arm, a.alternates, a.zone, "independent",
                 deps[j], carry[j], a.station)
        for j, (p, a) in enumerate(zip(order, assignments))
    )
    feed: dict[str, list[tuple[int, str]]] = {name: [] for name in recipe.pick_stations}
    for s in steps:
        feed[s.station].append((s.index, s.sku))
    return MixedPlan(recipe.content_hash, planner_version, steps,
                     MappingProxyType({k: tuple(v) for k, v in feed.items()}), tuple(order))
