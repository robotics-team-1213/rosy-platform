"""Full cube claims require nine physically released bars, including every earlier row."""
import copy
import json
from pathlib import Path
import sys
import subprocess

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
        for finger in (2*(i % 2), 2*(i % 2)+1):
            box['forces'][finger] = [0., .1, .3]
        box['net_force'] = [0., .2, .6]
        result['layers'].append(dict(item=i, arm=i % 2, source_center_z=.04,
            infeed_start=[.16, -.09, .041], infeed_settled=[.16, -.046, .04],
            lift_samples=[dict(copy.deepcopy(lifted), tick=t) for t in (0, 12, 24)],
            settle_samples=[dict(copy.deepcopy(settled), tick=t) for t in range(120, 253, 12)]))
    result.update(f.judge(result, cube=True))
    return result


def test_cube_plan_fills_27_cells_without_crossing_the_infeed():
    items = f.plan(cube=True)
    assert len(items) == 9
    occupied = [(x, row, level) for p in items for x in range(3)
                for _, row, level in [p['cell']]]
    assert len(set(occupied)) == 27
    assert set(occupied) == {(x, y, z) for x in range(3) for y in range(3) for z in range(3)}
    assert f.CUBE_FIXTURE['bin_size_m'] == [.09, .09, .09]
    assert f.CUBE_FIXTURE['trials'] == 1
    assert min(p['target'][1]-.015 for p in items) > -.046+.015+.01
    assert sum(p['mass'] for p in items) == pytest.approx(.54)
    assert len(f.plan()) == 3  # Keep the verified fallback distinct.


def test_nine_bar_judgement_requires_expected_row_support_and_stable_prefix():
    good = trial()
    assert good['task_success']
    for mutation in ('missing_bar', 'wrong_support', 'earlier_displaced', 'finger_held', 'moving'):
        bad = copy.deepcopy(good)
        if mutation == 'missing_bar':
            bad['layers'].pop()
        else:
            box = bad['layers'][8]['settle_samples'][0]['boxes'][8 if mutation != 'earlier_displaced' else 0]
            if mutation == 'wrong_support':
                box['forces'] = [[0., 0., 0.] for _ in box['forces']]
                box['forces'][f.contact_names(8, cube=True).index(f.plan(cube=True)[7]['id'])][2] = .6
            elif mutation == 'earlier_displaced':
                box['position'][1] += .01
            elif mutation == 'finger_held':
                box['forces'][0][2] = .1
                box['net_force'][2] += .1
            else:
                box['velocity'][2] = .0118
        assert not f.judge(bad, cube=True)['task_success'], mutation


def test_cube_report_recomputes_nine_body_contact_acceptance(tmp_path):
    value = dict(schema='rosy.omx-map-cube-stack/1', fixture=f.CUBE_FIXTURE,
        seed=42, sdk_version='6.2.0.0', controller=f.CUBE_FIXTURE['controller'],
        attachment_aid=False, trials=[trial()], task_success=True,
        images=['mapped-overview.png', 'mapped-initial.png', 'mapped-layer-9.png', 'mapped-trial-1.png'])
    path = tmp_path/'report.json'
    path.write_text(json.dumps(value))
    assert verify_report(path, sdk_version='6.2.0.0', seed=42, cube=True)['task_success']
    value['trials'][0]['layers'][8]['settle_samples'][0]['boxes'].pop()
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


def test_assigned_arm_can_reach_each_cube_release_pose(tmp_path):
    def request(operation, **fields):
        case = tmp_path/'case.json'
        out = tmp_path/f'frames-{len(list(tmp_path.glob("frames-*")))}.json'
        case.write_text(json.dumps(dict(schema='rosy.omx-sim-stack-plan/1', operation=operation, **fields)))
        subprocess.run([sys.executable, str(f.ROOT/'deploy/robot/omx/isaac_stack_plan.py'),
            '--case', str(case), '--out', str(out)], check=True, capture_output=True)
        return json.loads(out.read_text())
    homes = request('homes', bases=f.FIXTURE['arm_bases_m'], points=[f.home(0), f.home(1)])['homes']
    for item in f.plan(cube=True):
        target = item['target'][:]
        target[2] += .003+f.CUBE_FIXTURE['release_clearance_m']
        frames = request('move', base=f.FIXTURE['arm_bases_m'][item['arm']], start=homes[item['arm']],
            target=target, yaw=0., dt=f.DT)['frames']
        assert frames and all(len(q) == 5 for q in frames)
