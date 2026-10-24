"""Passive tracking diagnostics retain original control facts without authority."""
from pathlib import Path
import sys
from types import SimpleNamespace as NS

import pytest

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'deploy/robot/omx'))
from sim_policy_tracking import ControllerTracking

NAMES=tuple(f'joint{i}' for i in range(1,6))+('gripper_joint_1',)


def message():
    def point(value):return NS(positions=[value]*6,velocities=[value/2]*6)
    return NS(header=NS(stamp=NS(sec=23,nanosec=4)),joint_names=list(NAMES),
        reference=point(.3),feedback=point(.2),error=point(.1))


def make():
    clock=[10.]
    return ControllerTracking(NAMES,clock=lambda:clock[0],command_reference=lambda:'command-A'),clock


def finish(trace):
    documents=[]
    summary=trace.finish(Path('trace.json'),lambda path,doc:documents.append(doc))
    return summary,documents[0]


def test_freezes_jazzy_reference_feedback_error_with_two_distinct_clocks():
    trace,clock=make();msg=message();trace.observe(msg)
    msg.reference.positions[0]=99.
    clock[0]=10.05;trace.observe(message())
    clock[0]=10.1;trace.observe(message())
    summary,doc=finish(trace)
    assert summary['status']=='complete' and summary['samples']==2
    first=doc['samples'][0]
    assert first['reference']['positions']==[.3]*6
    assert first['feedback']['velocities']==[.1]*6
    assert first['error']['positions']==[.1]*6
    assert first['ros_stamp_ns']==23_000_000_004 and first['received_owner_ns']==10_000_000_000
    assert first['joint_names']==list(NAMES) and first['active_command_reference']=='command-A'
    assert doc['command_reference_scope']=='observation_only_not_controller_goal_binding'
    assert doc['sample_period_ns']==100_000_000
    clock[0]=11.;trace.observe(message())
    assert len(doc['samples'])==2


@pytest.mark.parametrize('bad', ['order','position_count','nonfinite','velocity_count','stamp','missing'])
def test_bad_messages_are_incomplete_and_never_escape_into_control(bad):
    trace,_=make();msg=message()
    if bad=='order':msg.joint_names.reverse()
    elif bad=='position_count':msg.feedback.positions.pop()
    elif bad=='nonfinite':msg.error.positions[0]=float('nan')
    elif bad=='velocity_count':msg.reference.velocities=[0.]
    elif bad=='stamp':msg.header.stamp.nanosec=1_000_000_000
    else:del msg.reference
    trace.observe(msg)
    summary,doc=finish(trace)
    assert summary['status']=='incomplete' and summary['invalid_messages']==1
    assert doc['samples']==[]


def test_missing_velocities_are_reported_as_missing_not_filled_in():
    trace,_=make();msg=message();msg.feedback.velocities=[];trace.observe(msg)
    _,doc=finish(trace)
    assert doc['samples'][0]['feedback']['velocities']==[]


def test_cap_is_bounded_and_does_not_silently_claim_complete():
    trace,clock=make()
    for index in range(6001):
        clock[0]=10.+index*.2;trace.observe(message())
    summary,doc=finish(trace)
    assert len(doc['samples'])==6000 and summary['truncated'] is True
    assert summary['status']=='incomplete'


def test_observer_or_writer_failure_cannot_replace_native_control_outcome():
    trace=ControllerTracking(NAMES,clock=lambda:1.,command_reference=lambda:1/0)
    trace.observe(message())
    def failed_writer(path,doc):raise OSError('diagnostic storage unavailable')
    summary=trace.finish(Path('trace.json'),failed_writer)
    assert summary['status']=='incomplete' and summary['invalid_messages']==1
    assert summary['write_error']=='OSError'
