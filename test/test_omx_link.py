from test_omx_guarded_native import Bus, Monitor, SimpleNamespace, action, guard, pytest
from omx_guarded_native_late_cases import _loop_module, _preroll_module

import functools
import json
import os
from pathlib import Path
import sys

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'deploy/robot/omx'))
import guarded_native_link as gl  # noqa: E402


def _patch_clock(guard, monkeypatch, clock):
    """Pin NativeJointMotion's clock across guard modules without real-time sleep flakes."""
    import guarded_native
    for mod in (guard, guarded_native, sys.modules.get('omx_guard_test')):
        if mod is not None and hasattr(mod, 'NativeJointMotion'):
            monkeypatch.setattr(mod, 'NativeJointMotion', functools.partial(mod.NativeJointMotion, clock=lambda: clock[0]))


def _control(directory, seq, cmd):
    directory.mkdir(parents=True, exist_ok=True)
    tmp = directory / 'control.json.tmp'
    tmp.write_text(json.dumps({'seq': seq, 'cmd': cmd}), encoding='utf-8')
    os.replace(tmp, directory / 'control.json')


def test_the_channel_hands_each_request_over_once_in_seq_order_and_publishes_the_recorders_state(tmp_path):
    channel = gl.LinkChannel(tmp_path / 'link')
    assert channel.poll() is None  # no file yet
    _control(tmp_path / 'link', 1, 'record')
    assert channel.poll() == 'record' and channel.poll() is None  # once
    _control(tmp_path / 'link', 1, 'next')  # a repeated or older seq is not a new request
    assert channel.poll() is None
    _control(tmp_path / 'link', 2, 'nonsense')
    assert channel.poll() is None
    _control(tmp_path / 'link', 3, 'rerecord')
    assert channel.poll() == 'rerecord' and channel.seq_seen == 3
    (tmp_path / 'link' / 'control.json').write_text('{half', encoding='utf-8')  # a half-written file is read again later, not an error
    assert channel.poll() is None
    _control(tmp_path / 'link', 4, 'finish')
    assert channel.poll() == 'finish'
    channel.episode = 2
    channel.publish('waiting')
    state = json.loads((tmp_path / 'link' / 'state.json').read_text(encoding='utf-8'))
    assert state['state'] == 'waiting' and state['episode'] == 2 and state['seq'] == 4 and state['pid'] == os.getpid()


def test_waiting_ends_on_record_or_finish_and_an_episode_sees_next_and_rerecord_as_lerobots_own_events(tmp_path):
    directory = tmp_path / 'link'
    real = {'exit_early': False, 'stop_recording': False, 'rerecord_episode': False}
    waiting = gl.LinkEvents(real, gl.LinkChannel(directory), True)
    assert waiting['exit_early'] is False
    _control(directory, 1, 'record')
    assert waiting['exit_early'] is True and waiting.started and not waiting.finished and real['exit_early'] is False
    finishing = gl.LinkEvents(dict(real), gl.LinkChannel(directory), True)
    _control(directory, 2, 'finish')
    assert finishing['exit_early'] is True and finishing.finished
    episode = gl.LinkEvents(real, gl.LinkChannel(directory), False)
    _control(directory, 3, 'next')
    assert episode['exit_early'] is True and real['exit_early'] is True
    real['exit_early'] = False
    _control(directory, 4, 'rerecord')
    assert episode['rerecord_episode'] is True and real['exit_early'] is True
    episode['stop_recording'] = True  # writes go to the real dict (the pause watch's stop request included)
    assert real['stop_recording'] is True
    only_waiting = gl.LinkEvents({'exit_early': False}, gl.LinkChannel(tmp_path / 'other'), True)
    _control(tmp_path / 'other', 1, 'next')
    assert only_waiting['exit_early'] is False  # a "next" while waiting does nothing


def _linked_run(guard, monkeypatch, tmp_path, script, in_episode=None):
    """lerobot's record flow around the guard's loop wrapper, in linked mode: the fake wait loop plays the bench by writing the next scripted request."""
    import json as json_module
    import os as os_module
    monkeypatch.setenv('ROSY_LINK_DIR', str(tmp_path / 'link'))
    monitor = Monitor()
    monkeypatch.setitem(sys.modules, 'motor_health', SimpleNamespace(MotorHealth=lambda: monitor))
    clock = [100.0]
    _patch_clock(guard, monkeypatch, clock)

    class Follower:
        def __init__(self):
            self.bus, self.cameras = Bus(), {}

    class Leader:
        def __init__(self):
            self.bus = Bus(leader=True)
    follower, leader, calls, states, seq = Follower(), Leader(), [], [], [0]
    dataset = object()

    def write(cmd):
        seq[0] += 1
        (tmp_path / 'link').mkdir(parents=True, exist_ok=True)
        tmp = tmp_path / 'link' / 'control.json.tmp'
        tmp.write_text(json_module.dumps({'seq': seq[0], 'cmd': cmd}), encoding='utf-8')
        os_module.replace(tmp, tmp_path / 'link' / 'control.json')

    def state():
        return json_module.loads((tmp_path / 'link' / 'state.json').read_text(encoding='utf-8'))['state']

    def fake_loop(*, robot, events, dataset=None, policy=None, control_time_s=None, **kw):
        calls.append((dataset, control_time_s))
        if dataset is not None:
            states.append(state())
            if in_episode:
                in_episode(write, events)
            clock[0] += 0.05
            robot.send_action(action(leader.bus))
            return
        if control_time_s == 180:
            appended = False
            for _ in range(100):
                if events['exit_early']:
                    events['exit_early'] = False
                    break
                clock[0] += 0.05
                robot.send_action(action(leader.bus))
                if not appended and state() == 'waiting':
                    appended = True
                    states.append('waiting')
                    if not script:
                        return  # nobody asks: the idle limit ended the wait
                    write(script.pop(0))
            return
        for _ in range(100):  # bounded (pre-roll)
            if events['exit_early']:
                events['exit_early'] = False
                break
            clock[0] += 0.05
            robot.send_action(action(leader.bus))
    module = SimpleNamespace(make_robot_from_config=lambda config: follower, make_teleoperator_from_config=lambda config: leader,
                             ACTION='action', build_dataset_frame=lambda features, values, prefix: values, record_loop=fake_loop)
    return module, Follower, Leader, calls, states, state, dataset


def test_linked_mode_waits_ready_between_episodes_skips_the_reset_period_and_finishes_cleanly(guard, monkeypatch, tmp_path):
    module, Follower, Leader, calls, states, state, dataset = _linked_run(guard, monkeypatch, tmp_path, ['record', 'finish'])
    events = {'exit_early': False, 'stop_recording': False, 'rerecord_episode': False}
    seen = {}

    def main():
        robot = module.make_robot_from_config(SimpleNamespace(use_degrees=False))
        teleop = module.make_teleoperator_from_config(None)
        robot.connect(), teleop.connect()
        common = dict(robot=robot, events=events, policy=None, teleop=teleop)
        module.record_loop(dataset=dataset, control_time_s=30, **common)  # pre-roll, ready wait (record), then episode 0
        seen['after_episode'] = state()
        module.record_loop(dataset=None, control_time_s=10, **common)  # lerobot's reset period: not run
        module.record_loop(dataset=dataset, control_time_s=30, **common)  # ready wait (finish): no episode
        seen['flags'] = (events['stop_recording'], events['rerecord_episode'])
    module.main = main
    guard.run_native(module, Follower, Leader)
    assert calls == [(None, 120), (None, 180), (dataset, 30), (None, 180)]  # the second episode call recorded nothing, the reset call never ran
    assert states == ['waiting', 'recording', 'waiting'] and seen['after_episode'] == 'saving'
    assert seen['flags'] == (True, True)  # stop + re-record: lerobot clears the empty buffer, leaves its loop and finalizes the dataset (exit 0)


def test_linked_mode_idle_limit_ends_the_session_the_same_clean_way(guard, monkeypatch, tmp_path):
    module, Follower, Leader, calls, states, state, dataset = _linked_run(guard, monkeypatch, tmp_path, [])  # nobody ever asks to record
    events = {'exit_early': False, 'stop_recording': False, 'rerecord_episode': False}

    def main():
        robot = module.make_robot_from_config(SimpleNamespace(use_degrees=False))
        teleop = module.make_teleoperator_from_config(None)
        robot.connect(), teleop.connect()
        module.record_loop(robot=robot, events=events, policy=None, teleop=teleop, dataset=dataset, control_time_s=30)
    module.main = main
    guard.run_native(module, Follower, Leader)
    assert (events['stop_recording'], events['rerecord_episode']) == (True, True) and calls == [(None, 120), (None, 180)]


def test_linked_mode_an_episode_takes_next_and_rerecord_requests_from_the_same_channel(guard, monkeypatch, tmp_path):
    seen = []

    def in_episode(write, events):
        write('rerecord')
        seen.append((events['rerecord_episode'], events['exit_early']))  # read through the channel: lerobot's own events are set
    module, Follower, Leader, calls, states, state, dataset = _linked_run(guard, monkeypatch, tmp_path, ['record'], in_episode)
    events = {'exit_early': False, 'stop_recording': False, 'rerecord_episode': False}

    def main():
        robot = module.make_robot_from_config(SimpleNamespace(use_degrees=False))
        teleop = module.make_teleoperator_from_config(None)
        robot.connect(), teleop.connect()
        module.record_loop(robot=robot, events=events, policy=None, teleop=teleop, dataset=dataset, control_time_s=30)
    module.main = main
    guard.run_native(module, Follower, Leader)
    assert seen == [(True, True)] and events['rerecord_episode'] is True


def test_without_the_link_directory_the_recorder_loops_are_untouched(guard, monkeypatch):
    monkeypatch.delenv('ROSY_LINK_DIR', raising=False)
    module, Follower, Leader, calls = _preroll_module(monkeypatch, lambda events: None)
    with pytest.raises(ValueError, match='leader alignment did not finish'):  # exactly the unlinked behaviour of the existing pre-roll test
        guard.run_native(module, Follower, Leader)
    assert calls == [(None, 120)]


def test_require_frame_defers_next_until_a_frame_is_recorded(tmp_path):
    directory = tmp_path / 'link'
    channel = gl.LinkChannel(directory)
    real = {'exit_early': False, 'stop_recording': False, 'rerecord_episode': False}
    episode = gl.LinkEvents(real, channel, False, require_frame=True)
    _control(directory, 1, 'next')
    assert episode['exit_early'] is False and real['exit_early'] is False and episode.pending_next is True
    channel.frames = 1
    assert episode['exit_early'] is True and real['exit_early'] is True and episode.pending_next is False


def test_rerecord_keeps_link_episode_unchanged_and_publishes_saving(guard, monkeypatch, tmp_path):
    def in_episode(write, events):
        write('rerecord')
        assert events['rerecord_episode'] is True
    module, Follower, Leader, calls, states, state, dataset = _linked_run(guard, monkeypatch, tmp_path, ['record'], in_episode)
    events = {'exit_early': False, 'stop_recording': False, 'rerecord_episode': False}
    seen = {}

    def main():
        robot = module.make_robot_from_config(SimpleNamespace(use_degrees=False))
        teleop = module.make_teleoperator_from_config(None)
        robot.connect(), teleop.connect()
        module.record_loop(robot=robot, events=events, policy=None, teleop=teleop, dataset=dataset, control_time_s=30)
        seen['state'] = json.loads((tmp_path / 'link' / 'state.json').read_text(encoding='utf-8'))
    module.main = main
    guard.run_native(module, Follower, Leader)
    assert seen['state']['state'] == 'saving' and seen['state']['episode'] == 0


def test_wait_linked_holds_aligning_after_save_pause_until_realigned(guard, monkeypatch, tmp_path):
    monkeypatch.setenv('ROSY_LINK_DIR', str(tmp_path / 'link'))
    monitor = Monitor()
    monkeypatch.setitem(sys.modules, 'motor_health', SimpleNamespace(MotorHealth=lambda: monitor))
    now = [100.0]
    monkeypatch.setattr('time.time', lambda: now[0])
    clock = [100.0]
    _patch_clock(guard, monkeypatch, clock)

    class Follower:
        def __init__(self):
            self.bus, self.cameras = Bus(), {}

    class Leader:
        def __init__(self):
            self.bus = Bus(leader=True)

    follower, leader, dataset = Follower(), Leader(), object()
    seen_before_realign, wait_ticks, seq = [], [], [0]

    def write(cmd):
        seq[0] += 1
        d = tmp_path / 'link'
        d.mkdir(parents=True, exist_ok=True)
        tmp = d / 'control.json.tmp'
        tmp.write_text(json.dumps({'seq': seq[0], 'cmd': cmd}), encoding='utf-8')
        os.replace(tmp, d / 'control.json')

    def fake_loop(*, robot, events, dataset=None, policy=None, control_time_s=None, **kw):
        if dataset is None and control_time_s == 120:
            while not events['exit_early']:
                clock[0] += 0.05
                robot.send_action(action(leader.bus))
                follower.bus.raw.update(follower.bus.goals)
            events['exit_early'] = False
            return
        if control_time_s == 180:
            write('record')  # premature record while >0.5s pause is still re-aligning
            for tick in range(30):
                clock[0] += 0.05
                if events['exit_early']:
                    wait_ticks.append(tick)
                    events['exit_early'] = False
                    return
                if tick == 0:
                    seen_before_realign.append(json.loads((tmp_path / 'link' / 'state.json').read_text())['state'])
                    assert events.started is False
                robot.send_action(action(leader.bus))
                follower.bus.raw.update(follower.bus.goals)
            return
        robot.send_action(action(leader.bus))

    module = SimpleNamespace(make_robot_from_config=lambda c: follower, make_teleoperator_from_config=lambda c: leader,
                             ACTION='action', build_dataset_frame=lambda f, v, prefix: v, record_loop=fake_loop)

    def main():
        r, t = module.make_robot_from_config(SimpleNamespace(use_degrees=False)), module.make_teleoperator_from_config(None)
        r.connect(), t.connect()
        common = dict(robot=r, events={'exit_early': False, 'stop_recording': False, 'rerecord_episode': False}, policy=None, teleop=t)
        module.record_loop(dataset=dataset, control_time_s=30, **common)
        now[0] += 1.2
        clock[0] += 1.2  # >0.5s save pause forces re-alignment before wait_linked can go waiting
        module.record_loop(dataset=dataset, control_time_s=30, **common)

    module.main = main
    guard.run_native(module, Follower, Leader)
    assert seen_before_realign == ['aligning', 'aligning']
    assert len(wait_ticks) == 2 and wait_ticks[1] >= 10


def test_late_next_at_poll_final_does_not_end_next_linked_wait(guard, monkeypatch, tmp_path):
    ep_done, seen = [0], {}

    def in_episode(write, events):
        if ep_done[0] == 0:
            ep_done[0] += 1
            write('next')  # late next right before episode 0 returns: only poll_final consumes it

    events = {'exit_early': False, 'stop_recording': False, 'rerecord_episode': False}
    module, Follower, Leader, calls, states, state, dataset = _linked_run(guard, monkeypatch, tmp_path, ['record', 'record', 'finish'], in_episode)

    def main():
        robot = module.make_robot_from_config(SimpleNamespace(use_degrees=False))
        teleop = module.make_teleoperator_from_config(None)
        robot.connect(), teleop.connect()
        common = dict(robot=robot, events=events, policy=None, teleop=teleop)
        module.record_loop(dataset=dataset, control_time_s=30, **common)
        seen['ep0_exit_early'] = events['exit_early']
        seen['ep0_state'] = json.loads((tmp_path / 'link' / 'state.json').read_text(encoding='utf-8'))
        module.record_loop(dataset=dataset, control_time_s=30, **common)
        module.record_loop(dataset=dataset, control_time_s=30, **common)
        seen['flags'] = (events['stop_recording'], events['rerecord_episode'])

    module.main = main
    guard.run_native(module, Follower, Leader)
    assert seen['ep0_exit_early'] is False
    assert seen['ep0_state']['episode'] == 1 and seen['ep0_state']['last_command']['cmd'] == 'next' and seen['ep0_state']['last_command']['applied'] is True
    assert calls == [(None, 120), (None, 180), (dataset, 30), (None, 180), (dataset, 30), (None, 180)]
    assert states == ['waiting', 'recording', 'waiting', 'recording', 'waiting']
    assert seen['flags'] == (True, True)


def test_linked_episode_start_keeps_boundary_false_so_first_tick_gap_does_not_realign(guard, monkeypatch, tmp_path):
    monkeypatch.setenv('ROSY_LINK_DIR', str(tmp_path / 'link'))
    monitor = Monitor()
    monkeypatch.setitem(sys.modules, 'motor_health', SimpleNamespace(MotorHealth=lambda: monitor))
    now, clock, seq = [100.0], [100.0], [0]
    monkeypatch.setattr('time.time', lambda: now[0])
    _patch_clock(guard, monkeypatch, clock)

    class Follower:
        def __init__(self):
            self.bus, self.cameras = Bus(), {}

    class Leader:
        def __init__(self):
            self.bus = Bus(leader=True)

    follower, leader, dataset = Follower(), Leader(), object()

    def write(cmd):
        seq[0] += 1
        d = tmp_path / 'link'
        d.mkdir(parents=True, exist_ok=True)
        tmp = d / 'control.json.tmp'
        tmp.write_text(json.dumps({'seq': seq[0], 'cmd': cmd}), encoding='utf-8')
        os.replace(tmp, d / 'control.json')

    def fake_loop(*, robot, events, dataset=None, policy=None, control_time_s=None, **kw):
        if dataset is None and control_time_s == 120:
            while not events['exit_early']:
                clock[0] += 0.05
                robot.send_action(action(leader.bus))
                follower.bus.raw.update(follower.bus.goals)
            events['exit_early'] = False
            return
        if control_time_s == 180:
            write('record')
            for _ in range(10):
                clock[0] += 0.05
                if events['exit_early']:
                    events['exit_early'] = False
                    return
                robot.send_action(action(leader.bus))
                follower.bus.raw.update(follower.bus.goals)
            return
        clock[0] += 0.6  # slow first camera read > MAX_GAP_S (0.5 s)
        robot.send_action(action(leader.bus))

    module = SimpleNamespace(make_robot_from_config=lambda c: follower, make_teleoperator_from_config=lambda c: leader,
                             ACTION='action', build_dataset_frame=lambda f, v, prefix: v, record_loop=fake_loop)

    def main():
        r, t = module.make_robot_from_config(SimpleNamespace(use_degrees=False)), module.make_teleoperator_from_config(None)
        r.connect(), t.connect()
        module.record_loop(robot=r, events={'exit_early': False, 'stop_recording': False, 'rerecord_episode': False},
                           policy=None, teleop=t, dataset=dataset, control_time_s=30)

    module.main = main
    with pytest.raises(ValueError, match='stale control loop'):
        guard.run_native(module, Follower, Leader)


def test_rerecord_end_of_episode_race_and_late_waiting_rejection(guard, monkeypatch, tmp_path):
    directory = tmp_path / 'link'
    channel = gl.LinkChannel(directory)
    real = {'exit_early': False, 'stop_recording': False, 'rerecord_episode': False}
    episode = gl.LinkEvents(real, channel, False)
    _control(directory, 1, 'rerecord')
    episode.poll_final()
    assert real['rerecord_episode'] is True and channel.last_command['applied'] is True

    # Late rerecord arriving during waiting records applied=False instead of silently dropping
    waiting = gl.LinkEvents(dict(exit_early=False, stop_recording=False, rerecord_episode=False), channel, True)
    _control(directory, 2, 'rerecord')
    assert waiting['exit_early'] is False
    st = json.loads((directory / 'state.json').read_text(encoding='utf-8'))
    assert st['last_command']['seq'] == 2 and st['last_command']['applied'] is False

    # Episode started timestamp lifecycle
    channel.publish('recording')
    rec_st = json.loads((directory / 'state.json').read_text(encoding='utf-8'))
    assert isinstance(rec_st['episode_started'], float)
    channel.publish('saving')
    sav_st = json.loads((directory / 'state.json').read_text(encoding='utf-8'))
    assert sav_st['episode_started'] is None
