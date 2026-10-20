"""Only recorded native acceptance/result and observed gripper/object count."""
from pathlib import Path
import sys

import pytest

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'deploy/robot/omx'))
from sim_policy_trial_evidence import goal_succeeded, object_transition


def trace():
    goal='12345678-1234-5678-1234-567812345678'
    return dict(driver_goal_id=goal,events=[
        dict(kind='GOAL_ACCEPTED',goal_id=goal),
        dict(kind='TERMINAL_RESULT',goal_id=goal,status=4,result_code=0)])


def test_goal_requires_original_accepted_uuid_and_successful_result():
    assert goal_succeeded(trace())
    for field,value in [('goal_id','other'),('status',5),('result_code',1),('kind','TERMINAL_UNKNOWN')]:
        row=trace();row['events'][-1][field]=value
        assert not goal_succeeded(row)
    row=trace();row['events']=row['events'][-1:]
    assert not goal_succeeded(row)


@pytest.mark.parametrize('held,xy,z,expected',[
    (True,.009,.009,'attach'),(False,0.,0.,None),
    (True,.011,0.,None),(True,0.,.011,None)])
def test_attach_requires_actual_verified_hold_and_observed_object_geometry(held,xy,z,expected):
    assert object_transition(attached=False,ever_attached=False,held=held,released=False,
        target_gripper=.5,contact_gripper=.6,xy_error_m=xy,z_error_m=z)==expected


def test_detach_uses_learned_opening_and_settle_requires_actual_release():
    state=dict(attached=True,ever_attached=True,held=True,released=False,
        target_gripper=.6,contact_gripper=.6,xy_error_m=0.,z_error_m=0.)
    assert object_transition(**state) is None
    assert object_transition(**dict(state,target_gripper=.63))=='detach'
    state.update(attached=False,held=False)
    assert object_transition(**state) is None
    assert object_transition(**dict(state,released=True))=='settle'
