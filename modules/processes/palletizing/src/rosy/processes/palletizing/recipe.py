"""recipe.yaml (schema rosy_cell.recipe/1) -> Recipe, with a content hash."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from . import SCHEMA_RECIPE, fields
from .fields import FieldError
from .load import Box, Pallet
from .pattern import PATTERNS
from .stack import LayerSpec

MODES = ("palletize", "depalletize")
_REQUIRED = ("schema", "name", "mode", "box", "pallets", "pick_station", "gap", "layers")
_OPTIONAL = ("slip_sheet",)
_BOX = ("length", "width", "height", "mass_kg")
_PALLET = ("id", "frame", "length", "width", "max_stack_height", "max_load_kg")


class RecipeError(ValueError):
    def __init__(self, problems: list[str]) -> None:
        super().__init__("; ".join(problems))
        self.problems = tuple(problems)


@dataclass(frozen=True)
class PalletSlot:
    id: str
    frame: str
    pallet: Pallet


@dataclass(frozen=True)
class Recipe:
    name: str
    mode: str
    box: Box
    pallets: tuple[PalletSlot, ...]
    pick_station: str
    gap: float
    slip_sheet_thickness: float | None
    slip_sheet_station: str | None
    layers: tuple[LayerSpec, ...]
    content_hash: str


def content_hash(data: object) -> str:
    """sha256 of canonical JSON (sorted keys, no spaces) over the parsed YAML values.

    The hash sees parsed values, not text: `gap: 0` (int) and `gap: 0.0` (float) hash
    differently. That can only reject a Job whose file is numerically the same (a false
    reject), never accept a changed one, so it errs in the safe direction. The loaders call
    it only after validation, so the data is JSON-serialisable.
    """
    return hashlib.sha256(json.dumps(data, sort_keys=True, separators=(",", ":")).encode("utf-8")).hexdigest()


def _box(value: object, field: str) -> Box:
    d = fields.mapping(value, field, _BOX)
    sizes = [fields.number(d[k], f"{field}.{k}") for k in _BOX]
    try:
        return Box(*sizes)
    except ValueError as exc:
        raise FieldError(f"{field}: {exc}") from None


def _pallets(value: object, field: str) -> tuple[PalletSlot, ...]:
    slots = []
    for i, raw in enumerate(fields.entries(value, field)):
        f = f"{field}[{i}]"
        d = fields.mapping(raw, f, _PALLET)
        sizes = [fields.number(d[k], f"{f}.{k}") for k in _PALLET[2:]]
        try:
            pallet = Pallet(*sizes)
        except ValueError as exc:
            raise FieldError(f"{f}: {exc}") from None
        slots.append(PalletSlot(fields.text(d["id"], f"{f}.id"), fields.text(d["frame"], f"{f}.frame"), pallet))
    return tuple(slots)


def _layers(value: object, field: str) -> tuple[LayerSpec, ...]:
    specs = []
    for i, raw in enumerate(fields.entries(value, field)):
        f = f"{field}[{i}]"
        d = fields.mapping(raw, f, ("pattern",), ("mirrored", "slip_sheet_below"))
        specs.append(
            LayerSpec(
                fields.text(d["pattern"], f"{f}.pattern"),
                fields.flag(d.get("mirrored", False), f"{f}.mirrored"),
                fields.flag(d.get("slip_sheet_below", False), f"{f}.slip_sheet_below"),
            )
        )
    return tuple(specs)


def _slip_sheet(value: object, field: str) -> tuple[float, str]:
    d = fields.mapping(value, field, ("thickness", "station"))
    return fields.positive(d["thickness"], f"{field}.thickness"), fields.text(d["station"], f"{field}.station")


def load_recipe(text: str) -> Recipe:
    try:
        data = fields.parse(text, "recipe")
    except FieldError as exc:
        raise RecipeError([str(exc)]) from None
    problems = fields.key_problems(data, "recipe", _REQUIRED, _OPTIONAL)

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
    box = read("box", _box)
    pallets = read("pallets", _pallets)
    pick_station = read("pick_station", fields.text)
    gap = read("gap", fields.non_negative)
    sheet = read("slip_sheet", _slip_sheet)
    layers = read("layers", _layers)

    if "schema" in data and data["schema"] != SCHEMA_RECIPE:
        problems.append(f"schema must be {SCHEMA_RECIPE}")
    if mode is not None and mode not in MODES:
        problems.append(f"mode must be one of {MODES}")
    if pallets is not None:
        if not pallets:
            problems.append("at least one pallet is required")
        ids = [slot.id for slot in pallets]
        problems += [f"duplicate pallet id {i!r}" for i in sorted({i for i in ids if ids.count(i) > 1})]
        taught = [slot.frame for slot in pallets]
        problems += [f"duplicate pallet frame {f!r}" for f in sorted({f for f in taught if taught.count(f) > 1})]
    if layers is not None:
        if not layers:
            problems.append("at least one layer is required")
        problems += [f"unknown pattern {s.pattern!r}" for s in layers if s.pattern not in PATTERNS]
        if any(s.slip_sheet_below for s in layers) and "slip_sheet" not in data:
            problems.append("slip_sheet (thickness, station) is required when a layer has slip_sheet_below")
    if problems:
        raise RecipeError(problems)
    return Recipe(
        name=name,
        mode=mode,
        box=box,
        pallets=pallets,
        pick_station=pick_station,
        gap=gap,
        slip_sheet_thickness=sheet[0] if sheet else None,
        slip_sheet_station=sheet[1] if sheet else None,
        layers=layers,
        content_hash=content_hash(data),
    )
