"""A camera centre must produce its geometric curvature under the loaded CORE law."""
import pytest

from core_events.events.bus import EventBus
from core_features.line_follow.manager import (
    LineFollowConfig, LineFollowManager, LineFollowMode, LineObservation,
)
from control.sensing.perception.drivable.drivable_steer import DrivableSteer


@pytest.mark.parametrize('cruise,gain,max_linear,min_confidence', [
    (.10, 2., .10, .35), (.08, .8, .10, .35), (.03, .4, .06, .5), (.08, .8, .10, 1.),
])
@pytest.mark.parametrize('y', [-.05, 0., .05])
@pytest.mark.parametrize('cap', [.7, .03])
def test_camera_arc_matches_actual_core_profile(cruise, gain, max_linear, min_confidence, y, cap):
    config = LineFollowConfig(cruise_speed=cruise, steering_gain=gain,
                              max_linear=max_linear, min_confidence=min_confidence)
    steer = DrivableSteer.from_config(vars(config))
    x, confidence = .25, (.9 if min_confidence < 1. else 1.)
    error = steer.pursuit_error(x, y, confidence)
    manager = LineFollowManager(EventBus('law-test'), config=config)
    observation = LineObservation(LineFollowMode.CAMERA_LINE, 1., True, error, confidence)
    linear, angular, reason = manager._steer(observation, None, cap)
    assert linear > 0. and reason == 'tracking'
    assert abs(angular) <= cap
    assert angular / linear == pytest.approx(2. * y / (x*x + y*y))


def test_gap_uses_the_same_profile_law_as_current_camera_targets():
    from control.sensing.perception.drivable.drivable_keep import _path_of
    steer = DrivableSteer.from_config(dict(cruise_speed=.10, steering_gain=2.))
    path = _path_of(steer, .0925)
    info = dict(strategy='drivable_centre', centre_path_m=((.1, 0.), (.3, .02), (.5, .08)))
    for stamp in (0., .1, .2):
        view = path.update((0., 0., 0.), stamp, info)
    assert view['committed']
    held = path.hold((.05, 0., 0.), .3)
    assert held['state'] == 'held'
    assert held['error'] == pytest.approx(steer.pursuit_error(*held['target_m'], held['confidence']))


@pytest.mark.parametrize('raw', [dict(cruise_speed=float('nan')), dict(steering_gain=0.),
                               dict(min_confidence=1.1)])
def test_invalid_profile_cannot_produce_camera_steering(raw):
    with pytest.raises(ValueError, match='CORE steering law'):
        DrivableSteer.from_config(raw)
