"""Recorded geometry: a local recentre must not erase the route's near exit."""
import copy

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
    step(monkeypatch, owner, hidden, 2., (-.3, 0., 0.))
    result = step(monkeypatch, owner, hidden, 3., (-.51, 0., 0.))
    assert not result.get('exit_from_route_memory') and owner._route_exit is None
