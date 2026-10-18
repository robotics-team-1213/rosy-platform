"""recipe.yaml (schema rosy_cell.recipe/3, D-781 §1) -> MixedRecipe, with a content hash.

recipe/3 lists items (sku, size, mass, quantity, orientation) instead of one box and layer
patterns. The planner (mixed_planner.py) decides where and in which order each item goes.
recipe/1 and /2 are untouched: they keep their own loader in recipe.py.
"""

from __future__ import annotations

import re
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from . import SCHEMA_RECIPE_MIXED, fields
from .fields import FieldError
from .load import Box
from .recipe import PalletSlot, RecipeError, _pallets, content_hash

_REQUIRED = ("schema", "name", "mode", "items", "pallets", "pick_stations", "gap", "stability", "planner")
# Keys recipe/1 and /2 accept that recipe/3 refuses by name (D-781 §1 "받지 않는 것").
_REFUSED = {
    "layers": "layers is not accepted by recipe/3: the planner places items, there are no layer patterns",
    "slip_sheet": "slip_sheet is not accepted by recipe/3",
    "box": "box is not accepted by recipe/3: list the items under items",
    "pick_station": "pick_station is not accepted by recipe/3: use the pick_stations list",
}
_ITEM = ("sku", "length", "width", "height", "mass_kg", "quantity", "orientation", "max_load_on_top_kg")
_ITEM_OPTIONAL = ("grasp_depth",)
ORIENTATIONS = ("yaw_only", "upright_fixed")
# The sku travels in the CELL_TRANSFER grant (D-781 §2), so it is a trimmed identifier like there.
_SKU = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.:-]{0,95}$")
STABILITY_RULES = ("support_ratio_v1",)
CANDIDATE_METHODS = ("extreme_points",)
YAWS_DEG = (0, 90)


@dataclass(frozen=True)
class GripRange:
    """Accepted gripper opening (m) for the grasped width. The cell profile allows 10-50 mm today."""

    min_m: float = 0.010
    max_m: float = 0.050


DEFAULT_GRIP_RANGE = GripRange()


@dataclass(frozen=True)
class Item:
    """One sku. The gripper squeezes the two faces `width` apart; `length` runs along the fingers."""

    sku: str
    length: float
    width: float
    height: float
    mass_kg: float
    grasp_depth: float
    quantity: int
    orientation: str
    max_load_on_top_kg: float

    def yaws_deg(self, allowed: tuple[int, ...]) -> tuple[int, ...]:
        # upright_fixed keeps the taught yaw 0; yaw_only may use every yaw the planner allows.
        return tuple(y for y in allowed if y == 0) if self.orientation == "upright_fixed" else allowed


@dataclass(frozen=True)
class Stability:
    rule: str
    max_height_to_base_ratio: float


@dataclass(frozen=True)
class PlannerSpec:
    candidates: str
    yaw_deg: tuple[int, ...]
    allow_push: bool


@dataclass(frozen=True)
class MixedRecipe:
    name: str
    mode: str
    items: tuple[Item, ...]
    pallets: tuple[PalletSlot, ...]
    pick_stations: tuple[str, ...]
    gap: float
    stability: Stability
    planner: PlannerSpec
    content_hash: str


def _quantity(value: object, field: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        raise FieldError(f"{field} must be a positive integer, got {value!r}")
    return value


def _item(raw: object, f: str, grip: GripRange, ratio: float | None) -> Item:
    d = fields.mapping(raw, f, _ITEM, _ITEM_OPTIONAL)
    sizes = [fields.number(d[k], f"{f}.{k}") for k in ("length", "width", "height", "mass_kg")]
    depth = fields.non_negative(d["grasp_depth"], f"{f}.grasp_depth") if "grasp_depth" in d else 0.0
    try:
        box = Box(*sizes, grasp_depth=depth)
    except ValueError as exc:
        raise FieldError(f"{f}: {exc}") from None
    orientation = fields.text(d["orientation"], f"{f}.orientation")
    if orientation not in ORIENTATIONS:
        raise FieldError(f"{f}.orientation must be one of {ORIENTATIONS}, got {orientation!r}")
    if not grip.min_m <= box.width <= grip.max_m:
        raise FieldError(f"{f}.width {box.width:.4f} m (the grasped width) is outside the gripper range "
                         f"{grip.min_m:.3f}-{grip.max_m:.3f} m")
    if ratio is not None and box.height > ratio * min(box.length, box.width) + 1e-12:
        raise FieldError(f"{f}.height {box.height:.4f} m exceeds max_height_to_base_ratio {ratio} "
                         f"times the short base side {min(box.length, box.width):.4f} m")
    sku = fields.text(d["sku"], f"{f}.sku")
    if not _SKU.fullmatch(sku):
        raise FieldError(f"{f}.sku must be 1-96 letters, digits, '_', '.', ':' or '-', got {sku!r}")
    return Item(
        sku=sku,
        length=box.length,
        width=box.width,
        height=box.height,
        mass_kg=box.mass_kg,
        grasp_depth=box.grasp_depth,
        quantity=_quantity(d["quantity"], f"{f}.quantity"),
        orientation=orientation,
        max_load_on_top_kg=fields.non_negative(d["max_load_on_top_kg"], f"{f}.max_load_on_top_kg"),
    )


def _stability(value: object, field: str) -> Stability:
    d = fields.mapping(value, field, ("rule", "max_height_to_base_ratio"))
    rule = fields.text(d["rule"], f"{field}.rule")
    if rule not in STABILITY_RULES:
        raise FieldError(f"{field}.rule must be one of {STABILITY_RULES}, got {rule!r}")
    return Stability(rule, fields.positive(d["max_height_to_base_ratio"], f"{field}.max_height_to_base_ratio"))


def _planner(value: object, field: str) -> PlannerSpec:
    d = fields.mapping(value, field, ("candidates", "yaw_deg", "allow_push"))
    method = fields.text(d["candidates"], f"{field}.candidates")
    if method not in CANDIDATE_METHODS:
        raise FieldError(f"{field}.candidates must be one of {CANDIDATE_METHODS}, got {method!r}")
    yaws = fields.entries(d["yaw_deg"], f"{field}.yaw_deg")
    if not yaws or any(isinstance(y, bool) or y not in YAWS_DEG for y in yaws) or len(set(yaws)) != len(yaws):
        raise FieldError(f"{field}.yaw_deg must be a non-empty list of distinct values from {list(YAWS_DEG)}")
    if fields.flag(d["allow_push"], f"{field}.allow_push"):
        raise FieldError(f"{field}.allow_push must be false until CELL_PUSH exists (D-778 §9)")
    return PlannerSpec(method, tuple(sorted(int(y) for y in yaws)), False)


def _stations(value: object, field: str) -> tuple[str, ...]:
    names = tuple(fields.text(v, f"{field}[{i}]") for i, v in enumerate(fields.entries(value, field)))
    if not names:
        raise FieldError(f"{field} needs at least one station")
    if len(set(names)) != len(names):
        raise FieldError(f"{field} has duplicate stations")
    return names


def load_mixed_recipe(text: str, *, grip_range: GripRange = DEFAULT_GRIP_RANGE) -> MixedRecipe:
    """Parse and validate a recipe/3 document. Raises RecipeError with every problem found."""
    try:
        data = fields.parse(text, "recipe")
    except FieldError as exc:
        raise RecipeError([str(exc)]) from None
    problems = [msg for key, msg in _REFUSED.items() if key in data]
    problems += [p for p in fields.key_problems(data, "recipe", _REQUIRED)
                 if not any(p == f"recipe.{key} is not a known field" for key in _REFUSED)]

    def read(key: str, parse: Callable[[object, str], Any]) -> Any:
        if key not in data:
            return None  # already reported by key_problems
        try:
            return parse(data[key], key)
        except FieldError as exc:
            problems.append(str(exc))
            return None

    name = read("name", fields.text)
    mode = read("mode", fields.text)
    stability = read("stability", _stability)
    ratio = stability.max_height_to_base_ratio if stability else None
    items: list[Item] = []
    if "items" in data:
        try:
            raw_items = fields.entries(data["items"], "items")
        except FieldError as exc:
            problems.append(str(exc))
            raw_items = []
        for i, raw in enumerate(raw_items):
            try:
                items.append(_item(raw, f"items[{i}]", grip_range, ratio))
            except FieldError as exc:
                problems.append(str(exc))
        if not raw_items:
            problems.append("at least one item is required")
        skus = [item.sku for item in items]
        problems += [f"duplicate sku {s!r}" for s in sorted({s for s in skus if skus.count(s) > 1})]
    pallets = read("pallets", _pallets)
    stations = read("pick_stations", _stations)
    gap = read("gap", fields.non_negative)
    planner = read("planner", _planner)

    if planner is not None:
        problems += [f"item {i.sku} is upright_fixed (yaw 0) but planner.yaw_deg has no 0" for i in items
                     if i.orientation == "upright_fixed" and 0 not in planner.yaw_deg]
    if "schema" in data and data["schema"] != SCHEMA_RECIPE_MIXED:
        problems.append(f"schema must be {SCHEMA_RECIPE_MIXED}")
    if mode == "depalletize":
        problems.append("mode depalletize is not accepted by recipe/3: unloading a mixed stack needs observation")
    elif mode is not None and mode != "palletize":
        problems.append("mode must be palletize")
    if pallets is not None:
        if not pallets:
            problems.append("at least one pallet is required")
        ids = [slot.id for slot in pallets]
        problems += [f"duplicate pallet id {i!r}" for i in sorted({i for i in ids if ids.count(i) > 1})]
        taught = [slot.frame for slot in pallets]
        problems += [f"duplicate pallet frame {f!r}" for f in sorted({f for f in taught if taught.count(f) > 1})]
    if problems:
        raise RecipeError(problems)
    return MixedRecipe(
        name=name,
        mode=mode,
        items=tuple(items),
        pallets=pallets,
        pick_stations=stations,
        gap=gap,
        stability=stability,
        planner=planner,
        content_hash=content_hash(data),
    )
