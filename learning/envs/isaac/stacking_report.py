"""Check a bounded training proof without loading or executing its checkpoint."""
import hashlib
import json
import math
import os
from pathlib import Path
import stat

from model_checks import EXPECTED_JOINTS
from stacking_fixture import FIXTURE


def read_regular(path, limit=1024*1024):
    fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    with os.fdopen(fd, 'rb') as stream:
        info = os.fstat(stream.fileno())
        if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1 or not 0 < info.st_size <= limit:
            raise ValueError('Unsafe stacking evidence')
        return stream.read(limit+1)


def verify_report(path, *, sdk_version, seed):
    path = Path(path)
    value = json.loads(read_regular(path))
    if (value.get('schema') != 'rosy.omx-stacking-rl/1' or value.get('fixture') != json.loads(json.dumps(FIXTURE))
            or value.get('sdk_version') != sdk_version or value.get('seed') != seed
            or value.get('updates') != 32 or value.get('transitions') != 1024
            or value.get('training_verified') is not True or value.get('attachment_aid') is not False
            or type(value.get('parameter_delta')) not in (int, float)
            or not math.isfinite(value['parameter_delta']) or value['parameter_delta'] <= 0
            or value.get('evaluation_episodes') != 1
            or value.get('evaluation_seed') != seed+FIXTURE['evaluation_seed_offset']
            or type(value.get('evaluation_steps')) is not int or not 1 <= value['evaluation_steps'] <= 600
            or type(value.get('evaluation_successes')) is not int or value['evaluation_successes'] not in (0, 1)
            or value.get('task_success') is not (value['evaluation_successes'] == 1)
            or value.get('images') != ['stacking-initial.png', 'stacking-evaluation.png']
            or len(value.get('articulations', [])) != 2 or len(set(value['articulations'])) != 2
            or len(value.get('joints', [])) != 2
            or any(not EXPECTED_JOINTS['omx_f'].intersection({'joint1','joint2','joint3','joint4','joint5',
                       'gripper_joint_1','gripper_joint_2'}) <= set(joints) for joints in value['joints'])):
        raise ValueError('Incomplete or mismatched stacking training proof')
    checkpoint = value.get('checkpoint', {})
    if checkpoint.get('name') != 'stacking-policy.pt':
        raise ValueError('Unexpected stacking checkpoint')
    raw = read_regular(path.parent/'stacking-policy.pt')
    if checkpoint.get('bytes') != len(raw) or checkpoint.get('sha256') != hashlib.sha256(raw).hexdigest():
        raise ValueError('Stacking checkpoint fingerprint differs')
    return value
