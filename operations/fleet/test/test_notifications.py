"""Team notifications use the incident journal, never a motion/provider tool outbox."""

import asyncio
import json
from contextlib import closing

import httpx
import pytest

from fleet.notifications import Channel, NotificationConfig, NotificationWorker
from fleet.stuck.board import LineStuckBoard
from fleet.stuck.reports import LineStuckAnswerLog
from test_judgment_receipts import row


DISCORD = 'https://discord.com/api/webhooks/123/private_token'
SLACK = 'https://hooks.slack.com/services/T1/B1/private_token'
TELEGRAM = 'https://api.telegram.org/bot123:private_token/sendMessage'


def setup(tmp_path, kinds=('discord',)):
    now = [100.0]
    log = LineStuckAnswerLog(tmp_path / 'fleet.sqlite3')
    urls = {'discord': DISCORD, 'slack': SLACK, 'telegram': TELEGRAM}
    config = NotificationConfig('https://fleet.example/console',
                                tuple(Channel(kind, urls[kind], 'team' if kind == 'telegram' else None)
                                      for kind in kinds))
    log.notifications.config = config
    board = LineStuckBoard(log=log, clock=lambda: now[0], wall=lambda: now[0])
    return now, log, board, config


def observe(board, now, stuck='case-1'):
    board.observe([row(now, stuck_id=stuck)])
    board.flush()


def run(log, config, now, handler):
    async def deliver():
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http:
            worker = NotificationWorker(log.notifications, config, http, clock=lambda: now)
            await worker.run_once()
    asyncio.run(deliver())


def test_normal_zero_send_deduplication_and_no_secrets_in_rows(tmp_path):
    now, log, board, config = setup(tmp_path)
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
    run(log, config, 100.0, send)
    run(log, config, 100.0, send)
    [delivery] = log.notifications.rows()
    assert delivery['state'] == 'SENT' and delivery['provider_id'] == '777'
    assert len(requests) == 1
    assert 'private_token' not in json.dumps(delivery)
    assert log.handoff.active() == [] and log.rows() == []


def test_outbox_failure_rolls_back_the_judgment_write(tmp_path):
    now, log, board, config = setup(tmp_path)
    observe(board, 100.0, None)
    board.observe([row(stuck_id='case-1')])
    receipt = board.judgment_view('pinky')
    with closing(log._connect()) as connection, connection:
        connection.execute("CREATE TRIGGER reject_outbox BEFORE INSERT ON fleet_notification_outbox BEGIN SELECT RAISE(ABORT, 'disk unavailable'); END")
    with pytest.raises(Exception, match='disk unavailable'):
        log.record_judgment(receipt)
    assert log.judgments()[0]['assessment']['necessity'] == 'DO_NOT_INTERVENE'
    assert log.notifications.rows() == []


@pytest.mark.parametrize('change', ['closed', 'replaced', 'claimed', 'expired', 'destination'])
def test_rechecks_current_case_before_sending(tmp_path, change):
    now, log, board, config = setup(tmp_path)
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
    run(log, config, now[0], send)
    assert not any('OPEN' in body and 'case-1' in body for body in sent)
    assert log.notifications.rows()[-1]['state'] in ('SUPERSEDED', 'EXPIRED')


def test_partial_delivery_429_and_timeout_are_distinct(tmp_path):
    now, log, board, config = setup(tmp_path, ('discord', 'slack', 'telegram'))
    observe(board, 100.0)
    def send(request):
        if request.url.host == 'discord.com':
            return httpx.Response(200, json={'id': '777'})
        if request.url.host == 'hooks.slack.com':
            return httpx.Response(429, headers={'Retry-After': '70'})
        raise httpx.ReadTimeout('secret ' + TELEGRAM, request=request)
    run(log, config, 100.0, send)
    states = {item['channel']: item for item in log.notifications.rows()}
    assert {key: item['state'] for key, item in states.items()} == {'discord': 'SENT', 'slack': 'RETRY', 'telegram': 'UNKNOWN'}
    assert states['slack']['next_attempt_at'] == 170.0
    assert 'private_token' not in json.dumps(states)
    observe(board, 170.0)
    run(log, config, 170.0, lambda request: httpx.Response(200, text='ok'))
    assert {item['channel']: item['state'] for item in log.notifications.rows()} == {'discord': 'SENT', 'slack': 'SENT', 'telegram': 'UNKNOWN'}


def test_restart_leaves_inflight_delivery_unknown_without_retry(tmp_path):
    now, log, board, config = setup(tmp_path)
    observe(board, 100.0)
    assert log.notifications.claim_due(100.0, config)['state'] == 'SENDING'
    reopened = LineStuckAnswerLog(log.path)
    run(reopened, config, 131.0, lambda request: pytest.fail('must not resend unknown delivery'))
    assert reopened.notifications.rows()[0]['state'] == 'UNKNOWN'


@pytest.mark.parametrize('url', ['http://discord.com/api/webhooks/1/t', 'https://discord.com.attacker.invalid/api/webhooks/1/t',
                                 'https://user@discord.com/api/webhooks/1/t', 'https://discord.com/api/webhooks/1/t?url=x'])
def test_destination_is_fixed_and_secret_errors_are_redacted(url):
    with pytest.raises(ValueError) as error:
        Channel('discord', url)
    assert url not in str(error.value)
