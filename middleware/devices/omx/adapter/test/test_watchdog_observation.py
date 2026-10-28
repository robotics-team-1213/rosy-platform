"""Decision-time watchdog evidence must survive cancellation and later feedback."""
from dataclasses import FrozenInstanceError, asdict
import json
from threading import Event, Thread
from types import SimpleNamespace

import pytest

from omx_adapter.command_owner import ArmCommandOwner
from test_omx_command_owner import FakeActionClient, SESSION, make_command, make_config, make_state


def active_owner():
    source, wall = [100.0], [5000.0]
    client = FakeActionClient()
    owner = ArmCommandOwner(make_config(wall_clock_bound_factor=4), client,
                            monotonic=lambda: source[0], wall_monotonic=lambda: wall[0], session_id=SESSION)
    assert owner.watchdog_observation is None
    assert owner.observe_joint_state(make_state())
    assert owner.submit(make_command()).accepted
    return owner, client, source, wall


def test_watchdog_evidence_exists_before_blocked_cancel_and_survives_later_feedback():
    owner, client, source, wall = active_owner()
    entered, release = Event(), Event()
    original_cancel = client.handles[0].cancel
    def cancel():
        entered.set()
        assert release.wait(3)
        original_cancel()
    client.handles[0].cancel = cancel
    source[0] = 100.75
    decisions = []
    thread = Thread(target=lambda: decisions.append(owner.poll()))
    thread.start()
    try:
        assert entered.wait(3)
        record = owner.watchdog_observation
        assert record.reason == 'joint_state_stale'
        assert record.command_id == 'cmd-1'
        assert record.owner_now == 100.75
        assert record.joint_sequence == 10 and record.joint_received_at == 100.0
        assert record.source_age_s == .75 and record.active_started_at == 100.0
        assert record.joint_wall == record.active_wall == 5000.0
        assert record.wall_now is None  # This branch never consulted the wall guard.
        assert record.max_joint_state_age_s == .5 and record.action_timeout_s == 3.0
        assert record.wall_clock_bound_factor == 4.0
        with pytest.raises(FrozenInstanceError):
            record.owner_now = 200.0
    finally:
        release.set()
        thread.join(3)
    assert not thread.is_alive()
    assert decisions[0].reason == 'joint_state_stale'
    assert client.handles[0].cancel_calls == 1 and len(client.commands) == 1
    assert owner.observe_joint_state(make_state(sequence=11, received_at=source[0]))
    assert owner.poll().reason == 'joint_state_stale'
    assert owner.watchdog_observation is record


@pytest.mark.parametrize('reason', ['action_timeout', 'joint_state_stale_wall_clock',
                                  'action_wall_timeout', 'owner_clock_jumped_back'])
def test_watchdog_latch_preserves_each_guard_and_its_existing_clock_reads(reason, monkeypatch):
    owner, client, source, wall = active_owner()
    if reason == 'action_timeout':
        source[0] = 103.0
        owner.observe_joint_state(make_state(sequence=11, received_at=source[0]))
    elif reason == 'joint_state_stale_wall_clock':
        wall[0] = 5002.1
    elif reason == 'action_wall_timeout':
        wall[0] = 5012.0
        owner.observe_joint_state(make_state(sequence=11))
    else:
        source[0] = 99.0
    reads = []
    def wall_clock():
        reads.append(wall[0])
        return wall[0]
    owner._wall = wall_clock
    source_reads = []
    def source_clock():
        source_reads.append(source[0])
        return source[0]
    owner._monotonic = source_clock
    def no_io(*args, **kwargs):
        pytest.fail('watchdog evidence attempted filesystem I/O')
    monkeypatch.setattr('builtins.open', no_io)
    result = owner.poll()
    assert result.reason == reason and result.state == 'hold'
    record = owner.watchdog_observation
    assert record.reason == reason and record.command_id == 'cmd-1'
    wall_guard = reason in {'joint_state_stale_wall_clock', 'action_wall_timeout'}
    assert reads == ([wall[0]] if wall_guard else [])
    assert source_reads == [source[0]]
    assert record.wall_now == (wall[0] if wall_guard else None)
    assert record.owner_now_steady_before <= record.owner_now_steady_after <= record.steady_now
    assert client.handles[0].cancel_calls == 1 and len(client.commands) == 1


def test_watchdog_record_is_bounded_and_a_new_incident_replaces_the_old_one():
    owner, client, source, wall = active_owner()
    source[0] = 100.75
    owner.poll()
    first = owner.watchdog_observation
    owner.observe_joint_state(make_state(sequence=11, received_at=source[0]))
    assert owner.recover(operator_confirmed=True, observed_sequence=11).accepted
    assert owner.submit(make_command(command_id='x' * 20000, sequence=11)).accepted
    source[0] += .75
    owner.poll()
    second = owner.watchdog_observation
    assert second is not first and len(second.command_id) == 256
    assert second.command_id_truncated is True
    assert second.joint_sequence == 11
    assert len(json.dumps(asdict(second), allow_nan=False).encode()) < 16384


def test_failed_observation_does_not_change_watchdog_hold_or_cancel(monkeypatch):
    owner, client, source, wall = active_owner()
    def broken_observation(*args, **kwargs):
        raise ValueError('diagnostic construction failed')
    monkeypatch.setattr('omx_adapter.command_owner.watchdog_observation', broken_observation)
    source[0] += .75
    result = owner.poll()
    assert result.reason == 'joint_state_stale' and result.state == 'hold'
    assert client.handles[0].cancel_calls == 1 and len(client.commands) == 1
    assert owner.watchdog_observation is None


def test_owner_clock_read_has_exact_steady_brackets_before_watchdog_cancellation(monkeypatch):
    import omx_adapter.command_owner as policy
    owner, client, source, wall = active_owner()
    source[0] += .75
    calls = []
    def steady():
        calls.append('steady')
        return 10000.0 + len(calls)
    def owner_clock():
        calls.append('owner')
        return source[0]
    monkeypatch.setattr(policy, 'time', SimpleNamespace(monotonic=steady))
    owner._monotonic = owner_clock
    result = owner.poll()
    record = owner.watchdog_observation
    assert calls == ['steady', 'owner', 'steady', 'steady']
    assert record.owner_now_steady_before == 10001.0
    assert record.owner_now_steady_after == 10003.0
    assert record.steady_now == 10004.0 and record.owner_now == 100.75
    assert result.reason == 'joint_state_stale' and client.handles[0].cancel_calls == 1


@pytest.mark.parametrize('failed_sample', [1, 2])
def test_bracket_sample_failure_cannot_suppress_provider_or_watchdog_hold(monkeypatch, failed_sample):
    import omx_adapter.command_owner as policy
    owner, client, source, wall = active_owner()
    source[0] += .75
    calls, providers = [], []
    def steady():
        calls.append(len(calls) + 1)
        if len(calls) == failed_sample:
            raise ValueError('diagnostic steady clock unavailable')
        return 10000.0 + len(calls)
    def owner_clock():
        providers.append(source[0])
        return source[0]
    monkeypatch.setattr(policy, 'time', SimpleNamespace(monotonic=steady))
    owner._monotonic = owner_clock
    result = owner.poll()
    record = owner.watchdog_observation
    assert result.reason == 'joint_state_stale' and providers == [100.75]
    assert record.owner_now_steady_before == (None if failed_sample == 1 else 10001.0)
    assert record.owner_now_steady_after == (None if failed_sample == 2 else 10002.0)
    assert client.handles[0].cancel_calls == 1


def test_bracketing_preserves_original_owner_provider_exception(monkeypatch):
    import omx_adapter.command_owner as policy
    owner, client, source, wall = active_owner()
    calls = []
    marker = RuntimeError('owner clock failed')
    def steady():
        calls.append('steady')
        return 10000.0
    def owner_clock():
        calls.append('owner')
        raise marker
    monkeypatch.setattr(policy, 'time', SimpleNamespace(monotonic=steady))
    owner._monotonic = owner_clock
    with pytest.raises(RuntimeError) as caught:
        owner.poll()
    assert caught.value is marker
    assert calls == ['steady', 'owner']
    assert owner.watchdog_observation is None and owner.state == 'active'
    assert client.handles[0].cancel_calls == 0
