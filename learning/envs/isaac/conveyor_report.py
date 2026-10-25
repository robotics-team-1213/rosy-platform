"""Validate bounded contact observations separately from the SDK controller."""
import hashlib
import json
import os
from pathlib import Path
import stat

from conveyor_fixture import FIXTURE, evaluate, fixture_sha256
from model_checks import ASSETS, EXPECTED_JOINTS, check_vendor_manifest


def verify_report(path, *, sdk_version):
    fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    with os.fdopen(fd, 'rb') as stream:
        info = os.fstat(stream.fileno())
        if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1 or info.st_size > 1024*1024:
            raise ValueError('Unsafe contact report')
        value = json.loads(stream.read(1024*1024+1))
    check_vendor_manifest()
    if (value.get('schema') != 'rosy.pinky-conveyor-report/1'
            or value.get('sdk_version') != sdk_version or value.get('fixture') != json.loads(json.dumps(FIXTURE))
            or value.get('fixture_sha256') != fixture_sha256()
            or value.get('assets_sha256') != hashlib.sha256((ASSETS/'manifest.json').read_bytes()).hexdigest()
            or not EXPECTED_JOINTS['omx_f'] <= set(value.get('joints', []))
            or not isinstance(value.get('samples'), list) or len(value['samples']) > 1200
            or type(value.get('completed_frames')) is not int or not 0 < value['completed_frames'] <= 4800
            or value.get('attachment_aid') is not False):
        raise ValueError('Mismatched contact report')
    judgement = evaluate(value['samples'])
    if value.get('error') is not None:
        judgement = dict(task_success=False, failures=[value['error']], evidence_class='INCOMPLETE_CONTACT_TASK')
    if value.get('judgement') != judgement:
        raise ValueError('Controller result disagrees with independent contact evaluation')
    images = value.get('images')
    if not isinstance(images, list) or any(name not in {
            'pinky_initial.png', 'out_lift.png', 'conveyor_settle.png',
            'back_lift.png', 'pinky_settle.png'} for name in images) or len(set(images)) != len(images):
        raise ValueError('Invalid contact image manifest')
    if judgement['task_success'] and len(images) != 5:
        raise ValueError('Successful contact task needs all phase images')
    value.update(stage='contact_roundtrip', task_success=judgement['task_success'], import_verified=True)
    return value
