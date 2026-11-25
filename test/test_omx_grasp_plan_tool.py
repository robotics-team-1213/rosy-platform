"""Unit tests for `cell_grasp_plan_tool`, arm_s q5 yaw wrap, and `grasp_plan` job spec."""
from __future__ import annotations

import json
import math
from pathlib import Path
import sys

import numpy as np
import pytest

ROOT = Path(__file__).resolve().parents[1]
OMX = ROOT / "deploy" / "robot" / "omx"
if str(OMX) not in sys.path:
    sys.path.insert(0, str(OMX))

import cell_area_zones as zones  # noqa: E402
import cell_grasp_plan_tool as tool  # noqa: E402
import cell_job_guards as guards  # noqa: E402
import cell_job_spec as spec  # noqa: E402


def _arm_s_plan() -> dict:
    return {
        "fps": 30,
        "tcp_x_m": 0.077,
        "grip_open": 57.4,
        "grip_closed": 48.8,
        "limits": {
            "park_reach_m": 0.24,
            "singularity_radius_m": 0.02,
            "workspace_min_m": [-0.30, -0.30, 0.00],
            "workspace_max_m": [0.30, 0.30, 0.35],
            "joints_rad": {
                "joint1": [-2.2, 2.2],
                "joint2": [-1.8, 1.8],
                "joint3": [-1.8, 2.2],
                "joint4": [-1.8, 2.1],
                "joint5": [-2.0, 2.0],
            },
        },
    }


def _arm_s_gripper(closing_offset: float | None = 90.0) -> dict:
    return {
        "tcp_x_m": 0.077,
        "held_30mm": 54.3,
        "gap_mm_per_unit": 5.0,
        "open_max_units": 58.15,
        "grip_closed_units": 48.8,
        "closing_axis_offset_deg": closing_offset,
        "nominal_margin_cm": 0.95,
        "min_margin_cm": 0.20,
        "max_margin_cm": 1.60,
    }


def test_evaluate_grasp_feasibility_rejects_long_axis_and_accepts_short_axis():
    obj = {
        "object_id": "container-2",
        "width_cm": 3.07,
        "length_cm": 6.76,
        "long_axis_deg": -88.6,
        "jaw_axis_deg_from_long": 90.0,
        "kg": 0.04,
    }
    plan = _arm_s_plan()
    grip = _arm_s_gripper(90.0)

    bad = tool.evaluate_grasp_feasibility(
        arm_id="arm_s",
        object_spec=obj,
        pick={"raw_xy_m": [0.0804, 0.1249], "z_m": 0.028, "yaw_override_deg": 1.4, "angle_err_deg": 0.0},
        gripper=grip,
        plan=plan,
    )
    assert bad["feasible"] is False
    assert any(r.startswith("jaw_span_exceeds_max:") for r in bad["refusal_reasons"])
    assert bad["metrics"]["max_jaw_open_cm"] == pytest.approx(4.925, abs=1e-3)
    assert bad["metrics"]["projected_span_cm"] == pytest.approx(6.76, abs=0.01)

    good = tool.evaluate_grasp_feasibility(
        arm_id="arm_s",
        object_spec=obj,
        pick={"raw_xy_m": [0.0804, 0.1249], "z_m": 0.028, "angle_err_deg": 5.0},
        gripper=grip,
        plan=plan,
        place={"xy_m": [0.095, -0.130], "z_m": 0.052, "dest_long_axis_deg": -96.5, "corridor_width_cm": 8.5},
        operating_conditions={"payload_max_kg": 0.15},
    )
    assert good["feasible"] is True, good
    assert good["metrics"]["pick_yaw_deg"] == pytest.approx(91.4, abs=0.2)
    assert good["metrics"]["place_yaw_deg"] == pytest.approx(-96.5, abs=0.5)
    assert good["metrics"]["max_angle_err_deg"] > 10.0
    assert good["metrics"]["pick_q5_margin_deg"] is not None and good["metrics"]["pick_q5_margin_deg"] > 10.0


def test_evaluate_grasp_feasibility_refusals_reach_workspace_q5_payload():
    obj = {"object_id": "container-2", "width_cm": 9.0, "length_cm": 10.0, "long_axis_deg": 0.0, "kg": None}
    plan = _arm_s_plan()
    plan["limits"]["park_reach_m"] = 0.20
    plan["limits"]["joints_rad"]["joint5"] = [-0.2, 0.2]

    res = tool.evaluate_grasp_feasibility(
        arm_id="arm_s",
        object_spec=obj,
        pick={"raw_xy_m": [0.29, 0.02], "z_m": 0.010, "surface_z_m": 0.012, "yaw_override_deg": 45.0},
        gripper=_arm_s_gripper(None),
        plan=plan,
        place={"xy_m": [0.09, -0.13], "z_m": 0.052, "dest_long_axis_deg": -90.0, "corridor_width_cm": 8.5},
        operating_conditions={"payload_max_kg": 0.10},
    )
    assert res["feasible"] is False
    joined = " | ".join(res["refusal_reasons"])
    assert "closing_offset_unmeasured" in joined
    assert "jaw_span_exceeds_max" in joined
    assert "depth_below_surface" in joined
    assert "workspace_out_of_bounds" in joined
    assert "reach_out_of_limit" in joined
    assert "corridor_width_exceeded" in joined
    assert "payload" in joined

    q5_bad = tool.evaluate_grasp_feasibility(
        arm_id="arm_s",
        object_spec={"object_id": "container-2", "width_cm": 3.07, "length_cm": 6.76, "long_axis_deg": -88.6, "kg": 0.04},
        pick={"raw_xy_m": [0.0804, 0.1249], "z_m": 0.028, "yaw_override_deg": -88.6},
        gripper=_arm_s_gripper(90.0),
        plan=plan,
    )
    assert not q5_bad["feasible"] and any("wrist_roll_out_of_range" in r for r in q5_bad["refusal_reasons"])


def test_normalize_pick_yaw_deg_uses_q5_bounds_without_changing_arm_b_default():
    assert zones.normalize_pick_yaw_deg(-88.6) == pytest.approx(-88.6)
    # With arm_s q5 in [-2.0, 2.0] rad and floor pan ~57 deg, -88.6 puts wrist roll outside [-114.6, 114.6]
    # unless flipped +180 deg to +91.4 deg.
    flipped = zones.normalize_pick_yaw_deg(-88.6, x_m=0.0804, y_m=0.1249, q5_bounds_rad=(-2.0, 2.0))
    assert flipped == pytest.approx(91.4, abs=0.1)


def test_plan_site_grasp_with_obb_override_builds_ready_job_body(tmp_path: Path):
    cal = {
        "schema": "rosy.cell-pivot.v1",
        "sites": {
            "floor": {"model": "homography", "H": np.eye(3).tolist()},
            "belt": {"model": "homography", "H": np.eye(3).tolist()},
        },
    }
    cfg = {
        "work_dir": str(tmp_path),
        "tcp_x_m": 0.077,
        "closing_axis_offset_deg": 90.0,
        "params": {},
        "plan": _arm_s_plan(),
        "operating_conditions": {"payload_max_kg": 0.15},
        "sites": {
            "floor": {"surface_z": 0.004, "grasp_depth_m": 0.008, "detect_roi": [0, 0, 640, 480]},
            "belt": {"surface_z": 0.032, "grasp_depth_m": 0.008, "place": [0.095, -0.130], "yaw_deg": -96.5},
        },
    }
    catalog = [{
        "id": "container-2", "width_mm": 30.7, "length_mm": 67.6, "top_height_mm": 32.0,
        "tolerance_mm": 6.0, "grasp": {"jaw_axis_deg_from_long": 90.0}, "mass_kg": 0.04,
    }]
    obb = {
        "matched": True,
        "object": "container-2",
        "colour": "yellow",
        "raw_m": [0.0804, 0.1249],
        "long_axis_deg": -88.6,
        "width_mm": 30.7,
        "length_mm": 67.6,
    }
    out = tool.plan_site_grasp(
        arm_id="arm_s", config=cfg, config_name="cell-arm-s.json", catalog=catalog, catalog_name="cat.json",
        cal=cal, source="floor", dest="belt", colour="yellow", obb_override=obb,
    )
    assert out["feasible"] is True, out
    body = out["ready_job_body"]
    assert body["arm"] == "arm_s" and body["object"] == "container-2"
    assert body["pick_yaw_deg"] == pytest.approx(91.4, abs=0.2)
    assert "person_at_switch" not in body


def test_grasp_plan_job_spec_and_area_xyz_pick_optional_fields(tmp_path: Path):
    wd = tmp_path / "wd"
    wd.mkdir()
    for name in ("cell-arm-s.json", "catalog-live.json"):
        (wd / name).write_text("{}", encoding="utf-8")

    job = spec.JOBS["grasp_plan"]
    assert spec.moves_arm(job, {}) is False
    params = {"arm": "arm_s", "config": "cell-arm-s.json", "catalog": "catalog-live.json", "source": "floor", "dest": "belt", "colour": "yellow"}
    eff, err = guards.authorize_principal("grasp_plan", job, params, guards.Principal(guards.ROLE_MACHINE, "cli"), moves_arm_fn=spec.moves_arm)
    assert err is None
    argv = spec.build_argv(job, eff, wd)
    assert "cell_grasp_plan_tool.py" in argv and "--colour" in argv and "yellow" in argv

    pick_job = spec.JOBS["area_xyz_pick"]
    assert "catalog" in pick_job["optional"] and "object" in pick_job["optional"]
