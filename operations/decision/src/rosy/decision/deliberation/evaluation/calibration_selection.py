"""Advisory threshold check against an externally pinned, reviewed artifact digest."""
from dataclasses import asdict
from .calibration_metrics import digest, group_key, probabilities, top
from ..contracts.profiles import BoundProfile, ModelProfile
from ..contracts.judgment import Judgment, judgment


def select_calibrated(problem, bound, checked, artifact, *, approved_artifacts, current_profile=None):
    result = dict(state='HOLD', reason='UNCERTIFIED', eligible=False, action_admissible=False,
                  subject_id=problem.subject_id, case_id=problem.case_id, generation=problem.generation,
                  input_hash=problem.digest, calibration_revision=None, calibrated_confidence=None,
                  raw_probability=None, raw_top_gap=None, choice=None)
    try:
        from .calibration import CalibrationArtifact
        if type(artifact) is not CalibrationArtifact:
            return result
        if type(bound) is not BoundProfile or type(bound.profile) is not ModelProfile or type(checked) is not Judgment:
            return result
        bound.validate(problem, current_profile=current_profile)
        payload = checked.payload
        if payload['missing_evidence'] or payload['objections'] or checked.action_admissible is not False:
            return {**result, 'reason': 'UNRESOLVED_EVIDENCE_OR_OBJECTION'}
        # Revalidate current case, references and catalog before consuming even a frozen Judgment.
        checked = judgment(problem, bound, payload)
        if checked.choice is None:
            return {**result, 'reason': 'NO_UNIQUE_ACTIVE_CHOICE'}
        report = artifact.report
        revision = bound.profile.calibration_revision
        if (type(approved_artifacts) is not dict or not revision
                or approved_artifacts.get(revision) != artifact.digest
                or report['state'] != 'PASS_OFFLINE_ONLY' or report['field_accepted'] is not False
                or report['schema_version'] != 2 or report['calibration_revision'] != revision
                or report['profile_revision'] != bound.profile.profile_revision
                or report['model_revision'] != bound.profile.model_revision or report['domain'] != problem.domain
                or report['full_profile_sha256'] != digest(asdict(bound.profile))
                or set(report['choices']) != set(problem.choices) or not report['limits']):
            return result
        values = probabilities(payload['alternatives'], problem.choices)
        choice, score, gap = top(values)
        choice_key, index = group_key(values)
        bucket = next(row for row in report['bins'] if row['choice'] == choice_key and row['index'] == index)
        minimum = report['limits']['minimum_bin_cases']
        confidence = bucket['calibrated_confidence']
        enough = min(bucket['count'], bucket['fit_count']) >= minimum
        eligible = enough and confidence >= .95 and gap >= .20
        return {**result, 'state': 'ELIGIBLE_ADVISORY_ONLY' if eligible else 'HOLD',
                'reason': 'CALIBRATED_CANDIDATE' if eligible else 'INSUFFICIENT_CALIBRATION_OR_GAP',
                'eligible': eligible, 'calibration_revision': revision, 'calibrated_confidence': confidence,
                'raw_probability': score, 'raw_top_gap': gap, 'choice': choice,
                'artifact_sha256': artifact.digest}
    except (ValueError, TypeError, KeyError, AttributeError, StopIteration):
        return {**result, 'reason': 'INVALID_OR_CHANGED_BINDING'}
