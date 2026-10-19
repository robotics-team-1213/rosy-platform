"""Losing a selected guide is not losing continuously observed odometry."""
import copy
import json
import math
from pathlib import Path

import pytest

from control.sensing.perception.drivable.drivable_steer import DrivableSteer
from control.sensing.perception.drivable.route_guard import RouteBridge, observed_route_candidate
from control.sensing.perception.learned.paint_motion import OdomHistory


def recorded():
    data = json.loads((Path(__file__).parent / 'fixtures' /
        'drivable_guide_gap_20261020.json').read_text())
    history = OdomHistory(maxlen=len(data['odom']) + 1)
    for sample in data['odom']:
        history.add(*sample)
    owner = DrivableSteer()
    origin = history.pose_at(data['origin_stamp'])
    bridge = owner._route_bridge = RouteBridge()
    bridge._alignment = dict(origin=origin, last=origin, stamp=data['origin_stamp'],
        observed=data['origin_observed'], used=0., limit=data['limit'], side='left', uncertain=False)
    return data, history, owner, bridge


def advance(data, history, owner, bridge, *, omit=None):
    for i in range(1, 44):
        stamp = data['origin_stamp'] + i / 8
        if stamp == omit:
            continue
        # Keep the recorded pose stream; only the final frame supplies expiry evidence.
        info = dict(strategy='drivable_turn_right', ahead_m=0., seen_exit=None)
        owner._ctx = dict(guide=stamp not in data['gap'], fresh=True, here=0.)
        observed_route_candidate(.1, .6, info, observed_only=stamp not in data['gap'], owner=owner,
            pose=history.pose_at(stamp), source_pose=history.pose_at(stamp - .125),
            current_stamp=stamp, observation_stamp=stamp - .125)
        if stamp == data['gap'][-1]:
            assert bridge._alignment['stamp'] == stamp
            if omit is None:
                assert not bridge._alignment['uncertain']
    ctx = data['info']['context']
    owner._ctx = dict(guide=True, fresh=ctx['fresh'], here=ctx['here_deg'], ahead=ctx['ahead_deg'])
    return observed_route_candidate(data['error'], data['confidence'], copy.deepcopy(data['info']),
        observed_only=True, owner=owner, pose=history.pose_at(data['stamp']),
        source_pose=history.pose_at(data['source_stamp']), current_stamp=data['stamp'],
        observation_stamp=data['source_stamp'])


def test_recorded_guide_gap_keeps_tracking_then_existing_progress_evidence_releases_the_episode():
    data, history, owner, bridge = recorded()
    result = advance(data, history, owner, bridge)
    assert result[:2] == (data['error'], data['confidence'])
    assert bridge._alignment is None


def test_a_real_missing_odometry_frame_remains_uncertain_after_the_guide_returns():
    data, history, owner, bridge = recorded()
    # Omit a real update outside the guide gap: .25s exceeds the existing .2s limit.
    advance(data, history, owner, bridge, omit=155.5)
    assert bridge._alignment is not None and bridge._alignment['uncertain']


def test_unselected_tracking_accumulates_yaw_without_replacing_the_candidate_or_ending_the_episode():
    data, history, owner, bridge = recorded()
    pose = history.pose_at(155.125)
    owner._ctx = dict(guide=False, fresh=True)
    info = dict(strategy='drivable_pivot_right', target_m=None)
    result = observed_route_candidate(.5, .35, info, observed_only=False, owner=owner, pose=pose,
        source_pose=history.pose_at(155.), current_stamp=155.125, observation_stamp=155.)
    assert result == (.5, .35, info) and result[2] is info
    assert bridge._alignment['used'] == pytest.approx(abs(math.remainder(
        pose[2] - bridge._alignment['origin'][2], math.tau)))
    assert bridge._alignment['used'] > 0.
    assert bridge._alignment['stamp'] == 155.125


def test_unselected_fresh_floor_cannot_end_or_create_an_alignment_episode():
    data, history, owner, bridge = recorded()
    pose = history.pose_at(data['stamp'])
    bridge._alignment.update(last=history.pose_at(160.25), stamp=160.25)
    owner._ctx = dict(guide=False, fresh=True)
    info = copy.deepcopy(data['info'])
    result = observed_route_candidate(.1, .6, info, observed_only=False, owner=owner, pose=pose,
        source_pose=history.pose_at(160.25), current_stamp=data['stamp'], observation_stamp=160.25)
    assert result == (.1, .6, info) and bridge._alignment is not None
    assert bridge._alignment['stamp'] == data['stamp']
    bridge._alignment = None
    observed_route_candidate(.1, .6, info, observed_only=False, owner=owner, pose=pose,
        source_pose=history.pose_at(160.25), current_stamp=data['stamp'], observation_stamp=160.25)
    assert bridge._alignment is None
    other = DrivableSteer()
    observed_route_candidate(.1, .6, info, observed_only=False, owner=other)
    assert '_route_bridge' not in other.__dict__
