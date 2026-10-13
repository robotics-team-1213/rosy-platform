"""Team notifications use the incident journal, never a motion/provider tool outbox."""

import asyncio
import json
import logging
import sqlite3
import threading
from contextlib import closing

import httpx
import pytest

from fleet.incidents.notifications import Channel, NotificationConfig, NotificationWorker
from fleet.stuck.board import LineStuckBoard
from fleet.stuck.reports import LineStuckAnswerLog
from test_judgment_receipts import row


DISCORD = 'https://discord.com/api/webhooks/123/private_token'
SLACK = 'https://hooks.slack.com/services/T1/B1/private_token'
TELEGRAM = 'https://api.telegram.org/bot123:private_token/sendMessage'


def _setup(tmp_path, kinds=('discord',)):
    now = [100.0]
    log = LineStuckAnswerLog(tmp_path / 'fleet.sqlite3')
    urls = {'discord': DISCORD, 'slack': SLACK, 'telegram': TELEGRAM}
    config = NotificationConfig('https://fleet.example/console',
                                tuple(Channel(kind, urls[kind], '-123' if kind == 'telegram' else None)
                                      for kind in kinds))
    log.notifications.config = config
    board = LineStuckBoard(log=log, clock=lambda: now[0], wall=lambda: now[0])
    return now, log, board, config


def observe(board, now, stuck='case-1'):
    board.observe([row(now, stuck_id=stuck)])
    board.flush()


def run(log, board, config, now, handler):
    async def deliver():
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http:
            worker = NotificationWorker(log.notifications, config, http, board=board, clock=lambda: now)
            await worker.run_once()
    asyncio.run(deliver())


def test_normal_zero_send_deduplication_and_no_secrets_in_rows(tmp_path):
    now, log, board, config = _setup(tmp_path)
    observe(board, 100.0, None)
    assert log.notifications.rows() == []
    observe(board, 100.0)
    for _ in range(3):
        observe(board, 100.0)
    assert len(log.notifications.rows()) == 1
    requests = []
    def send(request):
        requests.append(request)
        payload = json.loads(request.content)
        assert payload['allowed_mentions'] == {'parse': []}
        assert 'robot=pinky' in payload['content'] and 'incident=case-1' in payload['content']
        assert 'private_token' not in payload['content']
        assert request.url.params['wait'] == 'true'
        return httpx.Response(200, json={'id': '777'})
    run(log, board, config, 100.0, send)
    run(log, board, config, 100.0, send)
    [delivery] = log.notifications.rows()
    assert delivery['state'] == 'SENT' and delivery['provider_id'] == '777'
    assert len(requests) == 1
    assert 'private_token' not in json.dumps(delivery)
    assert log.handoff.active() == [] and log.rows() == []


def test_outbox_failure_rolls_back_the_judgment_write(tmp_path):
    now, log, board, config = _setup(tmp_path)
    observe(board, 100.0, None)
    board.observe([row(stuck_id='case-1')])
    receipt = board.judgment_view('pinky')
    with closing(log._connect()) as connection, connection:
        connection.execute("CREATE TRIGGER reject_outbox BEFORE INSERT ON fleet_notification_outbox BEGIN SELECT RAISE(ABORT, 'disk unavailable'); END")
    with pytest.raises(sqlite3.IntegrityError, match='disk unavailable'):
        log.record_judgment(receipt)
    assert log.judgments()[0]['assessment']['necessity'] == 'DO_NOT_INTERVENE'
    assert log.notifications.rows() == []


@pytest.mark.parametrize('change', ['closed', 'replaced', 'claimed', 'expired', 'destination'])
def test_rechecks_current_case_before_sending(tmp_path, change):
    now, log, board, config = _setup(tmp_path)
    observe(board, 100.0)
    if change == 'closed':
        observe(board, 100.0, None)
    elif change == 'replaced':
        observe(board, 100.0, 'case-2')
    elif change == 'claimed':
        log.handoff.claim('pinky', 'case-1', board.judgment_view('pinky'), 'alice', now=100.0)
    elif change == 'expired':
        now[0] = 701.0
    else:
        config = NotificationConfig(config.console_url, (Channel('discord', DISCORD.replace('123', '456')),))
    sent = []
    def send(request):
        sent.append(json.loads(request.content)['content'])
        return httpx.Response(200, json={'id': '777'})
    run(log, board, config, now[0], send)
    assert not any('OPEN' in body and 'case-1' in body for body in sent)
    assert log.notifications.rows()[-1]['state'] in ('SUPERSEDED', 'EXPIRED')


def test_partial_delivery_429_and_timeout_are_distinct(tmp_path):
    now, log, board, config = _setup(tmp_path, ('discord', 'slack', 'telegram'))
    observe(board, 100.0)
    def send(request):
        if request.url.host == 'discord.com':
            return httpx.Response(200, json={'id': '777'})
        if request.url.host == 'hooks.slack.com':
            return httpx.Response(429, headers={'Retry-After': '70'})
        raise httpx.ReadTimeout('secret ' + TELEGRAM, request=request)
    run(log, board, config, 100.0, send)
    states = {item['channel']: item for item in log.notifications.rows()}
    assert {key: item['state'] for key, item in states.items()} == {'discord': 'SENT', 'slack': 'RETRY', 'telegram': 'UNKNOWN'}
    assert states['slack']['next_attempt_at'] == 170.0
    assert 'private_token' not in json.dumps(states)
    now[0] = 170.0
    observe(board, 170.0)
    run(log, board, config, 170.0, lambda request: httpx.Response(200, text='ok'))
    assert {item['channel']: item['state'] for item in log.notifications.rows()} == {'discord': 'SENT', 'slack': 'SENT', 'telegram': 'UNKNOWN'}


def test_restart_leaves_inflight_delivery_unknown_without_retry(tmp_path):
    now, log, board, config = _setup(tmp_path)
    observe(board, 100.0)
    assert log.notifications.claim_due(100.0, config)['state'] == 'SENDING'
    reopened = LineStuckAnswerLog(log.path)
    run(reopened, board, config, 131.0, lambda request: pytest.fail('must not resend unknown delivery'))
    assert reopened.notifications.rows()[0]['state'] == 'UNKNOWN'


@pytest.mark.parametrize('url', ['http://discord.com/api/webhooks/1/t', 'https://discord.com.attacker.invalid/api/webhooks/1/t',
                                 'https://user@discord.com/api/webhooks/1/t', 'https://discord.com/api/webhooks/1/t?url=x'])
def test_destination_is_fixed_and_secret_errors_are_redacted(url):
    with pytest.raises(ValueError) as error:
        Channel('discord', url)
    assert url not in str(error.value)


@pytest.mark.parametrize('kind', ['discord', 'slack', 'telegram'])
def test_provider_receipt_and_http_logs_do_not_expose_endpoint(tmp_path, kind, caplog):
    now, log, board, config = _setup(tmp_path, (kind,))
    observe(board, 100.0)
    caplog.set_level(logging.INFO, logger='httpx')
    def send(request):
        if kind == 'slack':
            return httpx.Response(200, text='ok')
        return httpx.Response(200, json={'id': '777'} if kind == 'discord'
                              else {'ok': True, 'result': {'message_id': 777}})
    run(log, board, config, 100.0, send)
    assert log.notifications.rows()[0]['state'] == 'SENT'
    assert 'private_token' not in caplog.text


def test_rate_spacing_and_third_attempt_exhaustion(tmp_path):
    now, log, board, config = _setup(tmp_path)
    observe(board, 100.0)
    sent = []
    def connect_fail(request):
        sent.append(request)
        raise httpx.ConnectError('not connected', request=request)
    for instant in (100.0, 159.0, 160.0, 220.0, 280.0):
        now[0] = instant
        observe(board, instant)
        run(log, board, config, instant, connect_fail)
    [delivery] = log.notifications.rows()
    assert delivery['state'] == 'FAILED' and delivery['attempts'] == 3 and len(sent) == 3


def test_5xx_is_unknown_and_not_retried(tmp_path):
    now, log, board, config = _setup(tmp_path)
    observe(board, 100.0)
    run(log, board, config, 100.0, lambda request: httpx.Response(503))
    now[0] = 160.0
    observe(board, 160.0)
    run(log, board, config, 160.0, lambda request: pytest.fail('unknown is not retried'))
    assert log.notifications.rows()[0]['state'] == 'UNKNOWN'


@pytest.mark.parametrize('change', ['closed', 'claimed'])
def test_dequeued_request_is_rechecked_before_http(tmp_path, monkeypatch, change):
    now, log, board, config = _setup(tmp_path)
    observe(board, 100.0)
    entered, release = threading.Event(), threading.Event()
    original = log.notifications.claim_due
    def paused(*args):
        result = original(*args)
        entered.set()
        assert release.wait(5)
        return result
    monkeypatch.setattr(log.notifications, 'claim_due', paused)
    async def race():
        async with httpx.AsyncClient(transport=httpx.MockTransport(lambda request: pytest.fail('stale OPEN sent'))) as http:
            worker = NotificationWorker(log.notifications, config, http, board=board, clock=lambda: 100.0)
            task = asyncio.create_task(worker.run_once())
            try:
                assert await asyncio.to_thread(entered.wait, 5)
                if change == 'closed':
                    board.observe([row()])  # Current holder changes before its off-loop journal flush.
                else:
                    board._handoff_pending.add(('pinky', 'case-1'))
                release.set()
                await task
            finally:
                release.set()
    asyncio.run(race())
    assert log.notifications.rows()[0]['state'] == 'SUPERSEDED'


def test_cancellation_after_http_entry_stays_unknown(tmp_path):
    now, log, board, config = _setup(tmp_path)
    observe(board, 100.0)
    async def cancel():
        entered = asyncio.Event()
        async def send(request):
            entered.set()
            await asyncio.Future()
        async with httpx.AsyncClient(transport=httpx.MockTransport(send)) as http:
            worker = NotificationWorker(log.notifications, config, http, board=board, clock=lambda: 100.0)
            task = asyncio.create_task(worker.run_once())
            await entered.wait()
            task.cancel()
            with pytest.raises(asyncio.CancelledError):
                await task
    asyncio.run(cancel())
    assert log.notifications.rows()[0]['state'] == 'UNKNOWN'


def test_config_requires_private_endpoint_and_durable_journal(tmp_path, monkeypatch):
    from fleet.server.app import create_app
    from fakes import FakeRobot
    from test_line_stuck_api import _console
    path = tmp_path / 'notifications.yaml'
    path.write_text('console_url: https://fleet.example/console\nchannels:\n  - kind: discord\n    endpoint_env: ROSY_TEST_WEBHOOK\n', encoding='utf-8')
    monkeypatch.delenv('ROSY_TEST_WEBHOOK', raising=False)
    with pytest.raises(ValueError, match='endpoint is missing'):
        NotificationConfig.load(path)
    monkeypatch.setenv('ROSY_TEST_WEBHOOK', DISCORD)
    config = NotificationConfig.load(path)
    assert 'private_token' not in repr(config)
    with pytest.raises(ValueError, match='durable Fleet journal'):
        create_app(_console(FakeRobot('pinky')), notification_config=config)


def test_expiry_is_rechecked_after_dequeue(tmp_path, monkeypatch):
    now, log, board, config = _setup(tmp_path)
    observe(board, 100.0)
    original = log.notifications.claim_due
    def advance(*args):
        result = original(*args)
        if result is not None:
            now[0] = 701.0
            observe(board, now[0])
        return result
    monkeypatch.setattr(log.notifications, 'claim_due', advance)
    async def deliver():
        async with httpx.AsyncClient(transport=httpx.MockTransport(lambda request: pytest.fail('expired notification sent'))) as http:
            await NotificationWorker(log.notifications, config, http, board=board, clock=lambda: now[0]).run_once()
    asyncio.run(deliver())
    assert log.notifications.rows()[0]['state'] == 'EXPIRED'


def test_closure_outbox_failure_rolls_back_episode_close(tmp_path):
    now, log, board, config = _setup(tmp_path)
    observe(board, 100.0)
    with closing(log._connect()) as connection, connection:
        connection.execute("CREATE TRIGGER reject_closed BEFORE INSERT ON fleet_notification_outbox WHEN NEW.kind='CLOSED' BEGIN SELECT RAISE(ABORT, 'disk unavailable'); END")
    with pytest.raises(sqlite3.IntegrityError):
        log.close_episode('pinky', 'case-1', closed_at='1970-01-01T00:01:40+00:00',
                          close_reason='cleared', held_s_max=None, attempts_max=None)
    assert log.episodes()[0]['closed_at'] is None
    assert log.notifications.rows()[0]['state'] == 'PENDING'
