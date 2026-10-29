"""Recompute mapped physical success from bounded raw contact observations."""
import json
import math
from pathlib import Path

from mapped_stack_fixture import CUBE_FIXTURE, CUBE_REPORT_BYTES, FIXTURE, judge, plan
from stacking_report import read_regular


def verify_report(path, *, sdk_version, seed, cube=False):
    fixture = CUBE_FIXTURE if cube else FIXTURE
    count = len(plan(cube))
    value = json.loads(read_regular(Path(path), limit=CUBE_REPORT_BYTES if cube else 1024*1024))
    if (value.get('schema') != ('rosy.omx-map-cube-stack/1' if cube else 'rosy.omx-map-long-stack/1') or value.get('fixture') != fixture
            or value.get('seed') != seed or value.get('sdk_version') != sdk_version
            or value.get('controller') != FIXTURE['controller'] or value.get('attachment_aid') is not False
            or not isinstance(value.get('trials'), list) or not 1 <= len(value['trials']) <= fixture['trials']):
        raise ValueError('Mapped scene provenance differs')
    images = value.get('images')
    allowed = {'mapped-overview.png', 'mapped-initial.png', 'mapped-grasp-failed.png'} | ({'mapped-top.png', 'mapped-side.png'} if cube else set()) | {
        f'mapped-{kind}-{i}.png' for kind in ('layer', 'trial') for i in range(1, count+1)}
    if (not isinstance(images, list) or len(set(images)) != len(images) or not set(images) <= allowed
            or not {'mapped-overview.png', 'mapped-initial.png'} <= set(images)):
        raise ValueError('Unexpected mapped images')
    try:
        for i, trial in enumerate(value['trials']):
            if trial['seed'] != seed+i or not 0 <= len(trial['layers']) <= count:
                raise ValueError('Trial mismatch')
            for layer in trial['layers']:
                start, end = layer['infeed_start'], layer['infeed_settled']
                if (len(start) != 3 or len(end) != 3
                        or not all(type(x) in (int, float) and math.isfinite(x) for x in start+end)
                        or not .01 < end[1]-start[1] < .06
                        or abs(end[2]-layer['source_center_z']) > 1e-6):
                    raise ValueError('Belt transport was not observed for this layer')
                if not math.isfinite(layer['source_center_z']) or not .035 <= layer['source_center_z'] <= .05:
                    raise ValueError('Invalid belt source height')
                for samples in (layer['lift_samples'], layer['settle_samples']):
                    if not isinstance(samples, list) or len(samples) > 30:
                        raise ValueError('Unbounded contact samples')
                    prior_tick = -1
                    for sample in samples:
                        if type(sample['tick']) is not int or sample['tick'] <= prior_tick:
                            raise ValueError('Contact ticks are not increasing')
                        prior_tick = sample['tick']
                        if len(sample['boxes']) != count or len(sample['tcps']) != 2:
                            raise ValueError('Missing measured bodies')
                        for box in sample['boxes']:
                            if [len(box[k]) for k in ('position', 'orientation', 'velocity', 'angular_velocity', 'forces', 'net_force')] != [3, 4, 3, 3, count+5, 3]:
                                raise ValueError('Malformed rigid body observation')
                            vectors = [box['position'], box['orientation'], box['velocity'], box['angular_velocity'], box['net_force'], *box['forces']]
                            if any(len(v) != 3 for v in box['forces']):
                                raise ValueError('Malformed contact vector')
                            if not all(type(x) in (int, float) and math.isfinite(x) for v in vectors for x in v):
                                raise ValueError('Nonfinite rigid body observation')
                        if any(len(tcp) != 3 or not all(math.isfinite(x) for x in tcp) for tcp in sample['tcps']):
                            raise ValueError('Malformed measured TCP')
            actual = judge(trial, cube)
            if any(trial.get(k) != actual[k] for k in actual):
                raise ValueError('Claimed trial success differs from measured contacts')
        success = len(value['trials']) == fixture['trials'] and all(t['task_success'] for t in value['trials'])
        if value.get('task_success') is not success:
            raise ValueError('Claimed task success differs')
        if success and not {f'mapped-trial-{i}.png' for i in range(1, fixture['trials']+1)} | {f'mapped-layer-{count}.png'} <= set(images):
            raise ValueError('Missing completed stack images')
    except (KeyError, TypeError, IndexError) as exc:
        raise ValueError('Malformed mapped observations') from exc
    return value
