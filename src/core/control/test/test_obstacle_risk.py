from control.control.obstacle_risk import collision_risk, observation_risk
from control.control.obstacle_risk import camera_hold
from control.control.obstacle_risk import TrackedEvidence
from dataclasses import replace
import pytest


def test_future_or_malformed_packet_does_not_poison_current_observation():
    from control.control.obstacle_risk import accept_observation
    old = {'stamp': 9.9}
    for stamp in (1000., float('nan'), True, '10', -1.):
        assert accept_observation({'stamp': stamp}, old, 10.) is old
    current = {'stamp': 10.}
    assert accept_observation(current, old, 10.) is current


def track(x, y, vx=0., vy=0., state='moving'):
    return dict(position=(x, y), velocity=(vx, vy), state=state,
                age=0., observed=True, radius=.03)


def test_crossing_object_requires_yield_before_contact():
    result = collision_risk([track(.15, .3, 0., -.3)], (0., 0., 0.), .1, .08, .02)
    assert result['action'] == 'wait'


def test_diverging_object_does_not_force_wait():
    assert collision_risk([track(.5, .3, 0., .3)], (0., 0., 0.), .1, .08, .02)['action'] == 'clear'


def test_static_object_requests_replan_and_unknown_requires_wait():
    for state, action in [('stationary', 'replan'), ('unknown', 'wait')]:
        assert collision_risk([track(.15, 0., state=state)], (0., 0., 0.), .1, .08, .02)['action'] == action


def test_body_and_uncertainty_cannot_shrink_with_slow_speed():
    assert collision_risk([track(.1, 0.)], (0., 0., 0.), 0., .08, .02)['action'] == 'wait'


def test_reverse_uses_reverse_swept_path():
    assert collision_risk([track(-.15, 0.)], (0., 0., 0.), -.1, .08, .02)['action'] == 'wait'


def test_missing_stale_future_and_wrong_frame_evidence_holds():
    for evidence in [None, {'stamp': 0., 'frame': 'odom', 'tracks': []},
                     {'stamp': 2., 'frame': 'odom', 'tracks': []},
                     {'stamp': 1., 'frame': 'map', 'tracks': []}]:
        assert observation_risk(evidence, 1., (0.,0.,0.), .1, .08, .02)['action'] == 'wait'
    assert observation_risk({'stamp': 1., 'frame': 'odom', 'tracks': []}, 1.,
                            (0.,0.,0.), .1, .08, .02)['action'] == 'clear'


def test_camera_near_obstacle_and_missing_observation_require_hold():
    assert camera_hold(None, 1.) == 'camera_observation_unavailable'
    assert camera_hold({'stamp': 0., 'blocked': False}, 1.) == 'camera_observation_unavailable'
    assert camera_hold({'stamp': 1., 'blocked': True}, 1.) == 'camera_obstacle_unranged'
    assert camera_hold({'stamp': 1., 'blocked': False}, 1.) is None


def captured(tracks=None, camera=None, pose_stamp=100.):
    return TrackedEvidence.capture({'stamp': 100., 'frame': 'odom', 'tracks': tracks or []},
        camera or {'stamp': 100., 'blocked': False}, (0., 0., 0.), pose_stamp,
        source_now=100., received_at=10., radius=.08, margin=.02)


def test_frozen_tracking_preserves_wait_replan_and_camera_hold_distinctions():
    assert captured([track(.2, 0., state='stationary')]).evaluate(.1, 10.01) == {
        'action': 'limit', 'reason': 'obstacle_replan'}
    assert captured([track(.2, 0., vx=-.1)]).evaluate(.1, 10.01) == {
        'action': 'limit', 'reason': 'obstacle_wait'}
    assert captured(camera={'stamp': 100., 'blocked': True}).evaluate(.1, 10.01) == {
        'action': 'limit', 'reason': 'camera_obstacle_unranged'}
    assert captured(pose_stamp=99.5).evaluate(.1, 10.01)['action'] == 'stop'
    assert captured(camera={'stamp': 99., 'blocked': False}).evaluate(.1, 10.01)['action'] == 'stop'


def test_tracking_copy_is_bounded_and_rejects_invalid_geometry():
    with pytest.raises(ValueError):
        captured([track(.2, 0.)] * 65)
    assert captured([track(5., 0.)] * 64).evaluate(.1, 10.01)['action'] == 'clear'
    evidence = captured()
    for changes in ({'pose': [0., 0., 0.]}, {'radius': float('nan')}, {'margin': -.1}):
        assert replace(evidence, **changes).evaluate(.1, 10.01)['action'] == 'stop'
