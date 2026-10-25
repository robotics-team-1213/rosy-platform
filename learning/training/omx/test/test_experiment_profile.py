"""Learning setups must keep arm order, camera ownership and model inputs distinct."""
import copy
import importlib.util
from pathlib import Path

import pytest


def profile():
    return {
        'schema': 'rosy.omx.learning-profile/1',
        'name': 'Two arms and three views',
        'mode': 'cooperative',
        'task': 'Pick and hold the block together',
        'arms': [
            {'id': 'arm_a', 'joint_names': ['shoulder', 'elbow', 'gripper'], 'units': 'rad'},
            {'id': 'arm_b', 'joint_names': ['shoulder', 'elbow', 'gripper'], 'units': 'rad'},
        ],
        'cameras': [
            {'id': 'overhead', 'input_key': 'observation.images.top', 'arm_id': None,
             'role': 'top', 'source_identity': 'camera-001', 'placement': 'overhead-v1',
             'shape': [3, 64, 80], 'purposes': ['policy', 'record']},
            {'id': 'wrist_a', 'input_key': 'observation.images.arm_a_wrist', 'arm_id': 'arm_a',
             'role': 'wrist', 'source_identity': 'camera-002', 'placement': 'a-wrist-v1',
             'shape': [3, 64, 64], 'purposes': ['policy', 'record']},
            {'id': 'wrist_b', 'input_key': 'observation.images.arm_b_wrist', 'arm_id': 'arm_b',
             'role': 'wrist', 'source_identity': 'camera-003', 'placement': 'b-wrist-v1',
             'shape': [3, 64, 64], 'purposes': ['policy', 'record']},
        ],
    }


def module():
    path = Path(__file__).resolve().parents[1] / 'experiment_profile.py'
    spec = importlib.util.spec_from_file_location('omx_experiment_profile', path)
    loaded = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(loaded)
    return loaded


def test_online_action_space_is_declared_in_order_not_fitted_from_demonstrations():
    api = module()
    setup = profile()
    with pytest.raises(ValueError, match='declared'):
        api.action_bounds(setup)
    setup['schema'] = 'rosy.omx.learning-profile/2'
    setup['arms'][0]['action_limits'] = [[-2, 2], [-1, 1], [0, 1]]
    setup['arms'][1]['action_limits'] = [[-3, 3], [-1.5, 1.5], [0, 1]]
    assert api.action_bounds(api.validate_profile(setup)) == [
        [-2, 2], [-1, 1], [0, 1], [-3, 3], [-1.5, 1.5], [0, 1]]
    before = api.profile_revision(setup)
    setup['arms'][1]['action_limits'][0][1] = 2.5
    assert api.profile_revision(setup) != before


@pytest.mark.parametrize('limits', [[], [[0, 0]] * 3, [[1, -1]] * 3,
    [[False, 1]] * 3, [[0, float('inf')]] * 3, [[0, float('nan')]] * 3,
    [[0, '1']] * 3, [[0, 1, 2]] * 3, [[1, 1 + 1e-10]] * 3, [[0, 1e-50]] * 3])
def test_online_profile_rejects_missing_or_invalid_action_spaces(limits):
    api = module()
    setup = profile()
    setup['schema'] = 'rosy.omx.learning-profile/2'
    for arm in setup['arms']:
        arm['action_limits'] = limits
    with pytest.raises(ValueError):
        api.validate_profile(setup)


def test_two_arms_with_same_joint_names_keep_distinct_order_and_camera_inputs():
    api = module()
    source = profile()
    checked = api.validate_profile(source)
    assert api.action_names(checked) == [
        'arm_a/shoulder', 'arm_a/elbow', 'arm_a/gripper',
        'arm_b/shoulder', 'arm_b/elbow', 'arm_b/gripper',
    ]
    assert api.policy_cameras(checked) == [
        'observation.images.top', 'observation.images.arm_a_wrist',
        'observation.images.arm_b_wrist',
    ]
    source['arms'][0]['joint_names'][0] = 'changed'
    assert checked['arms'][0]['joint_names'][0] == 'shoulder'


@pytest.mark.parametrize('arm_count', [1, 3])
def test_arm_groups_are_not_fixed_to_two_members(arm_count):
    api = module()
    source = profile()
    source['arms'] = [dict(copy.deepcopy(source['arms'][0]), id=f'arm_{i}')
                      for i in range(arm_count)]
    source['cameras'] = [source['cameras'][0]]
    assert len(api.action_names(api.validate_profile(source))) == arm_count * 3


@pytest.mark.parametrize('mutation', [
    lambda p: p['arms'].append(copy.deepcopy(p['arms'][0])),
    lambda p: p['cameras'][1].update(arm_id='missing_arm'),
    lambda p: p['cameras'][1].update(source_identity='camera-001'),
    lambda p: p['cameras'][1].update(input_key='observation.images.top'),
    lambda p: p['cameras'][0].update(shape=[3, True, 80]),
    lambda p: p['cameras'][0].update(purposes=['policy', 'unrestricted_control']),
    lambda p: p.update(mode='unrestricted'),
])
def test_invalid_or_ambiguous_setup_is_refused(mutation):
    source = profile()
    mutation(source)
    with pytest.raises(ValueError):
        module().validate_profile(source)


def test_camera_placement_changes_the_profile_revision_without_renaming_device():
    api = module()
    source = profile()
    first = api.profile_revision(api.validate_profile(source))
    source['cameras'][0]['placement'] = 'oblique-left-v2'
    second = api.profile_revision(api.validate_profile(source))
    assert first != second
    assert source['cameras'][0]['source_identity'] == 'camera-001'


def test_monitoring_camera_is_not_implicitly_a_policy_input():
    api = module()
    source = profile()
    source['cameras'][2]['purposes'] = ['monitor']
    assert api.policy_cameras(api.validate_profile(source)) == [
        'observation.images.top', 'observation.images.arm_a_wrist',
    ]
