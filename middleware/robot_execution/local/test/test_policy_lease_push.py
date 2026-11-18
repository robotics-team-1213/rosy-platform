"""D-1024 3: pushed Fleet lease -> owner-monotonic lease -> OwnerPolicySession.renew; every failure is a HOLD."""
import itertools

import pytest

from test_omx_policy_session import (setup_session, candidate, OwnerPolicySession, JointStateSnapshot)
from rosy.execution.local.policy_lease import LeaseScope
from rosy.execution.local.policy_lease_push import PushLeaseReceiver

DIGEST = 'e' * 64


def build(tmp_path, first_window=600.0, **session_options):
    base, client, clock, _, _ = setup_session(tmp_path)
    lease = base.lease
    scope = LeaseScope(lease.identity, 'episode', lease.policy_revision, 'owner-session', 'w', 'rig', 'cal-7', 'scope')
    receiver = PushLeaseReceiver(scope, monotonic=lambda: clock[0], policy_digest=DIGEST)
    grant = dict(lease_id='lease', episode_id='episode', workcell_id=lease.identity.workcell_id, policy_digest=DIGEST,
                 rig_revision='rig', calibration_revision='cal-7', ttl_s=1.0, seq=1,
                 window_remaining_s=first_window)
    receiver.deliver(grant)
    grant = dict(grant, seq=2, window_remaining_s=600.0)  # the first push precedes the session, as in Fleet's tick order
    session = OwnerPolicySession(base.policy, base.owner, base.fence, receiver.acquire(),
                                 authority_current=receiver.authority, owner_identity=base._identity,
                                 monotonic=lambda: clock[0], enabled=True,
                                 max_lease_duration_ns=receiver.max_duration_ns, **session_options)
    receiver.attach(session)
    seq = itertools.count(100)

    def observe():  # the owner feeds joint state continuously; max observation age is 50 ms
        session.observe(JointStateSnapshot({'joint_1': 0.1, 'joint_2': 0.0}, next(seq), clock[0], 'cal-7'))
    observe()
    return receiver, session, client, clock, grant, observe


def test_pushed_lease_renews_the_session_and_converts_ttl_to_owner_ns(tmp_path):
    receiver, session, _, clock, grant, observe = build(tmp_path)
    first = session.lease
    assert first.expires_at_ns - first.issued_at_ns == 1_000_000_000 and first.issued_at_ns == 10_000_000_000
    clock[0] = 10.5
    observe()
    assert receiver.deliver(grant) is True
    assert session.lease.issued_at_ns == 10_500_000_000 and session.lease.expires_at_ns == 11_500_000_000
    assert not session.hold_reason


def test_unrenewed_lease_runs_out_into_hold(tmp_path):
    receiver, session, _, clock, grant, observe = build(tmp_path)
    clock[0] = 11.01  # a full period without a push: the owner clock alone ends authority
    observe()
    with pytest.raises(PermissionError):
        session.poll()
    assert session.hold_reason == 'policy_lease_expired_or_invalid'


@pytest.mark.parametrize('change', [
    dict(ttl_s=0), dict(ttl_s=-1.0), dict(ttl_s=float('nan')), dict(ttl_s=True), dict(ttl_s=2.5), dict(ttl_s='1'),
    dict(ttl_s=1.5),  # over this receiver's installed 1 s budget
    dict(seq=1), dict(seq=0), dict(seq=True), dict(seq='3'), dict(window_remaining_s=0),
    dict(window_remaining_s=-1.0), dict(window_remaining_s=float('nan')), dict(window_remaining_s=1801),
    dict(policy_digest='f' * 64), dict(workcell_id='other'), dict(rig_revision='rig2'),
    dict(calibration_revision='cal-8'), dict(lease_id='another'), dict(episode_id='another')])
def test_bad_grants_are_refused_and_hold_the_session(tmp_path, change):
    receiver, session, _, clock, grant, observe = build(tmp_path)
    clock[0] = 10.5
    observe()
    assert receiver.deliver(dict(grant, **change)) is False
    assert session.hold_reason.startswith('requested_hold:lease_delivery_failed')
    with pytest.raises(PermissionError):
        session.submit(candidate(session, observed_at_ns=10_500_000_000, produced_at_ns=10_500_000_000, sequence=101))


def test_extra_or_missing_grant_fields_are_refused(tmp_path):
    receiver, session, _, clock, grant, _ = build(tmp_path)
    assert receiver.deliver(dict(grant, extra=1)) is False
    assert receiver.deliver({k: v for k, v in grant.items() if k != 'ttl_s'}) is False


def test_hold_latches_and_a_later_valid_push_does_not_rearm(tmp_path):
    receiver, session, _, clock, grant, observe = build(tmp_path)
    receiver.hold('window_ended')
    assert session.hold_reason == 'requested_hold:window_ended'
    clock[0] = 10.4
    with pytest.raises(PermissionError):
        observe()  # a held session takes no more observations
    assert receiver.deliver(grant) is False and session.hold_reason == 'requested_hold:window_ended'
    with pytest.raises(PermissionError):
        receiver.acquire(timeout_s=0.01)


def test_hold_cancels_the_active_goal(tmp_path):
    receiver, session, client, clock, grant, observe = build(tmp_path)
    session.submit(candidate(session, sequence=session._snapshot.sequence, observed_at_ns=10_000_000_000,
                             produced_at_ns=10_000_000_000))
    assert session._active_command is not None
    receiver.hold('lease_delivery_failed')
    assert session.cancel_decision is not None


def test_clock_rollback_closes_the_receiver(tmp_path):
    receiver, session, _, clock, grant, observe = build(tmp_path)
    clock[0] = 9.0
    assert receiver.deliver(grant) is False and receiver.authority(session.lease) is False


def test_restart_drops_leases_a_new_receiver_has_none(tmp_path):
    base, _, clock, _, _ = setup_session(tmp_path)
    lease = base.lease
    scope = LeaseScope(lease.identity, 'episode', lease.policy_revision, 'owner-session', 'w', 'rig', 'cal-7', 'scope')
    fresh = PushLeaseReceiver(scope, monotonic=lambda: clock[0], policy_digest=DIGEST)
    assert fresh.authority(lease) is False
    with pytest.raises(PermissionError):
        fresh.acquire(timeout_s=0.01)


def test_receiver_budget_and_digest_are_validated(tmp_path):
    base, _, clock, _, _ = setup_session(tmp_path)
    lease = base.lease
    scope = LeaseScope(lease.identity, 'episode', lease.policy_revision, 'owner-session', 'w', 'rig', 'cal-7', 'scope')
    for kwargs in (dict(policy_digest='x'), dict(policy_digest=DIGEST, max_duration_ns=2_000_000_001),
                   dict(policy_digest=DIGEST, max_duration_ns=0)):
        with pytest.raises(ValueError):
            PushLeaseReceiver(scope, monotonic=lambda: 1.0, **kwargs)


def test_session_hold_is_idempotent_and_keeps_first_reason(tmp_path):
    receiver, session, *_ = build(tmp_path)
    session.hold('first')
    session.hold('second')
    assert session.hold_reason == 'requested_hold:first'


def test_replayed_or_stale_grant_is_refused_and_holds(tmp_path):
    receiver, session, _, clock, grant, observe = build(tmp_path)
    clock[0] = 10.5
    observe()
    assert receiver.deliver(grant) is True
    clock[0] = 10.6
    observe()
    assert receiver.deliver(grant) is False  # the identical grant again: seq did not increase
    assert session.hold_reason == 'requested_hold:lease_delivery_failed'


def test_delayed_grant_never_outlives_the_episode_deadline(tmp_path):
    receiver, session, _, clock, grant, observe = build(tmp_path, first_window=0.5)
    assert session.lease.expires_at_ns == 10_500_000_000  # capped at the window end, not issued + 1 s
    clock[0] = 10.3
    observe()
    assert receiver.deliver(dict(grant, window_remaining_s=600.0)) is True  # a forged longer window changes nothing
    assert session.lease.expires_at_ns == 10_500_000_000
    clock[0] = 10.6
    observe()
    assert receiver.deliver(dict(grant, seq=3)) is False  # past the deadline
    assert session.hold_reason


def test_watchdog_poll_alone_cancels_at_pushed_lease_expiry(tmp_path):
    from test_policy_runtime_binding import attached
    session, runtime, client, clock, authority, *_ = attached(tmp_path)
    lease = session.lease
    scope = LeaseScope(lease.identity, lease.episode_id, lease.policy_revision, lease.owner_session_id,
                       'w', 'rig', 'cal-7', 'scope')
    receiver = PushLeaseReceiver(scope, monotonic=lambda: clock[0], policy_digest=DIGEST)
    assert receiver.deliver(dict(lease_id=lease.lease_id, episode_id=lease.episode_id,
                                 workcell_id=lease.identity.workcell_id, policy_digest=DIGEST, rig_revision='rig',
                                 calibration_revision='cal-7', ttl_s=0.9, seq=1, window_remaining_s=60.0))
    session._authority = receiver.authority
    receiver.attach(session)
    session.submit(candidate(session))
    clock[0] = 11.5  # no push, no submit, no poll by any caller: only the runtime watchdog tick runs
    runtime._watchdog_tick()
    assert session.hold_reason == 'policy_lease_expired_or_invalid' and session.owner.state == 'hold'
    assert client.handles[0].cancel_calls == 1


def test_end_of_window_grant_is_a_no_op_not_an_error_then_the_lease_runs_out(tmp_path):
    receiver, session, _, clock, grant, observe = build(tmp_path, first_window=0.8)
    assert session.lease.expires_at_ns == 10_800_000_000
    clock[0] = 10.5
    observe()
    assert receiver.deliver(dict(grant, ttl_s=0.3, window_remaining_s=0.3)) is True  # Fleet's last renewal
    assert session.lease.expires_at_ns == 10_800_000_000 and not session.hold_reason
    clock[0] = 10.9
    observe()
    with pytest.raises(PermissionError):
        session.poll()
    assert session.hold_reason == 'policy_lease_expired_or_invalid'
    assert receiver.authority(session.lease) is False and receiver._closed


def test_expired_lease_latches_authority_and_acquire(tmp_path):
    receiver, session, _, clock, grant, observe = build(tmp_path)
    clock[0] = 12.0
    assert receiver.authority(session.lease) is False and receiver._closed
    (tmp_path / 'b').mkdir()
    base, _, clock2, _, _ = setup_session(tmp_path / 'b')
    lease = base.lease
    scope = LeaseScope(lease.identity, 'episode', lease.policy_revision, 'owner-session', 'w', 'rig', 'cal-7', 'scope')
    late = PushLeaseReceiver(scope, monotonic=lambda: clock2[0], policy_digest=DIGEST)
    assert late.deliver(dict(grant, seq=1, workcell_id=lease.identity.workcell_id))
    clock2[0] = 12.0  # the first push expired before the session was built
    with pytest.raises(PermissionError):
        late.acquire()
    assert late._closed
