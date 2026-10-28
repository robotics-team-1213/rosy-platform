"""The shipping workshop's real numerical output can be exported without paths."""
import importlib
import hashlib
import json
from pathlib import Path

import pytest

from rosy_vision.camera_calibration import fit_floor, fit_lenses
from test_camera_calibration import views


@pytest.mark.parametrize('model', ['pinhole', 'fisheye'])
def test_export_actual_workshop_candidates_and_reject_wrong_lens(model):
    exporter = importlib.import_module('rosy_vision.calibration_bundle')
    from core_common.protocol.measured_calibration import validate_bundle
    vector = json.loads((Path(__file__).resolve().parents[3]
                         / 'test/fixtures/protocol/measured-calibration.v1.json').read_text())
    samples = views(model)
    for sample in samples:
        sample['digest'] = hashlib.sha256(sample['digest'].encode()).hexdigest()
    report = fit_lenses(samples[:12], samples[12:], (640, 480),
                        source_id='ceiling_north', capture_signature='g', models=(model,))
    import numpy as np
    pixels = np.array([[50., 50.], [550., 50.], [550., 400.], [50., 400.]])
    checks = np.array([[150., 120.], [460., 130.], [300., 320.]])
    floor = fit_floor(report['candidates'][0], pixels, pixels/200-1, checks, checks/200-1,
                      map_id='map_v2_fleet', pixel_space='undistorted')
    context = {key: vector[key] for key in ('map_revision', 'survey_digest', 'capture',
                                          'bounds_m', 'evidence_kind')}
    context['capture'] = {**context['capture'], 'signature': 'g'}
    raw = exporter.export_bundle(report, floor, context)
    parsed = validate_bundle(raw)
    assert parsed.lens['revision'] == report['candidates'][0]['revision']
    assert parsed.floor['revision'] == floor['revision']
    assert 'training' not in raw and 'path' not in json.dumps(raw)
    with pytest.raises(ValueError):
        exporter.export_bundle(report, {**floor, 'lens_revision': 'wrong'}, context)
