"""Measured profiles bind original lens/floor revisions and independent evidence."""
import copy
import importlib
import json
from pathlib import Path

import pytest

VECTOR = Path(__file__).resolve().parents[3] / 'test/fixtures/protocol/measured-calibration.v1.json'


def contract():
    return importlib.import_module('core_common.protocol.measured_calibration')


def vector():
    return json.loads(VECTOR.read_text(encoding='utf-8'))


def test_bundle_round_trip_preserves_evidence_and_does_not_apply():
    api = contract()
    raw = vector()
    bundle = api.validate_bundle(raw)
    assert bundle.model_dump(mode='json', by_alias=True) == raw
    assert api.bundle_digest(bundle) == raw['digest']
    assert bundle.evidence_kind == 'synthetic'
    assert bundle.lens['applied'] is False


@pytest.mark.parametrize('mutate', [
    lambda b: b['lens']['K'][0].__setitem__(0, 600.),
    lambda b: b['floor']['undistorted_to_map'][0].__setitem__(0, .02),
    lambda b: b['floor'].__setitem__('lens_revision', 'other'),
    lambda b: b['floor'].__setitem__('source_id', 'other'),
    lambda b: b['floor'].__setitem__('map_id', 'other'),
    lambda b: b['floor'].__setitem__('pixel_space', 'raw'),
    lambda b: b['capture'].__setitem__('signature', 'other'),
    lambda b: b['capture'].__setitem__('rotation_deg', True),
    lambda b: b['lens']['K'][0].__setitem__(0, True),
    lambda b: b['lens']['K'][0].__setitem__(0, float('nan')),
    lambda b: b['lens'].__setitem__('model', []),
    lambda b: b['lens'].__setitem__('model', {}),
    lambda b: b.__setitem__('bounds_m', [1., 0., -1., 1.]),
    lambda b: b['capture'].__setitem__('private_path', '/secret'),
    lambda b: b['validation_digests'].__setitem__(0, b['training_digests'][0]),
    lambda b: b.__setitem__('survey_digest', ''),
])
def test_outer_reseal_cannot_hide_invalid_or_unbound_input(mutate):
    api = contract()
    raw = copy.deepcopy(vector())
    mutate(raw)
    try:
        raw['digest'] = api.bundle_digest(raw)
    except ValueError:
        pass
    with pytest.raises(ValueError):
        api.validate_bundle(raw)


def test_content_tampering_without_reseal_is_rejected():
    raw = vector()
    raw['map_revision'] = 'another-map-revision'
    with pytest.raises(ValueError, match='digest'):
        contract().validate_bundle(raw)
