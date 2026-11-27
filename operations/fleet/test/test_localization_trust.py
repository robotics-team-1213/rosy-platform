"""D-395 P2-2 pose trust: which snapshot poses traffic and bays may use, and the console badge."""

from __future__ import annotations

import pytest

from fleet.localization import trust


def loc(state="LOCALIZED", frame="map", **extra):
    return {"state": state, "pose_frame": frame, **extra}


def snap(localization=..., pose=(1.0, 2.0)):
    out = {"pose": {"x": pose[0], "y": pose[1], "yaw": 0.0}}
    if localization is not ...:
        out["localization"] = localization
    return out


@pytest.mark.parametrize("state, expected", [
    (snap(loc()), trust.TRUSTED),
    (snap(loc(frame="odom")), trust.UNTRUSTED),
    (snap(loc("CANDIDATES", "map")), trust.UNTRUSTED),
    (snap(loc("SUSPECT", "map")), trust.UNTRUSTED),
    (snap(loc("UNKNOWN", "odom")), trust.UNTRUSTED),
    (snap({"state": "LOCALIZED"}), trust.UNTRUSTED),      # present but malformed: not trusted
    (snap(), trust.UNTRUSTED),                                  # no field: a pre-D-395 robot
    (snap(None), trust.UNTRUSTED),                              # explicit null
    (None, trust.UNTRUSTED),
])
def test_classify(state, expected):
    assert trust.classify(state) == expected


def test_trusted_xy_only_from_localized_map_snapshots():
    """S2 Finding 1: a legacy-null pose (power-on odom) is never a *trusted* pose."""
    assert trust.trusted_xy(snap(loc())) == (1.0, 2.0)
    assert trust.trusted_xy(snap()) is None
    assert trust.trusted_xy(snap(None)) is None
    assert trust.trusted_xy(snap(loc(frame="odom"))) is None
    assert trust.trusted_xy({"localization": loc()}) is None          # no pose


def test_an_untrusted_robot_without_a_trusted_pose_blocks_every_route():
    assert trust.blocks([(0.0, 0.0), (5.0, 0.0)], None) is True
    assert trust.blocks([], None) is True


def test_an_untrusted_robot_blocks_routes_within_the_keep_out_of_its_last_trusted_pose():
    route = [(0.0, 0.0), (2.0, 0.0)]                  # one long segment: distance is to the segment
    assert trust.blocks(route, (1.0, 0.19)) is True
    assert trust.blocks(route, (1.0, 0.21)) is False
    assert trust.UNTRUSTED_KEEP_OUT_M == 0.20   # heading unknown: the circumscribed body counts, not the aligned 0.18


def test_an_unknown_route_is_not_blocked_by_a_located_obstacle():
    assert trust.blocks([], (0.0, 0.0)) is False


def test_badge_names_the_state_and_flags_legacy_and_needs_human():
    assert trust.badge(None) is None
    legacy = trust.badge(snap())
    assert legacy["legacy"] is False and legacy["label"] == "위치 모름"
    assert legacy["trusted"] is False and legacy["state"] == "UNKNOWN"
    ok = trust.badge(snap(loc()))
    assert ok == {"state": "LOCALIZED", "pose_frame": "map", "trusted": True, "legacy": False,
                  "needs_human": False, "label": "위치 확정"}
    odom = trust.badge(snap(loc("CANDIDATES", "odom")))
    assert odom["trusted"] is False and odom["state"] == "CANDIDATES"
    assert trust.badge(snap(loc("CANDIDATES", "odom")), {"needs_human": True})["label"] == "위치 확인 필요"
    assert trust.badge(snap(loc("SUSPECT", "map", needs_human=True)))["needs_human"] is True


def test_badge_of_a_lapsed_d395_robot_is_untrusted_not_legacy():
    lapsed = trust.badge(snap(), lapsed=True)
    assert lapsed["legacy"] is False and lapsed["trusted"] is False
    assert lapsed["label"] == "위치 모름"


def test_only_fresh_map_pose_supersedes_a_previous_recovery_ladder():
    fresh = {**snap(loc()), "timestamp": "2026-11-25T20:20:55.575+00:00",
             "evidence": {"pose": {"evidence": "fresh", "received_at": "2026-11-25T20:20:55.480+00:00"}}}
    ladder = {"rung": "needs_human", "needs_human": True, "candidates_for_s": 304.0, "rung_missions": []}

    assert trust.badge(fresh, ladder, state_age_s=1.0)["needs_human"] is False
    assert trust.ladder_for_state(fresh, ladder)["rung"] is None
    assert trust.ladder_for_state(fresh, ladder, state_age_s=2.0)["rung"] == "needs_human"
    assert ladder["rung"] == "needs_human"
    stale = trust.badge(fresh, ladder, state_age_s=2.0)
    assert stale["needs_human"] is True and stale["trusted"] is False
    assert trust.badge(None, ladder) is None

    no_pose = {**fresh, "evidence": {"pose": {"evidence": "disconnected"}}}
    assert trust.badge(no_pose, ladder)["trusted"] is False
    assert trust.badge({**fresh, "localization": loc("LOCALIZED", "odom")}, ladder)["needs_human"] is True
    assert trust.badge({**fresh, "localization": loc(needs_human=True)}, ladder)["needs_human"] is True
    manual = trust.badge(fresh, {**ladder, "pose_request": {"state": "needs_human"}})
    assert manual["needs_human"] and manual["pose_request_needs_human"]
