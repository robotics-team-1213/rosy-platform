"""D-854 CoreArmClient camera layout: a D-800 CORE's single `camera` and an N-camera CORE look the same."""
from pathlib import Path
import sys

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'integrations/robots/omx/src'))
from rosy.integrations.robots.omx.core_arm_client import CoreArmClient  # noqa: E402


def client(info, source):
    arm = CoreArmClient('http://127.0.0.1:8080', token='t', policy_revision='a' * 64)
    replies = {'policy': info, 'observations': source, 'stop': {}}
    arm.stopped = []
    def request(method, path, body=None):
        if path == 'stop':
            arm.stopped.append(True)
        return replies[path]
    arm._request = request
    return arm


BASE = dict(policy_revision='a' * 64, simulation=True, units='rad', joint_names=['joint1'])
FRONT = dict(name='front', shape=[3, 2, 2])
TOP = dict(name='top', shape=[3, 2, 2])


def test_single_camera_core_is_read_as_a_camera_list():
    arm = client(dict(BASE, camera=FRONT), dict(policy_revision='a' * 64, observation_id='o', positions={'joint1': 0.},
                                                camera=dict(FRONT, rgb_base64='')))
    arm.connect()
    assert arm.info['cameras'] == [FRONT]
    assert arm.get_observation()['cameras'] == [dict(FRONT, rgb_base64='')]


def test_camera_order_or_set_mismatch_stops_and_refuses():
    source = dict(policy_revision='a' * 64, observation_id='o', positions={'joint1': 0.},
                  cameras=[dict(TOP, rgb_base64=''), dict(FRONT, rgb_base64='')])
    arm = client(dict(BASE, cameras=[FRONT, TOP]), source)
    arm.connect()
    with pytest.raises(ValueError):
        arm.get_observation()
    assert arm.stopped == [True]
