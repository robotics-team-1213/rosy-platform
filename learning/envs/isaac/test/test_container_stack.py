"""Current-map extensions keep layer support and per-case provenance explicit."""
from pathlib import Path
import sys

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import mapped_stack_fixture as f
from run_catalog import normalize
from run_store import input_snapshot, requested


def bodies(fixture):
    items = f.plan(True, fixture=fixture)
    result = []
    for i, item in enumerate(items):
        names = f.contact_names(i, True, fixture=fixture)
        support = 'bin' if item['cell'][2] == 0 else next(
            v['id'] for v in items if v['cell'] == [0, item['cell'][1], item['cell'][2]-1])
        forces = [[0., 0., 0.] for _ in names]
        forces[names.index(support)][2] = .6
        result.append(dict(position=item['target'][:], orientation=[1., 0., 0., 0.],
            velocity=[0., 0., 0.], angular_velocity=[0., 0., 0.], forces=forces, net_force=[0., 0., .6]))
    return result


@pytest.mark.parametrize('case', ['nominal', 'offset', 'reverse'])
def test_three_layers_have_nine_distinct_cells_with_measured_support(case):
    fixture = f.container_fixture(layers=3, case=case)
    items = f.plan(True, fixture=fixture)
    assert len(items) == 9
    assert len({tuple(item['cell']) for item in items}) == 9
    assert fixture['bin_size_m'] == [.09, .097, .09]
    assert fixture['recording']['fps'] == 10
    assert fixture['release_gripper_acceleration_rad_s2'] == .025
    assert f.CUBE_FIXTURE['release_gripper_acceleration_rad_s2'] == .1
    boxes = bodies(fixture)
    assert all(f.stable_box(b, i, True, fixture=fixture) for i, b in enumerate(boxes))
    names = f.contact_names(3, True, fixture=fixture)
    boxes[3]['forces'][names.index('bar-1')][2] = 0.
    boxes[3]['forces'][names.index('bin')][2] = .6
    assert not f.stable_box(boxes[3], 3, True, fixture=fixture)


def held_scene(fixture, index, orientation=None):
    boxes = bodies(fixture)
    boxes[index]['position'][2] = fixture['carry_height_m']
    if orientation:
        boxes[index]['orientation'] = orientation
    boxes[index]['forces'] = [[0., 0., 0.] for _ in boxes[index]['forces']]
    arm = f.plan(True, fixture=fixture)[index]['arm']
    for k in (2*arm, 2*arm+1):
        boxes[index]['forces'][k] = [0., .1, .3]
    boxes[index]['net_force'] = [0., .2, .6]
    down = [2**-.5, 0., 2**-.5, 0.]
    return dict(boxes=boxes, tcps=[boxes[index]['position'][:], boxes[index]['position'][:]],
                wrist_orientations=[down[:], down[:]])


def touching(fixture):
    """Pre-D-929 touching rows: these cases exercise the tight-envelope code paths the gap no longer reaches."""
    fixture.update(row_gap_m=0., row_clearance_m=.0001, bin_origin_m=[.035, -.045, .074],
                   bin_size_m=[.09, .09, fixture['bin_size_m'][2]])
    return fixture


@pytest.mark.parametrize('case,order',[('nominal',[1,0,2]),('reverse',[1,2,0])])
def test_center_is_placed_before_each_independent_outer_row(case,order):
    fixture=touching(f.container_fixture(layers=3,case=case))
    items=f.plan(True,fixture=fixture)
    assert [v['cell'][1] for v in items[:3]] == order
    for i in (0,1,2):
        target=f.cube_release_target(i,held_scene(fixture,i),.04,fixture=fixture)
        direction=items[i]['cell'][1]-1
        assert target[1] == pytest.approx(items[i]['target'][1]+direction*.0001)
        assert target[2] >= items[i]['target'][2]+.015-1e-12


def test_outer_uses_measured_center_and_clears_neighbors_and_swept_jaws():
    fixture=touching(f.container_fixture(layers=3,case='nominal'))
    sample=held_scene(fixture,1,[1.,0.,0.,0.])
    sample['boxes'][0]['position'][1]=.0002
    target=f.cube_release_target(1,sample,.04,fixture=fixture)
    assert target[1] == pytest.approx(-.03)
    top=fixture['bin_origin_m'][2]+.03
    swept=f.pad_sweep_bottom_relative_tcp(sample['wrist_orientations'][0])
    nominal=fixture['bin_origin_m'][2]+.03
    assert target[2] == pytest.approx(max(nominal,top+.002-swept))
    assert target[2] < nominal+.013
    assert target[2]+swept >= top+.002-1e-12
    sample['wrist_orientations'][0]=[2**-.5,2**-.5,0.,0.]
    target=f.cube_release_target(1,sample,.04,fixture=fixture)
    swept=f.pad_sweep_bottom_relative_tcp(sample['wrist_orientations'][0])
    assert target[2]+swept >= top+.002-1e-12
    assert target[2] > .1


@pytest.mark.parametrize('case,index,direction',[('nominal',1,-1),('nominal',2,1),('reverse',1,1),('reverse',2,-1)])
def test_outer_rejects_projected_footprint_outside_original_envelope(case,index,direction):
    fixture=touching(f.container_fixture(layers=3,case=case))
    sample=held_scene(fixture,index)
    sample['boxes'][0]['position'][1]=direction*.001
    with pytest.raises(ValueError,match='envelope'):
        f.cube_release_target(index,sample,.04,fixture=fixture)


def test_strict_release_profile_rejects_held_roll_outside_envelope():
    import math
    fixture=touching(f.container_fixture(layers=3,case='nominal'))
    fixture.pop('transient_tilt_overhang_m',None)
    sample=held_scene(fixture,1,[math.cos(.02),math.sin(.02),0.,0.])
    with pytest.raises(ValueError,match='envelope'):
        f.cube_release_target(1,sample,.04,fixture=fixture)


def test_outer_readiness_checks_measured_envelope_despite_small_tracking_error():
    fixture=touching(f.container_fixture(layers=3,case='nominal'))
    sample=held_scene(fixture,2)
    sample['boxes'][0]['position'][1]=.00089
    target=f.cube_release_target(2,sample,.04,fixture=fixture)
    sample['boxes'][2]['position']=target[:]
    sample['tcps'][1]=target[:]
    assert f.cube_release_ready(2,sample,.04,fixture=fixture)
    sample['boxes'][2]['position'][1]+=.00004
    sample['tcps'][1][1]+=.00004
    assert not f.cube_release_ready(2,sample,.04,fixture=fixture)


def test_pad_swept_bound_covers_all_finger_angles_with_contact_skin():
    import math
    for q in ([2**-.5,0.,2**-.5,0.],[2**-.5,2**-.5,0.,0.],[1.,0.,0.,0.]):
        lower=f.pad_sweep_bottom_relative_tcp(q)
        row=f.rotation_matrix(q)[2]
        from run_omx_backend import PAD_HALF_LENGTH,PAD_RADIUS,PAD_CONTACT_OFFSET_M,jaw_contact_point
        x,y=jaw_contact_point();tcp=(.09193,-.0016,0.)
        for side,pivot in ((1,(.0295,.0075,0.)),(-1,(.0295,-.0108,0.))):
            for j in range(101):
                angle=-math.pi+2*math.pi*j/100
                px=x*math.cos(angle)-side*(y+PAD_RADIUS)*math.sin(angle)
                py=x*math.sin(angle)+side*(y+PAD_RADIUS)*math.cos(angle)
                bottom=sum(row[k]*(pivot[k]+(px,py,0.)[k]-tcp[k]) for k in range(3))
                bottom-=PAD_HALF_LENGTH*abs(row[2])+PAD_RADIUS+PAD_CONTACT_OFFSET_M
                assert bottom >= lower-1e-12


@pytest.mark.parametrize('layers,case', [(0, 'nominal'), (2, 'nominal'), (3, 'unknown'), (True, 'offset')])
def test_invalid_container_profiles_are_not_admitted(layers, case):
    with pytest.raises(ValueError):
        f.container_fixture(layers=layers, case=case)


def test_new_case_is_bound_to_immutable_scene_and_old_case_is_preserved():
    config = dict(seed=42, layers=3, case='offset')
    normalized = normalize('omx-map-container-stack', config)
    assert requested(normalized) == config
    value = input_snapshot('omx-map-container-stack', config, 'a'*40)['input']
    assert value['scene'] == f.container_fixture(layers=3, case='offset')
    assert value['scene']['infeed_jitter_xy_m'] == [.005, .008]
    assert normalize('omx-map-cube-stack', {'seed':42})['fixture'] == f.CUBE_FIXTURE['revision']
    assert len(f.plan(True)) == 3


@pytest.mark.parametrize('case',['nominal','column'])
def test_three_layer_carry_and_release_targets_are_reachable_by_the_owner(tmp_path,case):
    from mapped_stack_task import Planner
    fixture = f.container_fixture(layers=3, case=case)
    planner = Planner(tmp_path,scene=fixture.get('planning_scene'))
    homes = planner.request('homes', bases=fixture['arm_bases_m'],
        base_yaws=fixture['arm_base_yaws_rad'], points=[f.home(0, True,fixture=fixture), f.home(1, True,fixture=fixture)])['homes']
    for arm in (0, 1):
        q = homes[arm]
        hover = [*fixture['pickup_center_m'][:2], fixture['carry_height_m']]
        points = [(hover,0.),(fixture['pickup_center_m'],0.),(hover,0.)]
        if fixture.get('leveling_protocol'):
            center=fixture['leveling_center_m']
            staged_hover=[*center[:2],fixture['carry_height_m']]
            stage_yaw=fixture['leveling_yaws_rad'][arm]
            points += [(staged_hover,stage_yaw),([*center[:2],center[2]+.030],stage_yaw),(staged_hover,stage_yaw),
                (f.home(arm,True,fixture=fixture),0.),(staged_hover,stage_yaw),
                ([*center[:2],center[2]+.017],stage_yaw),(staged_hover,stage_yaw)]
        for item in f.plan(True, fixture=fixture):
            if item['arm'] == arm:
                points.extend([([*item['target'][:2], fixture['carry_height_m']],0.),
                    ([*item['target'][:2], item['target'][2]+.038],0.)])
        for target,yaw in points:
            frames = planner.request('move', base=fixture['arm_bases_m'][arm],
                base_yaw=fixture['arm_base_yaws_rad'][arm], start=q, target=target, yaw=yaw, dt=f.DT)['frames']
            q = frames[-1]
            assert len(q) == 5


@pytest.mark.parametrize('case', ['nominal', 'offset', 'reverse'])
def test_rows_keep_a_two_to_five_millimetre_gap_inside_the_widened_envelope(case):
    fixture = f.container_fixture(layers=3, case=case)
    assert fixture['row_gap_band_m'] == [.002, .005]
    assert fixture['row_clearance_m'] == .002
    assert f.row_gaps(dict(boxes=bodies(fixture)), fixture) == pytest.approx([.0035]*6)
    ys = sorted({round(item['target'][1], 6) for item in f.plan(True, fixture=fixture)})
    assert ys == pytest.approx([-.0335, 0., .0335])
    assert ys[0]-.015 == pytest.approx(fixture['bin_origin_m'][1])
    assert ys[-1]+.015 == pytest.approx(fixture['bin_origin_m'][1]+fixture['bin_size_m'][1])


@pytest.mark.parametrize('drift,gap', [(.0015, .002), (-.0015, .005)])
def test_outer_release_keeps_the_band_against_measured_center_drift(drift, gap):
    fixture = f.container_fixture(layers=3, case='nominal')
    sample = held_scene(fixture, 1)
    sample['boxes'][0]['position'][1] -= drift
    desired = f.packed_release_position(1, sample, fixture)
    assert -(desired[1]-sample['boxes'][0]['position'][1])-.03 == pytest.approx(gap)


def judged_trial(fixture):
    import copy
    items = f.plan(True, fixture=fixture)
    final = dict(boxes=bodies(fixture), tcps=[f.home(i, True, fixture=fixture) for i in range(2)])
    layers = []
    for i, item in enumerate(items):
        base = 1000*i
        window = [dict(copy.deepcopy(final), tick=base+t) for t in range(0, 145, 12)] if i else []
        layers.append(dict(item=i, arm=item['arm'], source_center_z=.05,
            lift_samples=[dict(final, tick=base+t) for t in (0, 12, 24)],
            prefix_window=window, release_sample=dict(tick=base+400),
            settle_samples=[dict(copy.deepcopy(final), tick=base+500+t) for t in range(0, 145, 12)]))
    return dict(layers=layers)


@pytest.mark.parametrize('mutation', [None, 'narrow', 'wide', 'no_window', 'late_window'])
def test_nine_container_judge_requires_gap_band_and_prior_stack_windows(monkeypatch, mutation):
    fixture = f.container_fixture(layers=3, case='nominal')
    monkeypatch.setattr(f, 'leveling_sequence_observed', lambda *a: True)
    monkeypatch.setattr(f, 'free_lift', lambda *a: True)
    trial = judged_trial(fixture)
    # Within the 1.5mm position tolerance, only the measured gap leaves the band; the boxes rest there.
    for final in trial['layers'][-1]['settle_samples']:
        if mutation == 'narrow':
            final['boxes'][1]['position'][1] += .0014
            final['boxes'][0]['position'][1] -= .0002
        elif mutation == 'wide':
            final['boxes'][2]['position'][1] += .0008
            final['boxes'][0]['position'][1] -= .0014
    if mutation == 'no_window':
        trial['layers'][4]['prefix_window'] = []
    elif mutation == 'late_window':
        trial['layers'][4]['release_sample']['tick'] = 4100
    result = f.judge(trial, True, fixture=fixture)
    expected = {None: [], 'narrow': ['row_gap_outside_band'], 'wide': ['row_gap_outside_band'],
                'no_window': ['layer_5:prior_stack_window_not_observed'],
                'late_window': ['layer_5:prior_stack_window_not_observed']}[mutation]
    assert result['failures'] == expected


def test_nine_container_budget_covers_the_measured_run_and_the_mp4_cap():
    import inspect
    import run_system
    import run_worker
    from run_catalog import catalog
    entry = next(e for e in catalog() if e['id'] == 'omx-map-container-stack')
    assert entry['timeout_seconds'] == 2520
    assert "timeout = 2520 if scenario == 'omx-map-container-stack'" in inspect.getsource(run_system)
    assert "'timeout': 2310 if container_task" in inspect.getsource(run_worker)
