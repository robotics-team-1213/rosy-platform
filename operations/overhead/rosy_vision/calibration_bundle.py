"""Export D-636 numerical reports to the D-775 preview contract, without paths."""
from copy import deepcopy
from typing import Mapping

from core_common.protocol.measured_calibration import bundle_digest, validate_bundle


def export_bundle(report: Mapping, floor: Mapping, context: Mapping) -> dict:
    candidates = [row for row in report['candidates'] if row['revision'] == floor['lens_revision']]
    if len(candidates) != 1:
        raise ValueError('floor needs exactly one matching measured lens candidate')
    if set(context) != {'map_revision', 'survey_digest', 'capture', 'bounds_m', 'evidence_kind'}:
        raise ValueError('explicit map, survey and capture context required')
    lens = candidates[0]
    if report['source_id'] != lens['source_id'] or report['capture_signature'] != lens['capture_signature']:
        raise ValueError('report and candidate identity mismatch')
    raw = {'schema': 'rosy.measured-calibration/1', 'source_id': lens['source_id'],
           'map_id': floor['map_id'], 'lens': deepcopy(lens), 'floor': deepcopy(floor),
           'training_digests': list(report['training_digests']),
           'validation_digests': list(report['validation_digests']), **deepcopy(context)}
    raw['digest'] = bundle_digest(raw)
    return validate_bundle(raw).model_dump(mode='json', by_alias=True)
