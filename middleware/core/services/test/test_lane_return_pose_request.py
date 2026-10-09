"""D-546 5: lane_return asks Fleet for a pose (CORE side); host-level, fakes, no ROS."""
import json
import pytest
from core_features.line_follow.model import LineFollowMode
from core_features.localization import LocalizationAssist, PoseRequests
from test_lane_return_manager import rig, frame


class Events:
    def __init__(self): self.sent=[]
    def publish(self,type_,severity='info',source='',data=None): self.sent.append((type_,dict(data or {})))
    def names(self): return [t for t,_ in self.sent]


def rigged(probe=lambda now,v,w: True):
    r=rig(probe)
    events=Events()
    book=PoseRequests(events,lambda:'rosy_test',clock=lambda:r[0][0])
    r[2].bind_pose_request(book.open,book.clear)
    return r,book,events


def exhaust_local(r):
    for step in range(101): frame(r,1.+step*.05,.055)  # motion proof denied: candidates run out


def test_fleet_required_opens_one_request_with_the_pose_evidence():
    r,book,events=rigged(lambda now,v,w:v==0)
    exhaust_local(r)
    request=book.current()
    assert request['reason']=='fleet_required' and request['robot_id']=='rosy_test'
    assert request['ttl_s']>0 and request['created_at']>0
    assert request['evidence']['odom_pose']['frame']=='odom'
    assert request['evidence']['odom_pose']['stamp_ns']>0
    assert request['evidence']['lane']['visible'] is True
    for t in (6.,6.05): frame(r,t,.055)          # still held, still the same request
    assert book.current()['request_id']==request['request_id']
    assert events.names().count('localization.request')==1
    assert r[2].status().state=='HOLD'


def test_pose_stale_asks_only_after_the_pose_stays_stale():
    r,book,_=rigged()
    frame(r,1.,.055); frame(r,1.05,.055)
    for t in (1.5,2.0,2.4):                       # no odom sample any more, ticks go on
        r[0][0]=t; r[2].tick(t)
    assert book.current() is None                 # < 1 s since the first stale tick (1.5)
    r[0][0]=2.6; r[2].tick(2.6)
    request=book.current()
    assert request is not None and request['reason']=='pose_stale'
    assert request['evidence']['odom_pose']['age_s']>=1.0
    frame(r,2.65,.055)                            # pose evidence is back: the request closes
    assert book.current() is None


def test_an_accepted_answer_resumes_the_fleet_phase_without_asking_again():
    r,book,events=rigged(lambda now,v,w:v==0)
    exhaust_local(r)
    for step in range(1,12): frame(r,6.+step*.05,.055-step*.005)
    assert book.current() is not None and r[2].status().stuck is not None
    assert book.clear('answered')                 # what LocalizationAssist does on result.accepted
    r[2].resume_after_pose()
    r[2].bind_return_motion(lambda now,v,w:True)
    for t in (6.6,6.65,6.7):
        assert frame(r,t).linear==0
    assert frame(r,6.75).linear>0                 # lane_return continues on fresh pose evidence
    assert r[2].status().stuck is None and book.current() is None


def test_resume_after_pose_is_a_no_op_outside_the_fleet_phase():
    r,book,_=rigged()
    frame(r,1.,.055); frame(r,1.05,.055)
    before=r[2].status().reason
    r[2].resume_after_pose()
    assert r[2].status().reason==before


def test_leaving_line_follow_clears_the_request():
    r,book,_=rigged(lambda now,v,w:v==0)
    exhaust_local(r)
    assert book.current() is not None
    r[2].set_mode(LineFollowMode.OFF)
    assert book.current() is None


def test_request_book_ttl_reopens_with_a_new_id_and_keeps_the_id_meanwhile():
    now=[100.]
    book=PoseRequests(Events(),lambda:'rosy_test',clock=lambda:now[0],ttl_s=10.)
    first=book.open('pose_stale',{'a':1})
    now[0]=105.
    again=book.open('pose_stale',{'a':2})
    assert again['request_id']==first['request_id'] and book.current()['evidence']=={'a':2}
    assert book.current()['age_s']==pytest.approx(5.)
    now[0]=111.
    assert book.current() is None                 # older than its ttl: Fleet must not use it
    assert book.open('pose_stale',{})['request_id']!=first['request_id']
    assert book.open('fleet_required',{})['reason']=='fleet_required'
    with pytest.raises(ValueError): book.open('because',{})


def test_assist_accepted_result_clears_the_request_and_resumes_line_follow():
    events=Events()
    assist=LocalizationAssist(events,lambda:'rosy_test')
    resumed=[]
    assist.on_pose_answered=lambda:resumed.append(1)
    assist.pose_requests.open('fleet_required',{})
    result=lambda ok: json.dumps({'request_id':'pose-1','accepted':ok,'state':'LOCALIZED' if ok else 'CANDIDATES'})
    assist.on_result(result(False))
    assert assist.pose_requests.current() is not None and not resumed   # the robot's check failed
    assist.on_result(result(True))
    assert assist.pose_requests.current() is None and resumed==[1]
    assert 'localization.request_cleared' in events.names()
