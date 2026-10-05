"""Private CORE trial restriction, synthetic bounds only; never motion evidence."""
from types import SimpleNamespace
import pytest
from core.bridge.cmd_vel import cmd_vel_cycle, Twist


def bounds(**changes):
    from core_features.command.bounded_trial import Bounds
    values=dict(speed_max_mps=.05, angular_max_radps=.5, decel_min_mps2=.1,
                latency_max_s=.1, source_age_max_s=.1, sample_gap_max_s=.2,
                measurement_error_m=.01, path_scale_upper=1.1, duration_s=5.,
                evidence_sha256='a'*64)
    return Bounds(**dict(values, **changes))


def guard(tmp_path, **changes):
    from core_features.command.bounded_trial import BoundedTrial
    return BoundedTrial(tmp_path/'one-trial.sqlite',trial_id='one',robot_id='9dfk',
                        boot_id='boot',frame_id='odom',bounds=bounds(**changes),now=10.)


def sample(g,x=0.,stamp=1000000000,now=10.,**changes):
    values=dict(x=x,y=0.,stamp_ns=stamp,source_now_ns=stamp,frame_id='odom',now=now)
    return g.observe(**dict(values,**changes))


def cycle(g,twist,now=10.,ready=True):
    sent=[]
    cmd=SimpleNamespace(select_output=lambda:twist,announce_pending=lambda:None)
    power=SimpleNamespace(on_activity=lambda _:None)
    readiness=SimpleNamespace(is_ready=lambda:ready)
    cmd_vel_cycle(cmd,power,sent.append,readiness,trial_guard=g,now=now)
    return sent[-1]


def test_core_final_path_allows_bounded_candidate_without_mask_prerequisite(tmp_path):
    g=guard(tmp_path);sample(g)
    assert cycle(g,Twist(.04,.2))==Twist(.04,.2)
    assert g.status()['issued'] is True


def test_readiness_stop_consumes_trial_and_never_replays_on_release(tmp_path):
    g=guard(tmp_path);sample(g);cycle(g,Twist(.04,0))
    assert cycle(g,Twist(.04,0),ready=False)==Twist()
    assert cycle(g,Twist(.04,0),ready=True)==Twist()


def test_guard_failure_is_zero_on_existing_sole_send_path(tmp_path):
    g=guard(tmp_path);sample(g);g.close()
    assert cycle(g,Twist(.04,0))==Twist()


def test_bridge_preserves_original_stamp_frame_and_source_clock(tmp_path):
    from core.bridge.odometry import observe_bounded_trial
    g=guard(tmp_path)
    bridge=SimpleNamespace(_bounded_trial_guard=g,_node=SimpleNamespace(
        get_clock=lambda:SimpleNamespace(now=lambda:SimpleNamespace(nanoseconds=1010000000))))
    msg=SimpleNamespace(header=SimpleNamespace(stamp=SimpleNamespace(sec=1,nanosec=0),frame_id='odom'))
    observe_bounded_trial(bridge,msg,{'x':0.,'y':0.},now=10.)
    assert g.status()['pose']['stamp_ns']==1000000000
    assert g.status()['pose']['source_age_s']==pytest.approx(.01)


def test_lost_send_ack_latches_stop_before_next_cycle(tmp_path):
    g=guard(tmp_path);sample(g);sent=[]
    def lost(out):
        sent.append(out)
        if out.linear:raise RuntimeError('unknown delivery')
    cmd=SimpleNamespace(select_output=lambda:Twist(.04,0),announce_pending=lambda:None)
    try:cmd_vel_cycle(cmd,SimpleNamespace(on_activity=lambda _:None),lost,trial_guard=g,now=10.)
    except RuntimeError:pass
    assert g.status()['halted'] is True
    assert cycle(g,Twist(.04,0))==Twist()


def test_existing_camera_controller_core_mux_guard_and_loss_stop_compose(tmp_path):
    from core_events.events.bus import EventBus
    from core_features.line_follow.manager import LineFollowManager,LineFollowConfig,LineFollowMode,LineObservation
    from core_features.command.manager import CommandManager
    from core_features.command.arbitration import Mode,ModeMachine,SourceRegistry
    from core_features.safety.manager import SafetyManager,SpeedLimits,BatteryPolicy
    clock=[10.]
    lane=LineFollowManager(EventBus('synthetic'),config=LineFollowConfig(
        cruise_speed=.04,max_linear=.04,max_angular=.4),clock=lambda:clock[0])
    lane.set_mode(LineFollowMode.CAMERA_LINE)
    lane.observe(LineObservation(source=LineFollowMode.CAMERA_LINE,stamp=10.,visible=True,
                                error=.1,confidence=1.),received_at=10.)
    modes=ModeMachine();modes.transition(Mode.NAVIGATION)
    command=CommandManager(SourceRegistry(),modes,SafetyManager(SpeedLimits(),BatteryPolicy()))
    g=guard(tmp_path);sample(g);sent=[]
    decision=lane.tick();command.set_nav_twist(Twist(decision.linear,decision.angular),now=10.)
    wrapper=SimpleNamespace(select_output=lambda:command.select_output(now=clock[0]),
                            announce_pending=command.announce_pending)
    power=SimpleNamespace(on_activity=lambda _:None)
    cmd_vel_cycle(wrapper,power,sent.append,trial_guard=g,now=10.)
    assert sent[-1].linear>0
    clock[0]=10.31
    decision=lane.tick();command.set_nav_twist(Twist(decision.linear,decision.angular),now=10.31)
    cmd_vel_cycle(wrapper,power,sent.append,trial_guard=g,now=10.31)
    assert sent[-1]==Twist()
    assert g.status()['halted'] is True


def test_committed_second_connection_stop_after_permits_prevents_submission(tmp_path,monkeypatch):
    import json
    import sqlite3
    g=guard(tmp_path);sample(g);permits=g.permits
    def stop_after_check(*args,**kwargs):
        allowed=permits(*args,**kwargs)
        with sqlite3.connect(tmp_path/'one-trial.sqlite') as other:
            other.execute('BEGIN IMMEDIATE')
            state=json.loads(other.execute('SELECT body FROM trial WHERE id=1').fetchone()[0])
            state.update(halted=True,reason='independent_owner_stop')
            other.execute('UPDATE trial SET body=? WHERE id=1',(json.dumps(state),))
        return allowed
    monkeypatch.setattr(g,'permits',stop_after_check)
    assert cycle(g,Twist(.04,0))==Twist()
    assert g.status()['halted'] is True
    assert cycle(g,Twist(.04,0))==Twist()


def test_actual_writer_holds_ledger_fence_against_reopen(tmp_path):
    import sqlite3
    g=guard(tmp_path);sample(g);sent=[]
    def writer(out):
        if out.linear:
            with pytest.raises(sqlite3.OperationalError,match='locked'):
                guard(tmp_path)
        sent.append(out)
    cmd=SimpleNamespace(select_output=lambda:Twist(.04,0),announce_pending=lambda:None)
    cmd_vel_cycle(cmd,SimpleNamespace(on_activity=lambda _:None),writer,trial_guard=g,now=10.)
    assert sent==[Twist(.04,0)]
    restarted=guard(tmp_path)
    assert restarted.status()['halted'] is True
    assert cycle(g,Twist(.04,0))==Twist()


@pytest.mark.parametrize('same_owner',[False,True])
def test_stop_waits_for_actual_writer_then_denies_next_positive(tmp_path,same_owner):
    import json
    import sqlite3
    import threading
    g=guard(tmp_path);sample(g);attempted=threading.Event();committed=threading.Event()
    errors=[];sent=[]
    def stop():
        try:
            if same_owner:
                attempted.set();g.stop('threaded_owner_stop')
            else:
                with sqlite3.connect(tmp_path/'one-trial.sqlite',timeout=1.) as other:
                    attempted.set();other.execute('BEGIN IMMEDIATE')
                    state=json.loads(other.execute('SELECT body FROM trial WHERE id=1').fetchone()[0])
                    state.update(halted=True,reason='threaded_owner_stop')
                    other.execute('UPDATE trial SET body=? WHERE id=1',(json.dumps(state),))
            committed.set()
        except Exception as exc:errors.append(exc)
    worker=threading.Thread(target=stop)
    def writer(out):
        worker.start()
        assert attempted.wait(1.)
        # STOP cannot commit while the actual final writer is in its fence.
        assert not committed.wait(.02)
        sent.append(out)
    cmd=SimpleNamespace(select_output=lambda:Twist(.04,0),announce_pending=lambda:None)
    try:
        cmd_vel_cycle(cmd,SimpleNamespace(on_activity=lambda _:None),writer,trial_guard=g,now=10.)
    finally:
        worker.join(2.)
    assert not worker.is_alive() and not errors
    assert committed.is_set() and sent==[Twist(.04,0)]
    assert g.status()['halted'] is True
    assert cycle(g,Twist(.04,0))==Twist()


def test_replacing_bounds_after_binding_cannot_widen_trial(tmp_path):
    g=guard(tmp_path);sample(g)
    g.bounds=bounds(angular_max_radps=2.)
    assert cycle(g,Twist(.04,1.))==Twist()


def actual_publish_method():
    # Execute only the real ROS-free delegate method, not a stub ROS runtime.
    import ast
    from pathlib import Path
    source=Path(__file__).parents[1]/'core/bridge/ros_bridge.py'
    tree=ast.parse(source.read_text(encoding='utf-8'))
    cls=next(n for n in tree.body if isinstance(n,ast.ClassDef) and n.name=='RosBridge')
    method=next(n for n in cls.body if isinstance(n,ast.FunctionDef) and n.name=='_publish_cmd_vel')
    scope={'cmd_vel_cycle':lambda *args,**kwargs:cmd_vel_cycle(*args,**kwargs,now=10.)}
    exec(compile(ast.Module(body=[method],type_ignores=[]),str(source),'exec'),scope)
    return scope['_publish_cmd_vel']


def test_actual_bridge_requires_declared_trial_binding_before_writer(tmp_path):
    sent=[]
    bridge=SimpleNamespace(_svc=SimpleNamespace(
        command=SimpleNamespace(select_output=lambda:Twist(.04,0),announce_pending=lambda:None),
        power=SimpleNamespace(on_activity=lambda _:None)),_send_twist=sent.append,
        _readiness=None,_node=SimpleNamespace(get_logger=lambda:SimpleNamespace(error=lambda _:None)))
    publish=actual_publish_method()
    with pytest.raises(AttributeError):publish(bridge)
    assert sent==[]
    bridge._bounded_trial_guard=None
    publish(bridge)
    assert sent==[Twist(.04,0)]
    g=guard(tmp_path);sample(g);bridge._bounded_trial_guard=g
    publish(bridge)
    assert sent[-1]==Twist(.04,0) and g.status()['issued']
    g.stop('owner_stop')
    publish(bridge)
    assert sent[-1]==Twist()


def test_odometry_requires_declared_trial_binding_but_none_remains_inactive():
    from core.bridge.odometry import observe_bounded_trial
    with pytest.raises(AttributeError):observe_bounded_trial(SimpleNamespace(),None,None)
    observe_bounded_trial(SimpleNamespace(_bounded_trial_guard=None),None,None)
