import asyncio

import pytest

from rosy.decision.deliberation.contracts.billing import CallResult
from rosy.decision.deliberation.judgment import judgment
from rosy.decision.deliberation.providers.cost_evidence import project
from rosy.decision.deliberation.providers.versioned_request import prepare_request
from fleet.incidents.automation.ledger.receipt import model_receipt, checked_receipt
from test_incident_model_receipt import fixture
from test_cost_evidence import host_receipt
from test_incident_case_worker import make_incident_worker, settled


def evidence(p, bound, checked):
    _, body = prepare_request(p, bound, (), 2, budget_usd=bound.profile.max_cost_usd)
    return project(p, bound, checked, 0.0, body, host_receipt(p, bound, body, checked.payload))


def test_cost_receipt_v2_keeps_unobserved_charge_separate_from_atomic_zero_marginal(tmp_path):
    scope, p, profiles, bound, checked, attempt = fixture()
    receipt = model_receipt(scope, p, bound, checked, profiles=profiles, cost_evidence=evidence(p, bound, checked))
    value = checked_receipt(scope, attempt, receipt)
    assert value['schema'] == 'rosy.incident.model_receipt/2'
    assert value['cost_evidence']['observed_usd_charge'] is None
    assert value['cost_evidence']['marginal_cash_usd'] == 0
    attempt['actual_micros'] = 1
    with pytest.raises(ValueError): checked_receipt(scope, attempt, receipt)
    assert checked_receipt(scope, {**attempt, 'actual_micros': 0},
                           model_receipt(scope, p, bound, checked, profiles=profiles))['schema'].endswith('/1')


@pytest.mark.parametrize('failed', [False, True])
def test_actual_worker_cost_evidence_or_failure_reaches_atomic_store_and_readonly_export(tmp_path, failed):
    import importlib.util
    from pathlib import Path
    spec = importlib.util.spec_from_file_location('cost_feedback', Path(__file__).resolve().parents[3] / 'tools/incident_model_feedback.py')
    exporter = importlib.util.module_from_spec(spec); spec.loader.exec_module(exporter)
    async def run():
        _, seen, _, _, _, store, worker, poll, _ = make_incident_worker(tmp_path, provider_cost=.05 if failed else 0)
        provider = worker.providers[0]
        async def wrapped(p, bound, prior, remaining, **kwargs):
            raw, cost = await provider(p, bound, prior, remaining, **kwargs)
            checked = judgment(p, bound, raw)
            return CallResult(checked, cost, evidence_error=True) if failed else CallResult(checked, cost, evidence(p, bound, checked))
        wrapped.profile, wrapped.adapter = provider.profile, provider.adapter
        worker.providers = (wrapped, worker.providers[1])
        worker.feed(poll()); await settled(worker)
        scope = worker._scope(seen[0][0])
        exported = exporter.snapshot(store.path, scope.subject_id, scope.case_id,
                                     [__import__('dataclasses').asdict(p) for p in worker.profiles])
        trace = exported['case']['attempts'][0]['model_receipt']
        assert exported['case']['spent_micros'] == (50000 if failed else 0)
        assert exported['case']['attempts'][0]['actual_micros'] == (50000 if failed else 0)
        assert exported['field_accepted'] is False
        if failed:
            assert trace is None and exported['case']['state'] == 'HOLD'
            worker.feed(poll(2)); await settled(worker)
            assert len(seen) == 1 and store.case(scope)['observations'] == 0
        else:
            assert trace['cost_evidence']['observed_usd_charge'] is None
            assert trace['cost_evidence']['provider_request_id'] == 'request-1'
            assert 'PRIVATE_' not in exporter.feedback_json(exported)
        await worker.aclose()
    asyncio.run(run())
