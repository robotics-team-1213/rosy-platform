"""Same held-out truth comparison; offline quality never grants runtime promotion."""
from .calibration import CalibrationArtifact, LINEAGE, evaluate_calibration
from .calibration_metrics import digest, serialize

FIELDS = {'fit', 'evaluation', 'training', 'reviewed_profile'}
TRUTH = ('id', *LINEAGE, 'expected', 'reviewed_by')
LOWER_IS_BETTER = ('brier', 'ece', 'p95_latency_ms')
HIGHER_IS_BETTER = ('accuracy_lower', 'calibrated_coverage')


def compare_calibrations(bundles):
    if type(bundles) not in (list, tuple) or not 2 <= len(bundles) <= 4:
        raise ValueError('INVALID_COMPARISON_CANDIDATES')
    candidates, profiles, common, baseline = [], set(), None, None
    truth_sha = None
    for bundle in bundles:
        if type(bundle) is not dict or set(bundle) != FIELDS:
            raise ValueError('INVALID_CALIBRATION_BUNDLE')
        artifact = evaluate_calibration(bundle['fit'], bundle['evaluation'],
            training=bundle['training'], reviewed_profile=bundle['reviewed_profile'])
        report = artifact.report
        profile_sha = report['full_profile_sha256']
        if profile_sha in profiles:
            raise ValueError('DUPLICATE_COMPARISON_PROFILE')
        profiles.add(profile_sha)
        truth = sorted(({field: row[field] for field in TRUTH}
                        for row in bundle['evaluation']), key=lambda row: row['id'])
        current = dict(truth=truth, domain=report['domain'], choices=report['choices'],
                       limits=report['limits'])
        if common is None:
            common, baseline, truth_sha = current, report['metrics'], digest(truth)
        elif current != common:
            raise ValueError('COMPARISON_TRUTH_OR_CRITERIA_CHANGED')
        metrics = report['metrics']
        regressions = [key for key in LOWER_IS_BETTER if metrics[key] > baseline[key]]
        regressions += [key for key in HIGHER_IS_BETTER if metrics[key] < baseline[key]]
        for key in ('calibrated_top_brier', 'calibrated_ece'):
            if baseline[key] is not None and (metrics[key] is None or metrics[key] > baseline[key]):
                regressions.append(key)
        candidates.append(dict(full_profile_sha256=profile_sha, artifact_sha256=artifact.digest,
            calibration_state=report['state'], metrics=metrics, regressions=regressions))
    state = ('FAIL' if any(row['calibration_state'] == 'FAIL' or row['regressions'] for row in candidates)
             else 'PASS_COMPARISON_OFFLINE_ONLY' if all(row['calibration_state'] == 'PASS_OFFLINE_ONLY'
                                                      for row in candidates) else 'HOLD')
    return CalibrationArtifact(serialize(dict(schema='rosy.calibration.comparison/1', state=state,
        promotion_state='HOLD', field_accepted=False, evaluation_truth_sha256=truth_sha,
        baseline_profile_sha256=candidates[0]['full_profile_sha256'], candidates=candidates,
        missing_operational_evidence=['closure', 'unknown_outcome', 'recurrence', 'handoff', 'actual_cost'])))
