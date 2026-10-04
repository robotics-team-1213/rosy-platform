"""Preserve completed Pinky recording sources as an immutable Episode/dataset."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / 'contracts/learning/src'))
from rosy.contracts.learning import seal, validate_dataset  # noqa: E402
from rosy.contracts.learning.pinky import validate_profile, validate_recording  # noqa: E402


def ref(path, root):
    digest = hashlib.sha256()
    with path.open('rb') as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b''):
            digest.update(chunk)
    return {'path': path.relative_to(root).as_posix(), 'bytes': path.stat().st_size,
            'sha256': digest.hexdigest()}


def convert(raw, metadata, output, *, environment, clock_domain):
    raw, metadata, output = Path(raw).resolve(), Path(metadata).resolve(), Path(output).resolve()
    if environment not in ('sim', 'real') or not clock_domain or (
            environment == 'real' and clock_domain in ('gazebo_sim', 'isaac_sim')):
        raise ValueError('explicit environment and compatible source clock required')
    if output.drive.upper() == 'F:':
        raise ValueError('artifact output belongs outside source drive F:')
    if output.exists() or any(output.is_relative_to(path) or path.is_relative_to(output)
                              for path in (raw, metadata.parent)):
        raise ValueError('new separate output directory required')
    checked = validate_recording(metadata, raw)
    original, session = checked['metadata'], checked['session']
    files = {f'source/raw/{path.relative_to(raw).as_posix()}': path
             for path in raw.rglob('*') if path.is_file()}
    converted = [metadata, metadata.parent / original['video']['file'],
                 metadata.parent / original['sidecar']['file']]
    if original.get('scan'):
        converted.append(metadata.parent / original['scan']['file'])
    files.update({f'source/video/{path.name}': path for path in converted})
    if any(path.is_symlink() or not path.resolve().is_relative_to(
            raw if name.startswith('source/raw/') else metadata.parent) for name, path in files.items()):
        raise ValueError('recording source path escapes root')
    binding = {'schema': 'rosy.pinky-episode-binding/1',
               'environment': environment, 'clock_domain': clock_domain}
    output.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix='.pinky-episode-', dir=output.parent) as scratch:
        stage = Path(scratch) / 'dataset'; stage.mkdir()
        refs = {}
        for name, path in files.items():
            before = ref(path, path.parent)
            target = stage / name; target.parent.mkdir(parents=True, exist_ok=True)
            with path.open('rb') as source, target.open('wb') as dest:
                for chunk in iter(lambda: source.read(1024 * 1024), b''):
                    dest.write(chunk)
                dest.flush(); os.fsync(dest.fileno())
            refs[name] = ref(target, stage)
            if any(before[key] != refs[name][key] for key in ('sha256', 'bytes')):
                raise ValueError('recording source changed during copy')
        path = stage / 'source/binding.json'
        path.write_text(json.dumps(binding, sort_keys=True), encoding='utf-8')
        refs['source/binding.json'] = ref(path, stage)
        doc = seal({'schema': 'rosy.episode/1', 'episode_id': original['source']['session'],
                    'profile': 'pinky_recording_session_v1', 'device': session['device'],
                    'robot_type': 'pinky_pro', 'environment': environment, 'clock_domain': clock_domain,
                    'task': session['reason'], 'skill': None,
                    'revisions': {'policy': None, 'model': session.get('model_revision'), 'calibration': None,
                                  'camera_profile': session.get('camera_profile_revision')},
                    'sources': list(refs.values()),
                    'streams': {'observation': refs['source/video/' + original['sidecar']['file']],
                                'action': refs['source/video/' + original['sidecar']['file']],
                                'events': refs['source/raw/session.json']},
                    'correlations': {'action_ids': [], 'attempt_ids': []}, 'status': 'complete',
                    'outcome': {'task': 'unknown', 'action': 'unknown', 'judge': 'unknown', 'evidence': []}})
        validate_profile(doc, root=stage)
        path = stage / 'episode.json'; path.write_text(json.dumps(doc, indent=2), encoding='utf-8')
        config_hash = hashlib.sha256(json.dumps(binding, sort_keys=True).encode()).hexdigest()
        dataset = seal({'schema': 'rosy.dataset-manifest/1', 'episodes': [doc['revision']],
                        'transformation': {'tool_revision': 'sha256:' + hashlib.sha256(
                            Path(__file__).read_bytes()).hexdigest(), 'config_sha256': config_hash},
                        'files': list(refs.values()) + [ref(path, stage)]})
        validate_dataset(dataset, root=stage)
        (stage / 'dataset-manifest.json').write_text(json.dumps(dataset, indent=2), encoding='utf-8')
        os.rename(stage, output)
    return doc


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('raw', type=Path); parser.add_argument('metadata', type=Path)
    parser.add_argument('output', type=Path)
    parser.add_argument('--environment', choices=('real', 'sim'), required=True)
    parser.add_argument('--clock-domain', required=True)
    args = parser.parse_args()
    print(json.dumps(convert(args.raw, args.metadata, args.output,
                             environment=args.environment, clock_domain=args.clock_domain)))


if __name__ == '__main__':
    main()
