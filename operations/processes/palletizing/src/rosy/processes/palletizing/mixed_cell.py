"""The workcell the mixed planner sees (D-778 §1-2, D-781 §3-4): arm bases, zones, fingers, reach.

Everything is in the `cell` frame (x, y in m on the table plane, z up, yaw in rad). A pallet's
frame is given by its origin in the cell frame with axes parallel to the cell axes. Reach is an
injected predicate so that the compiler can later call the shared D-402 IK; `annulus_reach` is a
simple stand-in for simulation and tests. This module does not import device code.
"""

from __future__ import annotations

import math
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from types import MappingProxyType

SHARED_BAND = "shared_band"

Rect = tuple[float, float, float, float]  # x_min, y_min, x_max, y_max
EPS = 1e-9


class WorkcellError(ValueError):
    pass


@dataclass(frozen=True)
class CellPose:
    """A TCP pose in the cell frame (x, y, z in m, yaw in rad)."""

    x: float
    y: float
    z: float
    yaw: float


@dataclass(frozen=True)
class ArmBase:
    role: str
    x: float
    y: float
    yaw: float
    zone_id: str | None = None  # the fixed zone this arm owns; None in a single-arm cell without zones


@dataclass(frozen=True)
class Zone:
    zone_id: str
    x_min: float
    y_min: float
    x_max: float
    y_max: float

    def contains(self, r: Rect) -> bool:
        return (r[0] >= self.x_min - EPS and r[1] >= self.y_min - EPS
                and r[2] <= self.x_max + EPS and r[3] <= self.y_max + EPS)

    def overlaps(self, other: Zone) -> bool:
        return (min(self.x_max, other.x_max) - max(self.x_min, other.x_min) > EPS
                and min(self.y_max, other.y_max) - max(self.y_min, other.y_min) > EPS)


@dataclass(frozen=True)
class Finger:
    """Gripper finger envelope (m). The fingers close on the two width faces of an item.

    Beside each width face the planner keeps `opening_margin_m + thickness_m` free, over a
    `breadth_m` strip centred on the item length, from `overhang_m` below the TCP up to the
    sky: the whole vertical approach path (D-781 §3 rule 3). Defaults follow the OMX sim notes in
    operations/processes/cell/examples/omx_sim/recipe.yaml (~10 mm fingers, 42 mm pads, tips
    2.57 mm past the TCP); a compiler passes the cell profile's values instead.
    """

    thickness_m: float = 0.010
    breadth_m: float = 0.042
    opening_margin_m: float = 0.004
    overhang_m: float = 0.003

    @property
    def reach_out_m(self) -> float:
        return self.opening_margin_m + self.thickness_m


Reach = Callable[[str, CellPose], bool]


@dataclass(frozen=True)
class Workcell:
    arms: tuple[ArmBase, ...]
    pallet_origins: Mapping[str, tuple[float, float, float]]
    stations: Mapping[str, tuple[float, float, float]]
    zones: tuple[Zone, ...] = ()
    finger: Finger = field(default_factory=Finger)
    approach_clearance_m: float = 0.02

    def __post_init__(self) -> None:
        object.__setattr__(self, "pallet_origins", MappingProxyType(dict(self.pallet_origins)))
        object.__setattr__(self, "stations", MappingProxyType(dict(self.stations)))
        problems = []
        roles = [a.role for a in self.arms]
        if not roles:
            problems.append("at least one arm is required")
        if len(set(roles)) != len(roles):
            problems.append("arm roles must be unique")
        ids = [z.zone_id for z in self.zones]
        if len(set(ids)) != len(ids):
            problems.append("zone ids must be unique")
        if len(self.arms) > 1 and not self.zones:
            problems.append("a cell with more than one arm needs zones")
        owned = [a.zone_id for a in self.arms if a.zone_id is not None]
        if len(set(owned)) != len(owned):
            problems.append("two arms own the same zone")
        problems += [f"arm {a.role} owns unknown zone {a.zone_id!r}" for a in self.arms
                     if a.zone_id is not None and a.zone_id not in ids]
        problems += [f"arm {a.role} cannot own {SHARED_BAND}" for a in self.arms if a.zone_id == SHARED_BAND]
        problems += [f"arm {a.role} needs a zone" for a in self.arms if self.zones and a.zone_id is None]
        # Zones are claims (D-779): two arms in different zones work at once, so zones must not overlap.
        problems += [f"zones {a.zone_id} and {b.zone_id} overlap" for i, a in enumerate(self.zones)
                     for b in self.zones[i + 1:] if a.overlaps(b)]
        if self.approach_clearance_m < 0:
            problems.append("approach_clearance_m must be non-negative")
        if problems:
            raise WorkcellError("; ".join(problems))

    def arm(self, role: str) -> ArmBase:
        return next(a for a in self.arms if a.role == role)

    def zone_of(self, envelope: Rect) -> Zone | None:
        """The one zone that holds the whole envelope, or None (straddling zones or outside them)."""
        return next((z for z in self.zones if z.contains(envelope)), None)


def annulus_reach(workcell: Workcell, r_min: float, r_max: float) -> Reach:
    """A reach model for simulation: the TCP xy lies in [r_min, r_max] of the arm base. Not IK."""
    if not 0 <= r_min < r_max:
        raise WorkcellError("annulus reach needs 0 <= r_min < r_max")
    bases = {a.role: (a.x, a.y) for a in workcell.arms}

    def reach(role: str, pose: CellPose) -> bool:
        bx, by = bases[role]
        return r_min - EPS <= math.hypot(pose.x - bx, pose.y - by) <= r_max + EPS

    return reach


def workcell_from_dict(data: Mapping) -> Workcell:
    """Build a Workcell from plain values, e.g. a parsed sim fixture.

    {arms: [{role, base_in_cell: {x, y, yaw}, zone_id}], zones: [{zone_id, x_min, y_min, x_max,
    y_max}], pallet_origins: {id: [x, y, z]}, stations: {name: [x, y, z]}, finger: {...},
    approach_clearance_m}
    """
    try:
        arms = tuple(ArmBase(a["role"], float(a["base_in_cell"]["x"]), float(a["base_in_cell"]["y"]),
                             float(a["base_in_cell"].get("yaw", 0.0)), a.get("zone_id"))
                     for a in data["arms"])
        zones = tuple(Zone(z["zone_id"], float(z["x_min"]), float(z["y_min"]), float(z["x_max"]),
                           float(z["y_max"])) for z in data.get("zones", ()))
        origins = {k: tuple(float(c) for c in v) for k, v in data["pallet_origins"].items()}
        stations = {k: tuple(float(c) for c in v) for k, v in data["stations"].items()}
        finger = Finger(**data["finger"]) if "finger" in data else Finger()
    except (KeyError, TypeError, ValueError) as exc:
        raise WorkcellError(f"workcell is malformed: {exc!r}") from None
    return Workcell(arms, origins, stations, zones, finger, float(data.get("approach_clearance_m", 0.02)))
