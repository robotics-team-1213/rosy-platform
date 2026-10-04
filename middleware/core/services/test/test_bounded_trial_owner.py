"""Pure bounded-trial ledger policy, synthetic bounds; no bridge or robot IO."""
import pytest
from core_features.command.manager import Twist
from core_features.command.bounded_trial import BoundedTrial, Bounds


def bounds(**changes):
    values=dict(speed_max_mps=.05, angular_max_radps=.5, decel_min_mps2=.1,
                latency_max_s=.1, source_age_max_s=.1, sample_gap_max_s=.2,
                measurement_error_m=.01, path_scale_upper=1.1, duration_s=5.,
                evidence_sha256='a'*64)
    return Bounds(**dict(values, **changes))

def guard(tmp_path, **changes):
    return BoundedTrial(tmp_path/'one-trial.sqlite',trial_id='one',robot_id='9dfk',
                        boot_id='boot',frame_id='odom',bounds=bounds(**changes),now=10.)

def sample(g,x=0.,stamp=1000000000,now=10.,**changes):
    values=dict(x=x,y=0.,stamp_ns=stamp,source_now_ns=stamp,frame_id='odom',now=now)
    return g.observe(**dict(values,**changes))


def cycle(g,twist,now=10.):
    # Test the owner's admission/callback result without importing a gateway.
    decision=g.submit_fenced(twist.linear,twist.angular,lambda:twist,now=now)
    return Twist() if decision is None else decision


def test_path_accumulates_backtracking_and_stops_before_reserve(tmp_path):
    g=guard(tmp_path);sample(g);assert cycle(g,Twist(.04,0)).linear>0
    for index in range(1,34):
        x=.0049 if index%2 else 0.
        sample(g,x,1000000000+index*100000000,10.+index*.1)
    assert cycle(g,Twist(.04,0),13.3)==Twist()
    assert g.status()['path_upper_m']==pytest.approx(.17787)
    assert g.status()['reason']=='distance_reserve'
    sample(g,.0069,4400000000,13.4)
    assert g.status()['path_upper_m']==pytest.approx(.18007)



@pytest.mark.parametrize('bad',[
    {'stamp_ns':1000000000}, {'stamp_ns':999999999}, {'x':float('nan')},
    {'x':.1}, {'frame_id':'map'}, {'source_now_ns':1400000000},
    {'source_now_ns':999999999}, {'now':10.4},
])
def test_bad_pose_latches_stop_and_fresh_sample_cannot_resume(tmp_path,bad):
    g=guard(tmp_path);sample(g);cycle(g,Twist(.04,0))
    sample(g,**dict(dict(stamp=1100000000,now=10.1),**bad))
    assert cycle(g,Twist(.04,0),10.1)==Twist()
    sample(g,stamp=1200000000,now=10.2)
    assert cycle(g,Twist(.04,0),10.2)==Twist()



def test_stale_pose_and_expiry_deny_before_command(tmp_path):
    g=guard(tmp_path);sample(g)
    assert cycle(g,Twist(.04,0),10.11)==Twist()
    assert g.status()['issued'] is False



def test_unknown_bounds_cannot_construct_or_arm(tmp_path):
    with pytest.raises(ValueError):guard(tmp_path,decel_min_mps2=None)
    with pytest.raises(ValueError):guard(tmp_path,evidence_sha256='')



def test_restart_never_creates_fresh_budget_or_replays_command(tmp_path):
    g=guard(tmp_path);sample(g);cycle(g,Twist(.04,0));sample(g,.005,1100000000,10.1)
    restarted=guard(tmp_path)
    assert restarted.status()['path_upper_m']==pytest.approx(.0055)
    assert cycle(restarted,Twist(.04,0))==Twist()
    assert cycle(g,Twist(.04,0),10.1)==Twist()



@pytest.mark.parametrize('twist',[Twist(.06,0),Twist(0,.6),Twist(float('nan'),0)])
def test_command_outside_measured_envelope_is_zero(tmp_path,twist):
    g=guard(tmp_path);sample(g)
    assert cycle(g,twist)==Twist()



def test_slow_durable_write_cannot_send_after_freshness_expires(tmp_path,monkeypatch):
    from core_features.command import bounded_trial
    clock=[10.]
    monkeypatch.setattr(bounded_trial.time,'monotonic',lambda:clock[0])
    g=guard(tmp_path);sample(g)
    write=g._write
    def slow(state):
        write(state)
        clock[0]=10.2
    monkeypatch.setattr(g,'_write',slow)
    assert g.permits(.04,0) is False






def test_nan_final_clock_cannot_grant(tmp_path,monkeypatch):
    from core_features.command import bounded_trial
    clock=[10.];monkeypatch.setattr(bounded_trial.time,'monotonic',lambda:clock[0])
    g=guard(tmp_path);sample(g);write=g._write
    def corrupt_clock(state):write(state);clock[0]=float('nan')
    monkeypatch.setattr(g,'_write',corrupt_clock)
    assert g.permits(.04,0) is False



def test_source_clock_reset_cannot_refresh_old_pose(tmp_path):
    g=guard(tmp_path)
    sample(g,source_now_ns=1100000000)
    sample(g,stamp=1050000000,source_now_ns=1050000000,now=10.05)
    assert cycle(g,Twist(.04,0),10.05)==Twist()



def test_second_connection_cannot_clobber_stop_from_old_read(tmp_path,monkeypatch):
    import sqlite3
    g=guard(tmp_path);sample(g);read=g._read;attempted=[]
    def interleave(**kwargs):
        state=read(**kwargs)
        if not attempted:
            attempted.append(True)
            with pytest.raises(sqlite3.OperationalError,match='locked'):guard(tmp_path)
        return state
    monkeypatch.setattr(g,'_read',interleave)
    sample(g,.001,1100000000,10.1)
    monkeypatch.setattr(g,'_read',read)
    restarted=guard(tmp_path)
    assert restarted.status()['halted'] is True
    assert cycle(g,Twist(.04,0),10.1)==Twist()

