"""Model PC pure calibration computation. Trusted approval is a separate caller input."""
from dataclasses import dataclass
import json
import re

from .. import identifier
from .calibration_metrics import ERRORS, calibrated_metrics, digest, finite, metrics, serialize, wilson_lower

IDENTITY = ('profile_revision', 'model_revision', 'domain', 'calibration_revision', 'full_profile_sha256')
LINEAGE = ('session_id', 'recording_id', 'session_sha256', 'recording_sha256')


def hash_value(value):
    if type(value) is not str or re.fullmatch('[0-9a-f]{64}', value) is None:
        raise ValueError('invalid calibration hash')
    return value


@dataclass(frozen=True)
class CalibrationArtifact:
    report_json: str

    @property
    def report(self):
        return json.loads(self.report_json)

    @property
    def digest(self):
        return digest(self.report)


def validated_rows(rows, profile, training):
    if type(rows) not in (list, tuple) or not 1 <= len(rows) <= 10000:
        raise ValueError('invalid bounded calibration dataset')
    seen, recordings, hashes = set(), set(), set()
    for row in rows:
        if type(row) is not dict:
            raise ValueError('invalid calibration row')
        for field in ('id', 'reviewed_by', *LINEAGE):
            identifier(row[field])
        for field in ('session_sha256', 'recording_sha256'):
            hash_value(row[field])
        if (row['id'] in seen or row['recording_id'] in recordings or row['recording_sha256'] in hashes
                or any(row[field] in training[key] for field, key in zip(LINEAGE,
                    ('sessions', 'recordings', 'session_hashes', 'recording_hashes')))):
            raise ValueError('duplicate or leaked calibration row')
        if any(row[field] != profile[field] for field in IDENTITY):
            raise ValueError('calibration revision identity differs')
        if row['expected'] not in profile['choices'] or any(type(row[field]) is not bool for field in (*ERRORS, 'abstained')):
            raise ValueError('invalid calibration truth or outcome')
        finite(row['latency_ms'])
        seen.add(row['id']); recordings.add(row['recording_id']); hashes.add(row['recording_sha256'])


def evaluate_calibration(fit, evaluation, *, training, reviewed_profile):
    """Compute fixed-bin fit/test metrics; missing reviewed limits always produce HOLD."""
    profile = reviewed_profile
    fields = {*IDENTITY, 'choices', 'reviewed_by', 'fit_sha256', 'evaluation_sha256', 'training_sha256', 'limits'}
    if type(profile) is not dict or set(profile) != fields:
        raise ValueError('invalid frozen calibration profile')
    for field in (*IDENTITY, 'reviewed_by'):
        identifier(profile[field])
    hash_value(profile['full_profile_sha256'])
    if profile['domain'] not in {'line_follow', 'door', 'arm_target'}:
        raise ValueError('invalid calibration domain')
    choices = profile['choices']
    if (type(choices) not in (list, tuple) or not 2 <= len(choices) <= 16
            or any(type(c) is not str for c in choices) or len(set(choices)) != len(choices)):
        raise ValueError('invalid calibration choices')
    for choice in choices:
        identifier(choice)
    if (type(training) is not dict or set(training) != {'sessions', 'recordings', 'session_hashes', 'recording_hashes'}
            or any(type(v) not in (list, tuple) or len(v) > 10000 for v in training.values())):
        raise ValueError('invalid frozen training manifest')
    for key, values in training.items():
        for value in values:
            hash_value(value) if key.endswith('hashes') else identifier(value)
    if any(hash_value(profile[key]) != digest(data) for key, data in
           (('fit_sha256', fit), ('evaluation_sha256', evaluation), ('training_sha256', training))):
        raise ValueError('calibration dataset hash differs from reviewed profile')
    validated_rows(fit, profile, training); validated_rows(evaluation, profile, training)
    if (set(row['id'] for row in fit) & set(row['id'] for row in evaluation)
            or any({row[field] for row in fit} & {row[field] for row in evaluation} for field in LINEAGE)):
        raise ValueError('leaked calibration and evaluation split')
    fit_metrics, fitted = metrics(fit, choices)
    test_metrics, bins = metrics(evaluation, choices)
    for fitted_bin, evaluated in zip(fitted, bins):
        evaluated.update(fit_count=fitted_bin['count'], fit_accuracy=fitted_bin['empirical_accuracy'],
                         fit_accuracy_lower=fitted_bin['accuracy_lower'])
        evaluated['calibrated_confidence'] = min(evaluated['accuracy_lower'], fitted_bin['accuracy_lower'])
    test_metrics.update(calibrated_metrics(bins, len(evaluation)))
    report = dict(schema_version=2, **{field: profile[field] for field in IDENTITY}, choices=list(choices),
        fit_sha256=profile['fit_sha256'], evaluation_sha256=profile['evaluation_sha256'],
        training_sha256=profile['training_sha256'], reviewed_by=profile['reviewed_by'],
        state='HOLD', field_accepted=False, selection_policy={'minimum_confidence': .95, 'minimum_raw_gap': .20},
        statistical_scope='pointwise_one_sided_95_wilson', bins=bins, metrics=test_metrics,
        fit_metrics=fit_metrics, limits=profile['limits'])
    limits = profile['limits']
    if limits is not None:
        expected = {'minimum_cases', 'minimum_bin_cases', 'minimum_accuracy_lower',
                    'maximum_brier', 'maximum_ece', 'maximum_p95_latency_ms'}
        if type(limits) is not dict or set(limits) != expected:
            raise ValueError('invalid reviewed calibration limits')
        for field in ('minimum_cases', 'minimum_bin_cases'):
            if type(limits[field]) is not int or not 1 <= limits[field] <= 10000:
                raise ValueError('invalid calibration minimum count')
        for field in ('minimum_accuracy_lower', 'maximum_brier', 'maximum_ece', 'maximum_p95_latency_ms'):
            finite(limits[field], maximum=1 if field in {'minimum_accuracy_lower', 'maximum_ece'} else None)
        enough = min(len(fit), len(evaluation)) >= limits['minimum_cases']
        failed = (test_metrics['accuracy_lower'] < limits['minimum_accuracy_lower']
            or any(test_metrics[metric] > limits[field] for metric, field in
                (('brier', 'maximum_brier'), ('ece', 'maximum_ece'), ('p95_latency_ms', 'maximum_p95_latency_ms')))
            or any(test_metrics[metric] is not None and test_metrics[metric] > limits[field] for metric, field in
                (('calibrated_top_brier', 'maximum_brier'), ('calibrated_ece', 'maximum_ece'))))
        complete = test_metrics['calibrated_coverage'] == 1 and all(
            min(bucket['count'], bucket['fit_count']) >= limits['minimum_bin_cases']
            for bucket in bins if bucket['count'])
        report['state'] = ('FAIL' if failed else 'PASS_OFFLINE_ONLY') if enough and complete else 'HOLD'
    if fit_metrics['forbidden'] or test_metrics['forbidden']:
        report['state'] = 'FAIL'
    return CalibrationArtifact(serialize(report))


from .calibration_selection import select_calibrated
