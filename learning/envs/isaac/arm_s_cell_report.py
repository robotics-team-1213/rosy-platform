"""Validate an arm S cell report independently of the task that wrote it (D-872)."""
import hashlib
import json
import os
import stat

from arm_s_cell_fixture import FIXTURE, evaluate, spec
from model_checks import ASSETS, check_vendor_manifest


def verify_report(path, *, scenario, frames_sha256, sdk_version):
    """``scenario``: the fixture name, or the checked case dict the run was given."""
    spec(scenario)  # KeyError / ValueError for an unknown name or a bad case
    fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    with os.fdopen(fd, 'rb') as stream:
        info = os.fstat(stream.fileno())
        if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1 or info.st_size > 1024*1024:
            raise ValueError('Unsafe arm S cell report')
        value = json.loads(stream.read(1024*1024+1))
    check_vendor_manifest()
    if (value.get('schema') != 'rosy.arm-s-cell-report/1' or value.get('scenario') != scenario
            or value.get('sdk_version') != sdk_version
            or value.get('fixture') != json.loads(json.dumps(FIXTURE)) or value.get('frames_sha256') != frames_sha256
            or value.get('assets_sha256') != hashlib.sha256((ASSETS/'manifest.json').read_bytes()).hexdigest()
            or not isinstance(value.get('samples'), list) or len(value['samples']) > 4000):
        raise ValueError('Mismatched arm S cell report')
    judgement = (evaluate(value['samples'], scenario) if value.get('error') is None
                 else dict(result='error', error=value['error'], matches_expectation=False))
    if value.get('judgement') != judgement:
        raise ValueError('Task result disagrees with the independent evaluation')
    images = value.get('images')
    if not isinstance(images, list) or any(name not in {'approach.png', 'grasp.png', 'transfer.png', 'release.png'}
                                           for name in images):
        raise ValueError('Invalid arm S cell image manifest')
    # the scenario's outcome was reproduced; a case without an expectation succeeds once it was measured
    value['task_success'] = judgement['matches_expectation'] is not False
    return value
