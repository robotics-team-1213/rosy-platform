"""Deterministic greedy placement for recipe/3 (D-781 §3).

Items are expanded by quantity and placed one at a time, largest base first. For each item the
planner lists candidate corners per pallet ("extreme points": the walls, the edges of every box
already placed offset by `gap`, and the zone edges), tries yaw 0 and 90 where the item allows it,
drops the item to its resting height and keeps the candidate that passes every rule with the
lowest score key:

    (pallet order, bottom height, x + y - CONTACT_BONUS_M * side contact, -distance from arm base)

Lowest, then deepest/closest to the pallet origin corner, with a bonus for touching walls and
neighbours; ties go to the spot far from the assigned arm's base (the old far-first rule, now per
arm). No randomness is used. Step assembly and ordering live in mixed_plan.py.
"""

from __future__ import annotations

import math
from collections.abc import Sequence

from .mixed_cell import EPS, SHARED_BAND, CellPose, Reach, Rect, Workcell
from .mixed_plan import Assignment, MixedPlan, PlanError, build_plan, pick_pose
from .mixed_recipe import Item, MixedRecipe
from .mixed_rules import (
    Placed,
    envelope,
    finger_low_z,
    finger_rects,
    gap_conflict,
    load_problems,
    overlap_area,
    rest_z,
    support_ok,
    support_ratio_and_corners,
)
from .recipe import PalletSlot

PLANNER_VERSION = "rosy.palletizing.mixed_greedy_ep/1"
CONTACT_BONUS_M = 0.005
_ROUND = 9


def _units(items: Sequence[Item]) -> list[Item]:
    units = [item for item in items for _ in range(item.quantity)]
    return sorted(units, key=lambda i: (-round(i.length * i.width, _ROUND), -i.height, -i.mass_kg, i.sku))


def _dims(item: Item, yaw: int) -> tuple[float, float]:
    # yaw 0: length along pallet x, width (the grasped faces) along y; yaw 90 swaps them.
    return (item.length, item.width) if yaw == 0 else (item.width, item.length)


class _Search:
    def __init__(self, recipe: MixedRecipe, cell: Workcell, reach: Reach) -> None:
        self.recipe, self.cell, self.reach = recipe, cell, reach
        self.placed: dict[str, list[Placed]] = {slot.id: [] for slot in recipe.pallets}
        self.order: list[Placed] = []
        self.assignments: list[Assignment] = []
        self.arm_counts = {a.role: 0 for a in cell.arms}
        # The highest the travel height can get for any Step: every pallet full to its limit and
        # every station. The real per-Step carry_z (mixed_plan.carry_heights) is never above this
        # bound plus the item hang, so the search checks reach at the bound and build_plan checks
        # it again at the real height.
        self.surface_bound = max([cell.pallet_origins[s.id][2] + s.pallet.max_stack_height for s in recipe.pallets]
                                 + [z for _, _, z in cell.stations.values()])

    def _station(self, role: str, p: Placed, place: CellPose) -> str | None:
        """Nearest pick station from which this arm can do the whole transfer of p.

        Checked poses: pick (station top surface + item height - grasp_depth, the placement yaw;
        the feeder presents the item in that yaw), both poses raised to the carry height bound,
        and the release pose. None if the arm cannot do it from any station.
        """
        if not self.reach(role, place):
            return None
        arm = self.cell.arm(role)
        carry = self.surface_bound + max(p.h - p.grasp_depth, self.cell.finger.overhang_m)             + self.cell.approach_clearance_m
        if not self.reach(role, CellPose(place.x, place.y, carry, place.yaw)):
            return None
        usable = []
        for n, name in enumerate(self.recipe.pick_stations):
            x, y, z = self.cell.stations[name]
            pick = pick_pose(self.cell, name, p.h, p.grasp_depth, place.yaw)
            if self.reach(role, pick) and self.reach(role, CellPose(x, y, carry, place.yaw)):
                usable.append((round(math.hypot(x - arm.x, y - arm.y), _ROUND), n, name))
        return min(usable)[2] if usable else None

    def assign(self, p: Placed) -> Assignment | None:
        ox, oy, oz = self.cell.pallet_origins[p.pallet_id]
        cx, cy = p.centre
        pose = CellPose(ox + cx, oy + cy, oz + p.top - p.grasp_depth, math.radians(p.yaw_deg))
        arms = self.cell.arms
        stations = {a.role: self._station(a.role, p, pose) for a in arms}
        alternates: tuple[str, ...] = ()
        if self.cell.zones:
            e = envelope(p, self.cell.finger)
            zone = self.cell.zone_of((e[0] + ox, e[1] + oy, e[2] + ox, e[3] + oy))
            if zone is None:
                return None
            if zone.zone_id == SHARED_BAND:
                able = [(self.arm_counts[a.role], n, a) for n, a in enumerate(arms) if stations[a.role]]
                if not able:
                    return None
                primary = min(able, key=lambda t: t[:2])[2]
                # Only shared-band Steps carry alternates (D-781 §4): a fixed zone belongs to its arm.
                alternates = tuple(a.role for a in arms if a.role != primary.role and stations[a.role])
            else:
                primary = next((a for a in arms if a.zone_id == zone.zone_id), None)
                if primary is None or not stations[primary.role]:
                    return None
            zone_id: str | None = zone.zone_id
        else:
            primary, zone_id = arms[0], arms[0].zone_id
            if not stations[primary.role]:
                return None
        distance = math.hypot(pose.x - primary.x, pose.y - primary.y)
        return Assignment(primary.role, alternates, zone_id, stations[primary.role], pose, distance,
                          tuple(stations[r] for r in alternates))

    def _coords(self, slot: PalletSlot, size: float, along_x: bool) -> list[float]:
        limit = (slot.pallet.length if along_x else slot.pallet.width) - size
        gap, out = self.recipe.gap, self.cell.finger.reach_out_m
        values = {0.0, limit}
        for q in self.placed[slot.id]:
            lo, ext = (q.x, q.lx) if along_x else (q.y, q.ly)
            values |= {lo, lo + ext + gap, lo + ext - size, lo - gap - size}
            values |= {lo - out - size, lo + ext + out}
        origin = self.cell.pallet_origins[slot.id][0 if along_x else 1]
        for z in self.cell.zones:
            for edge in ((z.x_min, z.x_max) if along_x else (z.y_min, z.y_max)):
                e = edge - origin
                values |= {e, e - size, e + out, e - out - size}
        return sorted({round(v, _ROUND) for v in values if -EPS <= v <= limit + EPS})

    def _contact(self, p: Placed, slot: PalletSlot, others: Sequence[Placed]) -> float:
        """Share of the side faces touching a pallet edge or a neighbour standing `gap` away."""
        x0, y0, x1, y1 = p.footprint
        length, width, gap = slot.pallet.length, slot.pallet.width, self.recipe.gap
        touch = (p.ly * ((x0 <= EPS) + (x1 >= length - EPS)) + p.lx * ((y0 <= EPS) + (y1 >= width - EPS))) * p.h
        for q in others:
            dz = min(p.top, q.top) - max(p.z, q.z)
            if dz <= EPS:
                continue
            qx0, qy0, qx1, qy1 = q.footprint
            span_y = min(y1, qy1) - max(y0, qy0)
            span_x = min(x1, qx1) - max(x0, qx0)
            if span_y > EPS and (abs(qx0 - x1 - gap) <= 1e-7 or abs(x0 - qx1 - gap) <= 1e-7):
                touch += span_y * dz
            if span_x > EPS and (abs(qy0 - y1 - gap) <= 1e-7 or abs(y0 - qy1 - gap) <= 1e-7):
                touch += span_x * dz
        return min(1.0, touch / (2 * (p.lx + p.ly) * p.h))

    def _try(self, item: Item, slot: PalletSlot, rank: int, yaw: int, x: float, y: float,
             mass_on_pallet: float, best: tuple | None) -> tuple | None:
        others = self.placed[slot.id]
        lx, ly = _dims(item, yaw)
        fp: Rect = (x, y, x + lx, y + ly)
        z = rest_z(fp, others)
        if z + item.height > slot.pallet.max_stack_height + EPS:
            return None
        if best is not None and (rank, round(z, 6)) > best[0][:2]:
            return None
        if mass_on_pallet + item.mass_kg > slot.pallet.max_load_kg + 1e-12:
            return None
        p = Placed(len(self.order), item.sku, slot.id, x, y, z, lx, ly, item.height, yaw, item.mass_kg,
                   item.max_load_on_top_kg, item.grasp_depth)
        if gap_conflict(p, others, self.recipe.gap) or not support_ok(*support_ratio_and_corners(p, others)):
            return None
        low = finger_low_z(p, self.cell.finger)
        strips = finger_rects(p, self.cell.finger)
        if any(q.top > low + EPS and overlap_area(r, q.footprint) > 0 for q in others for r in strips):
            return None
        a = self.assign(p)
        if a is None or load_problems([*others, p]):
            return None
        score = round(x + y - CONTACT_BONUS_M * self._contact(p, slot, others), 6)
        return ((rank, round(z, 6), score, -round(a.arm_distance, 6), yaw, x, y), p, a)

    def place(self, item: Item) -> bool:
        best = None
        for rank, slot in enumerate(self.recipe.pallets):
            mass = sum(q.mass_kg for q in self.placed[slot.id])
            for yaw in item.yaws_deg(self.recipe.planner.yaw_deg):
                lx, ly = _dims(item, yaw)
                if lx > slot.pallet.length + EPS or ly > slot.pallet.width + EPS:
                    continue
                for x in self._coords(slot, lx, True):
                    for y in self._coords(slot, ly, False):
                        found = self._try(item, slot, rank, yaw, x, y, mass, best)
                        if found is not None and (best is None or found[0] < best[0]):
                            best = found
        if best is None:
            return False
        _, p, a = best
        self.placed[p.pallet_id].append(p)
        self.order.append(p)
        self.assignments.append(a)
        self.arm_counts[a.arm] += 1
        return True


def _input_problems(recipe: MixedRecipe, cell: Workcell) -> list[str]:
    problems = [f"pallet {s.id} has no origin in the workcell" for s in recipe.pallets
                if s.id not in cell.pallet_origins]
    problems += [f"pick station {n} is not a workcell station" for n in recipe.pick_stations
                 if n not in cell.stations]
    problems += [f"item {i.sku}: grasp_depth {i.grasp_depth:.4f} + fingertip overhang "
                 f"{cell.finger.overhang_m:.4f} reaches below the item bottom" for i in recipe.items
                 if i.grasp_depth + cell.finger.overhang_m > i.height + EPS]
    return problems


def plan_mixed(recipe: MixedRecipe, cell: Workcell, reach: Reach) -> MixedPlan:
    """Plan every item of a recipe/3 into the workcell. Raises PlanError if any item cannot be placed."""
    problems = _input_problems(recipe, cell)
    if problems:
        raise PlanError(problems)
    search = _Search(recipe, cell, reach)
    # The real pick TCP (station top + item height - grasp_depth), not the station surface: an IK
    # reach refuses z = 0, which sits below the arm's floor.
    if not any(search.reach(a.role, pick_pose(cell, n, i.height, i.grasp_depth, 0.0)) for a in cell.arms
               for n in recipe.pick_stations for i in recipe.items):
        raise PlanError(["no arm reaches any pick station"])
    unplaced = [item.sku for item in _units(recipe.items) if not search.place(item)]
    if unplaced:
        raise PlanError([f"no placement satisfies the rules for {sku}" for sku in unplaced])
    return build_plan(recipe, cell, reach, search.order, search.assignments, PLANNER_VERSION)
