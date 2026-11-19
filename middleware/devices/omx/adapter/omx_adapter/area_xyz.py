"""Unified Area + 3D Coordinate (`AreaXYZ`) and Middleware -> `rosy-cell` Directive Contract (D-1014)."""
from __future__ import annotations

from typing import Any
import uuid

from .z_profile import (
    CONTAINER_SPECS_MM, OMX_AI_PROFILE_MM, TIER_GRASP_Z_MM, TIER_SURFACE_Z_MM, TIER_TOP_Z_MM,
    reconcile_tcp_z_mm, resolve_container_spec,
)

AREA_XYZ_SCHEMA = "rosy.omx-area-xyz.v1"
DIRECTIVE_SCHEMA = "rosy.omx-cell-area-xyz-directive.v1"
TIER_Z_M: dict[int, float] = {1: 0.0074, 2: 0.0398, 3: 0.0674}
TIER_Z_MM: dict[int, float] = dict(TIER_GRASP_Z_MM)
TIER_SITE_SUFFIX: dict[int, str] = {1: "l0", 2: "l1", 3: "l2"}

PALLET_SLOTS_XY_M: dict[tuple[int, int], tuple[float, float]] = {
    (1, 1): (0.1280, -0.0120), (2, 1): (0.1580, -0.0130), (3, 1): (0.1988, -0.0030),
    (1, 2): (0.1267, -0.1060), (2, 2): (0.1650, -0.1060), (3, 2): (0.2038, -0.1060),
}
TEMP_PLATE_B_SLOTS_XY_M: dict[int, tuple[float, float]] = {1: (0.1163, -0.1452), 2: (0.0584, -0.1567), 3: (-0.0004, -0.1521)}
TEMP_PLATE_B_YAW_DEG: dict[int, float] = {1: -141.3, 2: -159.6, 3: -0.1}
TEMP_PLATE_A_SLOTS_XY_M: dict[int, tuple[float, float]] = {1: (-0.0681, 0.1841), 2: (-0.0109, 0.1729), 3: (0.0419, 0.1465)}
TEMP_PLATE_A_YAW_DEG: dict[int, float] = {1: -3.1, 2: -18.7, 3: -34.4}
DEFAULT_COL_BIAS_MM: dict[int, list[float]] = {1: [0.0, 0.0], 2: [-3.8, 0.0], 3: [1.5, 0.0]}
AREA_DEFAULTS_XY_M: dict[str, tuple[float, float]] = {
    "pallet": (0.1580, -0.0130), "ship_hold": (0.1580, -0.0130), "beltend": (0.0150, 0.1750),
    "temp_plate_a": (-0.0109, 0.1729), "temp_plate_b": (0.0584, -0.1567),
}
WORKSPACE_MIN_M = (-0.095, -0.24, 0.005)
WORKSPACE_MAX_M = (0.26, 0.24, 0.145)


def resolve_area_xyz(
    area: str = "pallet", *, col: int | None = None, row: int | None = None, tier: int | None = 1,
    x: float | None = None, y: float | None = None, z: float | None = None,
    x_mm: float | None = None, y_mm: float | None = None, z_mm: float | None = None,
    yaw_deg: float = -90.0, bias_mm: list[float] | tuple[float, float] | None = None,
    apply_bias: bool = False, object_id: str | None = None, container_spec: str | dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Normalize an area + optional `(col, row, tier)` slot + coordinates into `rosy.omx-area-xyz.v1`."""
    norm_area = str(area or "pallet").strip().lower()
    if norm_area.startswith("pallet-l"):
        tier = {"l0": 1, "l1": 2, "l2": 3}.get(norm_area.split("-")[-1], tier or 1)
        norm_area = "pallet"
    elif norm_area in ("temp_plate", "temp_stand", "temp", "임시대"):
        norm_area = "temp_plate_b"
    elif norm_area.startswith("tmp-"):
        parts = norm_area.split("-")
        tag = parts[1] if len(parts) >= 2 else "b"
        if len(parts) >= 3 and parts[2].isdigit() and col is None:
            col = int(parts[2])
        if len(parts) >= 4 and parts[3].startswith("l"):
            tier = {"l0": 1, "l1": 2, "l2": 3}.get(parts[3], tier or 1)
        norm_area = f"temp_plate_{tag}"

    x = float(x_mm) / 1000.0 if (x is None and x_mm is not None) else x
    y = float(y_mm) / 1000.0 if (y is None and y_mm is not None) else y
    z = float(z_mm) / 1000.0 if (z is None and z_mm is not None) else z

    resolved_tier = int(tier) if tier in (1, 2, 3) else 1
    if z is not None:
        z_m = float(z)
        if tier is None:
            resolved_tier = min((1, 2, 3), key=lambda t: abs(TIER_Z_M[t] - z_m))
    else:
        z_m = TIER_Z_M[resolved_tier]

    lane_idx = int(col) if col in (1, 2, 3) else 2
    if x is not None and y is not None:
        x_m, y_m = float(x), float(y)
    elif norm_area in ("pallet", "ship_hold") and col in (1, 2, 3):
        x_m, y_m = PALLET_SLOTS_XY_M[(int(col), int(row) if row in (1, 2) else 1)]
    elif norm_area == "temp_plate_b":
        x_m, y_m, col = TEMP_PLATE_B_SLOTS_XY_M[lane_idx][0], TEMP_PLATE_B_SLOTS_XY_M[lane_idx][1], (col or lane_idx)
    elif norm_area == "temp_plate_a":
        x_m, y_m, col = TEMP_PLATE_A_SLOTS_XY_M[lane_idx][0], TEMP_PLATE_A_SLOTS_XY_M[lane_idx][1], (col or lane_idx)
    else:
        x_m, y_m = AREA_DEFAULTS_XY_M.get(norm_area, (0.1580, -0.0130))

    if norm_area == "temp_plate_b" and abs(float(yaw_deg) - (-90.0)) < 1e-3:
        yaw_deg = TEMP_PLATE_B_YAW_DEG.get(lane_idx, -159.6)
    elif norm_area == "temp_plate_a" and abs(float(yaw_deg) - (-90.0)) < 1e-3:
        yaw_deg = TEMP_PLATE_A_YAW_DEG.get(lane_idx, -18.7)

    b_mm = [float(bias_mm[0]), float(bias_mm[1])] if bias_mm is not None else (list(DEFAULT_COL_BIAS_MM[int(col)]) if (apply_bias and col in DEFAULT_COL_BIAS_MM) else [0.0, 0.0])
    eff_x, eff_y, eff_z = round(x_m + (b_mm[0] / 1000.0 if apply_bias else 0.0), 5), round(y_m + (b_mm[1] / 1000.0 if apply_bias else 0.0), 5), round(z_m, 5)
    for axis_name, val, lo, hi in (("x", eff_x, WORKSPACE_MIN_M[0], WORKSPACE_MAX_M[0]), ("y", eff_y, WORKSPACE_MIN_M[1], WORKSPACE_MAX_M[1]), ("z", eff_z, WORKSPACE_MIN_M[2], WORKSPACE_MAX_M[2])):
        if not (lo <= val <= hi):
            raise ValueError(f"AreaXYZ {axis_name}={val} outside workspace [{lo}, {hi}]")

    if norm_area in ("pallet", "ship_hold"):
        site_id = f"pallet-{TIER_SITE_SUFFIX[resolved_tier]}"
    elif norm_area in ("temp_plate_b", "temp_plate_a"):
        site_id = f"tmp-{'b' if norm_area == 'temp_plate_b' else 'a'}-{lane_idx}{f'-{TIER_SITE_SUFFIX[resolved_tier]}' if resolved_tier > 1 else ''}"
    else:
        site_id = norm_area

    spec_info = dict(container_spec) if isinstance(container_spec, dict) else resolve_container_spec(container_spec if isinstance(container_spec, str) else object_id)
    eff_x_mm, eff_y_mm, eff_z_mm = round(eff_x * 1000.0, 2), round(eff_y * 1000.0, 2), round(eff_z * 1000.0, 2)
    above_z_m = round(eff_z + 0.0400, 5)
    return {
        "schema": AREA_XYZ_SCHEMA, "area": norm_area, "site_id": site_id,
        "col": int(col) if col is not None else None, "row": int(row) if row is not None else None, "tier": resolved_tier,
        "x": round(x_m, 5), "y": round(y_m, 5), "z": round(z_m, 5),
        "x_mm": round(x_m * 1000.0, 2), "y_mm": round(y_m * 1000.0, 2), "z_mm": round(z_m * 1000.0, 2),
        "yaw_deg": round(float(yaw_deg), 2), "bias_mm": b_mm,
        "effective_xyz_m": [eff_x, eff_y, eff_z], "effective_xyz_mm": [eff_x_mm, eff_y_mm, eff_z_mm],
        "above_z_m": above_z_m, "above_z_mm": round(above_z_m * 1000.0, 2),
        "surface_z_mm": TIER_SURFACE_Z_MM[resolved_tier], "top_z_mm": TIER_TOP_Z_MM[resolved_tier],
        "spec_id": spec_info["spec_id"], "container_spec": spec_info,
        "profile_anchor_mm": {"base_plate_top_z_mm": OMX_AI_PROFILE_MM["base_plate_top_z_mm"], "joint2_shoulder_z_mm": OMX_AI_PROFILE_MM["joint2_z_mm"], "tcp_v21_x_mm": OMX_AI_PROFILE_MM["tcp_v21_x_mm"], **reconcile_tcp_z_mm(eff_z_mm)},
    }


def coerce_area_xyz(spec: dict[str, Any]) -> dict[str, Any]:
    if isinstance(spec, dict) and spec.get("schema") == AREA_XYZ_SCHEMA and "effective_xyz_m" in spec and "effective_xyz_mm" in spec:
        out = dict(spec)
        if "container_spec" not in out:
            c_spec = resolve_container_spec(out.get("spec_id") or out.get("object_id"))
            out["spec_id"], out["container_spec"] = c_spec["spec_id"], c_spec
        return out
    return resolve_area_xyz(
        area=spec.get("area", spec.get("site_id", "pallet")), col=spec.get("col"), row=spec.get("row"), tier=spec.get("tier"),
        x=spec.get("x"), y=spec.get("y"), z=spec.get("z"), x_mm=spec.get("x_mm"), y_mm=spec.get("y_mm"), z_mm=spec.get("z_mm"),
        yaw_deg=spec.get("yaw_deg", -90.0), bias_mm=spec.get("bias_mm"), apply_bias=bool(spec.get("apply_bias", False)),
        object_id=spec.get("object_id") or spec.get("spec_id"), container_spec=spec.get("container_spec"),
    )


def build_directive(
    *, arm_id: str = "arm_b", pick: dict[str, Any], place: dict[str, Any], directive_id: str | None = None,
    object_id: str = "container-v2-3", vision_refine: bool = True, grasp_deliberation: bool = True,
    transit_speed: float = 0.82, descend_pick_guard_frac: float = 0.30, descend_place_guard_frac: float = 0.26,
) -> dict[str, Any]:
    """Construct a `rosy.omx-cell-area-xyz-directive.v1` payload from ROSY middleware to `rosy-cell`."""
    c_spec = resolve_container_spec(object_id)
    pick_in, place_in = dict(pick), dict(place)
    pick_in.setdefault("object_id", object_id)
    place_in.setdefault("object_id", object_id)
    return {
        "schema": DIRECTIVE_SCHEMA, "directive_id": directive_id or f"dir-{uuid.uuid4().hex[:10]}",
        "arm_id": arm_id, "object_id": object_id, "spec_id": c_spec["spec_id"], "container_spec": c_spec,
        "pick": coerce_area_xyz(pick_in), "place": coerce_area_xyz(place_in),
        "execution": {
            "vision_refine": bool(vision_refine), "grasp_deliberation": bool(grasp_deliberation),
            "transit_speed": float(transit_speed), "descend_pick_guard_frac": float(descend_pick_guard_frac),
            "descend_place_guard_frac": float(descend_place_guard_frac), "approach_m": 0.04, "approach_mm": 40.0,
        },
    }


__all__ = [
    "AREA_DEFAULTS_XY_M", "AREA_XYZ_SCHEMA", "CONTAINER_SPECS_MM", "DEFAULT_COL_BIAS_MM", "DIRECTIVE_SCHEMA",
    "PALLET_SLOTS_XY_M", "TEMP_PLATE_A_SLOTS_XY_M", "TEMP_PLATE_A_YAW_DEG", "TEMP_PLATE_B_SLOTS_XY_M",
    "TEMP_PLATE_B_YAW_DEG", "TIER_SITE_SUFFIX", "TIER_Z_M", "TIER_Z_MM", "WORKSPACE_MAX_M", "WORKSPACE_MIN_M",
    "build_directive", "coerce_area_xyz", "resolve_area_xyz", "resolve_container_spec",
]
