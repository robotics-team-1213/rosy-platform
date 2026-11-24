"""Unit tests for the S3 zone-center baseline and 7-stage factory flow closure."""

from __future__ import annotations

import hashlib
import json
import math
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
for rel in ("tools/sim", "operations/fleet", "contracts/foundation"):
    p = str(REPO / rel)
    if p not in sys.path:
        sys.path.insert(0, p)

from fleet.site_map import SiteMap  # noqa: E402
from factory_flow_receipts import SCHEMA, STAGES, verify  # noqa: E402
from factory_isaac_handoff import prepare  # noqa: E402
from world_factory_close import close_factory_flow  # noqa: E402
from world_s3_baseline import S3_ZONE_PRECISION_STOP, apply_s3_zone_baseline  # noqa: E402


def _envelope() -> dict:
    return {
        "version": 368,
        "map": {
            "schema": "rosy.site_map/1",
            "map_id": "world_261026",
            "places": [
                {"id": "C2", "kind": "charge", "name": "C2", "x": -0.1914, "y": 0.47, "yaw": -1.5708},
                {"id": "S1", "kind": "stop", "name": "S1", "x": -0.66958, "y": -0.13502, "yaw": -1.570796},
                {"id": "S3", "kind": "stop", "name": "S3", "x": 0.745, "y": -0.207, "yaw": 3.141592},
            ],
            "edges": [
                {"id": "e1", "from": "C2", "to": "S1", "direction": "one_way", "drive_mode": "lane",
                 "width_m": 0.18, "speed_cap_mps": 0.15,
                 "polyline": [[-0.1914, 0.47], [-0.66958, -0.13502]]},
                {"id": "e2", "from": "S1", "to": "S3", "direction": "one_way", "drive_mode": "lane",
                 "width_m": 0.20, "speed_cap_mps": 0.15,
                 "polyline": [[-0.66958, -0.13502], [0.745, -0.207]]},
            ],
        },
    }


def _write_json(path: Path, payload: object) -> str:
    path.parent.mkdir(parents=True, exist_ok=True)
    raw = (json.dumps(payload, indent=2) + "\n").encode("utf-8")
    path.write_bytes(raw)
    return hashlib.sha256(raw).hexdigest()


def _make_prefix(root: Path, pose_xy_yaw: list[float]) -> tuple[Path, Path]:
    env = apply_s3_zone_baseline(_envelope())
    SiteMap.model_validate(env["map"])
    map_path = root / "site-map.json"
    map_sha = _write_json(map_path, env)
    bindings = {
        "run_id": "sim-test-001", "task_id": "task-1", "robot_id": "rosy_01",
        "cargo_id": "cargo-1", "site_map_sha256": map_sha,
    }
    shas = [
        _write_json(root / "ev/c2_departure.json", {**bindings, "stage": "c2_departure"}),
        _write_json(root / "ev/s1_yield.json", {**bindings, "stage": "s1_yield"}),
    ]
    obs_sha = _write_json(root / "ev/s3_stop.json", {
        "schema": "rosy.factory-s3-stop-observation.v1", **bindings,
        "source_kind": "gazebo_odom", "pose_frame": "site_map", "place_id": "S3",
        "samples": [
            {"sim_time_s": 10.0 + i * 0.25, "pose_xy_yaw": pose_xy_yaw,
             "linear_m_s": 0.0, "angular_rad_s": 0.0}
            for i in range(6)
        ],
    })
    shas.append(obs_sha)
    shas.append(_write_json(root / "ev/cell_claim.json", {
        "schema": "rosy.factory-sim-cell-claim.v1", **bindings,
        "scope": "isolated_sim", "cell_id": "cell_s", "stop_sha256": obs_sha,
        "claimed_sim_time_s": 11.75,
    }))
    names = ("ev/c2_departure.json", "ev/s1_yield.json", "ev/s3_stop.json", "ev/cell_claim.json")
    prefix_path = root / "prefix_receipts.json"
    _write_json(prefix_path, [
        {"schema": SCHEMA, **bindings, "stage": STAGES[i], "status": "pass",
         "evidence": [{"path": names[i], "sha256": shas[i]}]}
        for i in range(4)
    ])
    return prefix_path, map_path


def test_apply_s3_zone_baseline_and_rejections():
    orig = _envelope()
    updated = apply_s3_zone_baseline(orig)
    assert "precision_stop" not in orig["map"]["places"][2]
    assert updated["map"]["places"][2]["precision_stop"] == S3_ZONE_PRECISION_STOP
    SiteMap.model_validate(updated["map"])

    shifted = _envelope()
    shifted["map"]["places"][2]["x"] = 0.70
    with pytest.raises(ValueError, match="reference_pose"):
        apply_s3_zone_baseline(shifted)

    bad_limits = dict(S3_ZONE_PRECISION_STOP, position_uncertainty_m=0.03)
    with pytest.raises(ValueError, match="tolerance/uncertainty"):
        apply_s3_zone_baseline(orig, limits=bad_limits)


@pytest.mark.parametrize(
    ("pose", "should_pass"),
    [
        ([0.745, -0.207, math.pi], True),
        ([0.770, -0.220, math.pi + 0.05], True),
        ([0.745, -0.233, math.pi], False),  # 26 mm lateral > 25 mm
        ([0.786, -0.207, math.pi], False),  # 41 mm longitudinal > 40 mm
        ([0.745, -0.207, math.pi - 0.13], False),  # 0.13 rad > 0.12 rad
    ],
)
def test_s3_zone_handoff_bounds(tmp_path: Path, pose: list[float], should_pass: bool):
    prefix, site_map = _make_prefix(tmp_path / "run", pose)
    if should_pass:
        intake = prepare(prefix, site_map)
        assert intake["place_id"] == "S3"
        assert intake["cell_id"] == "cell_s"
    else:
        with pytest.raises(ValueError, match="outside measured stop bounds"):
            prepare(prefix, site_map)


def test_close_factory_flow_end_to_end_and_tamper_rejection(tmp_path: Path):
    prefix_dir = tmp_path / "prefix"
    prefix, site_map = _make_prefix(prefix_dir, [0.745, -0.207, math.pi])
    intake = prepare(prefix, site_map)
    _write_json(prefix_dir / "isaac-intake.json", intake)

    arm_s = tmp_path / "arm_s.json"
    belt = tmp_path / "belt.json"
    ab = tmp_path / "ab.json"
    _write_json(arm_s, {"stage": "arm_s_to_belt", "passed": True})
    _write_json(belt, {"stage": "belt_transit", "passed": True})
    _write_json(ab, {"stage": "ab_stack", "passed": True})

    closed = tmp_path / "closed"
    summary = close_factory_flow(prefix_dir, arm_s, belt, ab, closed)
    assert summary["stages"] == list(STAGES)
    errors, _ = verify(closed / "receipts.json")
    assert errors == []

    # Tampered intake must fail closed.
    _write_json(prefix_dir / "isaac-intake.json", {**intake, "site_map_version": 999})
    with pytest.raises(ValueError, match="does not match"):
        close_factory_flow(prefix_dir, arm_s, belt, ab, tmp_path / "bad_closed")
