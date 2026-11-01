"""Recompute mapped physical success from bounded raw contact observations."""
import json
import math
from pathlib import Path

from mapped_stack_fixture import CUBE_FIXTURE, CUBE_REPORT_BYTES, CONTAINER_REPORT_BYTES, FIXTURE, belt_transport_observed, container_fixture, cube_release_ready, judge, plan, source_height_observed, contact_names, leveling_sequence_observed
from stacking_report import read_regular


def verify_report(path, *, sdk_version, seed, cube=False, container=None):
    fixture = container_fixture(layers=container['layers'], case=container['case']) if container else CUBE_FIXTURE if cube else FIXTURE
    count = len(plan(cube, fixture=fixture))
    value = json.loads(read_regular(Path(path), limit=CONTAINER_REPORT_BYTES if container else CUBE_REPORT_BYTES if cube else 1024*1024))
    schema = 'rosy.omx-container-stack/1' if container else 'rosy.omx-map-cube-stack/1' if cube else 'rosy.omx-map-long-stack/1'
    if (value.get('schema') != schema or value.get('fixture') != fixture
            or value.get('seed') != seed or value.get('sdk_version') != sdk_version
            or value.get('controller') != FIXTURE['controller'] or value.get('attachment_aid') is not False
            or not isinstance(value.get('trials'), list) or not 1 <= len(value['trials']) <= fixture['trials']):
        raise ValueError('Mapped scene provenance differs')
    images = value.get('images')
    allowed = {'mapped-overview.png', 'mapped-initial.png', 'mapped-grasp-failed.png'} | ({'mapped-top.png', 'mapped-side.png'} if cube else set()) | {
        f'mapped-{kind}-{i}.png' for kind in ('layer', 'trial') for i in range(1, count+1)}
    if fixture.get('leveling_protocol'):
        allowed |= {f'mapped-leveling-{i}.png' for i in range(1,count+1)}
    if (not isinstance(images, list) or len(set(images)) != len(images) or not set(images) <= allowed
            or not {'mapped-overview.png', 'mapped-initial.png'} <= set(images)):
        raise ValueError('Unexpected mapped images')
    try:
        for i, trial in enumerate(value['trials']):
            if trial['seed'] != seed+i or not 0 <= len(trial['layers']) <= count:
                raise ValueError('Trial mismatch')
            for layer in trial['layers']:
                if container and fixture.get('packing_strategy') and 'opened_sample' in layer:
                    if not cube_release_ready(layer['item'], layer['release_sample'], layer['source_center_z'], fixture=fixture):
                        raise ValueError('Opened container lacks measured packing and swept-pad clearance')
                    if fixture.get('leveling_protocol') and not leveling_sequence_observed(layer,layer['item'],fixture):
                        raise ValueError('Opened container lacks measured tabletop leveling and regrasp')
                start, end = layer['infeed_start'], layer['infeed_settled']
                if (len(start) != 3 or len(end) != 3
                        or not all(type(x) in (int, float) and math.isfinite(x) for x in start+end)
                        or not belt_transport_observed(start, end, cube, fixture=fixture)
                        or abs(end[2]-layer['source_center_z']) > 1e-6):
                    raise ValueError('Belt transport was not observed for this layer')
                if not math.isfinite(layer['source_center_z']) or not source_height_observed(end,fixture):
                    raise ValueError('Invalid belt source height')
                collections = [layer['lift_samples'],layer['settle_samples'],layer.get('prefix_window',[])]
                if 'leveling' in layer:
                    stage = layer['leveling']
                    if not isinstance(stage,dict):
                        raise ValueError('Malformed leveling observations')
                    collections += [stage.get(k,[]) for k in ('lift_samples','settle_samples','grasp_samples','prefix_window')]
                    collections += [[stage[k]] for k in ('release_sample','opened_sample') if k in stage]
                for samples in collections:
                    if not isinstance(samples, list) or len(samples) > 30:
                        raise ValueError('Unbounded contact samples')
                    prior_tick = -1
                    for sample in samples:
                        if type(sample['tick']) is not int or sample['tick'] <= prior_tick:
                            raise ValueError('Contact ticks are not increasing')
                        prior_tick = sample['tick']
                        if len(sample['boxes']) != count or len(sample['tcps']) != 2:
                            raise ValueError('Missing measured bodies')
                        for j,box in enumerate(sample['boxes']):
                            if [len(box[k]) for k in ('position', 'orientation', 'velocity', 'angular_velocity', 'forces', 'net_force')] != [3, 4, 3, 3, len(contact_names(j,cube,fixture=fixture)), 3]:
                                raise ValueError('Malformed rigid body observation')
                            vectors = [box['position'], box['orientation'], box['velocity'], box['angular_velocity'], box['net_force'], *box['forces']]
                            if any(len(v) != 3 for v in box['forces']):
                                raise ValueError('Malformed contact vector')
                            if not all(type(x) in (int, float) and math.isfinite(x) for v in vectors for x in v):
                                raise ValueError('Nonfinite rigid body observation')
                        if any(len(tcp) != 3 or not all(math.isfinite(x) for x in tcp) for tcp in sample['tcps']):
                            raise ValueError('Malformed measured TCP')
            actual = judge(trial, cube, fixture=fixture)
            if any(trial.get(k) != actual[k] for k in actual):
                raise ValueError('Claimed trial success differs from measured contacts')
        success = len(value['trials']) == fixture['trials'] and all(t['task_success'] for t in value['trials'])
        if value.get('task_success') is not success:
            raise ValueError('Claimed task success differs')
        if success and not {f'mapped-trial-{i}.png' for i in range(1, fixture['trials']+1)} | {f'mapped-layer-{count}.png'} <= set(images):
            raise ValueError('Missing completed stack images')
    except (KeyError, TypeError, IndexError) as exc:
        raise ValueError('Malformed mapped observations') from exc
    if container:
        from container_recording import verify_video
        video = verify_video(Path(path).parent, value.get('video'), fixture)
        last_tick = max((sample['tick'] for trial in value['trials'] for layer in trial['layers']
            for sample in layer['settle_samples']+layer['lift_samples']), default=0)
        if video['last_tick'] < last_tick:
            raise ValueError('Video ends before the physical observations')
    return value


def summarize(report):
    """What a container run did, from its report: placements, error, final row gaps and unstable boxes."""
    from mapped_stack_fixture import norm, row_gaps, stable_box
    fixture, trial = report['fixture'], report['trials'][0]
    items = plan(True, fixture=fixture)
    layers = trial.get('layers', [])
    settled = [l['settle_samples'][-1] for l in layers if l.get('settle_samples')]
    sample = trial.get('failure_sample') or (settled[-1] if settled else None)
    placed = sum('opened_sample' in l for l in layers)
    unstable = []
    for j, box in enumerate(sample['boxes'][:placed] if sample else []):
        if not stable_box(box, j, True, fixture=fixture):
            unstable.append(dict(box=j, position_error_mm=round(1000*max(abs(box['position'][k]-items[j]['target'][k])
                                                                          for k in range(3)), 3),
                                 speed_m_s=round(norm(box['velocity']), 4), angular_rad_s=round(norm(box['angular_velocity']), 4)))
    return dict(task_success=report.get('task_success'), placed=placed,
                planned=len(items), error=trial.get('error'), failures=trial.get('failures'),
                row_gaps_mm=[round(g*1000, 3) for g in row_gaps(sample, fixture, placed)] if sample and fixture.get('row_gap_band_m') else None,
                unstable=unstable, frames=report.get('video', {}).get('frames'))


if __name__ == '__main__':
    import sys
    if len(sys.argv) != 3 or sys.argv[1] != 'summary':
        sys.exit('usage: mapped_stack_report.py summary <mapped-stack-report.json>')
    print(json.dumps(summarize(json.loads(Path(sys.argv[2]).read_text(encoding='utf-8'))), ensure_ascii=False))
