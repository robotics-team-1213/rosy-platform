"""Pure frozen evidence diagnostics; no operations imports or operating acceptance."""
from .operational_comparison import compare_with_inventory, fields, sha, timestamp
from .operational_sources import digest, encoded, verify_attestation, validate_window
from .operational_truth import measure_truth

BUNDLE = ('schema', 'profiles', 'profile', 'calibration_input', 'cohort', 'exports', 'inventories',
          'inventory_digests', 'truth', 'limits', 'windows', 'review')
LIMITS = ('minimum_cases', 'minimum_accuracy_lower', 'maximum_p95_latency_ms', 'maximum_cost_usd',
          'minimum_resolved_rate', 'maximum_recurrence_rate', 'maximum_capture_gap_s')
SUPPORTED = ('rosy.incident.operational_cohort/1', 'rosy.incident.operational_cohort/2',
    'rosy.incident.model_feedback/1', 'rosy.incident.model_feedback/2', 'rosy.incident.model_feedback/3',
    'rosy.incident.rule_feedback/1', 'rosy.incident.case_inventory/1',
    'rosy.pinky-raw-verification/1', 'rosy.fleet-observation-window/1')
UNSUPPORTED = ('feedback_prediction_export_lineage_admission',
    'authenticated_full_command_model_collector', 'physical_actor_credit', 'clock_calibration_admission',
    'original_cost_invoice_admission', 'physical_result_admission', 'recurrence_source_admission',
    'current_runtime_os_probe_admission', 'door_backend', 'arm_target_backend')


def reviewed_limits(document):
    fields(document, ('schema', 'values', 'attestation'))
    if document['schema'] != 'rosy.incident.operational_limits/1': raise ValueError('INVALID_OPERATING_LIMITS_SCHEMA')
    limits = document['values']; fields(limits, LIMITS)
    if type(limits['minimum_cases']) is not int or not 1 <= limits['minimum_cases'] <= 10000:
        raise ValueError('INVALID_OPERATING_MINIMUM_CASES')
    for field in LIMITS[1:]:
        value = timestamp(limits[field])
        if field.endswith('_rate') or field == 'minimum_accuracy_lower':
            if value > 1: raise ValueError('INVALID_OPERATING_RATE')
    if limits['maximum_capture_gap_s'] <= 0: raise ValueError('INVALID_OPERATING_CAPTURE_GAP')
    return limits


def compile_evidence(bundle, *, trusted, now, originals=None, profile_calibration=None):
    fields(bundle, BUNDLE); encoded(bundle); timestamp(now)
    if bundle['schema'] != 'rosy.incident.operational_evidence/1': raise ValueError('INVALID_OPERATING_BUNDLE_SCHEMA')
    profiles, selected = bundle['profiles'], bundle['profile']
    if (type(profiles) is not list or not 1 <= len(profiles) <= 2 or type(selected) is not dict
            or any(type(p) is not dict for p in profiles) or selected not in profiles):
        raise ValueError('OPERATING_FULL_PROFILE_NOT_SELECTED')
    missing = [name for name, key in (('calibration', 'calibration_input'), ('cohort', 'cohort'), ('truth', 'truth'),
                                    ('limits', 'limits'), ('windows', 'windows'), ('review', 'review')) if not bundle[key]]
    if type(selected.get('domains')) not in (list, tuple) or 'line_follow' not in selected['domains']:
        missing.append('domain_backend_not_supported')
    profile_set_sha256 = full_profile_sha256 = calibration_sha256 = None
    scope = 'not_recomputed'
    if bundle['calibration_input'] is not None:
        fields(bundle['calibration_input'], ('fit', 'evaluation', 'training', 'reviewed_profile'))
    if profile_calibration is None:
        missing.append('root_profile_calibration_not_recomputed')
    else:
        fields(profile_calibration, ('bundle_sha256', 'profile_set_sha256', 'full_profile_sha256',
                                    'calibration_sha256', 'calibration_state', 'domains'))
        if sha(profile_calibration['bundle_sha256']) != digest(bundle):
            raise ValueError('PROFILE_CALIBRATION_DIAGNOSTIC_BUNDLE_DIFFERS')
        profile_set_sha256 = sha(profile_calibration['profile_set_sha256'])
        full_profile_sha256 = sha(profile_calibration['full_profile_sha256'])
        calibration_sha256 = profile_calibration['calibration_sha256']
        state, domains = profile_calibration['calibration_state'], profile_calibration['domains']
        if (type(domains) is not list or not 1 <= len(domains) <= 3
                or any(d not in ('line_follow', 'door', 'arm_target') for d in domains)
                or len(set(domains)) != len(domains)):
            raise ValueError('INVALID_PROFILE_CALIBRATION_DIAGNOSTIC_DOMAINS')
        if calibration_sha256 is None:
            if state is not None or bundle['calibration_input'] is not None:
                raise ValueError('INVALID_PROFILE_CALIBRATION_DIAGNOSTIC_STATE')
        else:
            sha(calibration_sha256)
            if state not in ('HOLD', 'FAIL', 'PASS_OFFLINE_ONLY') or bundle['calibration_input'] is None:
                raise ValueError('INVALID_PROFILE_CALIBRATION_DIAGNOSTIC_STATE')
        if state != 'PASS_OFFLINE_ONLY': missing.append('accepted_calibration')
        scope = 'caller_supplied_diagnostics_only'
    comparison = None
    if bundle['cohort'] is not None:
        comparison = compare_with_inventory(bundle['cohort'], bundle['exports'], bundle['inventories'],
                                            expected_digests=bundle['inventory_digests'])
    elif any(bundle[k] for k in ('exports', 'inventories', 'inventory_digests')):
        raise ValueError('OPERATING_ORPHANED_COHORT_ORIGINALS')
    limits = None
    if bundle['limits'] is not None:
        limits = reviewed_limits(bundle['limits'])
        verify_attestation(bundle['limits']['attestation'], {k: v for k, v in bundle['limits'].items() if k != 'attestation'},
                           trusted=trusted, kind='operational_limits', now=now)
    windows = [validate_window(w, trusted=trusted, now=now) for w in bundle['windows']]
    if len({w['source_sha256'] for w in windows}) != len(windows): raise ValueError('DUPLICATE_OPERATING_WINDOW')
    if limits and any(gap > limits['maximum_capture_gap_s'] for w in windows for s in w['streams'].values() for gap in s['gaps']):
        missing.append('complete_capture_cadence')
    metrics = None
    if bundle['truth'] is not None:
        fields(bundle['truth'], ('schema', 'rows', 'attestation'))
        if bundle['truth']['schema'] != 'rosy.incident.operational_truth/1': raise ValueError('INVALID_OPERATING_TRUTH_SCHEMA')
        verify_attestation(bundle['truth']['attestation'], {k: v for k, v in bundle['truth'].items() if k != 'attestation'},
                           trusted=trusted, kind='operational_truth', now=now)
        metrics, missing_truth = measure_truth(bundle['truth']['rows']); missing.extend(missing_truth)
    if bundle['review'] is not None:
        original = {k: v for k, v in bundle.items() if k != 'review'}
        review = verify_attestation(bundle['review'], original, trusted=trusted, kind='operational_review', now=now)
        if any(w['attestation']['principal'] == review['principal'] for w in bundle['windows']):
            raise ValueError('INDEPENDENT_REVIEWER_AND_SOURCE_REQUIRED')
    # Original recorder/command/result correlation is required even with signed review metadata.
    if originals is None: missing.append('verified_original_sources')
    elif type(originals) is not dict or set(originals) != {'raw_recordings', 'observation_windows', 'coverage_scope'}:
        raise ValueError('ORIGINAL_SOURCE_LOADER_CONTRACT_REQUIRED')
    elif originals['coverage_scope'] != 'raw_sidecar_and_retained_observations_only':
        raise ValueError('ORIGINAL_SOURCE_SCOPE_CANNOT_BE_WIDENED')
    elif not originals['raw_recordings'] or not originals['observation_windows']:
        missing.append('verified_original_sources')
    missing.extend(UNSUPPORTED)
    return dict(schema='rosy.incident.operational_acceptance/1', state='HOLD', missing=sorted(set(missing)),
        field_accepted=False, truth_admitted=False, evidence_sha256=digest(bundle),
        profile_set_sha256=profile_set_sha256, full_profile_sha256=full_profile_sha256,
        calibration_sha256=calibration_sha256, profile_calibration_scope=scope,
        comparison_sha256=digest(comparison) if comparison else None,
        coverage_sha256=digest(windows) if windows else None, limits_sha256=digest(bundle['limits']) if limits else None,
        truth_sha256=digest(bundle['truth']) if bundle['truth'] else None, metrics=metrics,
        metrics_scope='authenticated_review_declarations_only',
        supported_original_contracts=list(SUPPORTED), unsupported=list(UNSUPPORTED))
