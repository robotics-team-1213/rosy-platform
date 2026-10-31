"""Retry a transient footprint failure without changing physical acceptance."""
import copy
import math
from pathlib import Path
import sys

import pytest

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
sys.path.insert(0,str(Path(__file__).resolve().parent))
import mapped_stack_fixture as f
import mapped_stack_task as task
from test_container_stack import held_scene,touching


def replay(*, resolves=True,bad=None):
    fixture=f.container_fixture(layers=3,case='nominal')
    fixture['transient_tilt_overhang_m']=0.
    touching(fixture)
    original=held_scene(fixture,1)
    original['boxes'][0]['position'][1]=-.0001874934
    original['boxes'][1]['orientation']=[-.0016473776,-.0006339789,-.0129270377,.9999149442]
    ticks=[0]
    def snapshot():
        value=copy.deepcopy(original)
        if resolves and ticks[0]>=36:value['boxes'][1]['orientation']=[1.,0.,0.,0.]
        if bad:bad(value)
        return value
    def step():
        ticks[0]+=1
        assert ticks[0]<=600
    command=task.packing_target(1,snapshot,step,.052,fixture)
    return command,ticks[0],original,fixture


def test_only_transient_footprint_failure_waits_and_then_uses_actual_geometry():
    command,ticks,original,fixture=replay()
    assert ticks==36
    sample=copy.deepcopy(original)
    sample['boxes'][1]['orientation']=[1.,0.,0.,0.]
    assert command==pytest.approx(f.cube_release_target(1,sample,.052,fixture=fixture))
    assert original['boxes'][1]['orientation']!=[1.,0.,0.,0.]


def test_persistent_tilt_still_fails_within_original_five_second_budget():
    with pytest.raises(ValueError,match='original envelope'):
        replay(resolves=False)


@pytest.mark.parametrize('kind',['finger','prefix'])
def test_contact_loss_and_prior_stack_instability_are_not_retryable(kind):
    seen=[]
    def bad(sample):
        seen.append(sample)
        if kind=='finger':sample['boxes'][1]['forces'][0]=[0.,0.,0.]
        else:sample['boxes'][0]['position'][1]+=.003
    with pytest.raises(ValueError,match='bilateral|[Pp]rior stack'):
        replay(bad=bad)
    assert len(seen)==1


def rocking(*,calm_after=None,moved_at=None):
    fixture=f.container_fixture(layers=3,case='nominal')
    original=held_scene(fixture,1)
    ticks=[0]
    def snapshot():
        value=dict(copy.deepcopy(original),tick=ticks[0])
        if calm_after is None or ticks[0]<calm_after:
            turn=.012*(ticks[0]//12%2)  # a real .12 rad/s turn over each 0.1 s step
            value['boxes'][0]['angular_velocity']=[.1004,0.,0.];value['boxes'][0]['orientation']=[math.cos(turn/2),math.sin(turn/2),0.,0.]
        if moved_at is not None and ticks[0]>=moved_at:value['boxes'][0]['position'][1]+=.003
        return value
    def step():
        ticks[0]+=1
    return fixture,snapshot,step,ticks


def test_speed_only_prefix_excursion_waits_for_the_original_stable_window():
    fixture,snapshot,step,ticks=rocking(calm_after=60)
    window=task.await_prefix(1,snapshot,step,fixture)
    assert [s['tick'] for s in window]==list(range(48,193,12))
    assert f.prefix_window_observed(window,1,fixture,192)
    assert not f.prefix_window_observed(window,1,fixture,191)
    assert not f.prefix_window_observed(window[1:],1,fixture,192)
    assert not f.prefix_window_observed([window[0]]+window[2:]+[window[-1]],1,fixture,192)


def test_persistent_prefix_speed_fails_after_ten_seconds():
    fixture,snapshot,step,ticks=rocking()
    with pytest.raises(ValueError,match='ten seconds') as error:
        task.await_prefix(1,snapshot,step,fixture)
    assert ticks[0]==1200
    # The refusal names which placed box failed, how often, and how fast it really moved.
    assert 'box0 fail 100/100 v 0.0000 w 0.1200 step 0.0e+00' in str(error.value)


def test_prefix_displacement_stops_at_once_even_while_waiting():
    fixture,snapshot,step,ticks=rocking(moved_at=24)
    with pytest.raises(ValueError,match='Prior stack moved'):
        task.await_prefix(1,snapshot,step,fixture)
    assert ticks[0]==24


def test_first_placement_has_no_prior_stack_window():
    fixture,snapshot,step,ticks=rocking()
    assert task.await_prefix(0,snapshot,step,fixture)==[]
    assert ticks[0]==0 and f.prefix_window_observed([],0,fixture,0)
