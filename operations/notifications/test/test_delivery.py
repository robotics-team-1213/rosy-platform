"""Fake HTTP proves delivery semantics; no live channel or cutover acceptance."""

import asyncio
import hashlib
from dataclasses import replace

import httpx
import pytest
from fastapi.testclient import TestClient
from core_common.notification_channels import Channel
from core_common.protocol.schemas import DeliveryRequest
from fleet.incidents.delivery_producer import FleetDeliveryProducer
from rosy.notifications.api import create_app
from rosy.notifications.config import Producer
from rosy.notifications.journal import DeliveryError, Journal
from rosy.notifications.service import DeliveryService


TOKENS = {'fleet': 'f' * 40, 'harbor': 'h' * 40}
PATH = '/api/notifications/v1/deliveries'


def body(producer='fleet', identity='notice-1', **changes):
    return dict(producer=producer, notification_id=identity, channel=producer,
                kind='HOLD' if producer == 'harbor' else 'OPEN', subject_id='opaque-job',
                occurrence_id='occurrence-1', revision='rev-1', classification='REVIEW',
                observed_at=100.0, expires_at=700.0, **changes)


@pytest.fixture
def setup(tmp_path):
    now, sent = [100.0], []
    channels = {p: Channel('discord', 'https://discord.com/api/webhooks/' + str(i) + '/fake')
                for i, p in enumerate(TOKENS, 1)}
    profiles = {p: Producer(p, hashlib.sha256(token.encode()).hexdigest(), frozenset([p]),
                            'https://owner.example/check', 'c' * 40, 'https://owner.example/work')
                for p, token in TOKENS.items()}

    def provider(request):
        sent.append(request)
        return httpx.Response(200, json={'id': '123'})

    http = httpx.AsyncClient(transport=httpx.MockTransport(provider))
    journal = Journal(tmp_path / 'delivery.sqlite3')

    async def valid(profile, request):
        return True

    service = DeliveryService(journal, channels, profiles, http, owner_check=valid, clock=lambda: now[0])
    yield service, now, sent
    journal.close()
    asyncio.run(http.aclose())


def accept(service, producer='fleet', identity='notice-1', **changes):
    request = DeliveryRequest.model_validate(body(producer, identity) | changes)
    return service.accept(request, service.producers[producer])


def run(service):
    asyncio.run(service.run_once())


def test_duplicate_conflict_and_independent_producers(setup):
    service, now, sent = setup
    first = accept(service)
    assert accept(service) == first
    with pytest.raises(DeliveryError, match='IDENTITY_CONFLICT'):
        accept(service, revision='rev-2')
    accept(service, 'harbor')
    run(service)
    assert len(sent) == 2
    assert service.journal.read('fleet', 'notice-1').state == 'SENT'
    assert service.journal.read('harbor', 'notice-1').state == 'SENT'


@pytest.mark.parametrize('result, expected', [(None, 'PENDING'), (False, 'SUPERSEDED'), ('raise', 'PENDING')])
def test_owner_unavailable_or_invalid_never_sends(setup, result, expected):
    service, now, sent = setup

    async def check(profile, request):
        if result == 'raise':
            raise OSError('owner disconnected')
        return result

    service.owner_check = check
    accept(service)
    run(service)
    row = service.journal.read('fleet', 'notice-1')
    assert (row.state, row.attempts, len(sent)) == (expected, 0, 0)


def test_unconfirmed_old_notice_does_not_starve_later_valid_notice(setup):
    service, now, sent = setup

    async def check(profile, request):
        return None if request.notification_id == 'notice-1' else True

    service.owner_check = check
    accept(service)
    accept(service, identity='notice-2')
    run(service)
    now[0] += 1
    run(service)
    assert service.journal.read('fleet', 'notice-2').state == 'SENT'
    assert len(sent) == 1


def test_ignored_chat_id_cannot_make_duplicate_webhook_cooldowns(setup):
    service, now, sent = setup
    channels = dict(service.channels)
    channels['alias'] = replace(channels['fleet'], chat_id='123')
    with pytest.raises(ValueError, match='approved channel'):
        DeliveryService(service.journal, channels, service.producers, service.http)


def test_expiry_is_rechecked_after_owner_reply(setup):
    service, now, sent = setup

    async def check(profile, request):
        now[0] = 700.0
        return True

    service.owner_check = check
    accept(service)
    run(service)
    assert service.journal.read('fleet', 'notice-1').state == 'EXPIRED'
    assert sent == []


def test_expiry_is_rechecked_after_durable_attempt_recording(setup, monkeypatch):
    service, now, sent = setup
    original = service.journal.start_attempt

    def delayed(*args):
        result = original(*args)
        now[0] = 700.0
        return result

    monkeypatch.setattr(service.journal, 'start_attempt', delayed)
    accept(service)
    run(service)
    assert service.journal.read('fleet', 'notice-1').state == 'EXPIRED'
    assert sent == []


@pytest.mark.parametrize('outcome', ['timeout', '500', 'cancel', 'restart'])
def test_unknown_never_replays_after_restart(setup, outcome):
    service, now, sent = setup
    accept(service)

    async def provider(request):
        sent.append(request)
        if outcome == 'timeout':
            raise httpx.ReadTimeout('unknown')
        if outcome == 'cancel':
            raise asyncio.CancelledError()
        return httpx.Response(500)

    http = httpx.AsyncClient(transport=httpx.MockTransport(provider))
    service.http = http
    if outcome == 'restart':
        service.journal.claim('fleet', now[0])
    elif outcome == 'cancel':
        with pytest.raises(asyncio.CancelledError):
            run(service)
    else:
        run(service)
    path = service.journal.path
    service.journal.close()
    service.journal = Journal(path)
    assert service.journal.read('fleet', 'notice-1').state == 'UNKNOWN'
    count = len(sent)
    now[0] += 60
    run(service)
    assert len(sent) == count
    service.journal.close()
    asyncio.run(http.aclose())


@pytest.mark.parametrize('outcome', ['429', 'connect'])
def test_retry_interval_attempt_budget_and_restart_preservation(setup, outcome):
    service, now, sent = setup
    accept(service)

    def provider(request):
        sent.append(request)
        if outcome == 'connect':
            raise httpx.ConnectError('not submitted')
        return httpx.Response(429, headers={'Retry-After': '1'})

    http = httpx.AsyncClient(transport=httpx.MockTransport(provider))
    service.http = http
    run(service)
    now[0] = 159.0
    run(service)
    assert len(sent) == 1
    path = service.journal.path
    service.journal.close()
    service.journal = Journal(path)
    for tick in (160.0, 220.0, 280.0):
        now[0] = tick
        run(service)
    assert len(sent) == 3
    assert service.journal.read('fleet', 'notice-1').state == 'FAILED'
    service.journal.close()
    asyncio.run(http.aclose())


def test_capacity_is_per_producer_and_duplicate_does_not_consume_it(setup):
    service, now, sent = setup
    service.producers['fleet'] = replace(service.producers['fleet'], capacity=1)
    accept(service)
    accept(service)
    with pytest.raises(DeliveryError, match='BUDGET'):
        accept(service, identity='notice-2')
    accept(service, 'harbor')
    run(service)
    assert len(sent) == 2


def test_terminal_history_does_not_consume_pending_capacity(setup):
    service, now, sent = setup
    service.producers['fleet'] = replace(service.producers['fleet'], capacity=1)
    accept(service)
    run(service)
    accept(service, identity='notice-2')
    assert service.journal.read('fleet', 'notice-1').state == 'SENT'
    assert service.journal.read('fleet', 'notice-2').state == 'PENDING'
    with service.journal.connect() as db:
        assert db.execute('SELECT COUNT(*) FROM deliveries').fetchone()[0] == 2


def test_channel_spacing_defers_owner_http_until_due_even_between_producers(setup):
    service, now, sent = setup
    service.producers['harbor'] = replace(service.producers['harbor'], channels=frozenset(['fleet']))
    checked = []

    async def owner(profile, request):
        checked.append((profile.identity, request.notification_id))
        return True

    service.owner_check = owner
    accept(service)
    accept(service, 'harbor', channel='fleet')
    run(service)
    assert len(checked) == len(sent) == 1
    for tick in (101.0, 120.0, 159.0):
        now[0] = tick
        run(service)
    assert len(checked) == len(sent) == 1
    with service.journal.connect() as db:
        assert db.execute("SELECT due FROM deliveries WHERE producer='harbor'").fetchone()[0] == 160
    now[0] = 160.0
    run(service)
    assert len(checked) == len(sent) == 2


@pytest.mark.parametrize('skew, accepted', [(0.0, True), (5.0, True), (5.001, False)])
def test_observation_clock_skew_has_a_small_fixed_bound(setup, skew, accepted):
    service, now, sent = setup
    if accepted:
        assert accept(service, observed_at=now[0] + skew).state == 'PENDING'
    else:
        with pytest.raises(DeliveryError, match='TIME_INVALID'):
            accept(service, observed_at=now[0] + skew)


def test_minute_budget_and_retention_remain_finite(setup):
    service, now, sent = setup
    service.producers['fleet'] = replace(service.producers['fleet'], admissions_per_minute=1)
    accept(service)
    with pytest.raises(DeliveryError, match='BUDGET'):
        accept(service, identity='notice-2')
    now[0] = 160.0
    accept(service, identity='notice-2')
    now[0] = 8 * 86400.0
    accept(service, identity='notice-3', observed_at=now[0], expires_at=now[0] + 600)
    with service.journal.connect() as db:
        assert db.execute('SELECT COUNT(*) FROM deliveries').fetchone()[0] == 1
    with pytest.raises(DeliveryError, match='TIME_INVALID'):
        accept(service)


def test_channel_cooldown_is_shared_between_notifications(setup):
    service, now, sent = setup
    accept(service)
    accept(service, identity='notice-2')
    run(service)
    run(service)
    assert len(sent) == 1
    now[0] = 160.0
    run(service)
    assert len(sent) == 2


def test_changed_destination_or_revoked_channel_never_sends(setup):
    service, now, sent = setup
    accept(service)
    service.channels['fleet'] = Channel('discord', 'https://discord.com/api/webhooks/99/fake')
    run(service)
    assert service.journal.read('fleet', 'notice-1').state == 'SUPERSEDED'
    assert sent == []


def test_single_process_and_fleet_cutover_guard(setup):
    service, now, sent = setup
    with pytest.raises(ValueError, match='ALREADY_ACTIVE'):
        Journal(service.journal.path)
    assert FleetDeliveryProducer().submit({}) is None
    with pytest.raises(ValueError, match='MULTIPLE_NOTIFICATION'):
        FleetDeliveryProducer(enabled=True)
    with pytest.raises(ValueError, match='CUTOVER_NOT_ACCEPTED'):
        FleetDeliveryProducer(enabled=True, legacy_enabled=False)


def test_http_machine_scope_input_bounds_and_read_isolation(setup):
    service, now, sent = setup
    headers = {'Authorization': 'Bearer ' + TOKENS['fleet']}
    with TestClient(create_app(service)) as client:
        assert client.post(PATH, json=body()).status_code == 401
        assert client.post(PATH, headers=headers, json=body('harbor')).status_code == 403
        assert client.post(PATH, headers=headers, json=body() | {'channel': 'harbor'}).status_code == 403
        assert client.post(PATH, headers=headers, json=body() | {'endpoint': 'https://evil.example'}).status_code == 422
        assert client.post(PATH, headers=headers, content=b'x' * 4097).status_code == 413
        reply = client.post(PATH, headers=headers, json=body())
        assert reply.status_code == 200 and reply.json()['state'] == 'PENDING'
        assert client.post(PATH, headers=headers, json=body()).json() == reply.json()
        assert client.post(PATH, headers=headers, json=body() | {'revision': 'rev-2'}).status_code == 409
        harbor = {'Authorization': 'Bearer ' + TOKENS['harbor']}
        assert client.get(PATH + '/notice-1', headers=harbor).status_code == 404
        assert client.get(PATH + '/notice-1', headers=headers).json() == reply.json()
    assert sent == []


def test_http_owner_reply_must_bind_identity_revision_and_no_redirect(setup):
    from rosy.notifications.service import HttpOwnerCheck
    service, now, sent = setup

    def owner(request):
        assert request.headers['authorization'] == 'Bearer ' + 'c' * 40
        return httpx.Response(200, json={'notification_id': 'wrong', 'revision': 'rev-1', 'valid': True})

    http = httpx.AsyncClient(transport=httpx.MockTransport(owner))
    service.owner_check = HttpOwnerCheck(http)
    accept(service)
    run(service)
    assert sent == []
    assert service.journal.read('fleet', 'notice-1').state == 'PENDING'
    asyncio.run(http.aclose())


@pytest.mark.parametrize('guard', ['fairness', 'expiry', 'destination'])
def test_regressions_detect_mutated_guards(setup, monkeypatch, guard):
    """Exercise the guards' regression assertions against real in-memory mutants."""
    import inspect
    import sys
    from rosy.notifications import journal, service as module

    instance = setup[0].journal if guard == 'fairness' else setup[0]
    owner = journal if guard == 'fairness' else module
    source = inspect.getsource(type(instance))
    if guard == 'fairness':
        mutated = source.replace('ORDER BY due, admitted, notification_id', 'ORDER BY admitted, notification_id')
        regression = lambda: test_unconfirmed_old_notice_does_not_starve_later_valid_notice(setup)
    elif guard == 'expiry':
        block = ("            if self.clock() >= request.expires_at:\n"
                 "                self.journal.finish(row, 'EXPIRED', self.clock())\n"
                 "                return\n            state,")
        mutated = source.replace(block, '            state,')
        regression = lambda: test_expiry_is_rechecked_after_durable_attempt_recording(setup, monkeypatch)
    else:
        mutated = source.replace("or any(channel.kind != 'telegram' and channel.chat_id is not None for channel in channels.values())", '')
        regression = lambda: test_ignored_chat_id_cannot_make_duplicate_webhook_cooldowns(setup)
    assert mutated != source, 'mutation must actually change the guarded implementation'
    namespace = dict(vars(owner))
    exec(compile(mutated, '<notification-guard-mutation>', 'exec'), namespace)
    variant = namespace[type(instance).__name__]
    if guard == 'destination':
        monkeypatch.setattr(sys.modules[__name__], 'DeliveryService', variant)
    else:
        instance.__class__ = variant
    with pytest.raises((AssertionError, pytest.fail.Exception)):
        regression()
