"""Wait for the original uninterrupted stability window, never relax its limits."""
import copy
import math
from pathlib import Path
import sys

import pytest

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
sys.path.insert(0,str(Path(__file__).resolve().parent))
import mapped_stack_fixture as f
import mapped_stack_task as task
from test_container_stack import bodies


def replay(*,persistent=False,prefix_spike=False,case='column',frozen=False):
    fixture=f.container_fixture(layers=3,case=case)
    index=len(f.plan(True,fixture=fixture))-1
    ticks=[0]
    def snapshot():
        boxes=copy.deepcopy(bodies(fixture))
        n=ticks[0]//12
        # Native58f: nine quiet observations, then three >.1rad/s, then quiet again.
        # Motion is judged from the pose change over each 0.1 s sample step, not the reported velocity
        # (run b326: .18 rad/s reported while poses moved 6 um). A .012 rad turn per step is .12 rad/s.
        turn=0. if frozen else .012*(n%2)
        if persistent or 9<=n<=11:
            boxes[index]['angular_velocity']=[.12,0.,0.];boxes[index]['orientation']=[math.cos(turn/2),math.sin(turn/2),0.,0.]
        if prefix_spike and n==20:boxes[0]['angular_velocity']=[.2,0.,0.];boxes[0]['orientation']=[math.cos(.01),math.sin(.01),0.,0.]
        return dict(tick=ticks[0],boxes=boxes,tcps=[f.home(a,True,fixture=fixture) for a in (0,1)])
    def step():
        ticks[0]+=1
        assert ticks[0]<=1200
    return task.settle_stack(index,snapshot,step,fixture)


@pytest.mark.parametrize('prefix_spike',[False,True])
@pytest.mark.parametrize('case',['column','nominal'])
def test_transient_motion_resets_the_whole_stack_window(prefix_spike,case):
    rows=replay(prefix_spike=prefix_spike,case=case)
    # The sample that turns back is the last moving one and becomes the pose reference.
    expected_start=252 if prefix_spike else 144
    assert [s['tick'] for s in rows]==list(range(expected_start,expected_start+145,12))
    fixture=f.container_fixture(layers=3,case=case)
    count=len(f.plan(True,fixture=fixture))
    assert all(f.stable_box(s['boxes'][j],j,True,fixture=fixture) for s in rows[1:] for j in range(count))
    assert f.window_observed(rows,lambda s:all(f.stable_box(s['boxes'][j],j,True,fixture=fixture) for j in range(count)))


def test_persistent_motion_fails_within_ten_seconds():
    with pytest.raises(ValueError,match='stable window'):
        replay(persistent=True)


def test_a_fixed_pose_with_a_reported_speed_is_at_rest():
    rows=replay(persistent=True,frozen=True)
    assert [s['tick'] for s in rows]==list(range(0,145,12))
    assert rows[5]['boxes'][-1]['angular_velocity']==[.12,0.,0.]  # the record keeps the raw reading
    assert f.measured_motion(rows)[5]['boxes'][-1]['angular_velocity']==pytest.approx([0.,0.,0.])


def test_measured_motion_is_the_pose_change_over_the_sample_step():
    fixture=f.container_fixture(layers=3,case='column')
    a=dict(tick=0,boxes=copy.deepcopy(bodies(fixture)))
    b=dict(tick=12,boxes=copy.deepcopy(bodies(fixture)))
    b['boxes'][0]['position'][1]+=.0012
    b['boxes'][0]['orientation']=[math.cos(.006),math.sin(.006),0.,0.]
    moved=f.measured_motion([a,b])[1]['boxes'][0]
    assert f.norm(moved['velocity'])==pytest.approx(.012)
    assert f.norm(moved['angular_velocity'])==pytest.approx(.12)
