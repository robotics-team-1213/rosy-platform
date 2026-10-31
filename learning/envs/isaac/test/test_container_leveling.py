"""Physical tabletop leveling must precede a second measured free lift."""
import copy
import math
import re
from pathlib import Path
import sys
import pytest
from types import ModuleType,SimpleNamespace

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
sys.path.insert(0,str(Path(__file__).resolve().parent))
import mapped_stack_fixture as f
from test_container_stack import held_scene


def table_sample(fixture,index=0):
    sample=held_scene(fixture,index)
    body=sample['boxes'][index]
    body['position']=[*fixture['leveling_center_m'][:2],fixture['leveling_center_m'][2]+.015]
    body['orientation']=[1.,0.,0.,0.]
    body['forces']=[[0.,0.,0.] for _ in f.contact_names(index,True,fixture=fixture)]
    body['forces'][-1]=[0.,0.,.6]
    body['net_force']=[0.,0.,.6]
    sample['tcps']=[f.home(i,True,fixture=fixture) for i in range(2)]
    return sample


def stage_record(fixture,index=0):
    arm=f.plan(True,fixture=fixture)[index]['arm']
    released=held_scene(fixture,index)
    position=[*fixture['leveling_center_m'][:2],fixture['leveling_center_m'][2]+.030]
    released['boxes'][index]['position']=position[:]
    released['tcps'][arm]=position[:]
    released['tick']=60
    table=table_sample(fixture,index)
    lifted=held_scene(fixture,index)
    lifted['boxes'][index]['position'][:2]=position[:2]
    lifted['tcps'][arm][:2]=position[:2]
    window=[dict(held_scene(fixture,index),tick=t) for t in range(-96,49,12)] if index else []
    return dict(arm=arm,source_center_z=table['boxes'][index]['position'][2],prefix_window=window,
        release_sample=released,opened_sample=dict(copy.deepcopy(table),tick=80),
        settle_samples=[dict(copy.deepcopy(table),tick=t) for t in range(120,253,12)],
        grasp_samples=[dict(copy.deepcopy(table),tick=260),dict(copy.deepcopy(table),tick=280)],
        lift_samples=[dict(copy.deepcopy(lifted),tick=t) for t in (300,312,324,336)])


def test_leveling_region_is_clear_of_the_pallet_and_uses_existing_table():
    fixture=f.container_fixture(layers=3,case='nominal')
    assert fixture['leveling_protocol']=='TABLE_SUPPORT_THEN_REGRASP'
    center,size=fixture['leveling_center_m'],fixture['leveling_size_m']
    assert center==pytest.approx([-.04,0.,.072])
    assert size==[.12,.10]
    assert fixture['leveling_yaws_rad']==pytest.approx([math.pi,math.pi])
    assert all(abs(math.sin(yaw))<1e-12 for yaw in fixture['leveling_yaws_rad'])
    assert center[0]+size[0]/2 < fixture['bin_origin_m'][0]
    assert f.contact_names(0,True,fixture=fixture)[-1]=='table'
    assert 'table' not in f.contact_names(0,True)


@pytest.mark.parametrize('index',[0,1,2,3,6])
def test_leveling_requires_supported_flat_settling_and_another_free_lift(index):
    fixture=f.container_fixture(layers=3,case='nominal')
    stage=stage_record(fixture,index)
    assert f.leveling_observed(stage,index,fixture)
    bad=copy.deepcopy(stage)
    bad['lift_samples'][-1]['boxes'][index]=table_sample(fixture,index)['boxes'][index]
    assert not f.leveling_observed(bad,index,fixture)
    bad=copy.deepcopy(stage)
    bad['lift_samples'][0]['tick']=200
    assert not f.leveling_observed(bad,index,fixture)


@pytest.mark.parametrize('failure',['tilt','moving','outside','finger','wrong_support'])
def test_time_alone_or_wrong_contacts_do_not_establish_leveling(failure):
    fixture=f.container_fixture(layers=1,case='nominal')
    body=table_sample(fixture)['boxes'][0]
    assert f.leveling_box_stable(body,0,fixture)
    if failure=='tilt':
        body['orientation']=[math.cos(.02),math.sin(.02),0.,0.]
    elif failure=='moving':
        body['velocity'][0]=.02
    elif failure=='outside':
        body['position'][0]=.01
    else:
        body['forces'][0 if failure=='finger' else 4]=[0.,0.,.02]
        body['net_force'][2]+=.02
    assert not f.leveling_box_stable(body,0,fixture)


def test_staging_stops_if_a_previously_placed_container_moves():
    fixture=f.container_fixture(layers=3,case='nominal')
    stage=stage_record(fixture,1)
    stage['settle_samples'][3]['boxes'][0]['position'][1]+=.005
    assert not f.leveling_observed(stage,1,fixture)


def test_prior_stack_speed_is_judged_by_the_window_before_leveling_release():
    fixture=f.container_fixture(layers=3,case='nominal')
    stage=stage_record(fixture,1)
    stage['settle_samples'][3]['boxes'][0]['angular_velocity']=[.12,0.,0.]
    stage['lift_samples'][1]['boxes'][0]['angular_velocity']=[.12,0.,0.]
    assert f.leveling_observed(stage,1,fixture)
    for mutate in ('missing','spike','late'):
        bad=copy.deepcopy(stage)
        if mutate=='missing':bad['prefix_window']=[]
        elif mutate=='spike':
            bad['prefix_window'][5]['boxes'][0]['angular_velocity']=[.1004,0.,0.]
            bad['prefix_window'][5]['boxes'][0]['orientation']=[math.cos(.006),math.sin(.006),0.,0.]
        else:bad['release_sample']['tick']=40
        assert not f.leveling_observed(bad,1,fixture)


def test_stage_release_feedback_requires_unsupported_hold():
    fixture=f.container_fixture(layers=1,case='nominal')
    sample=held_scene(fixture,0)
    target=f.leveling_release_target(0,sample,fixture)
    assert target==pytest.approx([-.04,0.,.102])
    sample['boxes'][0]['forces'][-1]=[0.,0.,.6]
    sample['boxes'][0]['net_force'][2]+=.6
    with pytest.raises(ValueError,match='unsupported'):
        f.leveling_release_target(0,sample,fixture)


@pytest.mark.parametrize('failure',[None,'first_lift','second_lift','opening','settling'])
def test_leveling_evidence_belongs_between_the_two_real_lifts_and_final_release(failure):
    fixture=f.container_fixture(layers=1,case='nominal')
    layer=dict(leveling=stage_record(fixture),lift_samples=[dict(tick=t) for t in (0,12,24)],
        release_sample=dict(tick=400),opened_sample=dict(tick=420),
        settle_samples=[dict(tick=t) for t in range(440,573,12)])
    if failure=='first_lift':
        layer['lift_samples'][-1]['tick']=70
    elif failure=='second_lift':
        layer['release_sample']['tick']=320
    elif failure=='opening':
        layer['opened_sample']['tick']=390
    elif failure=='settling':
        layer['settle_samples'][0]['tick']=410
    assert f.leveling_sequence_observed(layer,0,fixture) is (failure is None)


def test_leveling_outline_creates_valid_unique_visual_usd_prims(monkeypatch):
    from mapped_stack_task import build_map
    made=[]
    def create(kind):
        def object_(path,**values):
            assert path.startswith('/World/')
            assert re.fullmatch('[A-Za-z_][A-Za-z_0-9]*',path.rsplit('/',1)[-1]),path
            result=SimpleNamespace(path=path,kind=kind,values=values)
            made.append(result)
            return result
        return object_
    pxr=ModuleType('pxr');pxr.Gf=SimpleNamespace();pxr.UsdGeom=SimpleNamespace()
    monkeypatch.setitem(sys.modules,'pxr',pxr)
    for name in ('isaacsim','isaacsim.core','isaacsim.core.api','isaacsim.core.api.objects'):
        monkeypatch.setitem(sys.modules,name,ModuleType(name))
    objects=sys.modules['isaacsim.core.api.objects']
    objects.FixedCuboid=create('fixed');objects.VisualCuboid=create('visual')
    world=SimpleNamespace(scene=SimpleNamespace(add=lambda value:value))
    build_map(world,None,f.container_fixture(layers=1,case='nominal'))
    markers=[v for v in made if 'LevelingBoundary' in v.path]
    assert len(markers)==4 and len({v.path for v in markers})==4
    assert all(v.kind=='visual' and v.values['scale'][2]<=.001 for v in markers)
