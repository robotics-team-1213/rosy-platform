"""recipe.yaml (schema rosy_cell.recipe/1) -> Recipe, with a content hash."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass

import yaml

from . import SCHEMA_RECIPE
from .load import Box, Pallet
from .pattern import PATTERNS
from .sequence import APPROACHES
from .stack import LayerSpec

MODES = ("palletize", "depalletize")


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
    approach: str
    gap: float
    slip_sheet_thickness: float | None
    slip_sheet_station: str | None
    layers: tuple[LayerSpec, ...]
    content_hash: str


def content_hash(data: object) -> str:
    return hashlib.sha256(json.dumps(data, sort_keys=True, separators=(",", ":")).encode("utf-8")).hexdigest()


def load_recipe(text: str) -> Recipe:
    data = yaml.safe_load(text)
    if not isinstance(data, dict):
        raise RecipeError(["recipe must be a mapping"])
    try:
        box = Box(**data["box"])
        pallets = tuple(
            PalletSlot(
                str(p["id"]),
                str(p["frame"]),
                Pallet(p["length"], p["width"], p["max_stack_height"], p["max_load_kg"]),
            )
            for p in data["pallets"]
        )
        layers = tuple(LayerSpec(**layer) for layer in data["layers"])
        sheet = data.get("slip_sheet")
        recipe = Recipe(
            name=str(data["name"]),
            mode=data["mode"],
            box=box,
            pallets=pallets,
            pick_station=str(data["pick_station"]),
            approach=data["approach"],
            gap=float(data["gap"]),
            slip_sheet_thickness=float(sheet["thickness"]) if sheet else None,
            slip_sheet_station=str(sheet["station"]) if sheet else None,
            layers=layers,
            content_hash=content_hash(data),
        )
    except (KeyError, TypeError, ValueError) as exc:
        raise RecipeError([f"invalid recipe field: {exc}"]) from None

    problems: list[str] = []
    if data.get("schema") != SCHEMA_RECIPE:
        problems.append(f"schema must be {SCHEMA_RECIPE}")
    if recipe.mode not in MODES:
        problems.append(f"mode must be one of {MODES}")
    if recipe.approach not in APPROACHES:
        problems.append(f"approach must be one of {sorted(APPROACHES)}")
    if not recipe.pallets:
        problems.append("at least one pallet is required")
    ids = [slot.id for slot in recipe.pallets]
    problems += [f"duplicate pallet id {i!r}" for i in sorted({i for i in ids if ids.count(i) > 1})]
    if not recipe.layers:
        problems.append("at least one layer is required")
    problems += [f"unknown pattern {s.pattern!r}" for s in recipe.layers if s.pattern not in PATTERNS]
    if any(s.slip_sheet_below for s in recipe.layers) and recipe.slip_sheet_station is None:
        problems.append("slip_sheet (thickness, station) is required when a layer has slip_sheet_below")
    if recipe.gap < 0:
        problems.append("gap must be non-negative")
    if problems:
        raise RecipeError(problems)
    return recipe
