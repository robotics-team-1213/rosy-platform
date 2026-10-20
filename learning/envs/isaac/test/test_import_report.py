"""SDK exit and model-import proof are different evidence."""
import importlib
import json
from pathlib import Path
import sys

import pytest

ROOT = Path(__file__).resolve().parents[1]


def module():
    assert (ROOT / 'import_report.py').is_file(), 'Structured OMX import report is missing'
    sys.path.insert(0, str(ROOT))
    return importlib.import_module('import_report')


def test_report_requires_complete_frames_joints_and_asset_identity(tmp_path):
    mod = module()
    import model_checks
    path = tmp_path / 'report.json'
    mod.write_report(path, model='omx_f', frames=120, requested=120,
                     articulations=['/World/Manipulator'],
                     joints=sorted(model_checks.EXPECTED_JOINTS['omx_f']), sdk_version='5.1.0.0')
    report = mod.verify_report(path, model='omx_f', frames=120, sdk_version='5.1.0.0')
    assert report['task_success'] is None
    assert report['completed_frames'] == 120
    assert report['video_unavailable_reason']
    for key, value in [('completed_frames', 119), ('joints', []), ('assets_sha256', '0' * 64),
                       ('sdk_version', 'other'), ('articulations', []), ('task_success', True)]:
        path.write_text(json.dumps(dict(report, **{key: value})))
        with pytest.raises(ValueError):
            mod.verify_report(path, model='omx_f', frames=120, sdk_version='5.1.0.0')


def test_report_never_overwrites_and_missing_report_is_failure(tmp_path):
    mod = module()
    with pytest.raises(ValueError):
        mod.verify_report(tmp_path / 'missing.json', model='omx_f', frames=120, sdk_version='5.1.0.0')
    path = tmp_path / 'existing.json'
    path.write_text('previous proof')
    with pytest.raises(ValueError):
        mod.write_report(path, model='omx_f', frames=119, requested=120,
                         articulations=['/World/Manipulator'], joints=[], sdk_version='5.1.0.0')
    assert path.read_text() == 'previous proof'
