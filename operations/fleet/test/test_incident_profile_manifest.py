"""A frozen file selects installed configs; it creates no providers or authority."""
import asyncio
from dataclasses import asdict, replace
import hashlib
import importlib
import json
from pathlib import Path
import sys

import pytest

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT))
from test_incident_runtime import app, settings, poll
from test_incident_case_worker import settled
from fleet.incidents.automation.routing import IncidentProfileRoutes


def subject(): return importlib.import_module('tools.incident_reasoning')


def manifest(tmp_path, config, *, data=None):
    data = data or dict(schema='rosy.incident.profiles/1', profile_sets=[[asdict(p) for p in config['profiles']]])
    raw = json.dumps(data).encode()
    path = tmp_path / 'profiles.json'; path.write_bytes(raw)
    return path, hashlib.sha256(raw).hexdigest()


def test_frozen_file_reaches_existing_factory_without_calls_until_selected(tmp_path):
    async def run():
        config, calls = settings(enabled=True); clock = config.pop('clock')
        path, checksum = manifest(tmp_path, config)
        configured = subject().load_incident_profile_config(path, expected_sha256=checksum, installed=(config,), clock=clock)
        assert configured['profile_workers'][0]['providers'] is config['providers']
        assert configured['profile_workers'][0]['admission'] is config['admission']
        assert configured['profile_workers'][0]['budget'] is config['budget']
        assert configured['profile_workers'][0]['enabled'] is True and calls == []
        application = app(tmp_path / 'site', configured)
        dispatcher = application.state.stuck_resolver.incident_worker
        try:
            snapshot = poll(application)
            dispatcher.feed(snapshot); await settled(dispatcher)
            assert calls == [] and dispatcher.store.active_scopes() == ()
            request = application.state.line_stuck.intervention_assessment('pinky')
            worker = dispatcher.workers[0]
            routes = IncidentProfileRoutes(dispatcher.store)
            routes.select_profile('core', request.policy_revision, worker.profile_sha256, expected_revision=0)
            dispatcher.feed(snapshot); await settled(dispatcher)
            assert calls == ['case-1']
            restarted = subject().load_incident_profile_config(path, expected_sha256=checksum, installed=(config,), clock=clock)
            assert restarted['profile_workers'][0]['profiles'] == config['profiles']
        finally: await dispatcher.aclose()
    asyncio.run(run())


@pytest.mark.parametrize('field,value', [('model_id', 'uninstalled'), ('model_revision', 'changed'),
    ('max_calls', 2), ('timeout_s', 5), ('calibration_revision', 'other')])
def test_rehashed_foreign_identity_or_budget_cannot_bind_installed_provider(tmp_path, field, value):
    config, calls = settings(); clock = config.pop('clock')
    profiles = [asdict(p) for p in config['profiles']]; profiles[0][field] = value
    path, checksum = manifest(tmp_path, config, data=dict(schema='rosy.incident.profiles/1', profile_sets=[profiles]))
    with pytest.raises(ValueError):
        subject().load_incident_profile_config(path, expected_sha256=checksum, installed=(config,), clock=clock)
    assert calls == []


@pytest.mark.parametrize('fault', ['tampered', 'oversize', 'missing', 'extra', 'duplicate', 'provider', 'clock'])
def test_manifest_boundary_errors_are_redacted_and_do_not_call_providers(tmp_path, fault):
    config, calls = settings(); clock = config.pop('clock')
    path, checksum = manifest(tmp_path, config)
    if fault == 'tampered': path.write_text('{"private-token":"hidden-secret"}')
    elif fault == 'oversize':
        raw = b' ' * (65536 + 1); path.write_bytes(raw); checksum = hashlib.sha256(raw).hexdigest()
    elif fault == 'missing': path = tmp_path / 'hidden-secret'
    elif fault == 'extra':
        path, checksum = manifest(tmp_path, config, data=dict(schema='rosy.incident.profiles/1',
            profile_sets=[[asdict(p) for p in config['profiles']]], endpoint='hidden-secret'))
    elif fault == 'duplicate':
        path, checksum = manifest(tmp_path, config, data=dict(schema='rosy.incident.profiles/1',
            profile_sets=[[asdict(p) for p in config['profiles']]] * 2))
    elif fault == 'provider': config['providers'][0].profile = replace(config['profiles'][0], model_revision='changed')
    elif fault == 'clock': config['clock'] = clock
    with pytest.raises(ValueError) as error:
        subject().load_incident_profile_config(path, expected_sha256=checksum, installed=(config,), clock=clock)
    assert 'hidden-secret' not in str(error.value) and calls == []


@pytest.mark.parametrize('fault', ['deep', 'integer', 'duplicate-key'])
def test_adversarial_json_is_bounded_and_rejected_with_redacted_value_error(tmp_path, fault):
    config, calls = settings(); clock = config.pop('clock')
    path, _ = manifest(tmp_path, config)
    if fault == 'deep': raw = b'[' * 2000 + b'0' + b']' * 2000
    elif fault == 'integer':
        profiles = [asdict(p) for p in config['profiles']]; profiles[0]['timeout_s'] = 10**500
        raw = json.dumps(dict(schema='rosy.incident.profiles/1', profile_sets=[profiles])).encode()
    else: raw = path.read_bytes().replace(b'"schema":', b'"schema":"hidden-secret", "schema":', 1)
    path.write_bytes(raw)
    original_limit = sys.getrecursionlimit()
    try:
        if fault == 'deep': sys.setrecursionlimit(1000)
        with pytest.raises(ValueError, match='INCIDENT_PROFILE_INSTALLATION_BINDING_FAILED'):
            subject().load_incident_profile_config(path, expected_sha256=hashlib.sha256(raw).hexdigest(),
                                                  installed=(config,), clock=clock)
    finally: sys.setrecursionlimit(original_limit)
    assert calls == []
