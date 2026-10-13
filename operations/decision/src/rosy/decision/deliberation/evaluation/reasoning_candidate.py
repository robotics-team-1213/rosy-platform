"""Bound, recomputed reasoning evidence for the registry; grants no approval."""
from dataclasses import asdict, fields
import json

from rosy.contracts.learning import seal
from rosy.decision.deliberation.calibration import evaluate_calibration
from rosy.decision.deliberation.evaluation.calibration_metrics import digest
from rosy.decision.deliberation.profiles import ModelProfile

SCHEMA = 'rosy.reasoning-candidate/1'
LIMIT = 2 * 1024 * 1024
INPUT_FIELDS = {'fit', 'evaluation', 'training', 'reviewed_profile'}
FIELDS = {'schema', 'profile', 'domain', 'calibration_input', 'calibration_report',
          'field_accepted', 'revision'}


def byte_size(value):
    return len(json.dumps(value, sort_keys=True, separators=(',', ':'),
                          ensure_ascii=False, allow_nan=False).encode('utf-8'))


def build_candidate(profile, calibration_input):
    """Snapshot inputs and re-evaluate their exact full-profile/domain binding."""
    try:
        if (type(profile) is not dict or set(profile) != {f.name for f in fields(ModelProfile)}
                or type(calibration_input) is not dict or set(calibration_input) != INPUT_FIELDS
                or byte_size([profile, calibration_input]) > LIMIT):
            raise ValueError('INVALID_REASONING_CANDIDATE_INPUT')
        runtime = ModelProfile(**profile)
        reviewed = calibration_input['reviewed_profile']
        if (type(reviewed) is not dict or runtime.calibration_revision is None
                or reviewed.get('full_profile_sha256') != digest(asdict(runtime))
                or reviewed.get('profile_revision') != runtime.profile_revision
                or reviewed.get('model_revision') != runtime.model_revision
                or reviewed.get('calibration_revision') != runtime.calibration_revision
                or reviewed.get('domain') not in runtime.domains):
            raise ValueError('REASONING_CANDIDATE_PROFILE_BINDING_DIFFERS')
        artifact = evaluate_calibration(**calibration_input)
        candidate = seal(dict(schema=SCHEMA, profile=asdict(runtime), domain=reviewed['domain'],
            calibration_input=calibration_input, calibration_report=artifact.report, field_accepted=False))
        if byte_size(candidate) > LIMIT:
            raise ValueError('REASONING_CANDIDATE_TOO_LARGE')
        return candidate
    except (KeyError, TypeError, OverflowError) as error:
        raise ValueError('INVALID_REASONING_CANDIDATE_INPUT') from error


def validate_candidate(candidate):
    """A resealed report cannot override recomputation of preserved inputs."""
    if (type(candidate) is not dict or set(candidate) != FIELDS
            or candidate['schema'] != SCHEMA or candidate['field_accepted'] is not False):
        raise ValueError('INVALID_REASONING_CANDIDATE')
    if (byte_size(candidate) > LIMIT or seal(candidate) != candidate
            or build_candidate(candidate['profile'], candidate['calibration_input']) != candidate):
        raise ValueError('REASONING_CANDIDATE_EVIDENCE_DIFFERS')
    return seal(candidate)
