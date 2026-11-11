"""Unified Area + 3D Coordinate (`AreaXYZ`) and Middleware -> `rosy-cell` Directive Contract (D-1014).

Unifies logical workcell areas (`pallet` / `ship_hold`, `temp_plate_a`, `temp_plate_b`, `beltend`), slot indices
(`col`, `row`, `tier` = 1단/2단/3단), and metric arm-frame coordinates (`x, y, z, yaw_deg`) into a single canonical
coordinate schema (`rosy.omx-area-xyz.v1`), and constructs middleware directives (`rosy.omx-cell-area-xyz-directive.v1`)
that `rosy-cell` (`deploy/robot/omx/cell_area_xyz.py`) executes.
"""
from __future__ import annotations

from typing import Any
import uuid

AREA_XYZ_SCHEMA = "rosy.omx-area-xyz.v1"
DIRECTIVE_SCHEMA = "rosy.omx-cell-area-xyz-directive.v1"

TIER_Z_M: dict[int, float] = {
    1: 0.0074,  # 1단 (l0)
    2: 0.0398,  # 2단 (l1)
    3: 0.0674,  # 3단 (l2)
}

TIER_SITE_SUFFIX: dict[int, str] = {
    1: "l0",
    2: "l1",
    3: "l2",
}

# Canonical (x_m, y_m) slot centers in arm_b frame for pallet / ship_hold
PALLET_SLOTS_XY_M: dict[tuple[int, int], tuple[float, float]] = {
    (1, 1): (0.1280, -0.0120),
    (2, 1): (0.1580, -0.0130),
    (3, 1): (0.1988, -0.0030),
    (1, 2): (0.1267, -0.1060),
    (2, 2): (0.1650, -0.1060),
    (3, 2): (0.2038, -0.1060),
}

DEFAULT_COL_BIAS_MM: dict[int, list[float]] = {
    1: [0.0, 0.0],
    2: [-3.8, 0.0],
    3: [1.5, 0.0],
}

AREA_DEFAULTS_XY_M: dict[str, tuple[float, float]] = {
    "pallet": (0.1580, -0.0130),
    "ship_hold": (0.1580, -0.0130),
    "beltend": (0.0150, 0.1750),
    "temp_plate_a": (0.1600, -0.1500),
    "temp_plate_b": (0.1600, 0.1500),
}

WORKSPACE_MIN_M = (-0.05, -0.24, 0.005)
WORKSPACE_MAX_M = (0.26, 0.24, 0.145)


def resolve_area_xyz(
    area: str = "pallet",
    *,
    col: int | None = None,
    row: int | None = None,
    tier: int | None = 1,
    x: float | None = None,
    y: float | None = None,
    z: float | None = None,
    yaw_deg: float = -90.0,
    bias_mm: list[float] | tuple[float, float] | None = None,
    apply_bias: bool = False,
) -> dict[str, Any]:
    """Normalize an area + optional `(col, row, tier)` slot + optional `(x, y, z)` coordinates into `rosy.omx-area-xyz.v1`."""
    norm_area = str(area or "pallet").strip().lower()
    if norm_area.startswith("pallet-l"):
        suffix = norm_area.split("-")[-1]
        tier = {"l0": 1, "l1": 2, "l2": 3}.get(suffix, tier or 1)
        norm_area = "pallet"

    resolved_tier = int(tier) if tier in (1, 2, 3) else 1
    if z is not None:
        z_m = float(z)
        if tier is None:
            resolved_tier = min((1, 2, 3), key=lambda t: abs(TIER_Z_M[t] - z_m))
    else:
        z_m = TIER_Z_M[resolved_tier]

    if x is not None and y is not None:
        x_m, y_m = float(x), float(y)
    elif norm_area in ("pallet", "ship_hold") and col in (1, 2, 3):
        r_idx = int(row) if row in (1, 2) else 1
        x_m, y_m = PALLET_SLOTS_XY_M[(int(col), r_idx)]
    else:
        x_m, y_m = AREA_DEFAULTS_XY_M.get(norm_area, (0.1580, -0.0130))

    if bias_mm is not None:
        b_mm = [float(bias_mm[0]), float(bias_mm[1])]
    elif apply_bias and col in DEFAULT_COL_BIAS_MM:
        b_mm = list(DEFAULT_COL_BIAS_MM[int(col)])
    else:
        b_mm = [0.0, 0.0]

    eff_x = round(x_m + (b_mm[0] / 1000.0 if apply_bias else 0.0), 5)
    eff_y = round(y_m + (b_mm[1] / 1000.0 if apply_bias else 0.0), 5)
    eff_z = round(z_m, 5)

    if not (WORKSPACE_MIN_M[0] <= eff_x <= WORKSPACE_MAX_M[0]):
        raise ValueError(f"AreaXYZ x={eff_x} outside workspace [{WORKSPACE_MIN_M[0]}, {WORKSPACE_MAX_M[0]}]")
    if not (WORKSPACE_MIN_M[1] <= eff_y <= WORKSPACE_MAX_M[1]):
        raise ValueError(f"AreaXYZ y={eff_y} outside workspace [{WORKSPACE_MIN_M[1]}, {WORKSPACE_MAX_M[1]}]")
    if not (WORKSPACE_MIN_M[2] <= eff_z <= WORKSPACE_MAX_M[2]):
        raise ValueError(f"AreaXYZ z={eff_z} outside workspace [{WORKSPACE_MIN_M[2]}, {WORKSPACE_MAX_M[2]}]")

    site_id = (
        f"pallet-{TIER_SITE_SUFFIX[resolved_tier]}"
        if norm_area in ("pallet", "ship_hold")
        else norm_area
    )
    return {
        "schema": AREA_XYZ_SCHEMA,
        "area": norm_area,
        "site_id": site_id,
        "col": int(col) if col is not None else None,
        "row": int(row) if row is not None else None,
        "tier": resolved_tier,
        "x": round(x_m, 5),
        "y": round(y_m, 5),
        "z": round(z_m, 5),
        "yaw_deg": round(float(yaw_deg), 2),
        "bias_mm": b_mm,
        "effective_xyz_m": [eff_x, eff_y, eff_z],
        "above_z_m": round(eff_z + 0.0400, 5),
    }


def coerce_area_xyz(spec: dict[str, Any]) -> dict[str, Any]:
    if isinstance(spec, dict) and spec.get("schema") == AREA_XYZ_SCHEMA and "effective_xyz_m" in spec:
        return dict(spec)
    return resolve_area_xyz(
        area=spec.get("area", spec.get("site_id", "pallet")),
        col=spec.get("col"),
        row=spec.get("row"),
        tier=spec.get("tier"),
        x=spec.get("x"),
        y=spec.get("y"),
        z=spec.get("z"),
        yaw_deg=spec.get("yaw_deg", -90.0),
        bias_mm=spec.get("bias_mm"),
        apply_bias=bool(spec.get("apply_bias", False)),
    )


def build_directive(
    *,
    arm_id: str = "arm_b",
    pick: dict[str, Any],
    place: dict[str, Any],
    directive_id: str | None = None,
    object_id: str = "container-v2-3",
    vision_refine: bool = True,
    grasp_deliberation: bool = True,
    transit_speed: float = 0.82,
    descend_pick_guard_frac: float = 0.30,
    descend_place_guard_frac: float = 0.26,
) -> dict[str, Any]:
    """Construct a `rosy.omx-cell-area-xyz-directive.v1` payload from ROSY middleware to `rosy-cell`."""
    pick_xyz = coerce_area_xyz(pick)
    place_xyz = coerce_area_xyz(place)
    return {
        "schema": DIRECTIVE_SCHEMA,
        "directive_id": directive_id or f"dir-{uuid.uuid4().hex[:10]}",
        "arm_id": arm_id,
        "object_id": object_id,
        "pick": pick_xyz,
        "place": place_xyz,
        "execution": {
            "vision_refine": bool(vision_refine),
            "grasp_deliberation": bool(grasp_deliberation),
            "transit_speed": float(transit_speed),
            "descend_pick_guard_frac": float(descend_pick_guard_frac),
            "descend_place_guard_frac": float(descend_place_guard_frac),
            "approach_m": 0.04,
        },
    }
