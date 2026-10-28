"""Recorded geometry: a local recentre must not erase the route's near exit."""
import copy
import math

import numpy as np
import pytest

from control.sensing.perception.drivable.drivable_steer import DrivableSteer
from test_drivable_exit_admission import G, POSE, raw


def step(monkeypatch, owner, observation, key, pose=POSE, **kw):
    import control.sensing.perception.drivable.drivable_steer as module
    monkeypatch.setattr(module, 'way_target', lambda *a: copy.deepcopy(observation))
    return owner.update(np.ones((240, 320), bool), key, G, .03317, .0925, pose, pose,
                        guide_here_deg=25., guide_deg=-83., **kw)[2]


def left(ahead, target):
    result = raw()
    result.update(exit='left', seen_exit='left', exit_near={'left': True},
        exit_point_m={'left': (.19, .094)}, exit_reach_m={'left': .24},
        near_centre_m=(.163, .085), ahead_m=ahead, target_m=target)
    return result


def test_near_route_point_survives_local_recentre(monkeypatch):
    owner = DrivableSteer()
    observation = raw()
    observation['exit_point_m']['right'] = (.183, -.089)
    step(monkeypatch, owner, observation, 1.)
    middle = step(monkeypatch, owner, left(0., (.10, .10)), 2., (.07, 0., -.15))
    assert middle.get('recentre_first') and owner._side is None
    result = step(monkeypatch, owner, left(.142, (.134, .136)), 3., (.08, 0., .10))
    assert result.get('exit_from_route_memory') and result['exit'] == 'right'
    expected = (.103 * math.cos(.10) - .089 * math.sin(.10),
                -.103 * math.sin(.10) - .089 * math.cos(.10))
    assert result['exit_point_m']['right'] == pytest.approx(expected)


@pytest.mark.parametrize('invalidate', ['reset', 'route', 'wall', 'stale'])
def test_invalidated_point_cannot_return_after_latch_drop(monkeypatch, invalidate):
    from control.sensing.perception.drivable.drivable_keep import _route_transition
    owner = DrivableSteer()
    step(monkeypatch, owner, raw(), 1.)
    owner._side = None
    if invalidate == 'reset':
        owner.reset()
    elif invalidate == 'route':
        _route_transition(owner, ('new-leg',))
    elif invalidate == 'wall':
        step(monkeypatch, owner, left(.2, (.22, .04)), 2., side_clear_m={'right': .01})
    else:
        step(monkeypatch, owner, left(.2, (.22, .04)), 2., guide_fresh=False)
    result = step(monkeypatch, owner, left(.2, (.22, .04)), 3.)
    assert not result.get('exit_from_route_memory')
    assert owner._route_exit is None


def test_replayed_point_cannot_extend_original_travel_budget(monkeypatch):
    owner = DrivableSteer()
    step(monkeypatch, owner, raw(), 1.)
    hidden = left(.2, (.22, .04))
    replay = step(monkeypatch, owner, hidden, 5., (-.3, 0., 0.))
    assert replay.get('exit_from_route_memory')
    result = step(monkeypatch, owner, hidden, 8., (-.51, 0., 0.))
    assert not result.get('exit_from_route_memory') and owner._route_exit is None


@pytest.mark.parametrize('generated', [False, True])
def test_far_or_generated_point_is_not_an_observation(monkeypatch, generated):
    owner = DrivableSteer()
    observation = raw()
    observation.update(exit=None, seen_exit=None, exit_near={}, ahead_m=0.,
                       target_m=(.15, -.1))
    if generated:
        observation.update(exit_point_m={}, exit_reach_m={})
    step(monkeypatch, owner, observation, 1.)
    assert owner._route_exit is None


def test_cached_near_frame_keeps_original_source_and_stamp(monkeypatch):
    owner = DrivableSteer()
    step(monkeypatch, owner, raw(), 1.)
    original = owner._route_exit
    step(monkeypatch, owner, raw(), 1.)
    assert owner._route_exit == original


@pytest.mark.parametrize('stamp,pose', [(.5, POSE), (2., (.4, 0., 0.)), (1., (.01, 0., 0.))])
def test_clock_or_odometry_discontinuity_discards_old_point(monkeypatch, stamp, pose):
    owner = DrivableSteer()
    step(monkeypatch, owner, raw(), 1.)
    result = step(monkeypatch, owner, left(.2, (.22, .04)), stamp, pose)
    assert owner._route_exit is None and not result.get('exit_from_route_memory')


def test_wall_below_threshold_is_not_rounded_into_admission(monkeypatch):
    from control.sensing.perception.drivable.drivable_steer import SIDE_WALL_M
    owner = DrivableSteer()
    step(monkeypatch, owner, raw(), 1., side_clear_m={'right': SIDE_WALL_M - .0001})
    assert owner._route_exit is None and owner._side is None


def test_cached_source_does_not_hide_a_current_odometry_jump(monkeypatch):
    owner = DrivableSteer()
    step(monkeypatch, owner, raw(), 1.)
    import control.sensing.perception.drivable.drivable_steer as module
    monkeypatch.setattr(module, 'way_target', lambda *a: left(.2, (.22, .04)))
    result = owner.update(np.ones((240, 320), bool), 1., G, .03317, .0925,
        POSE, (.1, 0., 0.), current_stamp=1.125, guide_here_deg=25., guide_deg=-83.)[2]
    assert owner._route_exit is None and not result.get('exit_from_route_memory')
