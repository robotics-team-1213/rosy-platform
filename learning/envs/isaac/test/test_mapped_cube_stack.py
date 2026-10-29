"""Opposed-arm first-layer claims require three released bars and a stable prefix."""
import copy
import json
from pathlib import Path
import sys
import subprocess
import hashlib
import uuid
import math

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import mapped_stack_fixture as f
from mapped_stack_report import verify_report
from run_catalog import catalog, normalize


def trial():
    items = f.plan(cube=True)
    boxes = []
    for j, item in enumerate(items):
        forces = [[0., 0., 0.] for _ in f.contact_names(j, cube=True)]
        below = 'bin' if j < 3 else items[j-3]['id']
        forces[f.contact_names(j, cube=True).index(below)][2] = .6
        boxes.append(dict(position=item['target'][:], orientation=[1., 0., 0., 0.],
            velocity=[0., 0., 0.], angular_velocity=[0., 0., 0.], forces=forces, net_force=[0., 0., .6]))
    result = dict(seed=42, layers=[])
    for i, item in enumerate(items):
        settled = dict(boxes=copy.deepcopy(boxes), tcps=[[0., -.3, .2], [0., .3, .2]])
        lifted = copy.deepcopy(settled)
        box = lifted['boxes'][i]
        box['position'][2] = .145
        box['forces'] = [[0., 0., 0.] for _ in box['forces']]
        for finger in (2*item['arm'], 2*item['arm']+1):
            box['forces'][finger] = [0., .1, .3]
        box['net_force'] = [0., .2, .6]
        result['layers'].append(dict(item=i, arm=item['arm'], source_center_z=.04,
            infeed_start=[.295, 0., .041], infeed_settled=[.25, 0., .04],
            lift_samples=[dict(copy.deepcopy(lifted), tick=t) for t in (0, 12, 24)],
            settle_samples=[dict(copy.deepcopy(settled), tick=t) for t in range(120, 253, 12)]))
    result.update(f.judge(result, cube=True))
    return result


def test_opposed_first_layer_stays_inside_one_raised_workplate():
    fixture = f.CUBE_FIXTURE
    assert fixture['target_stage'] == 'FIRST_LAYER_ONLY'
    assert fixture['arm_base_yaws_rad'] == pytest.approx([math.pi/2, -math.pi/2])
    center, size = fixture['workplate_center_m'], fixture['workplate_size_m']
    top = center[2]+size[2]/2
    assert all(base[2] == pytest.approx(top) for base in fixture['arm_bases_m'])
    assert fixture['belt_center_m'][2]+fixture['belt_size_m'][2]/2 < top
    for base in fixture['arm_bases_m']:
        assert all(abs(base[k]-center[k]) < size[k]/2 for k in (0, 1))
    for item in f.plan(cube=True):
        assert all(abs(item['target'][k]-center[k])+item['size'][k]/2 < size[k]/2 for k in (0, 1))
    assert fixture['bin_origin_m'][2] >= top


def test_terminal_belt_arrives_at_the_plate_edge_with_a_small_gap():
    fixture = f.CUBE_FIXTURE
    edge = fixture['workplate_center_m'][0]+fixture['workplate_size_m'][0]/2
    endpoint = fixture['belt_center_m'][0]-fixture['belt_size_m'][0]/2
    assert .0005 <= endpoint-edge <= .002
    assert fixture['belt_velocity_m_s'] == [-fixture['belt_speed_m_s'], 0., 0.]
    assert fixture['pickup_center_m'][0] < .27  # Previous parallel-belt pickup distance.
    assert fixture['belt_stop_size_m'][0] < fixture['belt_stop_size_m'][1]
    assert fixture['upstream_belt_size_m'][1] > fixture['upstream_belt_size_m'][0]
    assert fixture['upstream_belt_center_m'][1]-fixture['upstream_belt_size_m'][1]/2 == pytest.approx(fixture['belt_size_m'][1]/2)


@pytest.mark.parametrize('end,passed', [([.25, 0., .04], True),
    ([.295, .045, .04], False), ([.34, 0., .04], False),
    ([.295, 0., .04], False), ([.25, .01, .04], False)])
def test_transport_evidence_follows_terminal_direction(end, passed):
    assert f.belt_transport_observed([.295, 0., .041], end, cube=True) is passed


def test_first_layer_plan_fills_nine_cells_without_crossing_the_infeed():
    items = f.plan(cube=True)
    assert len(items) == 3
    occupied = [(x, row, level) for p in items for x in range(3)
                for _, row, level in [p['cell']]]
    assert len(set(occupied)) == 9
    assert set(occupied) == {(x, y, 0) for x in range(3) for y in range(3)}
    assert f.CUBE_FIXTURE['bin_size_m'] == [.09, .09, .03]
    assert f.CUBE_FIXTURE['trials'] == 1
    assert max(p['target'][0]+.045 for p in items) < f.CUBE_FIXTURE['infeed_start_m'][0]-.045
    assert sum(p['mass'] for p in items) == pytest.approx(.18)
    assert len(f.plan()) == 3  # Keep the verified fallback distinct.


def test_first_layer_judgement_requires_support_and_stable_prefix():
    good = trial()
    assert good['task_success']
    for mutation in ('missing_bar', 'wrong_support', 'earlier_displaced', 'finger_held', 'moving'):
        bad = copy.deepcopy(good)
        if mutation == 'missing_bar':
            bad['layers'].pop()
        else:
            box = bad['layers'][2]['settle_samples'][0]['boxes'][2 if mutation != 'earlier_displaced' else 0]
            if mutation == 'wrong_support':
                box['forces'] = [[0., 0., 0.] for _ in box['forces']]
                box['forces'][f.contact_names(2, cube=True).index(f.plan(cube=True)[1]['id'])][2] = .6
            elif mutation == 'earlier_displaced':
                box['position'][1] += .01
            elif mutation == 'finger_held':
                box['forces'][0][2] = .1
                box['net_force'][2] += .1
            else:
                box['velocity'][2] = .0118
        assert not f.judge(bad, cube=True)['task_success'], mutation


def test_first_layer_report_recomputes_three_body_contact_acceptance(tmp_path):
    value = dict(schema='rosy.omx-map-cube-stack/1', fixture=f.CUBE_FIXTURE,
        seed=42, sdk_version='6.2.0.0', controller=f.CUBE_FIXTURE['controller'],
        attachment_aid=False, trials=[trial()], task_success=True,
        images=['mapped-overview.png', 'mapped-initial.png', 'mapped-layer-3.png', 'mapped-trial-1.png'])
    path = tmp_path/'report.json'
    path.write_text(json.dumps(value)+' '*1024*1024)
    assert verify_report(path, sdk_version='6.2.0.0', seed=42, cube=True)['task_success']
    path.write_text(json.dumps(value)+' '*f.CUBE_REPORT_BYTES)
    with pytest.raises(ValueError, match='Unsafe stacking evidence'):
        verify_report(path, sdk_version='6.2.0.0', seed=42, cube=True)
    value['trials'][0]['layers'][2]['settle_samples'][0]['boxes'].pop()
    path.write_text(json.dumps(value))
    with pytest.raises(ValueError):
        verify_report(path, sdk_version='6.2.0.0', seed=42, cube=True)


def test_cube_is_a_fixed_bounded_catalog_scenario():
    entry = next(x for x in catalog() if x['id'] == 'omx-map-cube-stack')
    assert entry['implemented'] and entry['timeout_seconds'] == 900
    config = normalize(entry['id'], {'seed': 42})
    assert config['trials'] == 1 and config['fixture'] == f.CUBE_FIXTURE['revision']
    with pytest.raises(ValueError):
        normalize(entry['id'], {'seed': 42, 'attachment_aid': True})


def owner_request(tmp_path, operation, **fields):
    case = tmp_path/'case.json'
    out = tmp_path/f'frames-{len(list(tmp_path.glob("frames-*")))}.json'
    case.write_text(json.dumps(dict(schema='rosy.omx-sim-stack-plan/1', operation=operation, **fields)))
    result = subprocess.run([sys.executable, str(f.ROOT/'deploy/robot/omx/isaac_stack_plan.py'),
        '--case', str(case), '--out', str(out)], capture_output=True)
    assert result.returncode == 0, f'{fields}\n{result.stderr.decode()}'
    return json.loads(out.read_text())


def test_assigned_arm_can_reach_each_cube_release_pose(tmp_path):
    fixture = f.CUBE_FIXTURE
    homes = owner_request(tmp_path, 'homes', bases=fixture['arm_bases_m'],
        base_yaws=fixture['arm_base_yaws_rad'], points=[f.home(0, True), f.home(1, True)])['homes']
    for item in f.plan(cube=True):
        target = item['target'][:]
        target[2] += .003+f.CUBE_FIXTURE['release_clearance_m']
        arm = item['arm']
        source = fixture['pickup_center_m'][:]
        source[1], source[2] = 0., .042
        q = homes[arm]
        for point in ([source[0], 0., fixture['carry_height_m']], source,
                      [source[0], 0., fixture['carry_height_m']],
                      [*target[:2], fixture['carry_height_m']], target, f.home(arm, True)):
            frames = owner_request(tmp_path, 'move', base=fixture['arm_bases_m'][arm],
                base_yaw=fixture['arm_base_yaws_rad'][arm], start=q, target=point, yaw=0., dt=f.DT)['frames']
            assert frames and all(len(joints) == 5 for joints in frames)
            q = frames[-1]


@pytest.mark.parametrize('passed', [False, True])
def test_cube_worker_success_requires_physical_task_success(passed):
    import run_worker
    results = []
    class Store:
        def get(self, run_id):
            return dict(input={'scenario_id': 'omx-map-cube-stack'}, revision=2, status='RUNNING')
        def finish(self, run_id, revision, result, artifacts):
            results.append(result)
    report = dict(task_success=passed, trials=[{'task_success': passed}])
    run_worker._finish(Store(), 'r', {'exit_code': 0, 'reason': 'process_exited'}, report, [], False)
    assert results[0]['stage'] == 'mapped_cube_stack'
    assert results[0]['status'] == ('SUCCEEDED' if passed else 'FAILED')
    assert results[0]['successful_trials'] == int(passed)


def test_cube_release_corrects_measured_cargo_offset_and_neighbor_clearance():
    sample = trial()['layers'][1]['lift_samples'][0]
    item = f.plan(True)[1]
    tcp = sample['tcps'][item['arm']]
    body = sample['boxes'][1]
    body['position'] = [.1295, -.0005, .0822]
    sample['boxes'][0]['position'][1] = -.03
    command = f.cube_release_target(1, sample, .04)
    predicted = [body['position'][k]+command[k]-tcp[k] for k in range(3)]
    assert predicted == pytest.approx([.13, .0002, .082])
    assert not f.cube_release_ready(1, sample, .04)
    body['position'] = predicted[:]
    assert f.cube_release_ready(1, sample, .04)
    body['position'][1] -= .00001
    assert not f.cube_release_ready(1, sample, .04)
    body['position'] = predicted[:]
    body['forces'][2*item['arm']] = [0., 0., 0.]
    with pytest.raises(ValueError, match='bilateral'):
        f.cube_release_target(1, sample, .04)
    with pytest.raises(ValueError, match='bilateral'):
        f.cube_release_ready(1, sample, .04)


def test_only_cube_contact_report_has_a_two_mib_artifact_budget(tmp_path):
    from run_store import RunStore
    store = RunStore(tmp_path/'runs')
    raw = b'{}'+b' '*(1024*1024)
    for scenario in ('omx-map-cube-stack', 'omx-map-long-stack'):
        run = store.create(uuid.uuid4().hex, scenario, {'seed': 42}, 'a'*40)
        name = 'mapped-stack-report.json'
        (store.root/'runs'/run['run_id']/name).write_bytes(raw)
        item = dict(id='mapped-stack-report', name=name, bytes=len(raw),
                    sha256=hashlib.sha256(raw).hexdigest(), media_type='application/json')
        def finish():
            return store.finish(run['run_id'], run['revision'],
                dict(status='FAILED', stage='mapped_cube_stack', task_success=False), [item])
        if scenario == 'omx-map-cube-stack':
            finish()
            assert store.artifact(run['run_id'], item['id'])['data'] == raw
        else:
            with pytest.raises(ValueError, match='artifact size exceeds limit'):
                finish()


def test_cube_feedback_accumulates_loaded_arm_tracking_error():
    sample = trial()['layers'][0]['lift_samples'][0]
    sample['tcps'][0] = [.1295, -.0304, .0835]
    sample['boxes'][0]['position'] = [.1295, -.0304, .0815]
    previous = [.13, -.03, .084]
    command = f.cube_release_target(0, sample, .04, commanded_tcp=previous)
    assert command == pytest.approx([.1305, -.0296, .0845])
    bias = [sample['tcps'][0][k]-previous[k] for k in range(3)]
    sample['tcps'][0] = [command[k]+bias[k] for k in range(3)]
    sample['boxes'][0]['position'] = [sample['tcps'][0][0], sample['tcps'][0][1], sample['tcps'][0][2]-.002]
    assert f.cube_release_ready(0, sample, .04)


def test_world_rotation_preserves_owner_joint_trajectory(tmp_path):
    home = owner_request(tmp_path, 'homes', bases=[[0., 0., 0.]]*2, points=[[.16, 0., .13]]*2)['homes'][0]
    target = [.15, .03, .12]
    baseline = owner_request(tmp_path, 'move', base=[0., 0., 0.], start=home, target=target, yaw=0., dt=f.DT)['frames']
    base = [.3, -.2, .01]
    for yaw in (math.pi/2, -math.pi/2, math.pi):
        c, s = math.cos(yaw), math.sin(yaw)
        world = [base[0]+c*target[0]-s*target[1], base[1]+s*target[0]+c*target[1], base[2]+target[2]]
        frames = owner_request(tmp_path, 'move', base=base, base_yaw=yaw, start=home, target=world, yaw=yaw, dt=f.DT)['frames']
        assert frames[-1] == pytest.approx(baseline[-1], abs=1e-7)
        assert len(frames) == len(baseline)


def test_opposed_homes_hold_the_same_world_pose_without_wrist_spin(tmp_path):
    bases = [[.1, -.14, 0.], [.1, .14, 0.]]
    yaws = [math.pi/2, -math.pi/2]
    points = [[b[0]+math.cos(y)*.08-math.sin(y)*.12,
               b[1]+math.sin(y)*.08+math.cos(y)*.12, .13] for b, y in zip(bases, yaws)]
    homes = owner_request(tmp_path, 'homes', bases=bases, base_yaws=yaws, points=points)['homes']
    for base, yaw, point, home in zip(bases, yaws, points, homes):
        frames = owner_request(tmp_path, 'move', base=base, base_yaw=yaw, start=home, target=point, yaw=0., dt=f.DT)['frames']
        assert max(abs(q[j]-home[j]) for q in frames for j in range(5)) < 1e-6
