"""Route priors retain their source frame when consumed by a later camera frame."""

import math

import pytest

from control.sensing.perception.drivable.drivable_keep import keep_step
from control.sensing.perception.drivable.drivable_steer import DrivableSteer
from test_drivable_keep import _Ways
from test_drivable_steer import G, HALF, XO, _lane
from core_common.protocol.lane_route_guide import LaneRouteGuide
from test_lane_route_guide_input import message
from control.lane_route_guide_input import LaneRouteGuideInput


def _consume(monkeypatch, guide, pose_at, stamp=1.5):
    steer, ways, last, received = DrivableSteer(), _Ways(_lane(HALF, -HALF)), {}, {}
    ways.stamp = stamp
    original = steer.update

    def observe(*args, **kwargs):
        received.update(kwargs)
        return original(*args, **kwargs)

    monkeypatch.setattr(steer, "update", observe)
    keep_step(steer, ways, last, G, XO, HALF, pose_at, stamp, None, guide)
    return received, last


def test_guide_angles_follow_rotation_since_source_pose(monkeypatch):
    guide = (90., 1., False, 45., 0., 0.)
    poses = lambda stamp: (0., 0., 0. if stamp == 1. else math.pi / 2)
    received, _ = _consume(monkeypatch, guide, poses)
    assert received["guide_deg"] == pytest.approx(0.)
    assert received["guide_here_deg"] == pytest.approx(-45.)


def test_future_guide_cannot_supply_direction_or_off_route_hold(monkeypatch):
    received, last = _consume(monkeypatch, (90., 2., True, 90., .3, 0.), lambda _: (0., 0., 0.))
    assert "guide_deg" not in received
    assert last.get("reason") != "off_route_hold"


def test_missing_guide_source_pose_drops_direction_prior(monkeypatch):
    received, _ = _consume(monkeypatch, (90., 1., True, 90., 0., 0.),
                           lambda stamp: None if stamp == 1. else (0., 0., 0.))
    assert "guide_deg" not in received


def test_missing_guide_pose_preserves_fresh_scalar_off_route_hold(monkeypatch):
    received, last = _consume(monkeypatch, (90., 1., True, 90., .3, 0.),
                              lambda stamp: None if stamp == 1. else (0., 0., 0.))
    assert not received
    assert last["reason"] == "off_route_hold"


@pytest.mark.parametrize("distance,has_direction", [(.25, True), (.05, False)])
def test_typed_route_prior_uses_only_sufficient_preview(monkeypatch, distance, has_direction):
    guide = LaneRouteGuide.model_validate_json(message(ahead_m=distance)).guide
    received, _ = _consume(monkeypatch, guide, lambda _: (0., 0., 0.), stamp=10.2)
    assert ("guide_deg" in received) is has_direction


def test_short_preview_still_carries_scalar_off_route_hold(monkeypatch):
    guide = LaneRouteGuide.model_validate_json(message(ahead_m=.05, off_route_m=.3)).guide
    received, last = _consume(monkeypatch, guide, lambda _: (0., 0., 0.), stamp=10.2)
    assert not received and last["reason"] == "off_route_hold"


def test_expired_typed_prior_cannot_hold_or_steer(monkeypatch):
    guide = LaneRouteGuide.model_validate_json(message(off_route_m=.3)).guide
    received, last = _consume(monkeypatch, guide, lambda _: (0., 0., 0.), stamp=10.8)
    assert "guide_deg" not in received and last.get("reason") != "off_route_hold"


def _closed_then_open():
    steer, ways, last = DrivableSteer(), _Ways(_lane(HALF, -HALF, x_max=.13)), {}
    guide = LaneRouteGuide.model_validate_json(message(heading_ahead_deg=0.)).guide
    ways.stamp = 10.1
    first = keep_step(steer, ways, last, G, XO, HALF, lambda _: (0., 0., 0.), 10.1, None, guide)
    ways.way, ways.stamp = _lane(HALF, -HALF), 10.2
    keep_step(steer, ways, last, G, XO, HALF, lambda _: (0., 0., 0.), 10.2, None, None)
    return first, last


def test_route_prior_bridges_unobserved_floor_only_at_creep():
    """D-769 rev 1: a map bridge under a route prior is a slow, bounded continuation, never full speed."""
    from control.sensing.perception.drivable.route_guard import BRIDGE_CONFIDENCE
    first, _ = _closed_then_open()
    assert first[0] is not None and first[0][1] <= BRIDGE_CONFIDENCE


def test_removed_guide_cannot_replay_cached_strategy_on_next_camera_frame():
    _, last = _closed_then_open()
    assert last["strategy"] == "drivable_centre"
    assert "switch_pending" not in last["drivable_steer"]


def test_map_only_candidate_cannot_hide_behind_previous_observed_strategy():
    steer, ways, last = DrivableSteer(), _Ways(_lane(HALF, -HALF, x_max=.13)), {}
    guide = LaneRouteGuide.model_validate_json(message(heading_ahead_deg=0.)).guide
    # Seed only the previous output: observed exit memory is a different veto.
    steer._route_identity = (guide.leg_id, guide.map_id, guide.map_revision, None)
    steer._last_out = (.1, .9, {'strategy': 'drivable_centre'})
    ways.stamp = 10.2
    result = keep_step(steer, ways, last, G, XO, HALF, lambda _: (0., 0., 0.), 10.2, None, guide)
    from control.sensing.perception.drivable.route_guard import BRIDGE_CONFIDENCE
    # D-769 rev 1: the bridge acts at once at its creep cap; the previous full-confidence output is not replayed
    assert result[0] is not None and result[0][1] <= BRIDGE_CONFIDENCE
    assert last['strategy'] == 'drivable_route_bridge' and 'switch_pending' not in last['drivable_steer']


def test_clear_and_reactivation_between_frames_discards_previous_route_decisions():
    inbox = LaneRouteGuideInput()
    inbox.receive(message(heading_ahead_deg=0.), 10.1)
    steer, ways, last = DrivableSteer(), _Ways(_lane(HALF, -HALF)), {}
    ways.stamp = 10.1
    keep_step(steer, ways, last, G, XO, HALF, lambda _: (0., 0., 0.), 10.1, None,
              inbox.for_frame(10.1), guide_generation=inbox.generation)
    steer._last_out = (.4, .7, {'strategy': 'drivable_turn_left'})
    edges, crosswalk = list(steer._edges), (0., 0., 0.)
    steer._crosswalk_pose = crosswalk
    inbox.receive(message(seq=2, clear=True), 10.15)
    inbox.receive(message(seq=3, heading_ahead_deg=0.), 10.2)
    keep_step(steer, ways, last, G, XO, HALF, lambda _: (0., 0., 0.), 10.2, None,
              inbox.for_frame(10.2), guide_generation=inbox.generation)
    assert last['strategy'] == 'drivable_centre'
    assert 'switch_pending' not in last['drivable_steer']
    assert steer._edges == edges and steer._crosswalk_pose == crosswalk


@pytest.mark.parametrize("left,side", [(.05, "right"), (-.05, "left"), (.02, None), (None, None)])
def test_a_route_prior_off_its_centre_names_the_side_the_next_way_starts_on(left, side):
    """D-769 rev 2: beyond ROUTE_SIDE_M off the route centre the paint worker prefers the run on the route's side."""
    extra = {} if left is None else dict(off_route_left_m=left, off_route_m=abs(left))
    guide = LaneRouteGuide.model_validate_json(message(**extra)).guide
    steer, ways, last = DrivableSteer(), _Ways(_lane(HALF, -HALF)), {}
    ways.stamp = 10.2
    keep_step(steer, ways, last, G, XO, HALF, lambda _: (0., 0., 0.), 10.2, None, guide)
    assert ways.route_side == side
