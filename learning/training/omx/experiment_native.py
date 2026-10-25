"""Sealed native demonstrations to ACT arrays; never invent online transitions."""
import hashlib
import json
from pathlib import Path

import numpy as np

from experiment_dataset import load_dataset
from experiment_profile import validate_profile
from native_cycle import native, validate_split


def _profile(profile, source):
    """Return the profile and the native joint layout it maps; two arms are exactly arm_a then arm_b."""
    profile = validate_profile(profile)
    arms = profile['arms']
    ids = [arm['id'] for arm in arms]
    if (ids not in ([ids[0]], ['arm_a', 'arm_b']) or profile['mode'] != 'independent'
            or any(arm['joint_names'] != native.JOINTS or arm['units'] != source.get('body_units')
                   for arm in arms)
            or source.get('body_units') != 'normalized_-100_100'
            or source.get('gripper_units') != 'normalized_0_100'):
        raise ValueError('native conversion requires one arm, or arm_a then arm_b, '
                         'each with the exact ordered six-joint normalized layout')
    for camera in profile['cameras']:
        if camera['role'] == 'wrist' and camera['arm_id'] not in ids:
            raise ValueError('native wrist camera requires its explicit arm binding')
    layout = native.JOINTS[:] if len(arms) == 1 else [f'{arm}.{joint}' for arm in ids for joint in native.JOINTS]
    return profile, layout


def convert_native(splits: Path, output: Path, *, profile: dict) -> dict:
    splits = Path(splits).resolve(strict=True)
    output = native._new_output(output, splits)
    output.mkdir(parents=True)
    try:
        receipt_bytes = (splits / 'split-receipt.json').read_bytes()
        receipt = validate_split(splits)
        source = receipt['source']
        profile, layout = _profile(profile, source)
        cameras = {camera['input_key']: camera['shape'] for camera in profile['cameras']}
        originals = {episode['episode_index']: episode for episode in source['episodes']}
        document = {'schema': 'rosy.omx.experiment-dataset/1', 'profile': profile,
                    'source': 'reviewed_demonstration', 'episodes': []}
        lineage = []
        for split, selected in receipt['splits'].items():
            reader = native.load_dataset(splits / split, source['repo_id'] + '_' + split)
            features = reader.meta.info['features']
            declared = {key: [3, *value['shape'][:2]] for key, value in features.items()
                        if key.startswith('observation.images.')}
            if declared != cameras:
                raise ValueError('profile camera keys/shapes differ from actual native reader')
            if native.joint_layout(reader.meta.info) != layout:
                raise ValueError('profile arms differ from the actual native joint layout')
            # inspect_frames also verifies contiguous frame/episode order and normalized RGB.
            rows = [reader[index] for index in range(len(reader))]
            inspected = native.inspect_frames(reader.meta.info, rows)
            if len(inspected['episodes']) != len(selected):
                raise ValueError('native split episode count differs from sealed selection')
            offset = 0
            for local, original_index in enumerate(selected):
                original = originals[original_index]
                actual = inspected['episodes'][local]
                if any(actual[key] != original[key] for key in ('frames', 'content_sha256')):
                    raise ValueError('reader episode bytes differ from original inspected source')
                session, parent = original.get('session_id'), original.get('cycle_id')
                if not session or not parent:
                    raise ValueError('original session_id and cycle_id are required; no inferred lineage')
                frames = rows[offset:offset + actual['frames']]
                offset += actual['frames']
                arrays = {key: np.stack([np.asarray(row[key], dtype=np.float32) for row in frames])
                          for key in ('observation.state', 'action')}
                for key in cameras:
                    pixels = np.stack([np.asarray(row[key], dtype=np.float32) for row in frames])
                    arrays[key] = np.rint(pixels * 255).astype(np.uint8)
                filename = f'{split}-{original_index}.npz'
                with (output / filename).open('xb') as stream:
                    np.savez_compressed(stream, **arrays)
                digest = hashlib.sha256((output / filename).read_bytes()).hexdigest()
                document['episodes'].append(dict(id=f'native-{original_index}',
                    session_id=session, parent_id=parent, split=split, file=filename, sha256=digest))
                lineage.append(dict(id=f'native-{original_index}', split=split,
                    original_episode_index=original_index, local_episode_index=local,
                    content_sha256=original['content_sha256']))
        native.write_json(output / 'dataset.json', document)
        loaded = load_dataset(output, method='act')
        if (validate_split(splits) != receipt
                or (splits / 'split-receipt.json').read_bytes() != receipt_bytes):
            raise ValueError('native source changed during conversion')
        native.write_json(output / 'native-split-receipt.json', receipt)
        files = {path.name: hashlib.sha256(path.read_bytes()).hexdigest()
                 for path in sorted(output.iterdir()) if path.is_file()}
        result = dict(schema='rosy.omx.native-experiment-conversion/1',
            source=loaded.source, dataset_revision=loaded.revision,
            split_receipt_sha256=hashlib.sha256(receipt_bytes).hexdigest(),
            rig_revision=source['rig_revision'], calibration_revision=source['calibration_revision'],
            reader='lerobot==0.4.4/pyav', episodes=lineage, files=files,
            act_only=True, online_transitions=False, physical_acceptance=False)
        native.write_json(output / 'conversion-receipt.json', result)
        return result
    except Exception as exc:
        native.write_json(output / 'failed.json', {'error': f'{type(exc).__name__}: {exc}'})
        raise
