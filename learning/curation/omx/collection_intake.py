"""Offline, closed OMX collection sessions into inspected native LeRobot datasets."""
from __future__ import annotations

import hashlib
import importlib.metadata
import json
import math
import os
from pathlib import Path, PurePosixPath
import re
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent))
from omx_output_paths import in_source_checkout
import camera_reference
from native_capture import ACTION, SCHEMA as CAPTURE_SCHEMA, redacted as _redacted
from native_environment import ROLES, _events, _number, _roles, seal_environment
from native_review import (JOINTS, dataset_files, inspect_dataset, inspect_frames, load_dataset,
                           static_episodes, write_json)
from collection_intake_helpers import (  # noqa: F401
    MAX_TIME_NS,
    REVISIONS,
    SCHEMA,
    TEACHER_FILE,
    TEACHER_SCHEMA,
    _completed_attempt,
    _constant,
    _hash,
    _json,
    _object,
    _read_source,
    _relative,
    _require,
    _sealed_collection,
    _sealed_teacher,
    _small_json,
    _source_episodes,
    _source_ns,
    _teacher_and_ledger,
    _text,
    _vector,
    validate_session,
)


def prepare(sessions, output, repo_id, *, completed_only=False, camera_references=None):
    """Produce a new, locally read-back dataset; leave all decisions unknown/exclude.

    ``camera_references`` (role -> reference JSON path) adds D-792 shadow checks as camera-setup.json."""
    records = [validate_session(path, completed_only=completed_only) for path in sessions]
    _require(bool(records), 'at least one session required')
    output = Path(output).absolute()
    _require(not output.exists() and not in_source_checkout(output), 'new output outside the source checkout required')
    for record in records:
        source = record['root']
        _require(not output.resolve().is_relative_to(source) and not source.is_relative_to(output.resolve()),
                 'output must be separate from every source')
    baseline = records[0]['manifest']
    keys = ('fps', 'task', 'rig_revision', 'calibration_revision', 'teacher_sha256', 'camera_shapes')
    _require(all(all(r['manifest'][k] == baseline[k] for k in keys) for r in records),
             'aggregate session configuration differs')
    _require(len({r['manifest']['session_id'] for r in records}) == len(records), 'duplicate session identity')
    records.sort(key=lambda r: r['manifest']['episodes'][0]['start_ns'])
    prior_end, prior_log, raw_logs = 0, 0, []
    episodes = []
    for record in records:
        attempts = record['manifest']['episodes']
        _require(attempts[0]['start_ns'] >= prior_end, 'aggregate session windows overlap')
        prior_end = attempts[-1]['end_ns']
        raw = record['blobs']['environment.jsonl']
        events = _events(raw.decode('utf-8'))
        _require(events[0]['recorded_ns'] > prior_log, 'aggregate environment clocks overlap')
        prior_log = events[-1]['recorded_ns']
        raw_logs.append(raw)
        episodes.extend((record, episode) for episode in record['selected'])
    windows = [dict(episode_index=i, **{k: e[k] for k in ('start_ns', 'end_ns', 'run_id', 'profile_sha256')})
               for i, (_, e) in enumerate(episodes)]
    # Validate combined log and selected windows before importing or writing LeRobot.
    raw_log = b''.join(raw_logs)
    seal_environment(raw_log, windows, {'validated': '0'*64}, rig_revision=baseline['rig_revision'],
                     calibration_revision=baseline['calibration_revision'])
    _require(importlib.metadata.version('lerobot') == '0.4.4', 'lerobot==0.4.4 required')
    os.environ['HF_HUB_OFFLINE'] = '1'
    os.environ['HF_DATASETS_OFFLINE'] = '1'
    import numpy as np
    from lerobot.datasets.lerobot_dataset import LeRobotDataset
    features = {key: dict(dtype='float32', shape=(6,), names=JOINTS[:])
                for key in ('observation.state', 'action')}
    features['source.capture_time_ns'] = dict(dtype='int64', shape=(1,), names=['fleet_host_unix_ns'])
    for source in ('joint', 'reference', *baseline['camera_shapes']):
        features[f'source.{source}_time_ns'] = dict(dtype='int64', shape=(1,), names=[source+'_source_unix_ns'])
    features.update({f'observation.images.{role}': dict(dtype='video', shape=tuple(shape),
                     names=['height', 'width', 'channels']) for role, shape in baseline['camera_shapes'].items()})
    dataset = LeRobotDataset.create(repo_id=repo_id, fps=baseline['fps'], root=output,
                                   robot_type='omx_follower', features=features, use_videos=True,
                                   video_backend='pyav', vcodec='h264', batch_encoding_size=1)
    try:
        for record, episode in episodes:
            for row in record['samples'][episode['episode_index']]:
                frame = {k: np.array(row[k], dtype=np.float32) for k in ('observation.state', 'action')}
                frame['source.capture_time_ns'] = np.array([row['time_ns']], dtype=np.int64)
                for source in ('joint', 'reference'):
                    frame[f'source.{source}_time_ns'] = np.array(
                        [_source_ns(row[source+'_source_stamp'])], dtype=np.int64)
                for role, shape in baseline['camera_shapes'].items():
                    frame[f'observation.images.{role}'] = np.frombuffer(
                        record['blobs'][row['images'][role]['path']], dtype=np.uint8).reshape(shape).copy()
                    frame[f'source.{role}_time_ns'] = np.array(
                        [_source_ns(row['images'][role]['source_stamp'])], dtype=np.int64)
                frame['task'] = baseline['task']
                dataset.add_frame(frame)
            dataset.save_episode(parallel_encoding=False)
    finally:
        dataset.finalize()
    files = dataset_files(output)
    capture = dict(schema=CAPTURE_SCHEMA, source_mode='scripted_teacher', action_semantics=ACTION,
                   body_units=baseline['body_units'], gripper_units=baseline['gripper_units'],
                   rig_revision=baseline['rig_revision'], calibration_revision=baseline['calibration_revision'],
                   teacher_sha256=baseline['teacher_sha256'], files=files,
                   episodes=[dict(episode_index=i, session_id=r['manifest']['session_id'], cycle_id=e['cycle_id'])
                             for i, (r, e) in enumerate(episodes)])
    environment = seal_environment(raw_log, windows, files, rig_revision=baseline['rig_revision'],
                                   calibration_revision=baseline['calibration_revision'])
    report = inspect_dataset(output, repo_id, body_units=baseline['body_units'],
                             rig_revision=baseline['rig_revision'],
                             calibration_revision=baseline['calibration_revision'],
                             source_mode='scripted_teacher', capture_provenance=capture,
                             environment_evidence=environment)
    _require(report['frame_count'] == sum(e['frames'] for _, e in episodes)
             and len(report['episodes']) == len(episodes), 'readback counts differ')
    for record in records:
        # Re-read source before writing the success receipt. Copies use validated original bytes.
        _require(_read_source(record['root'])[1] == record['blobs'], 'source changed during conversion')
    for i, record in enumerate(records):
        for relative, blob in record['blobs'].items():
            target = output / 'rosy_provenance' / f'session-{i:06d}' / relative
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(blob)
    receipt = dict(schema='rosy.omx-collection-intake.v1', reader_verified=True, uploaded=False,
                   completed_only=completed_only, fixture_only=False,
                   sessions=[dict(session_id=r['manifest']['session_id'], manifest_sha256=r['manifest_sha256'],
                                  manifest=r['manifest'], provenance_path=f'rosy_provenance/session-{i:06d}')
                             for i, r in enumerate(records)],
                   episodes=[dict(episode_index=i, session_id=r['manifest']['session_id'],
                                  attempt_index=e['episode_index'], cycle_id=e['cycle_id'])
                             for i, (r, e) in enumerate(episodes)])
    documents = [('capture.json', capture), ('environment.json', environment),
                 ('inspection.json', report), ('decisions.json', report['episodes'])]
    if camera_references:
        import camera_setup_intake
        references = {role: camera_setup_intake.load_reference(path) for role, path in camera_references.items()}
        documents.append(('camera-setup.json', camera_setup_intake.report(records, episodes, references)))
    for name, document in (*documents, ('intake-receipt.json', receipt)):
        write_json(output / name, document)
    return receipt


def prepare_native(collections, output, repo_id, *, rig_revision=None, calibration_revision=None, camera_references=None):
    """D-848: sealed leader or replay-teacher recordings -> one prepared intake; one session per recording,
    one cycle per episode. Replay-teacher intakes take the operator's rig and calibration revisions.

    The official LeRobot 0.4.4 aggregate joins recordings without re-encoding. Every aggregated
    episode must carry the content hash its source recording had, in sealed order. Decisions start unknown.
    """
    import shutil
    from lerobot.datasets.aggregate import aggregate_datasets
    references = camera_reference.load(camera_references) if camera_references else None
    collections = [Path(path).absolute() for path in collections]
    _require(bool(collections) and len({c.name for c in collections}) == len(collections),
             'distinct sealed collections required')
    operator = (None if rig_revision is None and calibration_revision is None
                else dict(rig_revision=rig_revision, calibration_revision=calibration_revision))
    sealed = [(c, *_sealed_collection(c, operator)) for c in collections]
    sealed.sort(key=lambda row: row[1].get('sealed_ns', 0))
    first = sealed[0][1]
    mode = first['source_mode']
    _require(all(m['source_mode'] == mode for _, m, _ in sealed),
             'leader_native and scripted_teacher recordings cannot share one intake')
    # teacher_sha256 names one fixed teacher (native_capture); different replays need separate intakes.
    _require(mode != 'scripted_teacher' or len({m['teacher_sha256'] for _, m, _ in sealed}) == 1,
             'recordings of different teachers cannot share one intake')
    _require(all(m['rig_revision'] == first['rig_revision'] and m['calibration_revision'] == first['calibration_revision']
                 and m.get('robot_type') == first.get('robot_type') for _, m, _ in sealed),
             'recordings with different rig, calibration or robot type cannot share one intake')
    output = Path(output).absolute()
    _require(not output.exists() and not in_source_checkout(output), 'new output outside the source checkout required')
    for collection, _, _ in sealed:
        _require(not output.resolve().is_relative_to(collection.resolve())
                 and not collection.resolve().is_relative_to(output.resolve()), 'output must be separate from every source')
    expected, groups, static, thresholds = [], [], [], []
    for collection, manifest, _ in sealed:
        episodes = _source_episodes(collection/'dataset', 'local/' + manifest['session_id'])
        _require(mode != 'scripted_teacher' or len(episodes) == 2, 'a replay recording has exactly episodes A and B')
        # record_session markers die in the aggregate; carry them over with aggregated indexes.
        static += [len(expected) + index for index in static_episodes(collection/'dataset', len(episodes))]
        if (collection/'dataset'/'static_episodes.json').is_file():
            thresholds.append(json.loads((collection/'dataset'/'static_episodes.json').read_text(encoding='utf-8'))['threshold'])
        for episode in episodes:
            expected.append(episode['content_sha256'])
            groups.append((manifest['session_id'], f"{manifest['session_id']}-ep{episode['episode_index']:04d}"))
    aggregate_datasets([f"local/{m['session_id']}" for _, m, _ in sealed], repo_id,
                       roots=[c/'dataset' for c, _, _ in sealed], aggr_root=output)
    setup = references and camera_reference.bind(references, json.loads((output/'meta'/'info.json').read_text(encoding='utf-8')))
    if thresholds:
        write_json(output/'static_episodes.json', dict(episodes=len(expected), static=static, threshold=max(thresholds)))
    for i, (collection, manifest, digest) in enumerate(sealed):
        provenance = output/'rosy_provenance'/f'session-{i:06d}'
        provenance.mkdir(parents=True)
        # Site-PC paths and device serials never leave the Fleet PC; the sealed hashes bind the originals.
        # Ports and camera by-id names carry serials, so those are dropped; teacher.source.dataset keeps its basename.
        for name in ('session.json', 'record-config.json'):
            write_json(provenance/name, _redacted(_json((collection/name).read_bytes())))
        write_json(provenance/'manifest.json', _redacted(_json((collection/'manifest.json').read_bytes()), keep_name=True))
        write_json(provenance/'redactions.json', dict(
            {name: dict(redacted_from_sha256=manifest['files'][name]) for name in ('session.json', 'record-config.json')},
            **{'manifest.json': dict(redacted_from_sha256=digest)}))
        if (collection/'calibration').is_dir():
            shutil.copytree(collection/'calibration', provenance/'calibration')
    files = dataset_files(output)
    digests = [d for _, _, d in sealed]
    lineage = (dict(collection_manifest_sha256=digests[0] if len(digests) == 1
                    else hashlib.sha256(json.dumps(digests).encode('utf-8')).hexdigest())
               if mode == 'leader_native' else dict(
        teacher_sha256=first['teacher_sha256'],
        teachers=[dict(session_id=m['session_id'], teacher_sha256=m['teacher_sha256'],
                       **_redacted({k: m['teacher'][k] for k in ('kind', 'segments', 'source')}, keep_name=True))
                  for _, m, _ in sealed]))
    capture = dict(schema=CAPTURE_SCHEMA, source_mode=mode, action_semantics=ACTION,
                   body_units='normalized_-100_100', gripper_units='normalized_0_100',
                   rig_revision=first['rig_revision'], calibration_revision=first['calibration_revision'],
                   **lineage, **(dict(camera_setup=setup) if setup else {}),
                   collection_manifests=[dict(session_id=m['session_id'], manifest_sha256=d,
                                              **{k: m[k] for k in ('session_id_origin', 'revision_origin') if k in m})
                                         for _, m, d in sealed],
                   files=files, episodes=[dict(episode_index=i, session_id=session, cycle_id=cycle)
                                          for i, (session, cycle) in enumerate(groups)])
    report = inspect_dataset(output, repo_id, body_units='normalized_-100_100', rig_revision=first['rig_revision'],
                             calibration_revision=first['calibration_revision'],
                             source_mode=mode, capture_provenance=capture, camera_setup=setup)
    _require([e['content_sha256'] for e in report['episodes']] == expected,
             'aggregated episodes differ from their sealed recordings')
    _require([_sealed_collection(c, operator)[1] for c, _, _ in sealed] == digests, 'source changed during intake')
    receipt = dict(schema='rosy.omx-collection-intake.v1', reader_verified=True, uploaded=False,
                   completed_only=False, fixture_only=False, source_mode=mode,
                   sessions=[dict(session_id=m['session_id'], manifest_sha256=d, provenance_path=f'rosy_provenance/session-{i:06d}')
                             for i, (_, m, d) in enumerate(sealed)],
                   episodes=[dict(episode_index=i, session_id=session, attempt_index=int(cycle.rsplit('-ep', 1)[1]),
                                  cycle_id=cycle) for i, (session, cycle) in enumerate(groups)])
    for name, document in (('capture.json', capture), ('environment.json', report['environment_summary']),
                           ('inspection.json', report), ('decisions.json', report['episodes']),
                           ('intake-receipt.json', receipt)):
        write_json(output / name, document)
    return receipt


def main():
    import collection_pipeline  # one CLI: its `prepare` takes the same arguments
    collection_pipeline.main()


if __name__ == '__main__':
    main()
