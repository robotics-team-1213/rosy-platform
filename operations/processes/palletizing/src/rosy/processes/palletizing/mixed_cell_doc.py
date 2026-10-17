"""cell.yaml for a multi-arm workcell (schema rosy_cell.cell/3) -> MixedCellDoc, with a content hash.

D-778 §1 puts the arms in cell.yaml (``cell_frame``, ``arms[{role, instance_id, base_in_cell}]``,
``zones``) but leaves the exact schema to G0. This is the smallest shape the recipe/3 compile
path needs; it is provisional and narrower than the D-778 sketch:

    schema: rosy_cell.cell/3
    cell_frame: cell
    arms:
      - role: left                      # D-779 §7 arm role
        instance_id: omx_01_control     # the arm's execution instance (D-281)
        workcell_id: omx_01             # the arm owner's own workcell (a Job-level claim, D-779)
        base_in_cell: {calibration_revision: r1, x: 0.0, y: 0.0, yaw: 0.0}
        zone_id: left_half
        home: {x: 0.12, y: 0.0, z: 0.12, yaw: 0.0}   # tool-down TCP home in THIS arm's base frame
    zones: [{zone_id: left_half, x_min: ..., y_min: ..., x_max: ..., y_max: ...}]
    pallet_frames: {pallet_a: {x: ..., y: ..., z: ...}}   # origin in the cell frame
    stations: {infeed_left: {x: ..., y: ..., z: ...}}     # top surface in the cell frame
    approach_clearance_m: 0.02
    reach: {model: annulus, r_min_m: 0.06, r_max_m: 0.23}
    finger: {thickness_m: ..., breadth_m: ..., opening_margin_m: ..., overhang_m: ...}  # optional

Narrower than D-778: ``base_in_cell`` is planar (x, y, yaw; the base sits at cell z 0) instead
of a transform matrix, zones are axis-aligned rectangles instead of polygons, pallet frames have
axes parallel to the cell frame, there are no ``fixtures``, and ``reach`` is the annulus stand-in
until the shared D-402 IK exists (D-781 §3 rule 4). A ``calibration_revision`` must be present
(D-778 §1: an arm without one is not assigned Steps).
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from . import SCHEMA_CELL_MIXED, fields
from .cell import CellError
from .fields import FieldError
from .mixed_cell import Reach, Workcell, WorkcellError, annulus_reach, workcell_from_dict
from .mixed_recipe import MixedRecipe
from .recipe import content_hash

_REQUIRED = ("schema", "cell_frame", "arms", "zones", "pallet_frames", "stations", "approach_clearance_m",
             "reach")
_OPTIONAL = ("finger",)
_ARM = ("role", "instance_id", "workcell_id", "base_in_cell", "zone_id", "home")
_BASE = ("calibration_revision", "x", "y", "yaw")
_XYZ = ("x", "y", "z")
_POSE = ("x", "y", "z", "yaw")
_ZONE = ("zone_id", "x_min", "y_min", "x_max", "y_max")
_REACH = ("model", "r_min_m", "r_max_m")
_FINGER = ("thickness_m", "breadth_m", "opening_margin_m", "overhang_m")


@dataclass(frozen=True)
class ArmSlot:
    """One arm of the cell: who runs it and where its tool goes home (base frame, m and rad)."""

    role: str
    instance_id: str
    workcell_id: str
    calibration_revision: str
    home: tuple[float, float, float, float]


@dataclass(frozen=True)
class MixedCellDoc:
    arms: tuple[ArmSlot, ...]
    content_hash: str
    _plain: dict  # the workcell_from_dict input without pallet origins (keyed by recipe pallet id later)
    pallet_frames: dict[str, tuple[float, float, float]]
    reach_m: tuple[float, float]

    def workcell(self, recipe: MixedRecipe) -> Workcell:
        """The planner's Workcell for this recipe: each recipe pallet takes its frame's origin."""
        missing = [f"pallet {s.id}: unknown frame {s.frame!r}" for s in recipe.pallets
                   if s.frame not in self.pallet_frames]
        if missing:
            raise CellError(missing)
        origins = {s.id: list(self.pallet_frames[s.frame]) for s in recipe.pallets}
        try:
            return workcell_from_dict({**self._plain, "pallet_origins": origins})
        except WorkcellError as exc:
            raise CellError([str(exc)]) from None

    def reach(self, workcell: Workcell) -> Reach:
        return annulus_reach(workcell, *self.reach_m)


def _numbers(raw: object, field: str, keys: tuple[str, ...]) -> tuple[float, ...]:
    d = fields.mapping(raw, field, keys)
    return tuple(fields.number(d[k], f"{field}.{k}") for k in keys)


def _identifier(value: object, field: str) -> str:
    s = fields.text(value, field)
    if not s or s != s.strip():
        raise FieldError(f"{field} must be non-empty without leading or trailing whitespace")
    return s


def _arm(raw: object, field: str) -> tuple[ArmSlot, dict]:
    d = fields.mapping(raw, field, _ARM)
    base = fields.mapping(d["base_in_cell"], f"{field}.base_in_cell", _BASE)
    x, y, yaw = (fields.number(base[k], f"{field}.base_in_cell.{k}") for k in _BASE[1:])
    slot = ArmSlot(_identifier(d["role"], f"{field}.role"), _identifier(d["instance_id"], f"{field}.instance_id"),
                   _identifier(d["workcell_id"], f"{field}.workcell_id"),
                   _identifier(base["calibration_revision"], f"{field}.base_in_cell.calibration_revision"),
                   _numbers(d["home"], f"{field}.home", _POSE))
    plain = {"role": slot.role, "base_in_cell": {"x": x, "y": y, "yaw": yaw},
             "zone_id": _identifier(d["zone_id"], f"{field}.zone_id")}
    return slot, plain


def _zone(raw: object, field: str) -> dict:
    d = fields.mapping(raw, field, _ZONE)
    return {"zone_id": _identifier(d["zone_id"], f"{field}.zone_id"),
            **{k: fields.number(d[k], f"{field}.{k}") for k in _ZONE[1:]}}


def _points(value: object, field: str) -> dict[str, tuple[float, ...]]:
    if not isinstance(value, dict) or not value:
        raise FieldError(f"{field} must be a non-empty mapping of name to {{x, y, z}}")
    return {_identifier(k, f"{field}: key {k!r}"): _numbers(v, f"{field}.{k}", _XYZ) for k, v in value.items()}


def load_mixed_cell(text: str) -> MixedCellDoc:
    """Parse and validate a rosy_cell.cell/3 document. Raises CellError with every problem found."""
    try:
        data = fields.parse(text, "cell config")
    except FieldError as exc:
        raise CellError([str(exc)]) from None
    problems = fields.key_problems(data, "cell", _REQUIRED, _OPTIONAL)

    def read(key: str, parse: Callable[[object, str], Any]) -> Any:
        if key not in data:
            return None
        try:
            return parse(data[key], key)
        except FieldError as exc:
            problems.append(str(exc))
            return None

    if "schema" in data and data["schema"] != SCHEMA_CELL_MIXED:
        problems.append(f"schema must be {SCHEMA_CELL_MIXED}")
    if "cell_frame" in data and data["cell_frame"] != "cell":
        problems.append("cell_frame must be cell")
    arms = read("arms", lambda v, f: [_arm(a, f"{f}[{i}]") for i, a in enumerate(fields.entries(v, f))])
    zones = read("zones", lambda v, f: [_zone(z, f"{f}[{i}]") for i, z in enumerate(fields.entries(v, f))])
    frames = read("pallet_frames", _points)
    stations = read("stations", _points)
    clearance = read("approach_clearance_m", fields.non_negative)
    reach = read("reach", lambda v, f: fields.mapping(v, f, _REACH))
    finger = read("finger", lambda v, f: dict(zip(_FINGER, _numbers(v, f, _FINGER))))
    if reach is not None:
        if reach["model"] != "annulus":
            problems.append("reach.model must be annulus (the shared D-402 IK is a follow-up)")
        try:
            reach_m = (fields.non_negative(reach["r_min_m"], "reach.r_min_m"),
                       fields.positive(reach["r_max_m"], "reach.r_max_m"))
            if reach_m[0] >= reach_m[1]:
                problems.append("reach.r_min_m must be below reach.r_max_m")
        except FieldError as exc:
            problems.append(str(exc))
    if arms is not None:
        for name in ("role", "instance_id", "workcell_id"):
            values = [getattr(slot, name) for slot, _ in arms]
            if len(set(values)) != len(values):
                problems.append(f"arm {name}s must be distinct")
    if problems:
        raise CellError(problems)
    plain = {"arms": [p for _, p in arms], "zones": zones, "stations": {k: list(v) for k, v in stations.items()},
             "approach_clearance_m": clearance, **({"finger": finger} if finger is not None else {})}
    try:  # checks arms, zones and zone ownership now; pallets come with the recipe
        workcell_from_dict({**plain, "pallet_origins": {}})
    except WorkcellError as exc:
        raise CellError([str(exc)]) from None
    return MixedCellDoc(tuple(slot for slot, _ in arms), content_hash(data), plain, frames, reach_m)


__all__ = ["ArmSlot", "MixedCellDoc", "load_mixed_cell"]
