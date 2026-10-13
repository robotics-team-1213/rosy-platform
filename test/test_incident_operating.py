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


@pytest.mark.parametrize('raw', [b'{"value":1,"value":2}', b'{"value":NaN}', b'{"value":1e309}',
                               b'[]', b'x' * (1048576 + 1)],
                         ids=['duplicate', 'nonfinite', 'float-overflow', 'nonobject', 'oversized'])
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


def test_revocation_delegates_to_existing_owner_even_when_new_evidence_is_hold(tmp_path):
    from rosy.contracts.learning import seal
    from rosy.contracts.learning.incident_operation import REVOKE
    module = owner()
    def forbidden(*args):
        raise AssertionError('revocation must use the stored binding, not new acceptance evidence')
    evidence = module.OperatingEvidenceOwner(tmp_path / 'absent-original.json', expected_sha256='1' * 64,
        grant_id='grant', installation=forbidden, calibrations=forbidden, trusted=forbidden,
        originals=forbidden, clock=forbidden)
    binding = dict(profile_set_sha256='1' * 64, full_profile_sha256='2' * 64, model_revision='source-only-r1',
        calibration_sha256='3' * 64, domain='line_follow', action='BACK_AND_RETRY',
        action_contract='rosy.line_stuck.conditional_back/1', policy_revision='policy-r1', installation_sha256='4' * 64,
        evaluation_sha256='5' * 64, coverage_sha256='6' * 64, limits_sha256='7' * 64, truth_sha256='8' * 64,
        evaluation_state='REVIEWED_FOR_OPERATION')
    receipt = dict(principal='isolated-source-fixture', payload=seal(dict(schema='rosy.incident.operation/1', kind=REVOKE,
        binding=binding, expected_epoch=1, valid_from_s=1, expires_s=2)), signature='0' * 64)
    class ExistingOwner:
        def apply(self, grant_id, received):
            assert grant_id == 'grant' and received == receipt
            return 'delegated-to-existing-verifier'
    assert module.import_operation(ExistingOwner(), 'grant', receipt, evidence=evidence) == 'delegated-to-existing-verifier'


def calibration_bundle():
    from dataclasses import asdict
    from rosy.decision.deliberation.profiles import ModelProfile
    module = owner()
    selected = asdict(ModelProfile(profile_id='primary', profile_revision='r1', role='primary', provider_kind='local',
        model_id='fixture', model_revision='model-r1', adapter='local-v2', domains=('line_follow',),
        modalities=('text',), timeout_s=1, max_output_bytes=1024, max_calls=1, max_cost_usd=0,
        calibration_revision='cal-r1'))
    identity = dict(profile_revision='r1', model_revision='model-r1', domain='line_follow',
                    calibration_revision='cal-r1', full_profile_sha256=module.digest(selected))
    def rows(split):
        return [dict(id=split, session_id=split, recording_id=split, session_sha256=module.digest(split),
            recording_sha256=module.digest(split), reviewed_by='fixture', expected='human', **identity,
            alternatives=[dict(choice='human', probability=.9), dict(choice='reobserve', probability=.1)],
            abstained=False, latency_ms=1, unsafe_error=False, binding_error=False,
            unnecessary_effect=False, required_abstain_error=False)]
    fit, evaluation = rows('fit'), rows('evaluation')
    training = dict(sessions=[], recordings=[], session_hashes=[], recording_hashes=[])
    reviewed = dict(**identity, choices=['human', 'reobserve'], reviewed_by='fixture', limits=None,
        fit_sha256=module.digest(fit), evaluation_sha256=module.digest(evaluation), training_sha256=module.digest(training))
    calibration = dict(fit=fit, evaluation=evaluation, training=training, reviewed_profile=reviewed)
    return dict(schema='rosy.incident.operational_evidence/1', profiles=[selected], profile=selected,
        calibration_input=calibration, cohort=None, exports=[], inventories=[], inventory_digests=[],
        truth=None, limits=None, windows=[], review=None)


def test_root_recomputes_existing_profile_and_calibration_without_operating_acceptance():
    from rosy.decision.deliberation.calibration import evaluate_calibration
    module = owner(); data = calibration_bundle()
    result = module.compile_original_evidence(data, trusted={}, now=100)
    assert result['profile_set_sha256'] == module.digest(data['profiles'])
    assert result['full_profile_sha256'] == module.digest(data['profile'])
    assert result['calibration_sha256'] == evaluate_calibration(**data['calibration_input']).digest
    assert result['profile_calibration_scope'] == 'root_recomputed_profile_and_calibration_only'
    assert result['state'] == 'HOLD' and result['field_accepted'] is False
    assert 'accepted_calibration' in result['missing']
    data['calibration_input']['evaluation'][0]['expected'] = 'reobserve'
    with pytest.raises(ValueError): module.compile_original_evidence(data, trusted={}, now=100)
