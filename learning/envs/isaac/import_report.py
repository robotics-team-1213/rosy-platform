"""Bounded, exclusive model-import proof; never a physical task result."""
import hashlib
import json
import os
from pathlib import Path
import stat

from model_checks import ASSETS, EXPECTED_JOINTS, check_vendor_manifest


def _validate(value, *, model, frames, sdk_version):
    check_vendor_manifest()
    digest = hashlib.sha256((ASSETS / 'manifest.json').read_bytes()).hexdigest()
    if (not isinstance(value, dict) or value.get('schema') != 'rosy.omx-import-report/1'
            or value.get('model') != model or value.get('sdk_version') != sdk_version
            or value.get('assets_sha256') != digest or value.get('requested_frames') != frames
            or type(value.get('completed_frames')) is not int or value['completed_frames'] != frames
            or frames <= 0 or value.get('task_success') is not None
            or value.get('import_verified') is not True
            or value.get('seed_effect') != 'NOT_USED_BY_MODEL_IMPORT'
            or not isinstance(value.get('joints'), list)
            or not all(isinstance(x, str) for x in value['joints'])
            or not EXPECTED_JOINTS[model] <= set(value['joints'])
            or not isinstance(value.get('articulations'), list)
            or len(value['articulations']) != 1
            or not isinstance(value['articulations'][0], str)
            or not value['articulations'][0].startswith('/')
            or value.get('video_unavailable_reason') != 'model_import_does_not_record_video'):
        raise ValueError('Incomplete or mismatched OMX import proof')
    return value


def write_report(path, *, model, frames, requested, articulations, joints, sdk_version):
    value = {'schema': 'rosy.omx-import-report/1', 'model': model,
             'completed_frames': frames, 'requested_frames': requested,
             'articulations': articulations, 'joints': sorted(joints), 'sdk_version': sdk_version,
             'assets_sha256': hashlib.sha256((ASSETS / 'manifest.json').read_bytes()).hexdigest(),
             'import_verified': True, 'task_success': None,
             'seed_effect': 'NOT_USED_BY_MODEL_IMPORT',
             'video_unavailable_reason': 'model_import_does_not_record_video'}
    _validate(value, model=model, frames=requested, sdk_version=sdk_version)
    try:
        with Path(path).open('x', encoding='utf-8') as stream:
            json.dump(value, stream, sort_keys=True, allow_nan=False)
            stream.flush()
            os.fsync(stream.fileno())
    except OSError as exc:
        raise ValueError('Import proof cannot be published exclusively') from exc


def verify_report(path, *, model, frames, sdk_version):
    try:
        fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
        with os.fdopen(fd, 'rb') as stream:
            info = os.fstat(stream.fileno())
            if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1 or info.st_size > 1024 * 1024:
                raise ValueError('Unsafe import proof')
            value = json.loads(stream.read(1024 * 1024 + 1))
        return _validate(value, model=model, frames=frames, sdk_version=sdk_version)
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise ValueError('Import proof is missing or unreadable') from exc
