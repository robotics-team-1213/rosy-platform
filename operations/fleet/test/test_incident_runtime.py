import asyncio

import pytest

from fleet.server.app import create_app
from fleet.incidents.automation.contract import CaseBudget
from test_stuck_resolver_loop import FleetConsole, RobotEndpoint, FakeRobot, FleetTaskStore, FleetTaskService
from test_incident_case_worker import settled
from test_judgment_profiles import profile, adapter
from test_judgment_receipts import row
from fleet.incidents.notifications import NotificationConfig, Channel


def settings(*, enabled=False):
    profiles = (profile(max_calls=1), profile(profile_id='reviewer', role='reviewer', max_calls=1))
    calls, providers = [], []
    for selected in profiles:
        async def call(problem, *args, **kwargs):
            calls.append(problem.case_id)
            raise RuntimeError('synthetic unknown result')
        call.profile, call.adapter = selected, adapter()
        providers.append(call)
    return dict(profiles=profiles, providers=tuple(providers), admission=lambda *_: True,
        current_profiles=lambda: profiles, enabled=enabled, clock=lambda: 100,
        budget=lambda _: CaseBudget(100, 130, 2, 1, 0, (('primary', 1), ('reviewer', 1)))), calls


def app(tmp_path, config=None, *, durable=True, resolver=True):
    console = FleetConsole([RobotEndpoint('pinky', 'http://127.0.0.1:8080', 'fixture-token')],
                           [FakeRobot('pinky')])
    task = FleetTaskService(FleetTaskStore(tmp_path / 'fleet.sqlite3'), robot_ids={'pinky'}) if durable else None
    return create_app(console, task_service=task, start_task_dispatcher=False,
        stuck_resolver_clients={} if resolver else None, incident_model_config=config)


def poll(application, *, stuck='case-1'):
    board = application.state.line_stuck
    board._wall = lambda: 100
    snapshot = {'robots': [row(100, stuck_id=stuck)]}
    board.observe(snapshot['robots']); board.flush()
    return snapshot


def test_app_without_model_configuration_preserves_no_worker(tmp_path):
    assert app(tmp_path).state.stuck_resolver.incident_worker is None


def test_root_factory_binds_existing_submission_owner_without_default_approval(tmp_path):
    config, calls = settings()
    config.update(recovery_enabled=True, operating=dict(grant_id='line-back', trusted=lambda: {}, evidence=lambda _: None))
    application = app(tmp_path, config)
    loop = application.state.stuck_resolver
    worker = loop.incident_worker
    assert loop.operating_state.store is worker.store
    assert worker.recovery_submit.__self__ is loop
    assert worker.recovery_submit.__func__ is loop._model_answer.__func__
    assert loop.operating_state.epoch() == 0 and calls == []
    with pytest.raises(ValueError): loop.operating_state.grant('line-back')


@pytest.mark.parametrize('missing', ['journal', 'resolver'])
def test_runtime_configuration_requires_existing_journal_and_loop(tmp_path, missing):
    config, _ = settings()
    with pytest.raises(ValueError):
        app(tmp_path, config, durable=missing != 'journal', resolver=missing != 'resolver')


def test_explicit_configuration_is_disabled_by_default_and_uses_the_fleet_journal(tmp_path):
    async def run():
        config, calls = settings()
        application = app(tmp_path, config)
        worker = application.state.stuck_resolver.incident_worker
        assert worker.store.path == application.state.line_stuck._log.path
        worker.feed(poll(application))
        await settled(worker)
        assert calls == [] and worker.store.active_scopes() == ()
        await worker.aclose()
    asyncio.run(run())


@pytest.mark.parametrize('ownership', ['named', 'resolver'])
def test_live_human_ownership_prevents_model_call(tmp_path, ownership):
    async def run():
        config, calls = settings(enabled=True)
        application = app(tmp_path, config)
        snapshot = poll(application)
        board = application.state.line_stuck
        if ownership == 'named':
            board._log.handoff.claim('pinky', 'case-1', board.judgment_view('pinky'), 'fixture-reviewer', now=100)
        else:
            application.state.stuck_resolver._resolver.claim('pinky', 'case-1')
        worker = application.state.stuck_resolver.incident_worker
        worker.feed(snapshot); await settled(worker)
        assert calls == []
        await worker.aclose()
    asyncio.run(run())


def test_unknown_model_result_queues_final_review_in_same_journal_without_claim(tmp_path):
    async def run():
        config, calls = settings(enabled=True)
        application = app(tmp_path, config)
        board = application.state.line_stuck
        board._log.notifications.config = NotificationConfig('https://fleet.example/console',
            (Channel('discord', 'https://discord.com/api/webhooks/123/fake-unit-token'),))
        worker = application.state.stuck_resolver.incident_worker
        worker.feed(poll(application)); await settled(worker)
        assert calls == ['case-1']
        assert [item['kind'] for item in board._log.notifications.rows()] == ['FINAL_REVIEW']
        assert board._log.handoff.active() == []
        await worker.aclose()
    asyncio.run(run())
