"""CORE judges the dock command's site_pose_evidence (Fleet session contract): position only, thresholds in DockingConfig."""

from __future__ import annotations

import pytest

from core_features.docking.model import DockingConfig
from core_features.docking.site_pose import judge_site_pose
from test_docking_bay_scan_pose import site_evidence

CFG = DockingConfig()


def test_sighting_and_track_with_a_fresh_anchor_and_a_small_residual_on_the_robots_map_are_accepted():
    for source in ("sighting", "track"):
        assert judge_site_pose(site_evidence(anchor_source=source), CFG, "map-1") == (True, None)
    assert judge_site_pose(site_evidence(identity_mode=None, camera_residual_deg=None), CFG, "map-1") == (True, None)      # identity mode and the angle are optional records


@pytest.mark.parametrize("over,words", [
    ({"anchor_source": "auto_locate"}, "auto_locate"), ({"anchor_source": "peer"}, "peer"), ({"anchor_source": "operator_pin"}, "operator_pin"),
    ({"anchor_source": None}, "anchor_source"), ({"anchor_age_s": None}, "anchor_age_s"), ({"anchor_age_s": 999.0}, "anchor_age_s"),
    ({"anchor_age_s": -1.0}, "anchor_age_s"), ({"anchor_age_s": float("nan")}, "anchor_age_s"), ({"camera_residual_m": None}, "camera_residual_m"),
    ({"camera_residual_m": 0.5}, "camera_residual_m"), ({"map_id": "map-2"}, "map_id"), ({"map_id": None}, "map_id")])
def test_anything_else_or_missing_is_rejected_with_the_reason(over, words):
    ok, why = judge_site_pose(site_evidence(**over), CFG, "map-1")
    assert ok is False and words in why


def test_no_evidence_or_an_unknown_robot_map_is_rejected_and_at_is_never_used():
    assert judge_site_pose(None, CFG, "map-1")[0] is False
    assert judge_site_pose(site_evidence(), CFG, None) == (False, "the robot's map id is unknown")
    assert judge_site_pose(site_evidence(at=-1e9), CFG, "map-1") == (True, None)               # clocks differ by ~21 s between hosts: `at` is a record only
    assert judge_site_pose(site_evidence(), DockingConfig(site_pose_max_anchor_age_s=1.0), "map-1")[0] is False      # thresholds are config, not constants


def test_the_manager_reports_the_judgement_in_status_and_the_zone_check_refuses_the_map_path_with_the_reason():
    from test_docking_bay import a_bay  # noqa: PLC0415
    from test_docking_bay_scan_pose import with_reference  # noqa: PLC0415
    p = a_bay()
    with_reference(p)
    p.manager._map_id_provider = lambda: "map-1"
    p.manager.dock(site_pose_evidence=site_evidence(anchor_source="peer"))
    status = p.manager.status()
    assert status.site_pose_verified is False and "peer" in status.site_pose_refusal
    assert "peer" in p.manager._bay_phases._map_verified(None)                            # the zone check's refusal text carries it
