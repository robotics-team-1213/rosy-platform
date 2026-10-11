import asyncio
from dataclasses import replace
from datetime import datetime, timezone

import pytest

from fleet.incidents.automation.worker import IncidentCaseWorker
from fleet.incidents.automation.store import CaseBudget, IncidentCaseStore
from fleet.incidents.automation.observation import IncidentObservationPort
from fleet.stuck.board import LineStuckBoard
from fleet.stuck.reports import LineStuckAnswerLog
from rosy.decision.deliberation.judgment import judgment
from test_judgment_profiles import profile, adapter
from test_model_judgment import payload


def setup(tmp_path, *, admitted=True, change=None, budget_calls=4, provider_hook=None):
    now, seen, handoffs = [101.0], [], []
    log = LineStuckAnswerLog(tmp_path / 'fleet.db')
    board = LineStuckBoard(log=log, clock=lambda: now[0], wall=lambda: now[0])
    profiles = (profile(max_calls=8), profile(profile_id='model-reviewer', role='reviewer', max_calls=8))
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
        return raw, 0.0
    providers = []
    for selected in profiles:
        async def call(*args, **kwargs): return await provider(*args, **kwargs)
        call.profile, call.adapter = selected, adapter()
        providers.append(call)
    store = IncidentCaseStore(log.path, clock=lambda: now[0])
    def budget(scope): return CaseBudget(now[0], now[0] + 30, budget_calls, 4, 0,
                                       tuple((p.role, p.max_calls) for p in profiles))
    async def handoff(scope, summary): handoffs.append((scope, summary))
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
        _, seen, _, _, _, store, worker, poll, _ = setup(tmp_path, admitted=False)
        for seq in range(20): worker.feed(poll(seq, normal=True))
        await settled(worker)
        assert seen == [] and store.active_scopes() == ()
        await worker.aclose()
    asyncio.run(run())


def test_new_poll_only_observation_and_persistent_aggregate_counts(tmp_path):
    async def run():
        now, seen, handoffs, _, _, store, worker, poll, _ = setup(tmp_path)
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
        _, seen, handoffs, _, _, store, worker, poll, _ = setup(tmp_path, change=change)
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
        now, seen, handoffs, log, _, _, worker, poll, _ = setup(tmp_path, budget_calls=1)
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
        now, seen, handoffs, _, _, store, worker, poll, _ = setup(tmp_path)
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
        now, seen, handoffs, _, _, store, worker, poll, current = setup(tmp_path)
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
        _, seen, handoffs, _, _, store, worker, poll, _ = setup(tmp_path, provider_hook=hang)
        worker.feed(poll()); await entered.wait()
        scope = store.active_scopes()[0]
        await worker.aclose()
        assert store.case(scope)['state'] == 'HOLD'
        assert len(handoffs) == 1 and handoffs[0][1]['reason'] == 'WORKER_CANCELLED'
        worker.feed(poll()); await settled(worker)
        assert len(seen) == 1
    asyncio.run(run())


def test_prepare_receipt_shares_transaction_and_does_not_reset_parent(tmp_path):
    _, _, _, log, board, store, worker, poll, _ = setup(tmp_path)
    poll()
    with log._connect() as conn:
        conn.execute('BEGIN IMMEDIATE')
        assert worker.prepare_receipt(conn, board.judgment_view('pinky')) is True
        scope = store.active_scopes()[0]
        assert worker.prepare_receipt(conn, board.judgment_view('pinky')) is True
        conn.rollback()
    assert store.active_scopes() == ()


def test_active_foreign_worker_is_not_recovered_or_replayed_automatically(tmp_path):
    async def run():
        _, seen, handoffs, log, board, store, worker, poll, _ = setup(tmp_path)
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
    asyncio.run(run())


@pytest.mark.parametrize('fault', ['replaced', 'left_roster', 'restart', 'stale_normal'])
def test_non_clearance_closures_never_become_observed_resolution(tmp_path, fault):
    async def run():
        now, _, _, log, board, store, worker, poll, _ = setup(tmp_path)
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
