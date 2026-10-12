"""ROOT original-file composition; explicit ports only, no default activation."""
import hashlib
import json
import math
from pathlib import Path
import re
import sys
from dataclasses import asdict

from learning.evaluation.decision.operational_evidence import BUNDLE, compile_evidence
from learning.evaluation.decision.operational_sources import digest, encoded, verify_attestation
from learning.evaluation.decision.operational_comparison import fields, sha, text, timestamp


def compile_original_evidence(bundle, *, trusted, now, originals=None):
    """ROOT composition of existing codecs; recomputation is diagnostic, never admission."""
    from rosy.decision.deliberation.profiles import ModelProfile, incident_profiles
    from rosy.decision.deliberation.calibration import evaluate_calibration
    fields(bundle, BUNDLE); encoded(bundle); timestamp(now)
    profiles = incident_profiles(tuple(ModelProfile(**p) for p in bundle['profiles']))
    selected = ModelProfile(**bundle['profile'])
    if selected not in profiles or selected.calibration_revision is None:
        raise ValueError('OPERATING_FULL_PROFILE_NOT_SELECTED')
    calibration = None
    if bundle['calibration_input'] is not None:
        fields(bundle['calibration_input'], ('fit', 'evaluation', 'training', 'reviewed_profile'))
        calibration = evaluate_calibration(**bundle['calibration_input'])
        report = calibration.report
        if (report['full_profile_sha256'] != digest(asdict(selected)) or report['domain'] != 'line_follow'
                or report['model_revision'] != selected.model_revision
                or report['calibration_revision'] != selected.calibration_revision):
            raise ValueError('OPERATING_CALIBRATION_OR_PROFILE_DIFFERS')
    diagnostic = dict(bundle_sha256=digest(bundle), profile_set_sha256=digest([asdict(p) for p in profiles]),
        full_profile_sha256=digest(asdict(selected)), domains=list(selected.domains),
        calibration_sha256=calibration.digest if calibration else None,
        calibration_state=calibration.report['state'] if calibration else None)
    result = compile_evidence(bundle, trusted=trusted, now=now, originals=originals, profile_calibration=diagnostic)
    result['profile_calibration_scope'] = 'root_recomputed_profile_and_calibration_only'
    return result


def load_frozen_json(source, *, expected_sha256):
    if type(expected_sha256) is not str or re.fullmatch('[0-9a-f]{64}', expected_sha256) is None:
        raise ValueError('EXTERNAL_OPERATING_FILE_PIN_REQUIRED')
    def unique(pairs):
        result = dict(pairs)
        if len(result) != len(pairs): raise ValueError('DUPLICATE_OPERATING_ORIGINAL_FIELD')
        return result
    def nonfinite(value):
        raise ValueError('NONFINITE_OPERATING_ORIGINAL')
    def finite_float(value):
        number = float(value)
        if not math.isfinite(number): nonfinite(value)
        return number
    try:
        with Path(source).open('rb') as stream: raw = stream.read(1024 * 1024 + 1)
        if len(raw) > 1024 * 1024 or hashlib.sha256(raw).hexdigest() != expected_sha256:
            raise ValueError('OPERATING_ORIGINAL_BYTES_DIFFER')
        document = json.loads(raw.decode('utf-8-sig'), object_pairs_hook=unique,
                              parse_constant=nonfinite, parse_float=finite_float)
        if type(document) is not dict: raise ValueError('OPERATING_ORIGINAL_OBJECT_REQUIRED')
        return document
    except (OSError, UnicodeError, RecursionError, OverflowError) as error:
        raise ValueError('OPERATING_ORIGINAL_READ_FAILED') from error


def import_operation(owner, grant_id, receipt, *, evidence):
    if type(evidence) is not OperatingEvidenceOwner or not callable(getattr(owner, 'apply', None)):
        raise ValueError('EXPLICIT_EXISTING_OPERATION_OWNER_REQUIRED')
    from rosy.contracts.learning.incident_operation import REVOKE, validate_operation_receipt
    if validate_operation_receipt(receipt)['payload']['kind'] == REVOKE:
        return owner.apply(grant_id, receipt)
    proof = evidence(grant_id)
    report = proof.get('report') if type(proof) is dict else None
    if (type(report) is not dict or report.get('state') != 'PASS_FOR_OPERATION'
            or report.get('field_accepted') is not True or report.get('truth_admitted') is not True
            or report.get('missing') != []):
        raise ValueError('ORIGINAL_OPERATING_EVIDENCE_HOLD')
    return owner.apply(grant_id, receipt)


def installation_getter(source, *, expected_sha256, artifact_root, current_runtime, trusted, clock):
    if not all(callable(port) for port in (current_runtime, trusted, clock)):
        raise ValueError('EXPLICIT_CURRENT_INSTALLATION_OWNER_PORTS_REQUIRED')
    base = Path(artifact_root).resolve(strict=True)
    if not base.is_dir() or Path(artifact_root).is_symlink(): raise ValueError('EXPLICIT_INSTALLED_ARTIFACT_ROOT_REQUIRED')
    def read():
        manifest = load_frozen_json(source, expected_sha256=expected_sha256)
        identity = ('installation_id', 'profile_set_sha256', 'full_profile_sha256', 'model_revision',
                    'calibration_sha256', 'policy_revision', 'action_contract', 'artifacts')
        fields(manifest, ('schema', *identity))
        if manifest['schema'] != 'rosy.incident.installation/1': raise ValueError('INVALID_INSTALLATION_SCHEMA')
        for key in identity[:-1]:
            sha(manifest[key]) if key.endswith('_sha256') else text(manifest[key])
        if manifest['action_contract'] != 'rosy.line_stuck.conditional_back/1':
            raise ValueError('INSTALLATION_ACTION_CONTRACT_DIFFERS')
        artifacts = manifest['artifacts']
        if type(artifacts) is not list or not 1 <= len(artifacts) <= 64:
            raise ValueError('BOUNDED_INSTALLED_ARTIFACTS_REQUIRED')
        names = set()
        for artifact in artifacts:
            fields(artifact, ('path', 'sha256')); name = text(artifact['path']); sha(artifact['sha256'])
            relative = Path(name)
            path = base / relative
            if (name in names or relative.is_absolute() or relative.drive or '\\' in name
                    or '..' in relative.parts or path.is_symlink()
                    or path.resolve(strict=True) != path or not path.is_file()):
                raise ValueError('INSTALLED_ARTIFACT_PATH_DIFFERS')
            names.add(name)
            with path.open('rb') as stream:
                if hashlib.file_digest(stream, 'sha256').hexdigest() != artifact['sha256']:
                    raise ValueError('INSTALLED_ARTIFACT_BYTES_DIFFER')
        runtime = current_runtime()
        fields(runtime, ('schema', *identity, 'observed_at', 'valid_until_s', 'process', 'attestation'))
        original = {k: v for k, v in runtime.items() if k != 'attestation'}
        now = clock()
        verify_attestation(runtime['attestation'], original, trusted=trusted(), kind='operational_runtime', now=now)
        if (runtime['schema'] != 'rosy.incident.runtime/1' or any(runtime[key] != manifest[key] for key in identity)
                or not timestamp(runtime['observed_at']) <= now < timestamp(runtime['valid_until_s'])):
            raise ValueError('CURRENT_INSTALLED_RUNTIME_DIFFERS')
        process = runtime['process']; fields(process, ('pid', 'start_ticks', 'executable_sha256', 'service_revision'))
        if any(type(process[key]) is not int or process[key] < 1 for key in ('pid', 'start_ticks')):
            raise ValueError('CURRENT_PROCESS_IDENTITY_REQUIRED')
        text(process['service_revision']); sha(process['executable_sha256'])
        if process['executable_sha256'] not in {row['sha256'] for row in artifacts}:
            raise ValueError('CURRENT_PROCESS_ARTIFACT_NOT_INSTALLED')
        return {**{key: manifest[key] for key in identity}, 'runtime_scope': 'signed_owner_declaration_only',
                'installation_sha256': digest(dict(manifest=manifest, process=process))}
    return read


def load_original_sources(configs, *, windows, max_gap_s):
    """Run existing raw/capture readers; their bounded scopes never imply full operation coverage."""
    if type(configs) is not list or len(configs) > 4096 or type(windows) is not list:
        raise ValueError('EXPLICIT_ORIGINAL_SOURCE_CONFIG_REQUIRED')
    if not configs: return None
    for config in configs:
        fields(config, ('window_sha256', 'episode_root', 'dataset_revision', 'observation_database', 'database_sha256'))
    from learning.curation.pinky.fleet_observations import capture_window
    source_dir = Path(__file__).resolve().parents[1] / 'learning/curation/pinky'
    if str(source_dir) not in sys.path: sys.path.insert(0, str(source_dir))
    from learning.curation.pinky.verify_raw import verify
    available = {digest({k: v for k, v in window.items() if k != 'attestation'}): window for window in windows}
    seen, recordings, captures = set(), [], []
    for config in configs:
        key = sha(config['window_sha256']); sha(config['dataset_revision']); sha(config['database_sha256'])
        if key in seen or key not in available: raise ValueError('ORIGINAL_SOURCE_WINDOW_DIFFERS')
        window = available[key]
        database = Path(config['observation_database'])
        if Path(str(database) + '-wal').exists(): raise ValueError('FROZEN_OBSERVATION_DATABASE_REQUIRED')
        def file_sha(path):
            with Path(path).open('rb') as stream: return hashlib.file_digest(stream, 'sha256').hexdigest()
        if file_sha(database) != config['database_sha256']: raise ValueError('ORIGINAL_OBSERVATION_BYTES_DIFFER')
        raw = verify(config['episode_root'])
        if raw['dataset_revision'] != config['dataset_revision']: raise ValueError('ORIGINAL_RAW_DATASET_DIFFERS')
        captured = capture_window(database, robot_id=window['subject_id'], start=window['start'],
                                  end=window['end'], max_gap_s=max_gap_s)
        if file_sha(database) != config['database_sha256']: raise ValueError('ORIGINAL_OBSERVATION_CHANGED_DURING_READ')
        recordings.append(dict(window_sha256=key, verification=raw))
        captures.append(dict(window_sha256=key, verification=captured))
        seen.add(key)
    if seen != set(available): raise ValueError('ORIGINAL_WINDOW_SOURCE_SET_INCOMPLETE')
    return dict(raw_recordings=recordings, observation_windows=captures,
                coverage_scope='raw_sidecar_and_retained_observations_only')


class OperatingEvidenceOwner:
    """A ROOT-computed port, never an injected PASS report or a receipt signer."""
    def __init__(self, source, *, expected_sha256, grant_id, installation, calibrations, trusted, originals, clock):
        text(grant_id)
        if not all(callable(port) for port in (installation, calibrations, trusted, originals, clock)):
            raise ValueError('EXPLICIT_CURRENT_OPERATING_SOURCE_PORTS_REQUIRED')
        self.source, self.expected_sha256, self.grant_id = source, expected_sha256, grant_id
        self.installation, self.calibrations, self.trusted, self.originals, self.clock = installation, calibrations, trusted, originals, clock

    def __call__(self, grant_id):
        if grant_id != self.grant_id: raise ValueError('UNREGISTERED_OPERATING_GRANT')
        bundle = load_frozen_json(self.source, expected_sha256=self.expected_sha256)
        report = compile_original_evidence(bundle, trusted=self.trusted(), now=self.clock(), originals=self.originals(bundle))
        if report['state'] != 'PASS_FOR_OPERATION': raise ValueError('ORIGINAL_OPERATING_EVIDENCE_HOLD')
        installed, approved = self.installation(), self.calibrations()
        profile = bundle['profile']
        for field in ('profile_set_sha256', 'full_profile_sha256', 'calibration_sha256'):
            if installed[field] != report[field]: raise ValueError('CURRENT_INSTALLATION_EVIDENCE_DIFFERS')
        if (type(approved) is not dict or approved.get(profile['calibration_revision']) != report['calibration_sha256']
                or installed['model_revision'] != profile['model_revision']):
            raise ValueError('CURRENT_APPROVED_CALIBRATION_DIFFERS')
        binding = dict(profile_set_sha256=report['profile_set_sha256'], full_profile_sha256=report['full_profile_sha256'],
            model_revision=profile['model_revision'], calibration_sha256=report['calibration_sha256'], domain='line_follow',
            action='BACK_AND_RETRY', action_contract=installed['action_contract'], policy_revision=installed['policy_revision'],
            installation_sha256=installed['installation_sha256'], evaluation_sha256=digest(report),
            coverage_sha256=report['coverage_sha256'], limits_sha256=report['limits_sha256'], truth_sha256=report['truth_sha256'],
            evaluation_state='REVIEWED_FOR_OPERATION')
        return dict(binding=binding, report=report, profiles=bundle['profiles'], profile=profile, approved_calibrations=approved)
