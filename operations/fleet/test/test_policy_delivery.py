"""D-1024 3: Fleet's CORE lease delivery port and ticker; any delivery failure closes the window and HOLDs."""
import io
import json
import threading
from urllib.error import HTTPError

import pytest

from fleet.server.policy_approval import PolicyApprovals
from fleet.server.policy_delivery import (CoreLeaseDelivery, PolicyApprovalTicker, build_policy_approvals,
                                          targets_from_file)

DIGEST = 'ab' * 32
GRANT = dict(lease_id='l', episode_id='e', workcell_id='cell-1', policy_digest=DIGEST, rig_revision='r',
             calibration_revision='c', ttl_s=1.0, seq=1, window_remaining_s=10.0)


class Reply:
    def __init__(self, body=b'{"accepted": true}', status=200):
        self.body, self.status = body, status

    def read(self, n=-1):
        return self.body

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


class Core:
    def __init__(self, *replies):
        self.calls, self.replies = [], list(replies)

    def __call__(self, request, timeout):
        assert timeout <= 0.25 and request.get_method() == 'POST'
        self.calls.append((request.full_url, json.loads(request.data), request.get_header('Authorization')))
        reply = self.replies.pop(0) if self.replies else Reply()
        if isinstance(reply, Exception):
            raise reply
        return reply


def port(core, **kw):
    return CoreLeaseDelivery({'cell-1': ('https://core.example', 'tok')}, opener=core, **kw)


def test_deliver_posts_exactly_the_grant_with_the_fleet_credential():
    core = Core()
    assert port(core).deliver(dict(GRANT, extra='dropped')) is True
    url, body, auth = core.calls[0]
    assert url == 'https://core.example/api/v1/arm/lease' and auth == 'Bearer tok'
    assert body == GRANT  # the same nine keys CORE's ArmLeaseGrant accepts, nothing else


@pytest.mark.parametrize('reply', [
    HTTPError('u', 409, 'x', {}, io.BytesIO(b'{}')), HTTPError('u', 403, 'x', {}, io.BytesIO(b'{}')),
    TimeoutError(), OSError('down'), Reply(b'not json'), Reply(b'{"accepted": false}'), Reply(b'[]'),
    Reply(b'{"accepted": true}', status=202)])
def test_every_failure_is_a_failed_delivery(reply):
    assert port(Core(reply)).deliver(GRANT) is False


def test_unconfigured_workcell_fails_closed_and_hold_raises_when_unconfirmed():
    core = Core(HTTPError('u', 500, 'x', {}, io.BytesIO(b'{}')))
    assert port(core).deliver(dict(GRANT, workcell_id='other')) is False and core.calls == []
    with pytest.raises(OSError):
        port(core).hold('cell-1', 'window_ended')
    with pytest.raises(OSError):
        port(Core(TimeoutError())).hold('cell-1', 'x')
    ok = Core()
    port(ok).hold('cell-1', 'x' * 200)
    assert ok.calls[0][0].endswith('/api/v1/arm/hold') and len(ok.calls[0][1]['reason']) == 96


@pytest.mark.parametrize('targets,kw', [
    ({}, {}), ({'c': ('http://core.example', 't')}, {}), ({'c': ('https://u:p@core.example', 't')}, {}),
    ({'c': ('https://core.example', 'a b')}, {}), ({'c': ('https://core.example', '')}, {}),
    ({'c': ('https://core.example/x', 't')}, {}), ({'c': ('https://core.example', 't')}, dict(timeout_s=1.0)),
    ({'c': ('https://core.example', 't')}, dict(timeout_s=0))])
def test_targets_and_timeout_are_validated(targets, kw):
    with pytest.raises(ValueError):
        CoreLeaseDelivery(targets, **kw)


def test_loopback_http_is_allowed_for_the_sim():
    CoreLeaseDelivery({'c': ('http://127.0.0.1:8080', 't')})


class Clock:
    now = 1000.0

    def __call__(self):
        return self.now


def window(core):
    clock = Clock()
    delivery = port(core)
    approvals = PolicyApprovals(monotonic=clock, deliver=delivery.deliver, hold=delivery.hold)
    item = approvals.propose(workcell_id='cell-1', proposer='a', policy_digest=DIGEST, rig_revision='r',
                             calibration_revision='c', scope='s', window_s=3)['id']
    approvals.approve(item, 'b')
    return approvals, clock, item


def test_window_drives_leases_then_hold_through_the_port():
    core = Core()
    approvals, clock, item = window(core)
    assert approvals.tick(item)['ttl_s'] == 1.0 and core.calls[0][0].endswith('/lease')
    clock.now += .5
    assert approvals.tick(item) is not None
    clock.now += 3
    assert approvals.view(item)['state'] == 'ended'
    assert core.calls[-1][0].endswith('/hold') and core.calls[-1][1] == {'reason': 'window_ended'}


def test_failed_lease_delivery_closes_the_window_and_holds_through_the_port():
    core = Core(Reply(b'{"accepted": false}'))
    approvals, clock, item = window(core)
    assert approvals.tick(item) is None
    view = approvals.view(item)
    assert view['state'] == 'held' and view['hold_reason'] == 'lease_delivery_failed'
    assert core.calls[-1][0].endswith('/hold')


def test_unconfirmed_hold_is_retried_by_the_next_tick():
    core = Core(Reply(), TimeoutError(), Reply())  # lease ok, hold lost, hold retried
    approvals, clock, item = window(core)
    approvals.tick(item)
    approvals.abort(item, 'b')
    assert approvals.view(item)['state'] == 'aborted'
    clock.now += .1
    approvals.tick_all()
    assert [c[0].rsplit('/', 1)[1] for c in core.calls] == ['lease', 'hold', 'hold']


def test_ticker_survives_a_failing_tick_runs_at_quarter_lease_and_holds_on_stop():
    class Fake:
        lease_s = 0.04
        ticks, held = 0, None
        seen = threading.Event()

        def tick_all(self):
            self.ticks += 1
            if self.ticks == 1:
                raise ValueError('clock fault')
            if self.ticks >= 3:
                self.seen.set()

        def hold_all(self, reason):
            self.held = reason

    fake = Fake()
    ticker = PolicyApprovalTicker(fake)
    assert ticker.period_s == pytest.approx(0.01)
    ticker.start()
    assert fake.seen.wait(2)
    with pytest.raises(RuntimeError):
        ticker.start()
    ticker.stop()
    assert fake.held == 'fleet_shutdown'


def test_approvals_hold_all_and_lease_s():
    core = Core()
    approvals, clock, item = window(core)
    assert approvals.lease_s == 1.0
    approvals.hold_all('fleet_shutdown')
    assert approvals.view(item)['state'] == 'held' and core.calls[-1][1] == {'reason': 'fleet_shutdown'}


def test_builder_without_targets_has_no_port_and_with_a_file_has_port_and_ticker(tmp_path):
    approvals, ticker = build_policy_approvals({})
    assert approvals.delivery_connected is False and ticker is None
    (tmp_path / 'tok').write_text('secret\n')
    targets = tmp_path / 't.json'
    row = {'url': 'https://core.example', 'token_file': str(tmp_path / 'tok')}
    targets.write_text(json.dumps({'cell-1': row}))
    assert targets_from_file(targets) == {'cell-1': ('https://core.example', 'secret')}
    approvals, ticker = build_policy_approvals({'ROSY_POLICY_LEASE_TARGETS': str(targets)})
    assert approvals.delivery_connected is True and ticker.period_s == 0.25
    targets.write_text(json.dumps({'cell-1': dict(row, url='http://core.example')}))
    assert build_policy_approvals({'ROSY_POLICY_LEASE_TARGETS': str(targets)})[1] is None  # insecure origin: no port


def test_grants_carry_increasing_seq_and_the_window_remaining():
    core = Core()
    approvals, clock, item = window(core)
    first = approvals.tick(item)
    clock.now += .5
    second = approvals.tick(item)
    assert (first['seq'], second['seq']) == (1, 2)
    assert first['window_remaining_s'] == pytest.approx(3.0) and second['window_remaining_s'] == pytest.approx(2.5)


def test_trickling_reply_hits_the_total_deadline():
    import time

    class Slow(Reply):
        def read(self, n=-1):
            time.sleep(1.0)
            return b'{"accepted": true}'
    started = time.monotonic()
    assert port(Core(Slow()), timeout_s=0.05).deliver(GRANT) is False
    assert time.monotonic() - started < 0.5
    with pytest.raises(TimeoutError):
        port(Core(Slow()), timeout_s=0.05).hold('cell-1', 'x')


def test_delivery_runs_outside_the_lock_and_a_window_aborted_meanwhile_stays_closed():
    gate, entered = threading.Event(), threading.Event()
    clock = Clock()

    def slow_deliver(grant):
        entered.set()
        gate.wait(2)
        return True
    approvals = PolicyApprovals(monotonic=clock, deliver=slow_deliver, hold=lambda c, r: None)
    item = approvals.propose(workcell_id='cell-1', proposer='a', policy_digest=DIGEST, rig_revision='r',
                             calibration_revision='c', scope='s', window_s=3)['id']
    approvals.approve(item, 'b')
    ticking = threading.Thread(target=approvals.tick, args=(item,))
    ticking.start()
    assert entered.wait(2)
    reader = threading.Thread(target=approvals.abort, args=(item, 'b'))
    reader.start()
    reader.join(1)
    assert not reader.is_alive()  # abort did not wait for the slow CORE
    gate.set()
    ticking.join(2)
    assert approvals.view(item)['state'] == 'aborted'


@pytest.mark.parametrize('env', ['', 'missing'])
def test_unusable_or_absent_targets_leave_no_delivery_port(tmp_path, env):
    value = {'ROSY_POLICY_LEASE_TARGETS': env if env == '' else str(tmp_path / 'nope.json')}
    approvals, ticker = build_policy_approvals(value)
    assert approvals.delivery_connected is False and ticker is None


@pytest.mark.parametrize('text', ['{bad json', '[]', '{"cell-1": {"url": "https://x"}}',
                                  '{"cell-1": {"url": "https://x", "token_file": "/no/such/file"}}'])
def test_garbled_targets_file_fails_closed_without_raising(tmp_path, text):
    targets = tmp_path / 't.json'
    targets.write_text(text)
    approvals, ticker = build_policy_approvals({'ROSY_POLICY_LEASE_TARGETS': str(targets)})
    assert approvals.delivery_connected is False and ticker is None


def test_ca_file_is_accepted_and_a_missing_one_refused(tmp_path):
    with pytest.raises(OSError):
        CoreLeaseDelivery({'c': ('https://core.example', 't')}, ca_file=str(tmp_path / 'none.pem'))


def test_site_estop_holds_every_window_and_no_further_lease_goes_out():
    import asyncio
    from fleet.server import task_dispatch_routes as routes
    core = Core()
    approvals, clock, item = window(core)
    approvals.tick(item)

    class Console:
        async def estop_all(self):
            return {'stopped': True}
    routes.STOP_LEASE_HOLDS.append(approvals.hold_all)
    try:
        result = asyncio.run(routes.execute_local_fleet_stop(
            console=Console(), task_service=None, configured_omx={}, stop_transport=None, stop_control=None,
            actor_id='op'))
    finally:
        routes.STOP_LEASE_HOLDS.remove(approvals.hold_all)
    assert result['omx_local_stop']['state'] == 'NOT_CONFIGURED'
    assert approvals.view(item)['state'] == 'held' and core.calls[-1][1] == {'reason': 'fleet_estop'}
    sent = len(core.calls)
    clock.now += .6
    assert approvals.tick_all() == [] and len(core.calls) == sent


def test_a_failing_hook_never_fails_the_stop():
    import asyncio
    from fleet.server import task_dispatch_routes as routes

    class Console:
        async def estop_all(self):
            return {'stopped': True}

    def boom(reason):
        raise OSError('core down')
    routes.STOP_LEASE_HOLDS.append(boom)
    try:
        assert asyncio.run(routes.execute_local_fleet_stop(
            console=Console(), task_service=None, configured_omx={}, stop_transport=None, stop_control=None,
            actor_id='op'))['stopped'] is True
    finally:
        routes.STOP_LEASE_HOLDS.remove(boom)


def test_hold_all_retries_a_closed_windows_unsent_hold():
    core = Core(Reply(), TimeoutError(), TimeoutError(), Reply())  # lease ok, abort hold lost, retry lost, retry ok
    approvals, clock, item = window(core)
    approvals.tick(item)
    approvals.abort(item, 'b')
    approvals.hold_all('fleet_estop')  # still due: tried again (lost)
    approvals.hold_all('fleet_estop')
    assert [c[0].rsplit('/', 1)[1] for c in core.calls] == ['lease', 'hold', 'hold', 'hold']


def test_no_lease_is_sent_for_the_last_sliver_of_a_window():
    core = Core()
    approvals, clock, item = window(core)
    approvals.tick(item)
    clock.now += 2.99  # 10 ms left
    assert approvals.tick(item) is None and len(core.calls) == 1


def test_lease_credential_must_differ_from_every_other_credential(tmp_path):
    from fleet.server.credential_isolation import assert_lease_tokens_isolated
    (tmp_path / 'tok').write_text('shared-secret')
    targets = tmp_path / 't.json'
    targets.write_text(json.dumps({'cell-1': {'url': 'https://core.example', 'token_file': str(tmp_path / 'tok')}}))
    env = {'ROSY_POLICY_LEASE_TARGETS': str(targets)}
    assert_lease_tokens_isolated(env, ('other', None))
    assert_lease_tokens_isolated({}, ('shared-secret',))  # nothing configured, nothing to isolate
    with pytest.raises(ValueError):
        assert_lease_tokens_isolated(env, ('x', 'shared-secret'))


def test_a_slow_lease_hold_never_delays_the_stop_response():
    import asyncio
    import time
    from fleet.server import task_dispatch_routes as routes

    class Console:
        async def estop_all(self):
            return {'stopped': True}
    release = threading.Event()
    routes.STOP_LEASE_HOLDS.append(lambda reason: release.wait(5))  # a CORE that never answers

    async def stop():
        started = time.monotonic()
        result = await routes.execute_local_fleet_stop(
            console=Console(), task_service=None, configured_omx={}, stop_transport=None, stop_control=None,
            actor_id='op')
        elapsed = time.monotonic() - started
        release.set()  # only now let the abandoned worker finish, so the loop can shut down
        return result, elapsed
    try:
        result, elapsed = asyncio.run(stop())
    finally:
        release.set()
        routes.STOP_LEASE_HOLDS.pop()
    assert result['stopped'] is True and elapsed < routes.STOP_LEASE_HOLD_WAIT_S + 0.5
