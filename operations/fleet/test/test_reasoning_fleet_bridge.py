"""Real approved registry -> root config -> existing app factory -> worker; synthetic provider only."""
import asyncio
from dataclasses import asdict, replace
import importlib
import json
from pathlib import Path
import sys
import threading

import pytest

ROOT = Path(__file__).resolve().parents[3]
sys.path[:0] = [str(ROOT), str(ROOT / 'learning/registry/policy'), str(ROOT / 'contracts/learning/src'),
               str(ROOT / 'operations/decision/src'), str(ROOT / 'learning/registry/policy/test')]
from test_reasoning_registry import opened, signed
from test_reasoning_candidate import subject as candidate_api
from test_judgment_calibration import rows, limits, digest, manifest
from test_incident_runtime import app, poll, settings
from test_incident_case_worker import settled
from test_judgment_profiles import adapter
from test_model_judgment import payload


def bridge_case(tmp_path):
    config, _ = settings(enabled=True)
    profiles = tuple(replace(p, calibration_revision='cal-' + p.role) for p in config['profiles'])
    providers, calls = [], []
    for selected in profiles:
        async def provider(problem, bound, prior, *args, **kwargs):
            calls.append((problem.case_id, bound.profile.role, prior))
            raw = payload(problem); raw['evidence_ids'] = list(problem.evidence_ids)
            for key in ('next_step', 'success_check'): raw[key]['evidence_ids'] = list(problem.evidence_ids)
            return raw, 0.0
        provider.profile, provider.adapter = selected, adapter()
        providers.append(provider)
    config.update(profiles=profiles, providers=tuple(providers), current_profiles=lambda: profiles)
    selected = profiles[0]
    identity = dict(profile_revision=selected.profile_revision, model_revision=selected.model_revision,
        calibration_revision=selected.calibration_revision, domain='line_follow', full_profile_sha256=digest(asdict(selected)))
    fit, evaluation = rows('fit'), rows('evaluation')
    for row in (*fit, *evaluation): row.update(identity)
    frozen = dict(**identity, choices=['reobserve', 'human'], reviewed_by='fixture-reviewer',
        fit_sha256=digest(fit), evaluation_sha256=digest(evaluation), training_sha256=digest(manifest()), limits=limits())
    candidate = candidate_api().build_candidate(asdict(selected), dict(fit=fit, evaluation=evaluation,
        training=manifest(), reviewed_profile=frozen))
    path = tmp_path / 'candidate.json'; path.write_text(json.dumps(candidate))
    registry = opened(tmp_path / 'registry'); registry.register(path)
    head = registry.history()[-1]['revision']
    registry.approve(candidate['revision'], signed(candidate, 'reasoning_calibration', head), expected_head=head)
    return config, calls, candidate, registry


def test_actual_factory_worker_reads_persistent_approval_and_revocation(tmp_path):
    async def run():
        config, calls, candidate, registry = bridge_case(tmp_path)
        bridge = importlib.import_module('tools.incident_reasoning')
        configured = bridge.registry_calibration_config(config, registry, domain='line_follow')
        application = app(tmp_path / 'site', configured)
        worker = application.state.stuck_resolver.incident_worker
        assert worker.store.path == application.state.line_stuck._log.path
        worker.feed(poll(application, stuck=None)); await settled(worker)
        assert calls == []
        worker.feed(poll(application)); await settled(worker)
        assert [role for _, role, _ in calls] == ['primary'] and worker._waiting
        head = registry.history()[-1]['revision']
        registry.revoke(candidate['revision'], signed(candidate, 'reasoning_revocation', head), expected_head=head)
        worker.feed(poll(application, stuck='case-2')); await settled(worker)
        assert [(case, role) for case, role, _ in calls] == [('case-1', 'primary'), ('case-2', 'primary'), ('case-2', 'reviewer')]
        assert len(calls[-1][2]) == 1 and worker._waiting
        await worker.aclose()
    asyncio.run(run())


def test_registry_bridge_reaches_actual_profile_dispatcher_without_selecting_or_enabling(tmp_path):
    from fleet.incidents.automation.routing import IncidentProfileRoutes
    async def run():
        config, calls, candidate, registry = bridge_case(tmp_path)
        clock = config.pop('clock')
        bridge = importlib.import_module('tools.incident_reasoning')
        combined = dict(profile_workers=(config,), clock=clock)
        configured = bridge.registry_calibration_config(combined, registry, domain='line_follow')
        assert configured['clock'] is clock and configured['profile_workers'][0]['providers'] is config['providers']
        assert 'calibration_artifacts' not in configured and 'calibration_artifacts' not in config
        application = app(tmp_path / 'site', configured)
        dispatcher = application.state.stuck_resolver.incident_worker
        try:
            snapshot = poll(application)
            dispatcher.feed(snapshot); await settled(dispatcher)
            assert calls == [] and dispatcher.store.active_scopes() == ()
            worker = dispatcher.workers[0]
            assessment = application.state.line_stuck.intervention_assessment('pinky')
            routes = IncidentProfileRoutes(dispatcher.store)
            routes.select_profile('core', assessment.policy_revision, worker.profile_sha256, expected_revision=0)
            dispatcher.feed(snapshot); await settled(dispatcher)
            assert [role for _, role, _ in calls] == ['primary']
            head = registry.history()[-1]['revision']
            registry.revoke(candidate['revision'], signed(candidate, 'reasoning_revocation', head), expected_head=head)
            dispatcher.feed(poll(application, stuck='case-2')); await settled(dispatcher)
            assert [role for _, role, _ in calls] == ['primary', 'primary', 'reviewer']
            assert len(calls[-1][2]) == 1
        finally: await dispatcher.aclose()
    asyncio.run(run())


@pytest.mark.parametrize('fault', ['empty', 'nested', 'clock', 'ports', 'top'])
def test_profile_registry_composition_refuses_ambiguous_or_owned_ports(tmp_path, fault):
    config, calls, _, registry = bridge_case(tmp_path)
    clock = config.pop('clock')
    combined = dict(profile_workers=(config,), clock=clock)
    if fault == 'empty': combined['profile_workers'] = ()
    elif fault == 'nested': config['profile_workers'] = (config.copy(),)
    elif fault == 'clock': config['clock'] = clock
    elif fault == 'ports': config['approved_artifacts'] = lambda: {}
    elif fault == 'top': combined['enabled'] = True
    bridge = importlib.import_module('tools.incident_reasoning')
    with pytest.raises(ValueError): bridge.registry_calibration_config(combined, registry, domain='line_follow')
    assert calls == []


@pytest.mark.parametrize('fault', ['profile', 'domain', 'revoked'])
def test_registry_will_not_supply_other_or_revoked_calibration(tmp_path, fault):
    config, _, candidate, registry = bridge_case(tmp_path)
    profile, domain = asdict(config['profiles'][0]), 'line_follow'
    if fault == 'profile': profile['max_calls'] = 2
    elif fault == 'domain': domain = 'door'
    else:
        head = registry.history()[-1]['revision']
        registry.revoke(candidate['revision'], signed(candidate, 'reasoning_revocation', head), expected_head=head)
    with pytest.raises(ValueError): registry.approved_candidate(profile, domain)


def test_bridge_preserves_existing_configuration_and_refuses_port_replacement(tmp_path):
    config, _, _, registry = bridge_case(tmp_path)
    bridge = importlib.import_module('tools.incident_reasoning')
    result = bridge.registry_calibration_config(config, registry, domain='line_follow')
    assert all(result[key] is value for key, value in config.items())
    assert 'calibration_artifacts' not in config
    with pytest.raises(ValueError): bridge.registry_calibration_config(result, registry, domain='line_follow')


def test_real_factory_claim_remains_responsive_while_approval_read_is_blocked(tmp_path):
    async def run():
        config, calls, _, registry = bridge_case(tmp_path)
        entered, release, finished = threading.Event(), threading.Event(), threading.Event()
        original = registry.approved_candidate
        def blocked(*args):
            entered.set()
            release.wait(2)
            finished.set()
            return original(*args)
        registry.approved_candidate = blocked
        bridge = importlib.import_module('tools.incident_reasoning')
        application = app(tmp_path / 'site', bridge.registry_calibration_config(config, registry, domain='line_follow'))
        worker = application.state.stuck_resolver.incident_worker
        try:
            worker.feed(poll(application))
            assert await asyncio.to_thread(entered.wait, 1)
            assert not finished.is_set()  # The event loop must run before the blocked read returns.
            scope = worker.store.active_scopes()[0]
            board = application.state.line_stuck
            board._log.handoff.claim('pinky', 'case-1', board.judgment_view('pinky'), 'fixture-reviewer', now=100)
            release.set(); await settled(worker)
            assert [role for _, role, _ in calls] == ['primary']
            assert worker.store.case(scope)['state'] == 'HOLD'
        finally:
            release.set(); await worker.aclose()
    asyncio.run(run())


def test_revoke_between_artifact_and_map_reads_cannot_certify_primary(tmp_path):
    async def run():
        config, calls, candidate, registry = bridge_case(tmp_path)
        original = registry.approved_candidate
        def revoke_after_read(*args):
            snapshot = original(*args)
            head = registry.history()[-1]['revision']
            registry.revoke(candidate['revision'], signed(candidate, 'reasoning_revocation', head), expected_head=head)
            return snapshot
        registry.approved_candidate = revoke_after_read
        bridge = importlib.import_module('tools.incident_reasoning')
        application = app(tmp_path / 'site', bridge.registry_calibration_config(config, registry, domain='line_follow'))
        worker = application.state.stuck_resolver.incident_worker
        try:
            worker.feed(poll(application)); await settled(worker)
            assert [role for _, role, _ in calls] == ['primary', 'reviewer']
            assert len(calls[-1][2]) == 1 and registry.approved_artifacts() == {}
        finally: await worker.aclose()
    asyncio.run(run())


@pytest.mark.parametrize('stop', ['deadline', 'cancel'])
def test_blocked_read_expiry_or_shutdown_cannot_resume_model_calls(tmp_path, stop):
    async def run():
        from fleet.incidents.automation.contract import CaseBudget
        config, calls, _, registry = bridge_case(tmp_path)
        if stop == 'deadline':
            config['budget'] = lambda _: CaseBudget(100, 100.1, 2, 1, 0, (('primary', 1), ('reviewer', 1)))
        entered, release = threading.Event(), threading.Event()
        original = registry.approved_candidate
        def blocked(*args):
            entered.set(); release.wait(2)
            return original(*args)
        registry.approved_candidate = blocked
        bridge = importlib.import_module('tools.incident_reasoning')
        application = app(tmp_path / 'site', bridge.registry_calibration_config(config, registry, domain='line_follow'))
        worker = application.state.stuck_resolver.incident_worker
        try:
            worker.feed(poll(application))
            assert await asyncio.to_thread(entered.wait, 1)
            scope = worker.store.active_scopes()[0]
            if stop == 'deadline': await settled(worker)
            else: await asyncio.wait_for(worker.aclose(), 1)
            assert worker.store.case(scope)['state'] != 'ACTIVE'
            assert [role for _, role, _ in calls] == ['primary']
            release.set(); await asyncio.sleep(.02)
            assert len(calls) == 1 and not worker._waiting
        finally:
            release.set(); await worker.aclose()
    asyncio.run(run())
