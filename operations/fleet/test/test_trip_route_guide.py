"""Fleet route priors use the selected plan and authority's exact pose sample."""

from dataclasses import replace

import pytest

from fleet.server.console_view import trip_caps
from test_trip_authority import AUTH, _setup, _ticks
from test_lane_traffic import _trip


def setup_guide(**pose_changes):
    caps = replace(AUTH, line_follow_route_guide=True, line_follow_authority_shrink=True)
    runner, store, fleet = _setup({'a': caps})
    _trip(runner, store, fleet, 'a', 'east:fwd', .3)
    fleet.p['a'].pose = replace(fleet.p['a'].pose, **{'map_id': store.active()[1].map_id, **pose_changes})
    _ticks(runner, fleet, dt=.1)
    return runner, store, fleet


def test_capability_is_explicit_and_defaults_off():
    item = dict(kind='base_velocity', robot_kind='pinky_pro', drive_modes=['lane'], trip_max_linear=.1)
    assert not trip_caps({'controls': {'items': [item]}}).line_follow_route_guide
    item['line_follow_route_guide'] = True
    assert trip_caps({'controls': {'items': [item]}}).line_follow_route_guide


def test_real_trip_period_attaches_selected_route_to_authority():
    runner, store, fleet = setup_guide()
    live = runner._live['a']
    assert getattr(live, 'route_guide_sample', None) is not None, (live.at, live.at_stamp, fleet.p['a'].pose,
        live.view['caps'], live.view['hold'], live.view['pose_observed_at'], live.segments)
    body = fleet.bodies['a'][-1]
    guide = body['route_guide']
    assert body['pose_stamp'] == fleet.p['a'].pose.odom_stamp
    assert guide['map_id'] == store.active()[1].map_id
    assert guide['map_revision'] == store.active()[0]
    assert guide['ahead_m'] == pytest.approx(.25)
    assert guide['heading_here_deg'] == pytest.approx(0.)
    assert guide['off_route_m'] == pytest.approx(0.)
    assert guide['max_age_s'] <= 1.
    assert 'route_guide' not in runner.authority.shrink(runner._live['a'])


@pytest.mark.parametrize('change', ['stamp', 'route', 'plan', 'age', 'hold'])
def test_changed_context_cannot_attach_captured_route_prior(change):
    runner, _, fleet = setup_guide()
    live = runner._live['a']
    if change == 'stamp':
        live.traffic['pose_stamp'] += .01
    elif change == 'route':
        live.route_rev += 1
    elif change == 'plan':
        live.segments[-1]['s_to'] -= .01
    elif change == 'age':
        fleet.advance(1.)
    else:
        live.view['hold'] = {'reason': 'test'}
    assert 'route_guide' not in runner.authority.body(live)


def test_old_pose_cannot_produce_direction():
    _, _, fleet = setup_guide(age_s=1.1)
    assert 'route_guide' not in fleet.bodies['a'][-1]


@pytest.mark.parametrize('map_id', [None, 'another-map'])
def test_unbound_map_frame_cannot_produce_direction(map_id):
    _, _, fleet = setup_guide(map_id=map_id)
    assert 'route_guide' not in fleet.bodies['a'][-1]


@pytest.mark.parametrize('side', [.04, -.04])
def test_the_route_prior_signs_the_offset_left_of_the_travel_direction(side):
    """D-769 rev 2: the camera's way choice needs which side of the route centre line the robot is on."""
    import math
    runner, _, fleet = setup_guide()
    pose = fleet.p['a'].pose
    tangent = runner._live['a'].arc(runner._live['a'].view['segment_index']).project(pose.x, pose.y)[2]
    # moved square to the lane (+ = left of the travel direction), so the plan station stays the same
    runner, _, fleet = setup_guide(x=pose.x - math.sin(tangent) * side, y=pose.y + math.cos(tangent) * side)
    guide = fleet.bodies['a'][-1]['route_guide']
    assert guide['off_route_left_m'] == pytest.approx(side, abs=1e-3)
    assert guide['off_route_m'] == pytest.approx(abs(side), abs=1e-3)
