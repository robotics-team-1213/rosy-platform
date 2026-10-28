"""Photo-layout provenance and three physical layers must precede a stacking success claim."""
import importlib
import json
import math
from pathlib import Path
import subprocess
import sys

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


def fixture():
    assert importlib.util.find_spec('mapped_stack_fixture'), 'mapped physical stacking fixture is missing'
    return importlib.import_module('mapped_stack_fixture')


def test_board_uses_the_confluence_cad_and_long_bars_use_both_arms():
    mod = fixture()
    assert mod.FIXTURE['board_size_m'] == [1.22, 2.44, .018]
    assert mod.FIXTURE['confluence_page'] == '8683759'
    assert mod.FIXTURE['cad_attachment'] == '8585450'
    assert mod.FIXTURE['photo_attachment'] == '8585456'
    assert mod.FIXTURE['cell_pose_scope'] == 'PHOTO_DERIVED_NOMINAL_NOT_CALIBRATED'
    assert [p['arm'] for p in mod.plan()] == [0, 1, 0]
    assert all(p['size'] == [.09, .03, .03] for p in mod.plan())
    assert [p['target'][2] for p in mod.plan()] == pytest.approx([.04, .07, .10])


def owner_plan(tmp_path, **case):
    mod = fixture()
    request = tmp_path/f'case-{len(list(tmp_path.iterdir()))}.json'
    output = request.with_suffix('.frames.json')
    request.write_text(json.dumps(dict(schema='rosy.omx-sim-stack-plan/1', **case)))
    subprocess.run([sys.executable, str(mod.ROOT/'deploy/robot/omx/isaac_stack_plan.py'),
                    '--case', str(request), '--out', str(output)], check=True, capture_output=True)
    value = json.loads(output.read_text())
    assert value['joints'] == ['joint'+str(i) for i in range(1, 6)]
    return value


def test_all_grasp_carry_and_three_layer_targets_have_nominal_profile_ik(tmp_path):
    mod = fixture()
    initial = owner_plan(tmp_path, operation='homes', bases=mod.FIXTURE['arm_bases_m'], points=[mod.home(0), mod.home(1)])
    assert initial['gripper']['close'] < initial['gripper']['preopen'] < initial['gripper']['release']
    for item in mod.plan():
        arm = item['arm']
        q = initial['homes'][arm]
        for point in ([.16, -.046, .145], [.16, -.046, .042], [.16, -.046, .145],
                      [.16, 0., .145], [*item['target'][:2], item['target'][2]+.003],
                      [.16, 0., .145], mod.home(arm)):
            value = owner_plan(tmp_path, operation='move', base=mod.FIXTURE['arm_bases_m'][arm],
                               start=q, target=point, yaw=0., dt=mod.DT)
            velocity = [0.]*5
            for frame in value['frames']:
                assert len(frame) == 5 and all(math.isfinite(v) for v in frame)
                next_velocity = [(frame[j]-q[j])/mod.DT for j in range(5)]
                assert max(abs(v) for v in next_velocity) <= .5
                assert max(abs(next_velocity[j]-velocity[j])/mod.DT for j in range(5)) <= .5
                q, velocity = frame, next_velocity


def test_offline_owner_rejects_unreachable_targets(tmp_path):
    mod = fixture()
    with pytest.raises(subprocess.CalledProcessError):
        owner_plan(tmp_path, operation='move', base=[0., 0., 0.], start=[0.]*5,
                   target=[10., 0., 0.], yaw=0., dt=mod.DT)


def test_native_wrist_pose_uses_the_pinned_tcp_offset():
    mod = fixture()
    assert mod.tcp_from_wrist([1., 2., 3.], [1., 0., 0., 0.]) == pytest.approx([1.09193, 1.9984, 3.])
    a = math.sqrt(.5)
    assert mod.tcp_from_wrist([1., 2., 3.], [a, 0., a, 0.]) == pytest.approx([1., 1.9984, 2.90807])


def test_reference_controller_is_a_distinct_mapped_scenario():
    import run_catalog
    row = run_catalog.normalize('omx-map-long-stack', {'seed': 42})
    assert row['trials'] == 3 and row['fixture'] == 'confluence-map-long-stack-v1'
    with pytest.raises(ValueError):
        run_catalog.normalize('omx-map-long-stack', {'seed': 42, 'attachment': True})


def test_mapped_ppo_uses_the_verified_geometry_and_a_three_layer_horizon():
    mod = fixture()
    import run_catalog
    config = run_catalog.normalize('omx-map-stacking-rl', {'seed': 42})
    assert config['fixture'] == mod.RL_FIXTURE['revision']
    for key in ('board_size_m', 'arm_bases_m', 'bin_origin_m', 'bin_size_m', 'finger_collision', 'fixed_base'):
        assert mod.RL_FIXTURE[key] == mod.FIXTURE[key]
    assert mod.RL_FIXTURE['max_episode_steps']*mod.RL_FIXTURE['control_decimation']*mod.DT >= 120
    assert mod.RL_FIXTURE['controller'] == 'RSL_RL_PPO_DIRECT_JOINT_VELOCITY'
    with pytest.raises(ValueError):
        run_catalog.normalize('omx-map-stacking-rl', {'seed': 42, 'iterations': 1000})


def test_tcp_is_a_massless_fixed_frame_in_the_pinned_vendor_model(tmp_path):
    mod = fixture()
    vendor = Path(__file__).resolve().parents[1]/'assets/open_manipulator_description/urdf/omx_f/omx_f.urdf'
    mod.check_massless_tcp(vendor)
    root = mod.physical_model(vendor).getroot()
    assert root.find("link[@name='end_effector_link']") is None
    assert root.find("joint[@name='end_effector_joint']") is None
    assert {j.get('name') for j in root.findall('joint')} >= {'joint1', 'joint2', 'joint3', 'joint4', 'joint5', 'gripper_joint_1', 'gripper_joint_2'}
    bad = tmp_path/'weighted.urdf'
    bad.write_text(vendor.read_text().replace('<link name="end_effector_link">',
        '<link name="end_effector_link"><inertial/>'))
    with pytest.raises(ValueError):
        mod.check_massless_tcp(bad)


def test_success_requires_free_lift_release_support_and_retreat():
    import copy
    mod = fixture()
    trial = {'layers': []}
    for i in range(3):
        boxes = []
        for j, item in enumerate(mod.plan()):
            forces = [[0., 0., 0.] for _ in range(8)]
            below = 'bin' if j == 0 else mod.plan()[j-1]['id']
            forces[mod.contact_names(j).index(below)][2] = .6
            boxes.append(dict(position=item['target'][:], orientation=[1., 0., 0., 0.],
                velocity=[0., 0., 0.], angular_velocity=[0., 0., 0.], forces=forces, net_force=[0., 0., .6]))
        settled = dict(boxes=boxes, tcps=[[0., -.15, .13], [0., .15, .13]])
        lifted = copy.deepcopy(settled)
        lifted['boxes'][i]['position'][2] = .145
        lifted['boxes'][i]['forces'] = [[0., 0., 0.] for _ in range(8)]
        for finger in (2*(i % 2), 2*(i % 2)+1):
            lifted['boxes'][i]['forces'][finger] = [0., .1, .3]
        lifted['boxes'][i]['net_force'] = [0., .2, .6]
        trial['layers'].append(dict(item=i, arm=i % 2, source_center_z=.04,
            lift_samples=[dict(copy.deepcopy(lifted), tick=t) for t in (0, 12, 24)],
            settle_samples=[dict(copy.deepcopy(settled), tick=t) for t in range(120, 253, 12)]))
    assert mod.judge(trial)['task_success']
    for mutation in ('held', 'no_lift', 'unsupported', 'displaced', 'hidden_support'):
        bad = copy.deepcopy(trial)
        layer = bad['layers'][2]
        if mutation == 'held':
            layer['settle_samples'][0]['boxes'][2]['forces'][0] = [0., 0., .1]
        elif mutation == 'no_lift':
            layer['lift_samples'][0]['boxes'][2]['position'][2] = .04
        elif mutation == 'unsupported':
            layer['settle_samples'][0]['boxes'][2]['forces'] = [[0., 0., 0.] for _ in range(8)]
        elif mutation == 'hidden_support':
            layer['lift_samples'][0]['boxes'][2]['net_force'][2] += .1
        else:
            layer['settle_samples'][0]['boxes'][0]['position'][0] += .01
        assert not mod.judge(bad)['task_success'], mutation
