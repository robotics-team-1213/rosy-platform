"""A measured curve bows away from the body's straight axis inside the near view."""
import copy
import json
import math
from pathlib import Path

import pytest

from control.sensing.perception.drivable.drivable_steer import DrivableSteer
from control.sensing.perception.drivable.route_guard import RouteBridge, _observed_turn
from control.sensing.perception.learned.paint_motion import OdomHistory


def recorded(index=0):
    data = json.loads((Path(__file__).parent / 'fixtures' /
        'drivable_curve_origin_20261020.json').read_text())
    sample = data['samples'][index]
    history = OdomHistory(maxlen=len(data['odom']) + 1)
    for row in data['odom']:
        history.add(*row)
    owner = DrivableSteer()
    ctx = sample['info']['context']
    owner._ctx = dict(guide=True, fresh=ctx['fresh'], here=ctx['here_deg'], ahead=ctx['ahead_deg'])
    return data, sample, history, owner


@pytest.mark.parametrize('index', [0, 1, 2])
def test_recorded_current_curve_is_supported_even_when_it_has_bowed_from_the_straight_axis(index):
    _, sample, history, owner = recorded(index)
    assert sample['info']['centre_path_m'][0][1] > .03
    assert _observed_turn(sample['info'], history.pose_at(sample['source_stamp']),
                          history.pose_at(sample['stamp']), owner)


def test_recorded_forward_curve_releases_the_old_episode_after_measured_progress():
    data, sample, history, owner = recorded()
    bridge = RouteBridge()
    times = [data['origin_stamp'] + i / 8 for i in range(38)]
    poses = [history.pose_at(t) for t in times]
    used = sum(abs(math.remainder(b[2] - a[2], math.tau)) for a, b in zip(poses, poses[1:]))
    assert used > data['limit']
    bridge._alignment = dict(origin=poses[0], last=poses[-1], stamp=times[-1],
        observed=data['origin_observed'], used=used, limit=data['limit'], side='right', uncertain=False)
    result = bridge.step(sample['error'], sample['confidence'], copy.deepcopy(sample['info']),
        history.pose_at(sample['stamp']), owner, source_pose=history.pose_at(sample['source_stamp']),
        current_stamp=sample['stamp'], observation_stamp=sample['source_stamp'])
    assert result[:2] == (sample['error'], sample['confidence'])
    assert bridge._alignment is None


def test_a_parallel_near_path_outside_the_selected_arc_corridor_is_rejected():
    _, sample, history, owner = recorded()
    info = copy.deepcopy(sample['info'])
    for i, point in enumerate(info['centre_path_m'][:8]):
        point[1] += .05 if i < 2 else .05 * (8 - i) / 6
    assert _observed_turn(info, history.pose_at(sample['source_stamp']),
                          history.pose_at(sample['stamp']), owner) is False


@pytest.mark.parametrize('point,target,accepted', [
    ((.14, .08), (.25, .12), False),
    ((.14, .032), (.25, -.12), False),
    ((.14, .6), (.25, .12), False),
    ((.3, .45), (.2, .2), False),
    ((.14, .029), (.25, 0.), True),
    ((.14, .031), (.25, 0.), False),
    ((.14, .029), (.25, 1e-12), True),
    ((.14, 0.), (0., 0.), False),
    ((math.nan, 0.), (.25, .12), False),
    ((.14, 0.), (.25, math.inf), False),
])
def test_selected_arc_corridor_handles_offsets_opposite_curves_short_branch_and_invalid_domain(point, target, accepted):
    from control.sensing.perception.drivable.route_guard import _near_selected_arc
    assert _near_selected_arc(point, target) is accepted
