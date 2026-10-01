"""Layers stacked on one pallet, with optional slip sheets."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass

from .load import Box, Pallet
from .pattern import PATTERNS, Placement, layer_issues, mirrored


@dataclass(frozen=True)
class LayerSpec:
    pattern: str
    mirrored: bool = False
    slip_sheet_below: bool = False


@dataclass(frozen=True)
class PlacedBox:
    layer: int
    x: float
    y: float
    z_top: float
    yaw: float


@dataclass(frozen=True)
class SlipSheet:
    below_layer: int
    z: float  # top surface of the sheet


@dataclass(frozen=True)
class StackPlan:
    layers: tuple[tuple[PlacedBox, ...], ...]
    slip_sheets: tuple[SlipSheet, ...]
    height: float
    mass_kg: float


def build_stack(
    box: Box, pallet: Pallet, layers: Sequence[LayerSpec], *, gap: float, slip_sheet_thickness: float
) -> StackPlan:
    z = 0.0
    out: list[tuple[PlacedBox, ...]] = []
    sheets: list[SlipSheet] = []
    for n, spec in enumerate(layers):
        try:
            make = PATTERNS[spec.pattern]
        except KeyError:
            raise ValueError(f"unknown pattern {spec.pattern!r}") from None
        placements = make(box, pallet, gap=gap)
        if spec.mirrored:
            placements = mirrored(placements, pallet)
        if spec.slip_sheet_below:
            z += slip_sheet_thickness
            sheets.append(SlipSheet(n, z))
        z += box.height
        out.append(tuple(PlacedBox(n, p.x, p.y, z, p.yaw) for p in placements))
    count = sum(len(layer) for layer in out)
    return StackPlan(tuple(out), tuple(sheets), z, count * box.mass_kg)


def stack_issues(plan: StackPlan, box: Box, pallet: Pallet, *, tol_m: float) -> list[str]:
    issues: list[str] = []
    if plan.height > pallet.max_stack_height + tol_m:
        issues.append(f"stack height {plan.height:.3f} m exceeds {pallet.max_stack_height:.3f} m")
    if plan.mass_kg > pallet.max_load_kg:
        issues.append(f"stack mass {plan.mass_kg:.3f} kg exceeds {pallet.max_load_kg:.3f} kg")
    for n, layer in enumerate(plan.layers):
        if not layer:
            issues.append(f"layer {n} is empty")
            continue
        placements = [Placement(b.x, b.y, b.yaw) for b in layer]
        issues += [f"layer {n}: {msg}" for msg in layer_issues(placements, box, pallet, tol_m=tol_m)]
    return issues
