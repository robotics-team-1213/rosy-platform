"""Independent review preserves scope and stops without creating execution authority."""
import asyncio
from dataclasses import replace
import importlib
import importlib.util

import pytest

from rosy.decision.deliberation import Problem
from rosy.decision.deliberation.profiles import AdapterCapabilities, ModelProfile


def api():
    name = 'rosy.decision.deliberation.cooperation'
    assert importlib.util.find_spec(name) is not None, 'conditional cooperation is missing'
    return importlib.import_module(name)


def problem(**changes):
    return replace(Problem('pinky', 'lane-1', 'g1', 'line_follow', 100.0,
        ('core-1',), ('reobserve', 'human'), 'INTERVENE', facts_json='{"state":"blocked"}',
        fleet_choice='human'), **changes)


def reply(request, choice='reobserve', objections=()):
    return dict(subject_id=request.subject_id, case_id=request.case_id, generation=request.generation,
        input_hash=request.digest, choice=choice, evidence_ids=['core-1'], objections=list(objections))


def test_trigger_requires_scoped_valid_opinion_and_preserves_safety():
    m, request = api(), problem()
    assert m.cooperation_trigger(request, reply(request)) == 'baseline_disagreement'
    assert m.cooperation_trigger(request, reply(request, 'human')) is None
    assert m.cooperation_trigger(request, reply(request, objections=['unsafe'])) is None
    assert m.cooperation_trigger(request, reply(request, objections=['conflict'])) == 'conflict'
    assert m.cooperation_trigger(request, reply(request, objections=['insufficient_evidence'])) == 'insufficient_evidence'
    assert m.cooperation_trigger(replace(request, necessity='DO_NOT_INTERVENE'), {}) is None
    with pytest.raises(ValueError): m.cooperation_trigger(request, reply(replace(request, generation='g2')))


def test_review_request_is_immutable_scoped_and_contains_readable_facts():
    m, request = api(), problem()
    review = m.ReviewRequest(request, 'critique', 'baseline_disagreement')
    assert review.body()['problem']['facts_json'] == '{"state":"blocked"}'
    assert review.body()['prior'] == []
    with pytest.raises(ValueError): m.ReviewRequest(request, 'controller', 'conflict')
    with pytest.raises(ValueError): m.ReviewRequest(request, 'critique', 'timeout')
    with pytest.raises(ValueError): m.ReviewRequest(replace(request, facts_json='{"state":"unknown"}'), 'critique', 'conflict')


class Exchange:
    def __init__(self, gate=None, choice='reobserve', *, fail=False, change=None):
        self.calls, self.cancelled = [], []
        self.gate, self.choice, self.fail, self.change = gate, choice, fail, change

    async def __call__(self, body, remaining, *, budget_usd):
        self.calls.append(body)
        if self.gate is not None: await self.gate.wait()
        if self.change is not None: self.change()
        if self.fail: raise OSError('unavailable')
        p = body['problem']
        return dict(request_hash=body['request_hash'], profile_key=body['profile_key'], cost_usd=0.01,
            opinion=dict(subject_id=p['subject_id'], case_id=p['case_id'], generation=p['generation'],
                input_hash=p['input_hash'], choice=self.choice, evidence_ids=['core-1'], objections=[]))

    async def cancel(self, call_id):
        self.cancelled.append(call_id)
        return True


def providers(exchanges=None):
    m = api()
    exchanges = exchanges or (Exchange(), Exchange())
    result = []
    for name, role, exchange in zip(('a', 'b'), ('primary', 'reviewer'), exchanges):
        profile = ModelProfile(name, 'r1', role, 'local', name, 'model-r1', 'review-v1',
            ('line_follow',), ('text',), 2, 16384, 1, 0.04)
        adapter = AdapterCapabilities('local', name, 'model-r1', 'review-v1', 2,
            ('line_follow',), ('text',), True, True, True)
        result.append(m.CooperationProvider(profile, adapter, exchange, prompt_revision='prompt-r1'))
    return result


class Admission:
    def __init__(self, reject_parallel=False):
        self.reservations, self.released = [], []
        self.reject_parallel = reject_parallel

    async def reserve(self, keys, revision):
        self.reservations.append(keys)
        return None if self.reject_parallel and len(keys) == 2 else 'slot-' + str(len(self.reservations))

    async def release(self, token):
        self.released.append(token)
        return True


def supervisor(ports, *, mode='auto', admission=None, primary=None, environment=None, clock=lambda: 101):
    schedule = importlib.import_module('rosy.decision.deliberation.cooperation_schedule')
    keys = tuple(p.profile_key for p in ports)
    return api().CooperationSupervisor(primary=primary or reply(problem()), primary_cost_usd=0.01,
        mode=mode, admission=admission or Admission(),
        environment=environment or (lambda: schedule.ExecutionEnvironment('env-1', 104, True, True)),
        measurements=schedule.ExecutionMeasurements('measure-1', keys, 104, 0.3, 0.1, (0.04, 0.04), 0.05, True),
        clock=clock, timeout_s=1.0, max_cost_usd=0.1)


@pytest.mark.parametrize('mode', ['sequential', 'parallel', 'auto'])
def test_two_independent_roles_agree_without_execution_authority(mode):
    ports = providers()
    result = asyncio.run(supervisor(ports, mode=mode).run(problem(), ports, current=lambda: True))
    assert result['state'] == 'CANDIDATE' and result['choice'] == 'reobserve'
    assert result['action_admissible'] is False
    assert result['calls'] == 2 and result['total_calls'] == 3
    assert result['cost_usd'] == pytest.approx(0.03)
    bodies = [p.exchange.calls[0] for p in ports]
    assert [b['role'] for b in bodies] == ['proposal', 'critique']
    assert all(b['prior'] == [] and b['problem']['input_hash'] == problem().digest for b in bodies)


def test_parallel_enters_both_providers_before_either_finishes():
    async def scenario():
        gate = asyncio.Event()
        ports = providers((Exchange(gate), Exchange(gate)))
        task = asyncio.create_task(supervisor(ports, mode='parallel').run(problem(), ports, current=lambda: True))
        for _ in range(30):
            if all(p.exchange.calls for p in ports): break
            await asyncio.sleep(0)
        entered = [len(p.exchange.calls) for p in ports]
        gate.set()
        result = await task
        assert entered == [1, 1]
        assert result['state'] == 'CANDIDATE'
    asyncio.run(scenario())


def test_sequential_does_not_enter_second_provider_early():
    async def scenario():
        gate = asyncio.Event()
        ports = providers((Exchange(gate), Exchange()))
        task = asyncio.create_task(supervisor(ports, mode='sequential').run(problem(), ports, current=lambda: True))
        for _ in range(30):
            if ports[0].exchange.calls: break
            await asyncio.sleep(0)
        assert ports[0].exchange.calls and not ports[1].exchange.calls
        gate.set()
        assert (await task)['state'] == 'CANDIDATE'
    asyncio.run(scenario())


def test_auto_falls_back_only_before_dispatch_and_forced_parallel_does_not():
    for mode, want, counts in [('auto', 'CANDIDATE', [1, 1]), ('parallel', 'HOLD', [0, 0])]:
        admission = Admission(reject_parallel=True)
        ports = providers()
        result = asyncio.run(supervisor(ports, mode=mode, admission=admission).run(problem(), ports, current=lambda: True))
        assert result['state'] == want
        assert [len(p.exchange.calls) for p in ports] == counts
        if mode == 'auto': assert result['effective_mode'] == 'sequential'


def test_failed_first_sequential_call_is_unknown_and_does_not_retry():
    admission, ports = Admission(), providers((Exchange(fail=True), Exchange()))
    result = asyncio.run(supervisor(ports, mode='sequential', admission=admission).run(problem(), ports, current=lambda: True))
    assert result['state'] == 'HOLD' and result['cost_complete'] is False
    assert result['cost_usd'] is None and result['calls'] == 1
    assert not ports[1].exchange.calls
    assert len(ports[0].exchange.cancelled) == 1


def test_current_change_during_call_blocks_candidate_and_second_sequential_call():
    current = [True]
    ports = providers((Exchange(change=lambda: current.__setitem__(0, False)), Exchange()))
    result = asyncio.run(supervisor(ports, mode='sequential').run(problem(), ports, current=lambda: current[0]))
    assert result['state'] == 'HOLD' and result['choice'] is None
    assert not ports[1].exchange.calls


def test_no_review_for_normal_or_matching_primary_or_unsafe():
    for request, primary in [(replace(problem(), necessity='DO_NOT_INTERVENE'), {}),
        (problem(), reply(problem(), 'human')), (problem(), reply(problem(), objections=['unsafe']))]:
        ports = providers()
        result = asyncio.run(supervisor(ports, primary=primary).run(request, ports, current=lambda: True))
        assert result['calls'] == 0 and result['action_admissible'] is False
        assert not any(p.exchange.calls for p in ports)


def test_changed_provider_response_binding_is_rejected():
    class Wrong(Exchange):
        async def __call__(self, *args, **kwargs):
            response = await super().__call__(*args, **kwargs)
            response['request_hash'] = 'other'
            return response
    ports = providers((Wrong(), Exchange()))
    result = asyncio.run(supervisor(ports, mode='sequential').run(problem(), ports, current=lambda: True))
    assert result['state'] == 'HOLD' and result['calls'] == 1
    assert not ports[1].exchange.calls


def test_journal_keeps_mode_and_profile_policy_fences(tmp_path):
    from fleet.server.deliberation_journal import DeliberationJournal
    ports, journal = providers(), DeliberationJournal(tmp_path / 'fleet.db')
    request = problem()
    first = asyncio.run(journal.run(request, supervisor(ports, mode='sequential'), ports, current=lambda: True))
    again = asyncio.run(journal.run(request, supervisor(ports, mode='sequential'), ports, current=lambda: True))
    changed = asyncio.run(journal.run(request, supervisor(ports, mode='parallel'), ports, current=lambda: True))
    assert first == again and first['state'] == 'CANDIDATE'
    assert changed['state'] == 'HOLD' and changed['reason'] == 'EVALUATION_CONFIGURATION_CHANGED'
    assert [len(p.exchange.calls) for p in ports] == [1, 1]
    ports[0].prompt_revision = 'prompt-r2'
    changed_profile = asyncio.run(journal.run(request, supervisor(ports, mode='sequential'), ports, current=lambda: True))
    assert changed_profile['state'] == 'HOLD'
    assert [len(p.exchange.calls) for p in ports] == [1, 1]


def test_journal_restart_after_dispatch_never_replays(tmp_path):
    from fleet.server.deliberation_journal import DeliberationJournal
    async def scenario():
        gate, journal = asyncio.Event(), DeliberationJournal(tmp_path / 'fleet.db')
        ports = providers((Exchange(gate), Exchange(gate)))
        task = asyncio.create_task(journal.run(problem(), supervisor(ports), ports, current=lambda: True))
        for _ in range(500):
            if any(p.exchange.calls for p in ports): break
            await asyncio.sleep(0.001)
        assert any(p.exchange.calls for p in ports)
        task.cancel()
        with pytest.raises(asyncio.CancelledError): await task
        restarted = await journal.run(problem(), supervisor(ports), ports, current=lambda: True)
        assert restarted['state'] == 'HOLD'
        assert restarted['reason'] == 'RESTART_OR_INFLIGHT_UNKNOWN'
        assert sum(len(p.exchange.calls) for p in ports) >= 1
    asyncio.run(scenario())


def test_readable_case_adapter_can_use_cooperation_without_new_execution_path(tmp_path):
    from fleet.server.deliberation_journal import DeliberationJournal
    from fleet.server.incident_deliberation import run_line_judgment, FleetBaseline
    from test_incident_deliberation import judgment
    assessment = judgment()
    ports = providers()
    baseline = FleetBaseline.from_assessment(assessment, 'human')
    # The adapter owns the canonical Problem; derive it from the same immutable Assessment.
    request = Problem(assessment.request.subject_id, assessment.request.case_id, assessment.request.revision,
        'line_follow', min(e.observed_at for e in assessment.request.evidence),
        tuple(e.reference for e in assessment.request.evidence), ('reobserve', 'human'), 'INTERVENE',
        facts_json='{"state":"blocked"}', fleet_choice='human')
    for port in ports:
        class BoundExchange(Exchange):
            async def __call__(self, body, remaining, *, budget_usd):
                response = await super().__call__(body, remaining, budget_usd=budget_usd)
                response['opinion']['evidence_ids'] = list(request.evidence_ids)
                return response
        port.exchange = BoundExchange()
    result = asyncio.run(run_line_judgment(assessment, DeliberationJournal(tmp_path / 'fleet.db'),
        supervisor(ports, primary={**reply(request), 'evidence_ids': list(request.evidence_ids)}), ports,
        current=lambda: assessment, baseline=baseline, current_baseline=lambda: baseline))
    assert result['state'] == 'CANDIDATE' and result['action_admissible'] is False


def test_reuse_calls_only_missing_role_with_its_own_budget():
    async def scenario():
        ports = providers()
        review = api().ReviewRequest(problem(), 'proposal', 'baseline_disagreement')
        previous = await ports[0](review, 1, budget_usd=0.04)
        runner = supervisor(ports)
        runner.reused, runner.max_cost_usd = previous, 0.06
        result = await runner.run(problem(), ports, current=lambda: True)
        assert result['state'] == 'CANDIDATE'
        assert result['calls'] == 1 and result['total_calls'] == 2
        assert [len(p.exchange.calls) for p in ports] == [1, 1]
        assert len(result['opinions']) == 2 and result['reused'] is True
    asyncio.run(scenario())


def test_environment_expiration_after_resource_reservation_prevents_dispatch():
    schedule = importlib.import_module('rosy.decision.deliberation.cooperation_schedule')
    now = [101.0]
    class Expiring(Admission):
        async def reserve(self, *args):
            token = await super().reserve(*args)
            now[0] = 102.0
            return token
    ports = providers()
    result = asyncio.run(supervisor(ports, admission=Expiring(), clock=lambda: now[0],
        environment=lambda: schedule.ExecutionEnvironment('env-1', 101.5, True, True)).run(
            problem(), ports, current=lambda: True))
    assert result['state'] == 'HOLD'
    assert not any(p.exchange.calls for p in ports)


def test_measurement_expiration_during_reservation_prevents_dispatch():
    now = [101.0]
    class Expiring(Admission):
        async def reserve(self, *args):
            token = await super().reserve(*args)
            now[0] = 101.5
            return token
    ports = providers()
    runner = supervisor(ports, admission=Expiring(), clock=lambda: now[0])
    runner.measurements = replace(runner.measurements, expires_at=101.25)
    result = asyncio.run(runner.run(problem(), ports, current=lambda: True))
    assert result['state'] == 'HOLD'
    assert not any(p.exchange.calls for p in ports)


def test_reused_opinion_must_equal_the_paid_triggering_primary():
    async def scenario():
        ports = providers((Exchange(choice='human'), Exchange(choice='human')))
        review = api().ReviewRequest(problem(), 'proposal', 'baseline_disagreement')
        previous = await ports[0](review, 1, budget_usd=0.04)
        runner = supervisor(ports)
        runner.reused = previous
        result = await runner.run(problem(), ports, current=lambda: True)
        assert result['state'] == 'HOLD'
        assert not ports[1].exchange.calls
    asyncio.run(scenario())


def test_stalled_resource_release_cannot_hang_the_journal():
    async def scenario():
        class Stalled(Admission):
            async def release(self, token):
                await asyncio.Event().wait()
        ports = providers()
        result = await asyncio.wait_for(supervisor(ports, mode='sequential', admission=Stalled()).run(
            problem(), ports, current=lambda: True), 0.8)
        assert result['state'] == 'HOLD'
        assert not ports[1].exchange.calls
    asyncio.run(scenario())


def test_cancel_uses_the_original_call_id_when_provider_revision_changes():
    ports = providers()
    ports[0].exchange.change = lambda: setattr(ports[0], 'prompt_revision', 'changed')
    result = asyncio.run(supervisor(ports, mode='sequential').run(problem(), ports, current=lambda: True))
    assert result['state'] == 'HOLD'
    assert ports[0].exchange.cancelled == [ports[0].exchange.calls[0]['call_id']]


def test_fallback_retains_original_selection_inputs():
    ports, admission = providers(), Admission(reject_parallel=True)
    result = asyncio.run(supervisor(ports, admission=admission).run(problem(), ports, current=lambda: True))
    assert result['state'] == 'CANDIDATE'
    assert result['initial_decision_inputs']['mode'] == 'parallel'
    assert result['decision_inputs']['mode'] == 'sequential'
