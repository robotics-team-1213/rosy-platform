import asyncio
from dataclasses import replace
from datetime import datetime, timezone

import pytest
import threading

from fleet.incidents.automation.worker import IncidentCaseWorker
from fleet.incidents.automation.store import CaseBudget, IncidentCaseStore
from fleet.incidents.automation.observation import IncidentObservationPort
from fleet.stuck.board import LineStuckBoard
from fleet.stuck.reports import LineStuckAnswerLog
from rosy.decision.deliberation.judgment import judgment
from test_judgment_profiles import profile, adapter
from test_model_judgment import payload


def make_incident_worker(tmp_path, *, admitted=True, change=None, budget_calls=4, budget_observations=4,
          provider_hook=None, handoff_hook=None, provider_cost=0.0):
    now, seen, handoffs = [101.0], [], []
    log = LineStuckAnswerLog(tmp_path / 'fleet.db')
    board = LineStuckBoard(log=log, clock=lambda: now[0], wall=lambda: now[0])
    cap = .1 if provider_cost else 0
    profiles = (profile(max_calls=8, max_cost_usd=cap),
                profile(profile_id='model-reviewer', role='reviewer', max_calls=8, max_cost_usd=cap))
    current = [profiles]
    human = [False]
    async def provider(p, bound, prior, remaining, **kwargs):
        seen.append((p, bound, prior))
        if provider_hook is not None: await provider_hook(p)
        raw = payload(p)
        raw['evidence_ids'] = list(p.evidence_ids)
        for key in ('next_step', 'success_check'):
            raw[key]['evidence_ids'] = list(p.evidence_ids)
        if change == 'conflict': raw['objections'] = ['conflict']
        if change == 'unsafe': raw['objections'] = ['unsafe']
        if change == 'invalid' and len(seen) == 1: raw['case_id'] = 'foreign'
        if change == 'unknown': raise RuntimeError('private provider error')
        if change == 'human': human[0] = True
        return raw, provider_cost
    providers = []
    for selected in profiles:
        async def call(*args, **kwargs): return await provider(*args, **kwargs)
        call.profile, call.adapter = selected, adapter()
        providers.append(call)
    store = IncidentCaseStore(log.path, clock=lambda: now[0])
    def budget(scope): return CaseBudget(now[0], now[0] + 30, budget_calls, budget_observations, .3 if provider_cost else 0,
                                       tuple((p.role, p.max_calls) for p in profiles))
    async def handoff(scope, summary):
        handoffs.append((scope, summary))
        return True if handoff_hook is None else await handoff_hook(scope, summary)
    worker = IncidentCaseWorker(store, IncidentObservationPort(board, human_owned=lambda *_: human[0], clock=lambda: now[0]),
        board, profiles=profiles, providers=tuple(providers), admission=lambda *_: admitted,
        current_profiles=lambda: current[0], human_owned=lambda *_: human[0], budget=budget,
        final_handoff=handoff, clock=lambda: now[0], enabled=admitted)
    def poll(seq=1, *, normal=False, case='lane-1'):
        row = dict(robot_id='pinky', online=True, state_age_s=1,
            state=dict(seq=seq, timestamp=datetime.fromtimestamp(now[0] - 1, timezone.utc).isoformat(),
                line_follow=dict(mode='OFF' if normal else 'CAMERA_LINE',
                    stuck=None if normal else dict(stuck_id=case, phase='ASKING'))))
        board.observe([row]); board.flush()
        return {'robots': [row]}
    return now, seen, handoffs, log, board, store, worker, poll, current


async def settled(worker):
    for _ in range(200):
        await asyncio.sleep(.002)
        if worker.idle: return
    raise AssertionError('worker did not become idle')


def test_normal_and_unadmitted_have_no_model_calls_or_nominal_case_flood(tmp_path):
    async def run():
        _, seen, _, _, _, store, worker, poll, _ = make_incident_worker(tmp_path, admitted=False)
        for seq in range(20): worker.feed(poll(seq, normal=True))
        await settled(worker)
        assert seen == [] and store.active_scopes() == ()
        await worker.aclose()
    asyncio.run(run())


def test_new_poll_only_observation_and_persistent_aggregate_counts(tmp_path):
    async def run():
        now, seen, handoffs, _, _, store, worker, poll, _ = make_incident_worker(tmp_path)
        first = poll(); worker.feed(first); await settled(worker)
        assert len(seen) == 1 and handoffs == []
        scope = store.active_scopes()[0]
        worker.feed(first); await settled(worker)
        assert store.case(scope)['observations'] == 0 and len(seen) == 1
        now[0] += 1; worker.feed(poll(2)); await settled(worker)
        case = store.case(scope)
        assert case['calls'] == 2 and case['observations'] == 1
        assert case['started_at'] == 101 and case['deadline'] == 131
        await worker.aclose()
    asyncio.run(run())


@pytest.mark.parametrize('change,expected_calls', [('conflict', 2), ('invalid', 2), ('unsafe', 1), ('unknown', 1), ('human', 1)])
def test_review_is_conditional_unknown_stops_and_human_ownership_cancels(tmp_path, change, expected_calls):
    async def run():
        _, seen, handoffs, _, _, store, worker, poll, _ = make_incident_worker(tmp_path, change=change)
        worker.feed(poll()); await settled(worker)
        assert len(seen) == expected_calls
        if change in {'conflict', 'invalid', 'unsafe'}: assert handoffs == []
        if change == 'unknown':
            scope = handoffs[0][0]
            assert store.case(scope)['state'] == 'HOLD'
            worker.feed(poll()); await settled(worker)
            assert len(seen) == 1 and len(handoffs) == 1
        await worker.aclose()
    asyncio.run(run())


def test_budget_exhaustion_produces_one_final_summary_and_no_named_claim(tmp_path):
    async def run():
        now, seen, handoffs, log, _, _, worker, poll, _ = make_incident_worker(tmp_path, budget_calls=1)
        worker.feed(poll()); await settled(worker)
        assert handoffs == []
        now[0] += 1; worker.feed(poll(2)); await settled(worker)
        worker.feed(poll(2)); await settled(worker)
        assert len(seen) == 1 and len(handoffs) == 1 and log.handoff.active() == []
        assert handoffs[0][1]['reason'] == 'CASE_BUDGET_EXHAUSTED'
        assert handoffs[0][1]['calls'] == 1
        await worker.aclose()
    asyncio.run(run())


def test_cleared_plus_later_normal_is_observed_receipt_without_action_credit(tmp_path):
    async def run():
        now, seen, handoffs, _, _, store, worker, poll, _ = make_incident_worker(tmp_path)
        worker.feed(poll()); await settled(worker)
        scope = store.active_scopes()[0]
        now[0] += 2; worker.feed(poll(2, normal=True)); await settled(worker)
        assert handoffs == [] and len(seen) == 1
        receipt = store.observed_closure(scope)
        assert receipt['state'] == 'RESOLVED_OBSERVED' and receipt['action_credit'] == 'NONE'
        assert store.case(scope)['calls'] == 1
        await worker.aclose()
    asyncio.run(run())


def test_profile_change_holds_original_case_without_budget_reset(tmp_path):
    async def run():
        now, seen, handoffs, _, _, store, worker, poll, current = make_incident_worker(tmp_path)
        worker.feed(poll()); await settled(worker)
        scope = store.active_scopes()[0]
        current[0] = (replace(current[0][0], profile_revision='p2'), current[0][1])
        now[0] += 1; worker.feed(poll(2)); await settled(worker)
        assert len(seen) == 1 and store.case(scope)['state'] == 'HOLD'
        assert handoffs[0][1]['reason'] == 'PROFILE_CHANGED'
        await worker.aclose()
    asyncio.run(run())


def test_cancelled_provider_is_unknown_final_and_cannot_replay(tmp_path):
    async def run():
        entered = asyncio.Event()
        async def hang(_):
            entered.set(); await asyncio.Event().wait()
        _, seen, handoffs, _, _, store, worker, poll, _ = make_incident_worker(tmp_path, provider_hook=hang)
        worker.feed(poll()); await entered.wait()
        scope = store.active_scopes()[0]
        await worker.aclose()
        assert store.case(scope)['state'] == 'HOLD'
        assert len(handoffs) == 1 and handoffs[0][1]['reason'] == 'PROVIDER_OUTCOME_UNKNOWN'
        worker.feed(poll()); await settled(worker)
        assert len(seen) == 1
    asyncio.run(run())


def test_prepare_receipt_shares_transaction_and_does_not_reset_parent(tmp_path):
    _, _, _, log, board, store, worker, poll, _ = make_incident_worker(tmp_path)
    poll()
    with log._connect() as conn:
        conn.execute('BEGIN IMMEDIATE')
        assert worker.prepare_receipt(conn, board.judgment_view('pinky')) is True
        assert worker.prepare_receipt(conn, board.judgment_view('pinky')) is True
        conn.rollback()
    assert store.active_scopes() == ()


def test_active_foreign_worker_is_not_recovered_or_replayed_automatically(tmp_path):
    async def run():
        _, seen, handoffs, log, board, store, worker, poll, _ = make_incident_worker(tmp_path)
        snapshot = poll()
        with log._connect() as conn:
            conn.execute('BEGIN IMMEDIATE')
            assert worker.prepare_receipt(conn, board.judgment_view('pinky'))
            conn.commit()
        scope = store.active_scopes()[0]
        store.reserve(scope, attempt_id='foreign-attempt', input_hash='c' * 64,
                      observation_revision='r1', kind='model', max_cost_usd=0, worker_id='foreign', role='primary')
        store.mark_submitting(scope, 'foreign-attempt', worker_id='foreign')
        worker.feed(snapshot); await settled(worker)
        assert store.attempt(scope, 'foreign-attempt')['state'] == 'SUBMITTING'
        assert seen == [] and handoffs == []
        await worker.aclose()
        assert store.attempt(scope, 'foreign-attempt')['state'] == 'SUBMITTING'
        assert store.case(scope)['state'] == 'ACTIVE' and handoffs == []
    asyncio.run(run())


def test_preparation_rejects_foreign_database_without_writing_parent(tmp_path):
    _, _, _, log, board, store, worker, poll, _ = make_incident_worker(tmp_path)
    poll()
    other = LineStuckAnswerLog(tmp_path / 'other.db')
    IncidentCaseStore(other.path)
    with other._connect() as conn:
        conn.execute('BEGIN IMMEDIATE')
        assert worker.prepare_receipt(conn, board.judgment_view('pinky')) is False
        assert conn.execute('SELECT COUNT(*) FROM fleet_incident_v2_cases').fetchone()[0] == 0
        conn.rollback()
    assert store.active_scopes() == ()


@pytest.mark.parametrize('boundary', ['reserve', 'mark_submitting'])
def test_cancel_during_database_commit_waits_and_closes_only_owned_reservation(tmp_path, boundary):
    async def run():
        _, seen, handoffs, _, _, store, worker, poll, _ = make_incident_worker(tmp_path)
        entered, released = threading.Event(), threading.Event()
        original = getattr(store, boundary)
        def delayed(*args, **kwargs):
            entered.set()
            if not released.wait(3): raise AssertionError('test release missing')
            return original(*args, **kwargs)
        setattr(store, boundary, delayed)
        worker.feed(poll())
        while not entered.is_set(): await asyncio.sleep(.002)
        closer = asyncio.create_task(worker.aclose())
        await asyncio.sleep(.01)
        released.set()
        await closer
        assert seen == [] and len(handoffs) == 1
        case = store.case(handoffs[0][0])
        assert case['state'] == 'HOLD' and case['reserved_micros'] == 0
        with store._transaction() as conn:
            row = conn.execute('SELECT state,actual_micros FROM fleet_incident_v2_attempts').fetchone()
            assert tuple(row) == ('REJECTED', 0)
    asyncio.run(run())


def test_restart_without_read_intent_admission_cannot_skip_observation_budget(tmp_path):
    async def run():
        now, seen, handoffs, _, board, store, worker, poll, _ = make_incident_worker(tmp_path, budget_observations=0)
        worker.feed(poll()); await settled(worker)
        scope = store.active_scopes()[0]
        replacement = IncidentCaseWorker(store, worker.observation, board, profiles=worker.profiles,
            providers=worker.providers, admission=worker.admission, current_profiles=worker.current_profiles,
            human_owned=worker.human_owned, budget=worker.budget, final_handoff=worker.final_handoff,
            clock=worker.clock, enabled=True)
        now[0] += 1; replacement.feed(poll(2)); await settled(replacement)
        assert len(seen) == 1 and store.case(scope)['observations'] == 0
        assert store.case(scope)['state'] == 'HOLD'
        assert handoffs[0][1]['reason'] == 'READ_CONTINUATION_NOT_ADMITTED'
        await replacement.aclose()
        await worker.aclose()
    asyncio.run(run())


def test_unknown_final_has_durable_revision_and_retries_queue_failure_without_model_calls(tmp_path):
    async def run():
        accept = [False]
        async def queue(*_): return accept[0]
        now, seen, handoffs, _, _, store, worker, poll, _ = make_incident_worker(
            tmp_path, change='unknown', handoff_hook=queue)
        worker.feed(poll()); await settled(worker)
        scope = handoffs[0][0]
        assert handoffs[0][1]['observation_revision'] == seen[0][0].generation
        assert store.pending_handoffs() == (scope,)
        accept[0] = True; now[0] += 1
        worker.feed(poll(2)); await settled(worker)
        assert len(seen) == 1 and len(handoffs) == 2
        assert store.pending_handoffs() == ()
        worker.feed(poll(2)); await settled(worker)
        assert len(handoffs) == 2
        await worker.aclose()
    asyncio.run(run())


def test_old_policy_scope_cannot_invoke_new_policy_provider(tmp_path):
    from fleet.incidents.automation.contract import CaseScope
    from fleet.incidents.notifications import Channel, NotificationConfig
    async def run():
        now, seen, _, log, board, store, worker, poll, _ = make_incident_worker(tmp_path)
        snapshot = poll()
        scope = CaseScope('pinky', 'lane-1', 'core', worker.profile_sha256, 'old-policy')
        revision = board.judgment_view('pinky')['request']['revision']
        store.begin_case(scope, worker.budget(scope), initial_revision=revision)
        log.notifications.config = NotificationConfig('https://console.example.test/console',
                                      (Channel('slack', 'https://hooks.slack.com/services/A/B/C'),))
        async def enqueue(scope, summary):
            return await asyncio.to_thread(log.notifications.enqueue_final, scope, summary, now=now[0])
        worker.final_handoff = enqueue
        worker.feed(snapshot); await settled(worker)
        assert seen == [] and store.case(scope)['state'] == 'HOLD'
        assert store.case(scope)['reason'] == 'POLICY_CHANGED'
        assert store.case(scope)['started_at'] == 101
        finals = [row for row in log.notifications.rows() if row['kind'] == 'FINAL_REVIEW']
        assert len(finals) == 1 and finals[0]['state'] == 'PENDING'
        assert store.pending_handoffs() == () and log.handoff.active() == []
        await worker.aclose()
    asyncio.run(run())


@pytest.mark.parametrize('failure', ['unknown', 'budget'])
def test_real_outbox_managed_open_is_suppressed_and_final_is_durably_queued(tmp_path, failure):
    from fleet.incidents.notifications import Channel, NotificationConfig
    async def run():
        now, seen, _, log, _, store, worker, poll, _ = make_incident_worker(
            tmp_path, change='unknown' if failure == 'unknown' else None, budget_calls=1)
        async def enqueue(scope, summary):
            return await asyncio.to_thread(log.notifications.enqueue_final, scope, summary, now=now[0])
        worker.final_handoff = enqueue
        log.notifications.set_automation(worker.prepare_receipt)
        configured = NotificationConfig('https://console.example.test/console',
                                       (Channel('slack', 'https://hooks.slack.com/services/A/B/C'),))
        if failure == 'budget': log.notifications.config = configured
        worker.feed(poll()); await settled(worker)
        assert log.notifications.rows() == []
        if failure == 'unknown': assert len(store.pending_handoffs()) == 1
        log.notifications.config = configured
        now[0] += 1; worker.feed(poll(2)); await settled(worker)
        events = log.notifications.rows()
        assert len(events) == 1 and events[0]['kind'] == 'FINAL_REVIEW'
        assert events[0]['state'] == 'PENDING' and len(seen) == 1
        assert store.pending_handoffs() == () and log.handoff.active() == []
        now[0] += 1; worker.feed(poll(3)); await settled(worker)
        assert len(log.notifications.rows()) == 1 and len(seen) == 1
        await worker.aclose()
    asyncio.run(run())


def test_legacy_poll_does_not_wait_for_model_and_loop_shutdown_cleans_worker(tmp_path):
    from types import SimpleNamespace
    from fleet.stuck.loop import StuckResolverLoop
    async def run():
        entered = asyncio.Event()
        async def hang(_): entered.set(); await asyncio.Event().wait()
        now, _, _, _, board, store, worker, poll, _ = make_incident_worker(tmp_path, provider_hook=hang)
        class Resolver:
            config = SimpleNamespace(poll_s=1)
            ai_verdicts = []
            def step(self, *_): return []
            def is_claimed(self, *_): return False
        async def snapshot(): return poll()
        loop = StuckResolverLoop(snapshot, board, Resolver(), clients=lambda: {}, clock=lambda: now[0],
                                 incident_worker=worker)
        await asyncio.wait_for(loop.run_once(), .5)
        await asyncio.wait_for(entered.wait(), .5)
        await asyncio.wait_for(loop.run_once(), .5)
        running = asyncio.create_task(loop.run())
        await asyncio.sleep(.01); running.cancel()
        await asyncio.gather(running, return_exceptions=True)
        assert worker.idle and len(store.pending_handoffs()) == 0
    asyncio.run(run())


@pytest.mark.parametrize('kind', ['model', 'observation'])
def test_cancel_at_terminal_commit_preserves_known_receipt_and_closes_active_case(tmp_path, kind):
    async def run():
        now, _, handoffs, _, _, store, worker, poll, _ = make_incident_worker(tmp_path)
        entered, released = threading.Event(), threading.Event()
        original = store.complete
        def delayed(*args, **kwargs):
            match = kwargs['summary']['reason'] == ('MODEL_CHECKED' if kind == 'model' else 'NEW_CORE_OBSERVATION')
            if match:
                entered.set()
                if not released.wait(3): raise AssertionError('test release missing')
            return original(*args, **kwargs)
        if kind == 'observation':
            worker.feed(poll()); await settled(worker)
            now[0] += 1
        store.complete = delayed
        worker.feed(poll(2 if kind == 'observation' else 1))
        while not entered.is_set(): await asyncio.sleep(.002)
        closer = asyncio.create_task(worker.aclose())
        await asyncio.sleep(.01); released.set(); await closer
        assert len(handoffs) == 1
        case = store.case(handoffs[0][0])
        assert case['state'] == 'HOLD' and case['spent_micros'] == case['reserved_micros'] == 0
        with store._transaction() as conn:
            rows = conn.execute('SELECT state,actual_micros FROM fleet_incident_v2_attempts').fetchall()
            assert rows and all(tuple(row) == ('COMPLETED', 0) for row in rows)
    asyncio.run(run())


def test_verified_model_receipt_keeps_bounded_judgment_digest_and_scope(tmp_path):
    import json
    async def run():
        _, seen, _, _, _, store, worker, poll, _ = make_incident_worker(tmp_path)
        worker.feed(poll()); await settled(worker)
        with store._transaction() as conn:
            row = conn.execute('SELECT summary_json FROM fleet_incident_v2_attempts WHERE kind=?', ('model',)).fetchone()
            receipt = json.loads(row[0])
        assert receipt['verdict'] == 'reobserve' and receipt['choice'] == 'reobserve'
        assert len(receipt['receipt_sha256']) == 64 and receipt['observation_revision'] == seen[0][0].generation
        assert len(row[0].encode()) <= 1024 and 'alternatives' not in receipt
        await worker.aclose()
    asyncio.run(run())


def test_second_cancellation_does_not_interrupt_durable_shutdown_cleanup(tmp_path):
    async def run():
        _, seen, handoffs, _, _, store, worker, poll, _ = make_incident_worker(tmp_path)
        entered, released = threading.Event(), threading.Event()
        original = store.reserve
        def delayed(*args, **kwargs):
            entered.set()
            if not released.wait(3): raise AssertionError('test release missing')
            return original(*args, **kwargs)
        store.reserve = delayed
        worker.feed(poll())
        while not entered.is_set(): await asyncio.sleep(.002)
        closer = asyncio.create_task(worker.aclose())
        await asyncio.sleep(.01); closer.cancel()
        await asyncio.sleep(.01); closer.cancel()
        released.set()
        result = await asyncio.gather(closer, return_exceptions=True)
        assert isinstance(result[0], asyncio.CancelledError)
        assert seen == [] and len(handoffs) == 1
        assert store.case(handoffs[0][0])['state'] == 'HOLD'
    asyncio.run(run())


@pytest.mark.parametrize('prepared', [False, True])
def test_cancel_before_first_attempt_closes_only_owned_created_case(tmp_path, prepared):
    async def run():
        _, seen, handoffs, log, _, store, worker, poll, _ = make_incident_worker(tmp_path)
        if prepared:
            log.notifications.set_automation(worker.prepare_receipt)
            poll()
            assert len(store.active_scopes()) == 1
            await worker.aclose()
        else:
            entered, released = threading.Event(), threading.Event()
            original = store.begin_case
            def delayed(*args, **kwargs):
                entered.set()
                if not released.wait(3): raise AssertionError('test release missing')
                return original(*args, **kwargs)
            store.begin_case = delayed
            worker.feed(poll())
            while not entered.is_set(): await asyncio.sleep(.002)
            closer = asyncio.create_task(worker.aclose())
            await asyncio.sleep(.01); released.set(); await closer
        assert seen == [] and len(handoffs) == 1
        case = store.case(handoffs[0][0])
        assert case['state'] == 'HOLD' and case['calls'] == case['observations'] == 0
        assert handoffs[0][1]['observation_revision'] is not None
    asyncio.run(run())


def test_stale_model_response_retains_verified_billing_and_does_not_become_current(tmp_path):
    async def run():
        entered, released = asyncio.Event(), asyncio.Event()
        async def delayed(_):
            if not entered.is_set(): entered.set(); await released.wait()
        now, seen, _, _, _, store, worker, poll, _ = make_incident_worker(
            tmp_path, provider_hook=delayed, provider_cost=.05)
        worker.feed(poll()); await entered.wait()
        now[0] += 1; worker.feed(poll(2)); released.set(); await settled(worker)
        assert len(seen) == 2
        scope = store.active_scopes()[0]
        assert store.case(scope)['spent_micros'] == 100000
        with store._transaction() as conn:
            rows = conn.execute('SELECT state,actual_micros,observation_revision FROM fleet_incident_v2_attempts ORDER BY rowid').fetchall()
            assert tuple(rows[0]) == ('REJECTED', 50000, seen[0][0].generation)
            assert tuple(rows[1]) == ('COMPLETED', 50000, seen[1][0].generation)
        await worker.aclose()
    asyncio.run(run())


@pytest.mark.parametrize('fault', ['replaced', 'left_roster', 'restart', 'stale_normal'])
def test_non_clearance_closures_never_become_observed_resolution(tmp_path, fault):
    async def run():
        now, _, _, log, board, store, worker, poll, _ = make_incident_worker(tmp_path)
        worker.feed(poll()); await settled(worker)
        scope = store.active_scopes()[0]
        now[0] += 2
        snapshot = poll(2, normal=True)
        if fault == 'stale_normal': now[0] += 4
        else:
            with log._connect() as conn:
                conn.execute('UPDATE fleet_line_stuck_episodes SET close_reason=? WHERE robot_id=? AND stuck_id=?',
                             (dict(replaced='replaced', left_roster='left_roster', restart='fleet_restart')[fault], 'pinky', 'lane-1'))
                conn.commit()
        worker.feed(snapshot); await settled(worker)
        assert store.observed_closure(scope) is None
        await worker.aclose()
    asyncio.run(run())
