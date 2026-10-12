"""ROOT frozen file and installation boundaries, with no runtime or provider activation."""
import hashlib
import hmac
import importlib.util
import json
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]


def owner():
    path = ROOT / 'tools/incident_operating.py'
    assert path.exists(), 'root operating evidence owner missing'
    spec = importlib.util.spec_from_file_location('incident_operating', path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def frozen(tmp_path, raw):
    path = tmp_path / 'original.json'; path.write_bytes(raw)
    return path, hashlib.sha256(raw).hexdigest()


def test_loader_pins_original_bytes_instead_of_document_hash(tmp_path):
    path, expected = frozen(tmp_path, b'{"schema":"source-fixture","value":1}')
    assert owner().load_frozen_json(path, expected_sha256=expected)['value'] == 1
    path.write_bytes(b'{"schema":"source-fixture","value":2}')
    with pytest.raises(ValueError): owner().load_frozen_json(path, expected_sha256=expected)


@pytest.mark.parametrize('raw', [b'{"value":1,"value":2}', b'{"value":NaN}', b'[]', b'x' * (1048576 + 1)],
                         ids=['duplicate', 'nonfinite', 'nonobject', 'oversized'])
def test_loader_rejects_duplicate_nonfinite_nonobject_or_large_original(tmp_path, raw):
    path, expected = frozen(tmp_path, raw)
    with pytest.raises(ValueError): owner().load_frozen_json(path, expected_sha256=expected)


def test_importer_refuses_compiled_hold_before_existing_db_apply():
    module = owner()
    class ExistingOwner:
        def apply(self, *args):
            raise AssertionError('HOLD must not reach the existing DB importer')
    with pytest.raises(ValueError):
        module.import_operation(ExistingOwner(), 'grant', {}, evidence=lambda _: {'report': {'state': 'HOLD'}})


def installation(tmp_path):
    base = tmp_path / 'installed'; base.mkdir()
    artifact = base / 'runtime.py'; artifact.write_bytes(b'source-only installed artifact fixture')
    manifest = dict(schema='rosy.incident.installation/1', installation_id='source-fixture-installation',
        profile_set_sha256='1' * 64, full_profile_sha256='2' * 64, model_revision='model-r1',
        calibration_sha256='3' * 64, policy_revision='policy-r1', action_contract='rosy.line_stuck.conditional_back/1',
        artifacts=[dict(path='runtime.py', sha256=hashlib.sha256(artifact.read_bytes()).hexdigest())])
    raw = json.dumps(manifest, sort_keys=True, separators=(',', ':')).encode()
    path = tmp_path / 'installation.json'; path.write_bytes(raw)
    runtime = dict(schema='rosy.incident.runtime/1', installation_id=manifest['installation_id'],
        profile_set_sha256=manifest['profile_set_sha256'], full_profile_sha256=manifest['full_profile_sha256'],
        model_revision=manifest['model_revision'], calibration_sha256=manifest['calibration_sha256'],
        policy_revision=manifest['policy_revision'], action_contract=manifest['action_contract'],
        artifacts=manifest['artifacts'], observed_at=99, valid_until_s=105,
        process=dict(pid=10, start_ticks=1234, executable_sha256=manifest['artifacts'][0]['sha256'],
                     service_revision='service-r1'))
    key = b'source-only-runtime-attestation-key'
    encode = lambda v: json.dumps(v, sort_keys=True, separators=(',', ':')).encode()
    payload = dict(schema='rosy.incident.evidence_attestation/1', kind='operational_runtime',
        source_sha256=hashlib.sha256(encode(runtime)).hexdigest(), valid_from_s=90, expires_s=110)
    signed = dict(principal='installation-owner', payload=payload,
        signature=hmac.new(key, encode(payload), hashlib.sha256).hexdigest())
    current = {**runtime, 'attestation': signed}
    trusted = {'installation-owner': dict(key=key, kinds={'operational_runtime'})}
    return path, hashlib.sha256(raw).hexdigest(), base, artifact, current, trusted


def test_getter_derives_current_installation_from_pinned_artifact_and_runtime(tmp_path):
    module = owner(); path, expected, base, artifact, current, trusted = installation(tmp_path)
    getter = module.installation_getter(path, expected_sha256=expected, artifact_root=base,
        current_runtime=lambda: current, trusted=lambda: trusted, clock=lambda: 100)
    result = getter()
    assert result['installation_id'] == 'source-fixture-installation'
    assert len(result['installation_sha256']) == 64 and 'field_accepted' not in result
    artifact.write_bytes(b'changed installation')
    with pytest.raises(ValueError): getter()


@pytest.mark.parametrize('fault', ['runtime_identity', 'runtime_expired', 'runtime_signature', 'escape'])
def test_getter_refuses_changed_current_runtime_or_escaping_artifact(tmp_path, fault):
    module = owner(); path, expected, base, artifact, current, trusted = installation(tmp_path)
    if fault == 'runtime_identity': current['installation_id'] = 'other-installation'
    elif fault == 'runtime_expired': current['valid_until_s'] = 99
    elif fault == 'runtime_signature': current['attestation']['signature'] = '0' * 64
    else:
        manifest = json.loads(path.read_bytes()); manifest['artifacts'][0]['path'] = '../outside.py'
        path.write_text(json.dumps(manifest)); expected = hashlib.sha256(path.read_bytes()).hexdigest()
    getter = module.installation_getter(path, expected_sha256=expected, artifact_root=base,
        current_runtime=lambda: current, trusted=lambda: trusted, clock=lambda: 100)
    with pytest.raises(ValueError): getter()


def test_importer_does_not_accept_a_fake_flags_only_owner_port():
    module = owner()
    class ExistingOwner:
        def apply(self, *args):
            raise AssertionError('fake field flags must not reach SQLite apply')
    fake = dict(report=dict(schema='rosy.incident.operational_acceptance/1', state='PASS_FOR_OPERATION',
                           field_accepted=True, truth_admitted=True, missing=[]))
    with pytest.raises(ValueError): module.import_operation(ExistingOwner(), 'grant', {}, evidence=lambda _: fake)


def test_original_source_loader_cannot_use_a_fake_raw_verification_report(tmp_path):
    module = owner()
    forged = dict(schema='rosy.pinky-raw-verification/1', verdict='pass', dataset_revision='1' * 64)
    config = dict(window_sha256='2' * 64, episode_root=str(tmp_path), dataset_revision='1' * 64,
        observation_database=str(tmp_path / 'absent.sqlite3'), database_sha256='3' * 64,
        raw_verification=forged)
    with pytest.raises(ValueError): module.load_original_sources([config], windows=[], max_gap_s=1)


def test_empty_original_sources_are_missing_coverage_not_an_accepted_empty_window():
    module = owner()
    assert module.load_original_sources([], windows=[], max_gap_s=1) is None
