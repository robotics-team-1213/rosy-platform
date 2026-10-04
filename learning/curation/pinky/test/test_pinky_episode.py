"""Historical Pinky recordings keep final commands, source clocks and unknown outcomes."""
import hashlib
import json
from pathlib import Path
import sys

import pytest

ROOT = Path(__file__).resolve().parents[4]
sys.path[:0] = [str(ROOT / 'contracts/learning/src'), str(ROOT / 'learning/curation/pinky'),
               str(ROOT / 'learning/registry/policy')]
from rosy.contracts.learning import seal
from rosy.contracts.learning.pinky import validate_profile, validate_recording
from pinky_episode import convert
from dataset_store import DatasetStore


def recording(root):
    raw = root / 'capture'; (raw / 'bag').mkdir(parents=True)
    (raw / 'bag/bag_0.mcap').write_bytes(b'fixture raw file; not decoded MCAP evidence')
    session = {'schema': 'rosy.recording.session/1', 'device': 'fixture-pinky',
               'camera_profile_revision': None, 'model_revision': None, 'task_id': 'capture-purpose',
               'reason': 'capture curve', 'started_at': '2026-09-30T00:00:00+00:00',
               'ended_at': '2026-09-30T00:00:02+00:00', 'harvested': False,
               'topics': ['camera/front', 'cmd_vel']}
    (raw / 'session.json').write_text(json.dumps(session))
    video = root / 'video'; video.mkdir()
    (video / 'capture.mp4').write_bytes(b'fixture video; no decoded pixels')
    rows = [{'index': i, 't': 1.0 + i * .1, 'stamp_ns': 1_000_000_000 + i * 100_000_000,
             'log_ns': 1_010_000_000 + i * 100_000_000,
             'side': {'cmd_vel': {'linear': .02, 'angular': -.1}}, 'dt': {'cmd_vel': -.01}}
            for i in range(2)]
    (video / 'capture.jsonl').write_text('\n'.join(json.dumps(row) for row in rows)+'\n')
    metadata = {'schema': 'rosy.teleop.video/1', 'session': session,
                'source': {'session': 'capture', 'bag_bytes': (raw / 'bag/bag_0.mcap').stat().st_size},
                'video': {'file': 'capture.mp4', 'bytes': (video / 'capture.mp4').stat().st_size, 'frames': 2,
                          'width': 8, 'height': 6, 'fps': 10},
                'sidecar': {'file': 'capture.jsonl', 'max_gap_s': .5}, 'scan': None}
    meta = video / 'capture.json'; meta.write_text(json.dumps(metadata))
    return raw, meta


def test_snapshot_register_preserves_unknown_and_no_fleet_ids(tmp_path):
    raw, meta = recording(tmp_path)
    output = tmp_path / 'common'
    doc = convert(raw, meta, output, environment='real', clock_domain='ros_system')
    assert doc['outcome'] == {'task': 'unknown', 'action': 'unknown', 'judge': 'unknown', 'evidence': []}
    assert doc['correlations'] == {'action_ids': [], 'attempt_ids': []}
    assert doc['revisions'] == dict(policy=None, model=None, calibration=None, camera_profile=None)
    assert doc['task'] == 'capture curve'
    assert validate_profile(doc, root=output)['commands'] == 2
    manifest = DatasetStore(tmp_path / 'store').register(output)
    (raw / 'bag/bag_0.mcap').write_bytes(b'changed later')
    assert DatasetStore(tmp_path / 'store').require([manifest['revision']]) == [manifest['revision']]


@pytest.mark.parametrize('change,reason', [
    (lambda row: row['dt'].update(cmd_vel=.01), 'future'),
    (lambda row: row['dt'].update(cmd_vel=-1), 'stale'),
    (lambda row: row['side']['cmd_vel'].update(linear=float('nan')), 'finite'),
    (lambda row: row.update(stamp_ns=True), 'clocks'),
    (lambda row: row.update(t=9), 'timestamp'),
])
def test_invalid_sidecar_refused_before_output(tmp_path, change, reason):
    raw, meta = recording(tmp_path)
    sidecar = meta.with_suffix('.jsonl')
    rows = [json.loads(row) for row in sidecar.read_text().splitlines()]
    change(rows[0]); sidecar.write_text('\n'.join(json.dumps(row) for row in rows))
    with pytest.raises(ValueError, match=reason):
        convert(raw, meta, tmp_path / 'output', environment='real', clock_domain='ros_system')
    assert not (tmp_path / 'output').exists()


def test_original_metadata_and_common_binding_cannot_be_relabelled(tmp_path):
    raw, meta = recording(tmp_path)
    doc = convert(raw, meta, tmp_path / 'common', environment='real', clock_domain='ros_system')
    doc['device'] = 'another-pinky'
    with pytest.raises(ValueError, match='binding'):
        validate_profile(seal(doc), root=tmp_path / 'common')
    session = json.loads((raw / 'session.json').read_text()); session['ended_at'] = None
    (raw / 'session.json').write_text(json.dumps(session))
    with pytest.raises(ValueError, match='session binding'):
        validate_recording(meta, raw)


def test_resealed_future_command_still_fails_dataset_registration(tmp_path):
    raw, meta = recording(tmp_path); output = tmp_path / 'common'
    doc = convert(raw, meta, output, environment='real', clock_domain='ros_system')
    sidecar = output / 'source/video/capture.jsonl'
    rows = [json.loads(row) for row in sidecar.read_text().splitlines()]
    rows[0]['dt']['cmd_vel'] = .01
    sidecar.write_text('\n'.join(json.dumps(row) for row in rows))
    def refreshed(ref):
        data = (output / ref['path']).read_bytes()
        return {**ref, 'bytes': len(data), 'sha256': hashlib.sha256(data).hexdigest()}
    doc['sources'] = [refreshed(ref) for ref in doc['sources']]
    doc['streams'] = {key: refreshed(ref) for key, ref in doc['streams'].items()}
    doc = seal(doc); (output / 'episode.json').write_text(json.dumps(doc))
    manifest = json.loads((output / 'dataset-manifest.json').read_text())
    manifest['files'] = [refreshed(ref) for ref in manifest['files']]
    manifest['episodes'] = [doc['revision']]
    (output / 'dataset-manifest.json').write_text(json.dumps(seal(manifest)))
    with pytest.raises(ValueError, match='future'):
        DatasetStore(tmp_path / 'store').register(output)
