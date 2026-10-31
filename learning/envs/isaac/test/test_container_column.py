"""Authorized 3x1x3 fallback: three long bars, one per floor, alternating arms."""
from pathlib import Path
import sys

import pytest

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
sys.path.insert(0,str(Path(__file__).resolve().parent))
import mapped_stack_fixture as f
from run_catalog import normalize
from run_store import input_snapshot
from run_store import RunStore
from test_container_stack import bodies,held_scene


def test_column_has_three_floors_and_keeps_the_actual_map_and_nominal_infeed():
    fixture=f.container_fixture(layers=3,case='column')
    items=f.plan(True,fixture=fixture)
    assert fixture['target_cells']==[3,1,3]
    assert fixture['bin_size_m']==[.09,.03,.09]
    assert fixture['bin_origin_m']==[.035,-.015,.074]
    assert fixture['arm_bases_m']==f.container_fixture(layers=3,case='nominal')['arm_bases_m']
    assert fixture['infeed_jitter_xy_m']==[.001,.001]
    assert fixture['infeed_yaw_jitter_rad']==.01
    assert [v['cell'] for v in items]==[[0,0,0],[0,0,1],[0,0,2]]
    assert [v['arm'] for v in items]==[0,1,0]
    assert [v['target'][2] for v in items]==pytest.approx([.089,.119,.149])


def test_column_requires_each_actual_lower_bar_instead_of_the_floor():
    fixture=f.container_fixture(layers=3,case='column')
    boxes=bodies(fixture)
    assert all(f.stable_box(b,i,True,fixture=fixture) for i,b in enumerate(boxes))
    names=f.contact_names(1,True,fixture=fixture)
    boxes[1]['forces'][names.index('bar-1')][2]=0.
    boxes[1]['forces'][names.index('bin')][2]=.6
    assert not f.stable_box(boxes[1],1,True,fixture=fixture)


def test_column_uses_center_release_without_outer_row_packing():
    fixture=f.container_fixture(layers=3,case='column')
    for i,item in enumerate(f.plan(True,fixture=fixture)):
        command=f.cube_release_target(i,held_scene(fixture,i),.052,fixture=fixture)
        assert command[1]==0.
        assert command[2]==pytest.approx(item['target'][2]+.015)


def test_column_is_explicit_in_immutable_inputs_and_requires_three_layers():
    fixture=f.container_fixture(layers=3,case='column')
    assert normalize('omx-map-container-stack',dict(seed=42,layers=3,case='column'))['case']=='column'
    assert input_snapshot('omx-map-container-stack',dict(seed=42,layers=3,case='column'),'a'*40)['input']['scene']==fixture
    with pytest.raises(ValueError):f.container_fixture(layers=1,case='column')
    assert len(f.plan(True,fixture=f.container_fixture(layers=3,case='nominal')))==9


@pytest.mark.parametrize('case,last,accepted',[('column',3,True),('column',9,False),('nominal',3,False),('nominal',9,True)])
def test_store_requires_the_actual_last_placement_for_each_grid(tmp_path,monkeypatch,case,last,accepted):
    store=RunStore(tmp_path/'runs')
    row=store.create('1'*32,'omx-map-container-stack',dict(seed=42,layers=3,case=case),'a'*40)
    row=store.update(row['run_id'],row['revision'],dict(status='RUNNING'))
    ids=['mapped-stack-report','mapped-video','mapped-video-frames','mapped-video-encoder','mapped-trial-1',f'mapped-layer-{last}']
    # Byte and video verification have their own tests; this isolates the final-grid evidence gate.
    monkeypatch.setattr(store,'_manifest',lambda run_id,items,**kwargs:dict(snapshot='FINAL',files=items))
    result=dict(status='SUCCEEDED',stage='mapped_container_stack',task_success=True,
        successful_trials=1,video_verified=True,import_verified=True,exit_code=0,
        cleanup='OWNED_PROCESSES_EXITED_GPU_RELEASED')
    if accepted:
        assert store.finish(row['run_id'],row['revision'],result,[dict(id=v) for v in ids])['status']=='SUCCEEDED'
    else:
        with pytest.raises(ValueError,match='Layered container'):
            store.finish(row['run_id'],row['revision'],result,[dict(id=v) for v in ids])
