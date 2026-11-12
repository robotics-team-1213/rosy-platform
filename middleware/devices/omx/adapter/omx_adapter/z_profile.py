"""OMX-AI Self-Profile-Anchored Z-Axis (and 3D) Millimeter (`mm`) Coordinate & Multi-View Projection System."""
from __future__ import annotations

import math
from typing import Any, Sequence

Z_PROFILE_SCHEMA = "rosy.omx-z-profile-mm.v1"
SCHEMA = Z_PROFILE_SCHEMA

OMX_AI_PROFILE_MM: dict[str, Any] = {
    "schema": Z_PROFILE_SCHEMA, "model": "ROBOTIS-OMX-AI-Follower", "link0_bottom_z_mm": 0.0,
    "base_plate_size_mm": (150.0, 120.0, 13.0), "base_plate_top_z_mm": 13.0, "servo_mount_top_z_mm": 32.0,
    "link1_top_z_mm": 57.5, "joint1_xyz_mm": (-11.25, 0.0, 34.0), "joint2_rel_xyz_mm": (0.0, 0.0, 63.5),
    "joint2_z_mm": 97.5, "joint2_above_plate_top_mm": 84.5, "joint3_rel_xyz_mm": (41.5, 0.0, 113.15),
    "l1_mm": round(math.hypot(41.5, 113.15), 4), "joint4_rel_xyz_mm": (162.0, 0.0, 0.0), "l2_mm": 162.0,
    "joint5_rel_xyz_mm": (28.7, 0.0, 0.0), "wrist_length_mm": 28.7, "gripper_pivot_x_mm": 29.5,
    "jaw_v21_tip_from_pivot_mm": 44.6, "tcp_stock_x_mm": 91.93, "stock_fingertip_x_mm": 94.51,
    "tcp_v21_x_mm": 74.1, "legacy_plan_tcp_x_mm": 88.5, "wrist_cam_mount_part": "PR33_C02_F9_REV1_5",
    "wrist_cam_part": "CAMERA_INNOMAKER_720P_11", "wrist_cam_rel_link5_xyz_mm": (36.24, 0.0, 45.84),
    "wrist_cam_screw_lower_yz_stp_mm": (249.41, 243.20), "wrist_cam_screw_upper_yz_stp_mm": (271.48, 260.43),
    "wrist_cam_pitch_from_approach_deg": 38.0, "wrist_cam_ray_intersect_link5_x_mm": 94.91,
    "wrist_cam_above_stock_tcp_mm": 55.69, "wrist_cam_above_v21_tcp_mm": 37.86, "wrist_cam_v21_parallax_mm": 14.3,
    "default_table_fk_offset_mm": -8.3, "silicone_tape_datum_z_mm": 3.0,
    "default_joint_zero_offset_deg": (4.0, 1.0, 3.2, 2.8, 2.4), "container_height_mm": 30.0, "pallet_plate_thickness_mm": 10.0,
}

CONTAINER_MM: dict[str, float] = {"width_mm": 30.0, "length_mm": 90.0, "height_mm": 30.0, "stack_pitch_mm": 32.4, "cone_engage_mm": 2.4}
CONTAINER_SPECS_MM: dict[str, dict[str, Any]] = {
    "C3": {"spec_id": "C3", "id": "container-3", "cells": 3, "cone_count": 3, "width_mm": 30.0, "length_mm": 90.0, "height_mm": 30.0, "stack_pitch_mm": 32.4, "expected_area_mm2": 2700.0, "slot_x_candidates_mm": [0.0]},
    "C2": {"spec_id": "C2", "id": "container-2", "cells": 2, "cone_count": 2, "width_mm": 30.0, "length_mm": 60.0, "height_mm": 30.0, "stack_pitch_mm": 32.4, "expected_area_mm2": 1800.0, "slot_x_candidates_mm": [-15.0, 15.0]},
    "C1": {"spec_id": "C1", "id": "container-1", "cells": 1, "cone_count": 1, "width_mm": 30.0, "length_mm": 30.0, "height_mm": 30.0, "stack_pitch_mm": 32.4, "expected_area_mm2": 900.0, "slot_x_candidates_mm": [-30.0, 0.0, 30.0]},
}
_CONTAINER_SPEC_ALIASES: dict[str, str] = {
    "c3": "C3", "container-3": "C3", "container-v2-3": "C3", "container_3x9x3": "C3", "3x9x3": "C3", "3": "C3",
    "c2": "C2", "container-2": "C2", "container-v2-2": "C2", "container_3x6x3": "C2", "3x6x3": "C2", "2": "C2",
    "c1": "C1", "container-1": "C1", "container-v2-1": "C1", "container_3x3x3": "C1", "3x3x3": "C1", "1": "C1",
}

TIER_GRASP_Z_MM: dict[int, float] = {1: 7.4, 2: 39.8, 3: 67.4}
TIER_SURFACE_Z_MM: dict[int, float] = {1: 0.0, 2: 30.0, 3: 60.0}
TIER_TOP_Z_MM: dict[int, float] = {1: 30.0, 2: 62.4, 3: 94.8}
TIER_MID_Z_MM: dict[int, float] = {1: 15.0, 2: 45.0, 3: 75.0}
DEFAULT_SIDE_TIER_V_PX: dict[int, tuple[float, float]] = {1: (252.0, 315.0), 2: (190.0, 252.0), 3: (120.0, 190.0)}


def resolve_container_spec(object_id: str | None = "C3") -> dict[str, Any]:
    """Resolve a container identifier (`C1`/`C2`/`C3` or catalog alias) into its canonical 3D `ContainerSpec` in `mm`."""
    spec = dict(CONTAINER_SPECS_MM[_CONTAINER_SPEC_ALIASES.get(str(object_id or "C3").strip().lower(), "C3")])
    spec["slot_x_candidates_mm"] = list(spec["slot_x_candidates_mm"])
    return spec


def evaluate_signed_tier_residual_mm(
    z_top_mm: float, expected_tier: int, *, valid_depth_ratio: float = 1.0, dz_top_side_mm: float = 0.0,
    tilt_deg: float = 0.0, obs_area_mm2: float | None = None, spec_id: str = "C3",
) -> dict[str, Any]:
    """Evaluate the Round 2 Consensus Z-Judge signed residual `r_k = z_top_mm - h_k` (`h_k in {30.0, 62.4, 94.8}` mm)."""
    spec, tier_k = resolve_container_spec(spec_id), (int(expected_tier) if int(expected_tier) in TIER_TOP_Z_MM else 1)
    h_k, r_k = float(TIER_TOP_Z_MM[tier_k]), round(float(z_top_mm) - float(TIER_TOP_Z_MM[tier_k]), 2)
    area_ratio = 1.0 if obs_area_mm2 is None else round(float(obs_area_mm2) / float(spec["expected_area_mm2"]), 3)
    gate_ok = bool(float(valid_depth_ratio) >= 0.80 and abs(float(dz_top_side_mm)) <= 8.0 and float(tilt_deg) <= 10.0 and area_ratio >= 0.65)
    if float(valid_depth_ratio) >= 0.80 and (r_k <= -4.0 or float(tilt_deg) > 10.0):
        verdict, failure_code = "FAIL", "S2_TOPPLED_OR_SLUMPED"
    elif not gate_ok:
        verdict, failure_code = "UNKNOWN", "S5_VIEW_OR_GATE_MISMATCH"
    elif 1.0 <= r_k <= 3.0:
        verdict, failure_code = "FAIL", "S6_UNSEATED_CONE"
    elif r_k <= -4.0:
        verdict, failure_code = "FAIL", "S2_TOPPLED_OR_SLUMPED"
    elif -4.0 < r_k < 1.0:
        verdict, failure_code = "PASS", None
    else:
        verdict, failure_code = "UNKNOWN", "S5_HEIGHT_ANOMALY"
    return {"verdict": verdict, "failure_code": failure_code, "gate_ok": gate_ok, "expected_tier": tier_k,
            "expected_top_z_mm": h_k, "z_top_mm": round(float(z_top_mm), 2), "r_k_mm": r_k, "area_ratio": area_ratio, "spec_id": spec["spec_id"]}


def _rot_y(a: float) -> tuple[tuple[float, float, float], ...]:
    c, s = math.cos(a), math.sin(a)
    return ((c, 0.0, s), (0.0, 1.0, 0.0), (-s, 0.0, c))


def _rot_z(a: float) -> tuple[tuple[float, float, float], ...]:
    c, s = math.cos(a), math.sin(a)
    return ((c, -s, 0.0), (s, c, 0.0), (0.0, 0.0, 1.0))


def _rot_x(a: float) -> tuple[tuple[float, float, float], ...]:
    c, s = math.cos(a), math.sin(a)
    return ((1.0, 0.0, 0.0), (0.0, c, -s), (0.0, s, c))


def _matmul(a: Sequence[Sequence[float]], b: Sequence[Sequence[float]]) -> tuple[tuple[float, float, float], ...]:
    return tuple(tuple(sum(a[i][k] * b[k][j] for k in range(3)) for j in range(3)) for i in range(3))


def _matvec(a: Sequence[Sequence[float]], v: Sequence[float]) -> tuple[float, float, float]:
    return (a[0][0] * v[0] + a[0][1] * v[1] + a[0][2] * v[2], a[1][0] * v[0] + a[1][1] * v[1] + a[1][2] * v[2], a[2][0] * v[0] + a[2][1] * v[1] + a[2][2] * v[2])


def _add3(a: Sequence[float], b: Sequence[float]) -> list[float]:
    return [round(float(a[0] + b[0]), 3), round(float(a[1] + b[1]), 3), round(float(a[2] + b[2]), 3)]


def fk_landmarks_mm(
    joints: Sequence[float], *, unit: str = "rad", tcp_x_mm: float = 74.1,
    joint_zero_offset_deg: Sequence[float] = (0.0, 0.0, 0.0, 0.0, 0.0), table_z_offset_mm: float = 0.0,
) -> dict[str, Any]:
    """Compute exact 3D `mm` positions (`[x_mm, y_mm, z_mm]`) and `z_mm` heights for every OMX-AI landmark in `link0`."""
    if len(joints) < 5:
        raise ValueError("fk_landmarks_mm requires at least 5 joint values (joint1..joint5)")
    q_rad = [(math.radians(float(joints[i]) * 1.8) if unit == "norm" else (math.radians(float(joints[i])) if unit == "deg" else float(joints[i]))) - math.radians(float(joint_zero_offset_deg[i] if i < len(joint_zero_offset_deg) else 0.0)) for i in range(5)]
    z0, p_j1, r1 = float(table_z_offset_mm), [-11.25, 0.0, 34.0 + float(table_z_offset_mm)], _rot_z(q_rad[0])
    p_j2, r2 = _add3(p_j1, _matvec(r1, (0.0, 0.0, 63.5))), _matmul(r1, _rot_y(q_rad[1]))
    p_j3, r3 = _add3(p_j2, _matvec(r2, (41.5, 0.0, 113.15))), _matmul(r2, _rot_y(q_rad[2]))
    p_j4, r4 = _add3(p_j3, _matvec(r3, (162.0, 0.0, 0.0))), _matmul(r3, _rot_y(q_rad[3]))
    p_j5, r5 = _add3(p_j4, _matvec(r4, (28.7, 0.0, 0.0))), _matmul(r4, _rot_x(q_rad[4]))
    p_pivot, p_tcp = _add3(p_j5, _matvec(r5, (29.5, 0.0, 0.0))), _add3(p_j5, _matvec(r5, (float(tcp_x_mm), 0.0, 0.0)))
    p_tcp_stock, p_tcp_legacy, p_wrist_cam = _add3(p_j5, _matvec(r5, (91.93, 0.0, 0.0))), _add3(p_j5, _matvec(r5, (88.5, 0.0, 0.0))), _add3(p_j5, _matvec(r5, (36.24, 0.0, 45.84)))
    cam_opt_world = _matvec(r5, (math.cos(math.radians(38.0)), 0.0, -math.sin(math.radians(38.0))))
    landmarks = {
        "base_bottom": [0.0, 0.0, round(z0, 3)], "base_plate_top": [0.0, 0.0, round(13.0 + z0, 3)],
        "servo_mount_top": [0.0, 0.0, round(32.0 + z0, 3)], "link1_top": [-11.25, 0.0, round(57.5 + z0, 3)],
        "joint1": [round(v, 3) for v in p_j1], "joint2": p_j2, "joint3": p_j3, "joint4": p_j4, "joint5": p_j5,
        "gripper_pivot": p_pivot, "wrist_cam": p_wrist_cam, "tcp": p_tcp, "jaw_tip": p_tcp,
        "tcp_stock_91_93mm": p_tcp_stock, "tcp_legacy_88_5mm": p_tcp_legacy,
    }
    return {
        "schema": Z_PROFILE_SCHEMA, "tcp_x_mm": round(float(tcp_x_mm), 2), "tcp_xyz_mm": [round(float(v), 3) for v in p_tcp],
        "table_z_offset_mm": round(z0, 3), "landmarks_xyz_mm": landmarks, "landmarks_z_mm": {k: round(float(v[2]), 3) for k, v in landmarks.items()},
        "approach_axis": [round(r5[0][0], 5), round(r5[1][0], 5), round(r5[2][0], 5)],
        "wrist_cam_optical_axis": [round(cam_opt_world[0], 5), round(cam_opt_world[1], 5), round(cam_opt_world[2], 5)],
        "wrist_cam_pitch_from_approach_deg": 38.0, "wrist_cam_height_above_tcp_mm": round(float(p_wrist_cam[2] - p_tcp[2]), 2),
        "top_down_pitch_sum_deg": round(math.degrees(q_rad[1] + q_rad[2] + q_rad[3]), 2),
    }


def fk_tcp_z_mm_from_joints_rad(joints_rad: Sequence[float], *, tcp_x_mm: float = 74.1, table_z_offset_mm: float = 0.0) -> float:
    return float(fk_landmarks_mm(joints_rad, unit="rad", tcp_x_mm=tcp_x_mm, table_z_offset_mm=table_z_offset_mm)["landmarks_z_mm"]["tcp"])


def reconcile_tcp_z_mm(z_plan_mm: float, *, plan_tcp_x_mm: float = 88.5, physical_tcp_x_mm: float = 74.1, table_fk_offset_mm: float = -8.3) -> dict[str, float]:
    tcp_delta_mm = float(plan_tcp_x_mm) - float(physical_tcp_x_mm)
    cad_jaw_tip_z_mm = float(z_plan_mm) + tcp_delta_mm
    physical_jaw_tip_z_mm = cad_jaw_tip_z_mm + float(table_fk_offset_mm)
    return {"plan_z_mm": round(float(z_plan_mm), 2), "plan_tcp_x_mm": round(float(plan_tcp_x_mm), 2), "physical_tcp_x_mm": round(float(physical_tcp_x_mm), 2),
            "tcp_length_delta_mm": round(tcp_delta_mm, 2), "table_fk_offset_mm": round(float(table_fk_offset_mm), 2), "cad_jaw_tip_z_mm": round(cad_jaw_tip_z_mm, 2),
            "physical_jaw_tip_z_mm": round(physical_jaw_tip_z_mm, 2), "above_base_plate_top_mm": round(physical_jaw_tip_z_mm - 13.0, 2)}


class SideViewZProfile:
    """Vertical pixel-to-millimeter (`v_px <-> z_mm`) projection for the Side View camera (`Jieli`, 640×480)."""

    def __init__(self, *, v_z0_px: float = 315.0, mm_per_px_z: float = 0.46875, u_m_per_px: float = 0.00070, datum_z_offset_mm: float = 0.0, datum_slope_v_per_u: float = 0.0, u_ref_px: float = 272.0, k1: float = 0.0, k2: float = 0.0, anchors: dict[str, Any] | None = None) -> None:
        self.v_z0_px, self.mm_per_px_z, self.u_m_per_px = float(v_z0_px), float(mm_per_px_z), float(u_m_per_px)
        self.datum_z_offset_mm, self.datum_slope_v_per_u, self.u_ref_px, self.k1, self.k2 = float(datum_z_offset_mm), float(datum_slope_v_per_u), float(u_ref_px), float(k1), float(k2)
        self.anchors = dict(anchors or {
            "surface_z0": {"v_px": round(self.v_z0_px, 1), "z_mm": 0.0},
            "visual_datum": {"v_px": round(self.z_mm_to_v(self.datum_z_offset_mm), 1), "z_mm": round(self.datum_z_offset_mm, 2)},
            "base_plate_top": {"v_px": round(self.z_mm_to_v(13.0), 1), "z_mm": 13.0},
            "tier1_top": {"v_px": round(self.z_mm_to_v(30.0), 1), "z_mm": 30.0},
            "tier2_top": {"v_px": round(self.z_mm_to_v(60.0), 1), "z_mm": 60.0},
            "tier3_top": {"v_px": round(self.z_mm_to_v(90.0), 1), "z_mm": 90.0},
            "joint2_shoulder": {"v_px": round(self.z_mm_to_v(97.5), 1), "z_mm": 97.5},
        })

    @classmethod
    def fit_from_landmarks(cls, landmarks_v_and_z_mm: Sequence[tuple[float, float]], *, datum_z_offset_mm: float = 0.0, datum_slope_v_per_u: float = 0.0, k1: float = 0.0, k2: float = 0.0) -> "SideViewZProfile":
        pts = [(float(v), float(z)) for v, z in landmarks_v_and_z_mm]
        if len(pts) < 2 or (denom := sum((v - (v_mean := sum(p[0] for p in pts) / len(pts))) ** 2 for v, _ in pts)) < 1e-6:
            return cls(datum_z_offset_mm=datum_z_offset_mm, datum_slope_v_per_u=datum_slope_v_per_u, k1=k1, k2=k2)
        z_mean = sum(p[1] for p in pts) / len(pts)
        slope = sum((v - v_mean) * (z - z_mean) for v, z in pts) / denom
        mm_per_px_z = max(0.15, min(1.50, -slope if slope < 0 else abs(slope)))
        return cls(v_z0_px=round(v_mean + (z_mean / mm_per_px_z), 2), mm_per_px_z=round(mm_per_px_z, 5), datum_z_offset_mm=datum_z_offset_mm, datum_slope_v_per_u=datum_slope_v_per_u, k1=k1, k2=k2, anchors={f"pt_{i}": {"v_px": round(v, 1), "z_mm": round(z, 2)} for i, (v, z) in enumerate(pts)})

    def undistort_uv(self, u_px: float, v_px: float, width: int = 640, height: int = 480) -> tuple[float, float]:
        if abs(self.k1) < 1e-7 and abs(self.k2) < 1e-7:
            return float(u_px), float(v_px)
        cx, cy, f = 0.5 * float(width), 0.5 * float(height), 540.0
        xn, yn = (float(u_px) - cx) / f, (float(v_px) - cy) / f
        r2 = xn * xn + yn * yn
        scale = 1.0 / max(0.75, 1.0 + self.k1 * r2 + self.k2 * r2 * r2)
        return round(cx + xn * scale * f, 2), round(cy + yn * scale * f, 2)

    def datum_v_at_u(self, u_px: float = 272.0) -> float:
        return round(self.z_mm_to_v(self.datum_z_offset_mm) + self.datum_slope_v_per_u * (float(u_px) - self.u_ref_px), 2)

    def v_to_z_mm(self, v_px: float, u_px: float | None = None) -> float:
        if u_px is None:
            return round((self.v_z0_px - float(v_px)) * self.mm_per_px_z, 2)
        u_u, v_u = self.undistort_uv(float(u_px), float(v_px))
        return round(((self.v_z0_px + self.datum_slope_v_per_u * (u_u - self.u_ref_px)) - v_u) * self.mm_per_px_z, 2)

    def z_mm_to_v(self, z_mm: float) -> float:
        return round(self.v_z0_px - (float(z_mm) / max(self.mm_per_px_z, 1e-6)), 1)

    def tier_band_mm(self, tier: int) -> dict[str, float]:
        t = int(tier) if int(tier) in (1, 2, 3) else 1
        z_bot, z_top, z_mid, z_grasp = TIER_SURFACE_Z_MM[t], TIER_TOP_Z_MM[t], TIER_MID_Z_MM[t], TIER_GRASP_Z_MM[t]
        return {"tier": t, "surface_z_mm": z_bot, "mid_z_mm": z_mid, "grasp_z_mm": z_grasp, "top_z_mm": z_top, "v_bottom_px": self.z_mm_to_v(z_bot), "v_mid_px": self.z_mm_to_v(z_mid), "v_grasp_px": self.z_mm_to_v(z_grasp), "v_top_px": self.z_mm_to_v(z_top)}

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema": Z_PROFILE_SCHEMA, "v_z0_px": round(self.v_z0_px, 2), "mm_per_px_z": round(self.mm_per_px_z, 5),
            "u_mm_per_px": round(self.u_m_per_px * 1000.0, 4), "datum_z_offset_mm": round(self.datum_z_offset_mm, 2),
            "datum_slope_v_per_u": round(self.datum_slope_v_per_u, 6), "u_ref_px": round(self.u_ref_px, 1), "k1": round(self.k1, 5), "k2": round(self.k2, 5),
            "landmarks_v_px": {"surface_0mm": self.z_mm_to_v(0.0), "visual_datum_px": self.z_mm_to_v(self.datum_z_offset_mm), "base_plate_top_13mm": self.z_mm_to_v(13.0), "tier1_top_30mm": self.z_mm_to_v(30.0), "tier2_top_60mm": self.z_mm_to_v(60.0), "tier3_top_90mm": self.z_mm_to_v(90.0), "joint2_shoulder_97_5mm": self.z_mm_to_v(97.5)},
            "anchors": self.anchors,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any] | None) -> "SideViewZProfile":
        if not isinstance(data, dict):
            return cls()
        return cls(v_z0_px=float(data.get("v_z0_px", 315.0)), mm_per_px_z=float(data.get("mm_per_px_z", 0.46875)), u_m_per_px=float(data.get("u_mm_per_px", 0.70)) / 1000.0, datum_z_offset_mm=float(data.get("datum_z_offset_mm", 0.0)), datum_slope_v_per_u=float(data.get("datum_slope_v_per_u", 0.0)), u_ref_px=float(data.get("u_ref_px", 272.0)), k1=float(data.get("k1", 0.0)), k2=float(data.get("k2", 0.0)), anchors=data.get("anchors"))


class TopDepthZProfile:
    """Top-View Depth (`D435 Z16`) self-profile gauge anchored to the OMX-AI `13.0 mm` base plate (`PR33_C02_BASE`)."""

    def __init__(self, *, measured_plate_top_mm: float | None = 13.0, cad_plate_top_mm: float = 13.0, pallet_surface_mm: float = 0.0) -> None:
        self.cad_plate_top_mm = float(cad_plate_top_mm)
        self.measured_plate_top_mm = float(measured_plate_top_mm) if measured_plate_top_mm is not None else None
        self.depth_scale = round(self.cad_plate_top_mm / self.measured_plate_top_mm, 4) if (self.measured_plate_top_mm is not None and 7.0 <= self.measured_plate_top_mm <= 22.0) else 1.0
        self.pallet_surface_mm = float(pallet_surface_mm)

    def raw_height_to_link0_z_mm(self, raw_height_above_table_mm: float) -> float:
        return round(float(raw_height_above_table_mm) * self.depth_scale, 2)

    def raw_height_to_pallet_z_mm(self, raw_height_above_table_mm: float) -> float:
        return round(self.raw_height_to_link0_z_mm(raw_height_above_table_mm) - self.pallet_surface_mm, 2)

    def to_dict(self) -> dict[str, Any]:
        return {"cad_plate_top_mm": self.cad_plate_top_mm, "measured_plate_top_mm": self.measured_plate_top_mm, "depth_scale": self.depth_scale, "pallet_surface_mm": round(self.pallet_surface_mm, 2)}


SIDE_CAMERA_PROFILE: dict[str, Any] = SideViewZProfile().to_dict()
TOP_CAMERA_PROFILE: dict[str, Any] = TopDepthZProfile().to_dict()


def top_depth_to_z_mm(depth_or_height_mm: float, *, table_depth_mm: float | None = None, measured_plate_top_mm: float | None = 13.0, pallet_surface_mm: float = 0.0) -> float:
    raw_h = (float(table_depth_mm) - float(depth_or_height_mm)) if table_depth_mm is not None else float(depth_or_height_mm)
    return TopDepthZProfile(measured_plate_top_mm=measured_plate_top_mm, pallet_surface_mm=pallet_surface_mm).raw_height_to_pallet_z_mm(raw_h)


def side_pixel_v_to_z_mm(v_px: float, u_px: float | None = None, profile: dict[str, Any] | SideViewZProfile | None = None) -> float:
    return (profile if isinstance(profile, SideViewZProfile) else SideViewZProfile.from_dict(profile)).v_to_z_mm(v_px, u_px=u_px)


def z_mm_to_side_pixel_v(z_mm: float, profile: dict[str, Any] | SideViewZProfile | None = None) -> float:
    return (profile if isinstance(profile, SideViewZProfile) else SideViewZProfile.from_dict(profile)).z_mm_to_v(z_mm)


def infer_tier_from_top_z_mm(z_top_mm: float) -> int:
    return min((1, 2, 3), key=lambda t: abs(TIER_TOP_Z_MM[t] - float(z_top_mm)))


def reconcile_top_and_side_z_mm(top_z_mm: float | None, side_z_mm: float | None, *, tol_mm: float = 8.0) -> dict[str, Any]:
    if top_z_mm is not None and side_z_mm is not None:
        dz, aligned = round(float(top_z_mm) - float(side_z_mm), 2), abs(float(top_z_mm) - float(side_z_mm)) <= float(tol_mm)
        fused = round(0.65 * float(side_z_mm) + 0.35 * float(top_z_mm), 2) if aligned else round(float(side_z_mm), 2)
    elif side_z_mm is not None:
        dz, aligned, fused = 0.0, True, round(float(side_z_mm), 2)
    elif top_z_mm is not None:
        dz, aligned, fused = 0.0, True, round(float(top_z_mm), 2)
    else:
        return {"top_z_mm": None, "side_z_mm": None, "fused_z_mm": None, "dz_mm": None, "dz_top_side_mm": None, "aligned": False, "inferred_tier": None}
    return {"top_z_mm": round(float(top_z_mm), 2) if top_z_mm is not None else None, "side_z_mm": round(float(side_z_mm), 2) if side_z_mm is not None else None, "fused_z_mm": fused, "dz_mm": dz, "dz_top_side_mm": dz, "aligned": aligned, "inferred_tier": infer_tier_from_top_z_mm(fused)}


def self_calibrate_arm_z_profile(arm_id: str = "arm_b", *, landmark_observations: Sequence[tuple[float, float]] | None = None, measured_plate_top_mm: float | None = 13.0, datum_z_offset_mm: float = 0.0) -> dict[str, Any]:
    return {"schema": Z_PROFILE_SCHEMA, "arm_id": arm_id, "cad_profile_mm": dict(OMX_AI_PROFILE_MM), "side_view": SideViewZProfile.fit_from_landmarks(landmark_observations or [], datum_z_offset_mm=datum_z_offset_mm).to_dict(), "top_depth": TopDepthZProfile(measured_plate_top_mm=measured_plate_top_mm).to_dict(), "tier_grasp_z_mm": dict(TIER_GRASP_Z_MM), "tier_surface_z_mm": dict(TIER_SURFACE_Z_MM), "tier_top_z_mm": dict(TIER_TOP_Z_MM)}


def build_profile_summary(profile: dict[str, Any] | None = None, *, arm_id: str = "arm_b") -> dict[str, Any]:
    return {**dict(profile or self_calibrate_arm_z_profile(arm_id=arm_id)), "container_mm": dict(CONTAINER_MM), "container_specs_mm": {k: resolve_container_spec(k) for k in ("C1", "C2", "C3")}}


class SimRealTwin:
    """Digital twin of OMX-AI 30 Hz joint tracking (`NativeJointMotion` velocity lag + Dynamixel static PID deadband)."""

    DEFAULT_LAG_FRAMES = (0.45, 1.05, 1.68, 1.25, 0.55)
    DEFAULT_DEADBAND_UNITS = (0.04, 0.36, 0.48, 0.14, 0.22)

    def __init__(self, *, lag_frames: Sequence[float] | None = None, deadband_units: Sequence[float] | None = None, lead_gain: float = 0.85, samples: int = 0) -> None:
        self.lag_frames = [float(v) for v in (lag_frames or self.DEFAULT_LAG_FRAMES)[:5]]
        self.deadband_units = [float(v) for v in (deadband_units or self.DEFAULT_DEADBAND_UNITS)[:5]]
        self.lead_gain, self.samples = float(lead_gain), int(samples)

    def simulate_chunk_mm(self, frames: Sequence[Sequence[float]], *, ideal_frames: Sequence[Sequence[float]] | None = None, tcp_x_mm: float = 74.1) -> dict[str, Any]:
        ref = list(ideal_frames if ideal_frames is not None else frames)
        if not frames or not ref:
            return {"max_lateral_bow_mm": 0.0, "terminal_error_norm_mm": 0.0, "terminal_error_xyz_mm": [0.0, 0.0, 0.0]}
        q, u, max_lat_bow, max_x_bow, sim_xyz, ideal_xyz = [float(v) for v in frames[0][:5]], [float(v) for v in frames[0][:5]], 0.0, 0.0, [], []
        for k, f in enumerate(frames):
            r_k = [float(v) for v in f[:5]]
            if k > 0:
                for j in range(5):
                    u[j] += (1.0 / (1.0 + max(0.0, self.lag_frames[j]))) * (r_k[j] - u[j])
                    err, db = u[j] - q[j], max(0.0, self.deadband_units[j])
                    if abs(err) > db:
                        q[j] = u[j] - (db if err > 0.0 else -db)
            fk_sim = fk_landmarks_mm(q, unit="norm", tcp_x_mm=tcp_x_mm)["tcp_xyz_mm"]
            fk_ref = fk_landmarks_mm([float(v) for v in ref[min(k, len(ref) - 1)][:5]], unit="norm", tcp_x_mm=tcp_x_mm)["tcp_xyz_mm"]
            sim_xyz.append(fk_sim)
            ideal_xyz.append(fk_ref)
            max_lat_bow, max_x_bow = max(max_lat_bow, math.hypot(fk_sim[0] - fk_ref[0], fk_sim[1] - fk_ref[1])), max(max_x_bow, abs(fk_sim[0] - fk_ref[0]))
        term_err = [round(sim_xyz[-1][i] - ideal_xyz[-1][i], 2) for i in range(3)]
        return {"goal_xyz_mm": ideal_xyz[-1], "simulated_terminal_xyz_mm": sim_xyz[-1], "terminal_error_xyz_mm": term_err, "terminal_error_norm_mm": round(math.sqrt(sum(e * e for e in term_err)), 2), "max_lateral_bow_mm": round(max_lat_bow, 2), "max_x_bow_mm": round(max_x_bow, 2)}

    def compensate_vertical_triplet(self, down_frames: Sequence[Sequence[float]], hold_frames: Sequence[Sequence[float]], lift_frames: Sequence[Sequence[float]], *, fps: int = 30, tcp_x_mm: float = 74.1) -> dict[str, Any]:
        down, hold, lift = [list(f) for f in down_frames], [list(f) for f in hold_frames], [list(f) for f in lift_frames]
        if len(down) < 3 or not hold or not lift:
            return {"down": down, "hold": hold, "lift": lift, "terminal_offset_units": [0.0] * 5}
        before_sim = self.simulate_chunk_mm(down, ideal_frames=down, tcp_x_mm=tcp_x_mm)
        base_step = max((abs(down[k][j] - down[k - 1][j]) for k in range(1, len(down)) for j in range(5)), default=0.14)
        max_step, net = max(0.84 * (5.0 / max(1, int(fps))), base_step + 0.12), [down[-1][j] - down[0][j] for j in range(5)]
        term_off = [max(-0.75, min(0.75, (1.0 if net[j] > 0.0 else -1.0) * self.deadband_units[j])) if abs(net[j]) > 0.15 else 0.0 for j in range(5)]
        comp_down, n_down, ramp_len = [list(down[0])], len(down), max(6.0, min(16.0, 0.35 * len(down)))
        for k in range(1, n_down):
            prev, row, ramp, fade = comp_down[-1], list(down[k]), min(1.0, k / ramp_len), min(1.0, (n_down - 1 - k) / 6.0)
            for j in range(5):
                lead = max(-0.45, min(0.45, self.lead_gain * self.lag_frames[j] * (down[k][j] - down[k - 1][j]))) * fade
                row[j] = round(max(-100.0, min(100.0, prev[j] + max(-max_step, min(max_step, (down[k][j] + ramp * term_off[j] + lead) - prev[j])))), 3)
            comp_down.append(row)
        end_off = [round(comp_down[-1][j] - down[-1][j], 3) for j in range(5)]
        comp_hold = [[round(max(-100.0, min(100.0, f[j] + end_off[j])), 3) for j in range(5)] + [round(float(f[5]), 3)] for f in hold]
        comp_lift, n_lift, lift_ramp = [list(comp_hold[-1][:5]) + [round(float(lift[0][5]), 3)]], len(lift), max(6.0, min(16.0, 0.35 * len(lift)))
        for k in range(1, n_lift):
            prev, row, decay = comp_lift[-1], list(lift[k]), max(0.0, 1.0 - (k / lift_ramp))
            for j in range(5):
                row[j] = round(max(-100.0, min(100.0, prev[j] + max(-max_step, min(max_step, (lift[k][j] + decay * end_off[j]) - prev[j])))), 3)
            comp_lift.append(row)
        return {"down": comp_down, "hold": comp_hold, "lift": comp_lift, "terminal_offset_units": end_off, "before_sim": before_sim, "after_sim": self.simulate_chunk_mm(comp_down, ideal_frames=down, tcp_x_mm=tcp_x_mm)}

    def update_from_real_tracking(self, tracking_list: Sequence[dict[str, Any] | None]) -> "SimRealTwin":
        updated, alpha = False, (0.35 if self.samples > 0 else 0.50)
        for tr in tracking_list:
            if isinstance(tr, dict) and tr.get("ok") and isinstance(lags := tr.get("joint_lags_units"), list) and len(lags) >= 5:
                for j in range(5):
                    if 0.02 <= (obs := abs(float(lags[j]))) <= 1.50:
                        self.deadband_units[j] = round((1.0 - alpha) * self.deadband_units[j] + alpha * max(0.02, min(0.75, obs)), 4)
                        updated = True
        if updated:
            self.samples += 1
        return self

    def to_dict(self) -> dict[str, Any]:
        return {"lag_frames": [round(v, 3) for v in self.lag_frames], "deadband_units": [round(v, 4) for v in self.deadband_units], "lead_gain": round(self.lead_gain, 3), "samples": self.samples}

    @classmethod
    def from_dict(cls, data: dict[str, Any] | None) -> "SimRealTwin":
        if not isinstance(data, dict):
            return cls()
        return cls(lag_frames=data.get("lag_frames"), deadband_units=data.get("deadband_units"), lead_gain=float(data.get("lead_gain", 0.85)), samples=int(data.get("samples", 0)))
