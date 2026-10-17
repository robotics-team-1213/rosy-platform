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

from .mixed_cell import CellPose, Reach, Workcell
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
    alternate_stations: tuple[str, ...] = ()  # pick station of each alternate, same order


def pick_pose(workcell: Workcell, station: str, height: float, grasp_depth: float, yaw: float) -> CellPose:
    """TCP at pick: the item stands on the station surface; the feeder presents it in the place yaw."""
    x, y, z = workcell.stations[station]
    return CellPose(x, y, z + height - grasp_depth, yaw)


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
    pick_cell: CellPose  # TCP at pick
    alternate_stations: tuple[str, ...] = ()  # pick station of each alternate, same order

    def to_dict(self) -> dict:
        p, q = self.pose_cell, self.pick_cell
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
            "pick_cell": {k: round(v, _DIGITS) for k, v in (("x", q.x), ("y", q.y), ("z", q.z), ("yaw", q.yaw))},
            "alternate_stations": dict(zip(self.alternates, self.alternate_stations)),
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


def descendants(deps: Sequence[tuple[int, ...]]) -> list[set[int]]:
    """For each Step, the Steps that wait for it directly or through others."""
    out: list[set[int]] = [set() for _ in deps]
    for j in range(len(deps) - 1, -1, -1):
        for d in deps[j]:
            out[d] |= {j} | out[j]
    return out


def carry_heights(order: Sequence[Placed], deps: Sequence[tuple[int, ...]], recipe: MixedRecipe,
                  workcell: Workcell, stations: Sequence[tuple[str, ...]]) -> list[float]:
    """Per Step: highest surface that may exist when it runs + the held item's hang below the TCP
    + the approach clearance (D-781 §3 rule 5).

    Two arms do not keep the reference order between independent Steps, so any Step that does
    not wait for this one (not a descendant) may already be placed. The surfaces are the pallets,
    those Steps' tops, and the pick stations this Step may use (its arm's and its alternates').
    """
    pallet_z = [workcell.pallet_origins[s.id][2] for s in recipe.pallets]
    after = descendants(deps)
    heights = []
    for j, p in enumerate(order):
        tops = pallet_z + [workcell.pallet_origins[q.pallet_id][2] + q.top for k, q in enumerate(order)
                           if k != j and k not in after[j]]
        tops += [workcell.stations[name][2] for name in stations[j]]
        hang = max(p.h - p.grasp_depth, workcell.finger.overhang_m)
        heights.append(max(tops) + hang + workcell.approach_clearance_m)
    return heights


def build_plan(recipe: MixedRecipe, workcell: Workcell, reach: Reach, order: Sequence[Placed],
               assignments: Sequence[Assignment], planner_version: str) -> MixedPlan:
    arms = [a.arm for a in assignments]
    deps = dependencies(order, arms, workcell)
    carry = carry_heights(order, deps, recipe, workcell,
                          [(a.station, *a.alternate_stations) for a in assignments])
    steps = []
    problems = []
    for j, (p, a) in enumerate(zip(order, assignments)):
        pick = pick_pose(workcell, a.station, p.h, p.grasp_depth, a.pose.yaw)
        for role, station in ((a.arm, a.station), *zip(a.alternates, a.alternate_stations)):
            src = pick_pose(workcell, station, p.h, p.grasp_depth, a.pose.yaw)
            high = (CellPose(src.x, src.y, carry[j], src.yaw), CellPose(a.pose.x, a.pose.y, carry[j], a.pose.yaw))
            if not all(reach(role, pose) for pose in (src, a.pose, *high)):
                problems.append(f"step {j}: arm {role} cannot reach its poses at carry_z {carry[j]:.3f}")
        steps.append(PlanStep(j, "place", p.sku, p.pallet_id, a.pose, a.arm, a.alternates, a.zone, "independent",
                              deps[j], carry[j], a.station, pick, a.alternate_stations))
    if problems:
        raise PlanError(problems)
    feed: dict[str, list[tuple[int, str]]] = {name: [] for name in recipe.pick_stations}
    for s in steps:
        feed[s.station].append((s.index, s.sku))
    return MixedPlan(recipe.content_hash, planner_version, tuple(steps),
                     MappingProxyType({k: tuple(v) for k, v in feed.items()}), tuple(order))
