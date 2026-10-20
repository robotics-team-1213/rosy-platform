"""A measured curved departure ends this location's limited alignment episode."""
import copy
import json
import math
from pathlib import Path

from control.sensing.perception.drivable.drivable_steer import DrivableSteer
from control.sensing.perception.drivable.route_guard import RouteBridge, _observed_turn
from control.sensing.perception.learned.paint_motion import OdomHistory


def recorded():
    data = json.loads((Path(__file__).parent / 'fixtures' /
        'drivable_curve_episode_20261020.json').read_text())
    history = OdomHistory(maxlen=len(data['odom']) + 1)
    for sample in data['odom']:
        history.add(*sample)
    owner = DrivableSteer()
    owner._ctx = dict(fresh=True, guide=True, here=data['here'], ahead=data['ahead'])
    return data, history, owner


def test_recorded_curve_agrees_with_the_near_heading_even_when_the_far_chord_turns():
    data, history, owner = recorded()
    assert _observed_turn(data['info'], history.pose_at(data['source_stamp']),
                          history.pose_at(data['stamp']), owner)


def test_measured_curved_progress_releases_the_old_spent_episode_before_the_next_pivot():
    data, history, owner = recorded()
    guard = RouteBridge()
    times = [data['origin_stamp'] + i / 8 for i in range(35)]
    poses = [history.pose_at(t) for t in times]
    used = sum(abs(math.remainder(b[2] - a[2], math.tau)) for a, b in zip(poses, poses[1:]))
    assert used > data['limit']
    guard._alignment = dict(origin=poses[0], last=poses[-1], stamp=times[-1],
        observed=data['origin_observed'], used=used, limit=data['limit'], side='right', uncertain=False)
    result = guard.step(data['error'], data['confidence'], copy.deepcopy(data['info']),
        history.pose_at(data['stamp']), owner, source_pose=history.pose_at(data['source_stamp']),
        current_stamp=data['stamp'], observation_stamp=data['source_stamp'])
    assert result[:2] == (data['error'], data['confidence'])
    assert guard._alignment is None
    pivot = dict(data['info'], strategy='drivable_pivot_left', target_m=None)
    assert guard.step(-.5, .35, pivot, history.pose_at(138.125), owner,
        source_pose=history.pose_at(138.), current_stamp=138.125, observation_stamp=138.)[2]['strategy'] == 'drivable_pivot_left'


def test_a_sideways_first_segment_cannot_masquerade_as_a_matching_near_heading():
    data, history, owner = recorded()
    info = copy.deepcopy(data['info'])
    info['centre_path_m'][:2] = [[.139118, 0.], [.140118, .02]]
    owner._ctx['here'] = 0.
    assert not _observed_turn(info, history.pose_at(data['source_stamp']),
                              history.pose_at(data['stamp']), owner)
