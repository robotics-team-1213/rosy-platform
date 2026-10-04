"""D-442 U2 binding: one original immutable grant, one send, one cycle."""

from dataclasses import replace
from types import SimpleNamespace

import pytest

from core.bridge import cmd_vel as cycle
from rosy.contracts.motion import BaseTwist, GuardedMotion


def issued(clock=None):
    sent = []
    port = cycle.PinkyTwistPort(sent.append, **({"clock": clock} if clock else {}))
    original = GuardedMotion(BaseTwist(0.2, -0.1), cycle.GUARD_REVISION, cycle._BINDING_TOKEN)
    port._bind(original)
    return port, original, sent


def test_only_original_is_accepted_once_and_unwraps_existing_twist_shape():
    port, original, sent = issued()
    assert port.submit(original).accepted
    assert (sent[0].linear, sent[0].angular) == (0.2, -0.1)
    assert not port.submit(original).accepted and len(sent) == 1


@pytest.mark.parametrize("kind", ["copy", "replace", "forged", "lookalike", "subclass"])
def test_copied_forged_or_alternate_type_is_rejected_without_consuming_original(kind):
    import copy
    port, original, sent = issued()

    class Other(GuardedMotion):
        pass
    fake = {"copy": lambda: copy.copy(original), "replace": lambda: replace(original),
            "forged": lambda: GuardedMotion(original.payload, original.guard_revision, object()),
            "lookalike": lambda: SimpleNamespace(payload=original.payload, guard_revision=original.guard_revision,
                                                 _token=original._token),
            "subclass": lambda: Other(original.payload, original.guard_revision, original._token)}[kind]()
    assert not port.submit(fake).accepted and not sent
    assert port.submit(original).accepted and len(sent) == 1


def test_original_from_another_port_is_rejected():
    port, original, sent = issued()
    other = cycle.PinkyTwistPort(sent.append)
    assert not other.submit(original).accepted and not sent
    assert port.submit(original).accepted


def test_cycle_close_and_expiry_invalidate_grants():
    now = [10.0]
    port, original, sent = issued(lambda: now[0])
    now[0] += cycle.GUARD_LIFETIME_S
    assert not port.submit(original).accepted and not sent
    port, original, sent = issued()
    port.close()
    assert not port.submit(original).accepted and not sent


def test_send_exception_consumes_original_and_never_replays():
    calls = []

    def lost_ack(out):
        calls.append(out)
        raise RuntimeError("lost ACK")
    port, original, _ = issued()
    port._send = lost_ack
    with pytest.raises(RuntimeError, match="lost ACK"):
        port.submit(original)
    assert not port.submit(original).accepted and len(calls) == 1


def test_cycle_guard_construction_failure_sends_zero_and_next_cycle_continues(monkeypatch):
    sent, warnings, events = [], [], []
    command = SimpleNamespace(select_output=lambda: SimpleNamespace(linear=0.2, angular=-0.1),
                              announce_pending=lambda: events.append("announce"))
    power = SimpleNamespace(on_activity=lambda source: events.append(source))
    real = cycle.GuardedMotion

    def fail(*args):
        raise ValueError("guard failed")
    monkeypatch.setattr(cycle, "GuardedMotion", fail)
    cycle.cmd_vel_cycle(command, power, sent.append, warn=warnings.append)
    assert [(out.linear, out.angular) for out in sent] == [(0.0, 0.0)]
    assert warnings and not events
    monkeypatch.setattr(cycle, "GuardedMotion", real)
    cycle.cmd_vel_cycle(command, power, sent.append)
    assert [(out.linear, out.angular) for out in sent] == [(0.0, 0.0), (0.2, -0.1)]


def test_original_cycle_grant_expires_after_return_and_payload_is_snapshot(monkeypatch):
    observed = []
    real = cycle.PinkyTwistPort._bind

    def capture(port, guarded):
        observed.append((port, guarded))
        real(port, guarded)
    monkeypatch.setattr(cycle.PinkyTwistPort, "_bind", capture)
    candidate = SimpleNamespace(linear=0.2, angular=-0.1)
    command = SimpleNamespace(select_output=lambda: candidate, announce_pending=lambda: None)
    power = SimpleNamespace(on_activity=lambda source: None)
    sent = []
    cycle.cmd_vel_cycle(command, power, sent.append)
    candidate.linear = 2.0
    port, original = observed[0]
    assert original.payload.linear_mps == 0.2
    assert not port.submit(original).accepted and len(sent) == 1


def test_two_concurrent_submissions_emit_exactly_once():
    from concurrent.futures import ThreadPoolExecutor
    from threading import Barrier
    port, original, sent = issued()
    barrier = Barrier(2)

    def submit():
        barrier.wait(timeout=3)
        return port.submit(original).accepted

    with ThreadPoolExecutor(max_workers=2) as pool:
        futures = [pool.submit(submit) for _ in range(2)]
        assert sorted(f.result(timeout=3) for f in futures) == [False, True]
    assert len(sent) == 1


def test_cycle_expired_grant_emits_zero_and_closes_without_announcing(monkeypatch):
    real = cycle.PinkyTwistPort._bind

    def expire(port, guarded):
        port._clock = lambda: 10.0
        real(port, guarded)
        port._clock = lambda: 10.0 + cycle.GUARD_LIFETIME_S

    monkeypatch.setattr(cycle.PinkyTwistPort, "_bind", expire)
    sent, events, warnings = [], [], []
    command = SimpleNamespace(select_output=lambda: SimpleNamespace(linear=0.2, angular=0.1),
                              announce_pending=lambda: events.append("announce"))
    power = SimpleNamespace(on_activity=lambda source: events.append(source))
    cycle.cmd_vel_cycle(command, power, sent.append, warn=warnings.append)
    assert [(out.linear, out.angular) for out in sent] == [(0.0, 0.0)]
    assert warnings and not events


def test_readonly_interface_reports_unknown_stop_and_never_releases_or_cancels_by_guess():
    port, original, sent = issued()
    status = port.estop_status()
    assert status.software_latched is None and status.physical_latched is None
    assert port.capabilities().supports_stream is True
    assert port.capabilities().supports_goals is False
    assert port.state().state == "ready"
    assert not port.cancel("unknown-intent").accepted and not sent
    assert port.submit(original).accepted
    assert not hasattr(port, "release") and not hasattr(port, "rearm")


def test_binding_constructor_failure_emits_zero_warns_and_next_cycle_continues(monkeypatch):
    sent, warnings = [], []
    command = SimpleNamespace(select_output=lambda: SimpleNamespace(linear=0.2, angular=-0.1),
                              announce_pending=lambda: None)
    power = SimpleNamespace(on_activity=lambda source: None)
    real = cycle.PinkyTwistPort

    def broken(send):
        raise ValueError("binding constructor failed")

    monkeypatch.setattr(cycle, "PinkyTwistPort", broken)
    cycle.cmd_vel_cycle(command, power, sent.append, warn=warnings.append)
    assert [(out.linear, out.angular) for out in sent] == [(0.0, 0.0)] and warnings
    monkeypatch.setattr(cycle, "PinkyTwistPort", real)
    cycle.cmd_vel_cycle(command, power, sent.append)
    assert [(out.linear, out.angular) for out in sent] == [(0.0, 0.0), (0.2, -0.1)]
