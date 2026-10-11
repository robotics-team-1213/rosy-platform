"""Record actual choices without replaying a selector or granting model authority."""
import asyncio
from dataclasses import replace

import pytest
from fleet.stuck.board import LineStuckBoard
from fleet.stuck.loop import StuckResolverLoop
from fleet.stuck.reports import LineStuckAnswerLog
from fleet.stuck.resolver import StuckResolver, ResolverConfig, Answer
from fleet.stuck import pipeline
from test_judgment_receipts import row


def make_loop(tmp_path, *, normal=False, autonomous=False):
    from fleet.observe.rules import RuleSelectionStore
    source = row(100, stuck_id='case-1')
    if normal:
        source['state']['line_follow'] = {'mode': 'OFF', 'stuck': None}
    else:
        source['state']['line_follow']['stuck']['cause'] = 'unsupported-cause'
    board = LineStuckBoard(clock=lambda: 10, wall=lambda: 100,
                           log=LineStuckAnswerLog(tmp_path / 'fleet.db'))
    async def snapshot():
        board.observe([source])
        return {'robots': [source]}
    resolver = StuckResolver(ResolverConfig())
    resolver.autonomous_robots = frozenset({'pinky'} if autonomous else ())
    loop = StuckResolverLoop(snapshot, board, resolver, clients=lambda: {}, clock=lambda: 10)
    assert isinstance(loop.rule_selections, RuleSelectionStore)
    return loop, source


@pytest.mark.parametrize('normal,autonomous,kind,choice', [
    (True, False, 'NONE', None), (False, True, 'HOLD', 'reobserve'),
    (False, False, 'HANDOFF', 'human'),
])
def test_actual_selector_result_is_recorded_once_without_model_or_command_claims(tmp_path, normal, autonomous, kind, choice):
    loop, _ = make_loop(tmp_path, normal=normal, autonomous=autonomous)
    original, calls = loop._resolver.step, []
    def select(now, rows):
        calls.append(now)
        return original(now, rows)
    loop._resolver.step = select
    asyncio.run(loop.run_once())
    records = loop.rule_selections.read()
    assert calls == [10] and len(records) == 1
    receipt = records[0]['receipt']
    assert receipt['selection']['kind'] == kind and receipt['strategy'] == 'RULE_ONLY'
    assert receipt['verification'] == 'selected_not_executed' and receipt['action_admissible'] is False
    assert receipt['outcome'] is None and 'timestamp' not in str(receipt['selection'])
    assessment = loop._board.intervention_assessment('pinky')
    baseline = loop.rule_baseline(assessment)
    assert (baseline.choice if baseline is not None else None) == choice
    assert loop.rule_baseline(replace(assessment, request=replace(assessment.request, case_id='other'))) is None


def test_physical_answer_is_not_reobserve_and_stale_is_not_a_baseline(tmp_path):
    loop, _ = make_loop(tmp_path, autonomous=True)
    asyncio.run(loop.run_once())
    assessment = loop._board.intervention_assessment('pinky')
    physical = pipeline.selection_receipt(assessment, Answer('pinky', 'case-1', 'BACK_AND_RETRY', 'R3'),
                                         source_sha256='a'*64, config_sha256='b'*64, mixed=False)
    loop._rule_selections['pinky'] = physical
    assert loop.rule_baseline(assessment) is None
    asyncio.run(loop.run_once())
    loop._board._wall = lambda: 104
    assert loop.rule_baseline(loop._board.intervention_assessment('pinky')) is None


def test_ai_input_is_mixed_and_recording_failure_clears_the_current_baseline(tmp_path):
    loop, source = make_loop(tmp_path, autonomous=True)
    source['ai_facts'] = [{'kind': 'obstacle'}]
    asyncio.run(loop.run_once())
    assert loop.rule_selections.read()[0]['receipt']['strategy'] == 'MIXED'
    assert loop.rule_baseline(loop._board.intervention_assessment('pinky')) is None
    source.pop('ai_facts')
    loop.rule_selections.append_batch = lambda *_args, **_kwargs: (_ for _ in ()).throw(OSError('synthetic storage failure'))
    asyncio.run(loop.run_once())
    assert loop._rule_selections == {}


def test_rule_store_validates_hashes_kinds_and_keeps_retention(tmp_path):
    from fleet.observe.rules import RuleSelectionStore
    loop, _ = make_loop(tmp_path, autonomous=True)
    asyncio.run(loop.run_once())
    receipt = loop.rule_selections.read()[0]['receipt']
    store = RuleSelectionStore(tmp_path / 'retained.db', max_rows=1, retention_s=2)
    store.append_batch([receipt], now=100)
    store.append_batch([receipt], now=101)
    records = store.read()
    assert len(records) == 1 and len(records[0]['sha256']) == 64
    for changes in ({'source_sha256': 'invalid'}, {'action_admissible': True}, {'outcome': 'success'}):
        with pytest.raises(ValueError): store.append_batch([{**receipt, **changes}], now=101)
    with pytest.raises(ValueError): store.append_batch([receipt, receipt], now=101)
    assert len(store.read()) == 1


def test_disabled_ai_first_is_not_mixed_and_default_factory_uses_actual_selection(tmp_path):
    from fleet.stuck.ai_first import AiFirst
    loop, _ = make_loop(tmp_path, autonomous=True)
    loop._resolver.ai_first = AiFirst()
    asyncio.run(loop.run_once())
    assert loop.rule_selections.read()[0]['receipt']['strategy'] == 'RULE_ONLY'
    assert loop.rule_baseline(loop._board.intervention_assessment('pinky')).choice == 'reobserve'
    from test_incident_runtime import app, settings
    config, _ = settings()
    application = app(tmp_path / 'runtime', config)
    actual = application.state.stuck_resolver
    assert actual.incident_worker.baseline == actual.rule_baseline
    custom = lambda _: None
    application = app(tmp_path / 'custom', {**config, 'baseline': custom})
    assert application.state.stuck_resolver.incident_worker.baseline is custom


def test_claim_during_journal_await_preserves_human_ownership(tmp_path):
    async def run():
        loop, _ = make_loop(tmp_path, autonomous=True)
        original, running = loop.rule_selections.append_batch, asyncio.get_running_loop()
        def append(receipts, **kwargs):
            running.call_soon_threadsafe(loop.claim, 'pinky', 'case-1')
            return original(receipts, **kwargs)
        loop.rule_selections.append_batch = append
        await loop.run_once()
        assert loop._board.resolver_note('pinky', 'case-1')['tier'] == 'human'
        assert loop.rule_baseline(loop._board.intervention_assessment('pinky')) is None
    asyncio.run(run())


def test_rule_contract_and_storage_reject_malformed_or_impossible_receipts(tmp_path):
    from copy import deepcopy
    from rosy.contracts.learning.incident_rule import validate_rule
    from fleet.observe.rules import RuleSelectionStore
    loop, _ = make_loop(tmp_path, autonomous=True)
    asyncio.run(loop.run_once())
    receipt = loop.rule_selections.read()[0]['receipt']
    for path, value in [('schema', 'other'), ('strategy', []), ('source_sha256', 'g'*64),
                         ('assessment.evaluated_at', float('nan')), ('assessment.request.extra', True),
                         ('selection.kind', 'UNKNOWN'), ('selection.yield_m', 1),
                         ('selection.reason', '-----BEGIN PRIVATE KEY-----')]:
        changed = deepcopy(receipt)
        target, *_, = [changed]
        keys = path.split('.')
        for key in keys[:-1]: target = target[key]
        target[keys[-1]] = value
        with pytest.raises(ValueError): validate_rule(changed)
    for maximum in (True, 0, -1, 100_001):
        with pytest.raises(ValueError): RuleSelectionStore(tmp_path / 'invalid.db', max_rows=maximum)
