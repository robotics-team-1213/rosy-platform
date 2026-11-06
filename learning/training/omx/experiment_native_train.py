"""Source-bound native ACT worker: human review -> split -> train -> reload -> eval."""
import argparse
import hashlib
import io
import json
from pathlib import Path
import time
import uuid
import zipfile

from experiment_io import identifier, read_json, write_json
from experiment_jobs import check_request, launch
from experiment_process import process_stamp
from experiment_native import native_inputs_api, validate_source_profile
from experiment_reviews import Reviews, canonical
import native_cycle as cycle
import native_segments

SCHEMA = 'rosy.omx.native-train-request/1'
REQUEST_LIMIT = 16 * 1024 * 1024
_UNSET = object()


def _selection(source, review, segments):
    if source['fixture_only']:
        raise ValueError('fixture-only intake cannot train a production policy')
    if (review is None) == (segments is None):
        raise ValueError('exactly one saved human review or segment version required')
    if review is not None:
        if (not isinstance(review, dict)
                or set(review) != {'id', 'source_revision', 'decisions', 'sha256', 'reviewer_identity'}
                or review['source_revision'] != source['source_revision']
                or hashlib.sha256(canonical(review['decisions'])).hexdigest() != review['sha256']):
            raise ValueError('saved review snapshot or source revision changed')
        identifier(review['id'])
        cycle.native.reviewed_splits(source['inspection'], review['decisions'])
    else:
        if (not isinstance(segments, dict) or set(segments) != {'version', 'document'}
                or type(segments['version']) is not int or segments['version'] < 1):
            raise ValueError('saved segment version required')
        native_segments.validate_selection(source['inspection'], segments['document'])


def prepare_request(body, prepared, *, review=None, segments=None, tasks=None, host_id=None):
    required = {'prepared_id', 'steps', 'batch_size', 'request_id'}
    if (not isinstance(body, dict)
            or set(body) - {'task_id', 'compute_host'} not in (required | {'review_id'}, required | {'segment_version'})
            or ('task_id' in body) != ('compute_host' in body)
            or body['prepared_id'] != prepared.get('id')):
        raise ValueError('fixed registered native training request required')
    check_request(dict(dataset_id=body['request_id'], method='act', device='cpu', seed=0,
                       **{key: body[key] for key in ('request_id', 'steps', 'batch_size')}), {'act': {'devices': ['cpu']}})
    if ('review_id' in body and (review is None or body['review_id'] != review.get('id'))
            or 'segment_version' in body and (segments is None
                or type(body['segment_version']) is not int or body['segment_version'] != segments.get('version'))):
        raise ValueError('selected saved review identity differs')
    source = Reviews.source(prepared)
    _selection(source, review, segments)
    request = dict(schema=SCHEMA, prepared_root=str(source['root']), prepared_id=body['prepared_id'],
                   source_revision=source['source_revision'], steps=body['steps'], batch_size=body['batch_size'])
    fields = dict(prepared_id=body['prepared_id'], method='act', source='reviewed_demonstration',
                  execution_mode='native_train', steps=body['steps'], batch_size=body['batch_size'])
    if 'task_id' in body:
        if tasks is None or host_id not in ('model', 'ai') or body['compute_host'] != host_id:
            raise ValueError('matching trusted native task compute host required')
        task = next((task for task in tasks.snapshot()['tasks'] if task['id'] == body['task_id']), None)
        if task is None or not task['runnable']:
            raise ValueError('registered runnable native learning task required')
        profile, _ = validate_source_profile(task['profile']['profile'], source['inspection'], source['root'])
        binding = tasks.resolve_native(task['id'], body['prepared_id'], source['source_revision'],
            task['profile_revision'], [arm['id'] for arm in profile['arms']], host_id)
        native_inputs_api().check_binding(binding, resolved=True)
        request['learning_task'] = fields['learning_task'] = binding
    if review is not None:
        request['review'] = review
        fields['review_id'] = review['id']
    else:
        request['segments'] = segments
        fields['segment_version'] = segments['version']
    if len(json.dumps(request, ensure_ascii=False, allow_nan=False).encode('utf-8')) > REQUEST_LIMIT:
        raise ValueError('native training request exceeds 16 MiB')
    return request, fields


def check_native_task(binding, prepared):
    native_inputs_api().check_binding(binding, resolved=True)
    source = Reviews.source(prepared)
    if (binding['prepared_id'] != prepared['id']
            or binding['source_revision'] != source['source_revision']):
        raise ValueError('native learning task source association changed')
    validate_source_profile(binding['task']['profile']['profile'], source['inspection'], source['root'])
    return binding


def start(center, body, prepared, segments=None):
    identifier(body.get('request_id'))
    source = Path(prepared['path']).resolve()
    if source.is_relative_to(center.root) or center.root.is_relative_to(source):
        raise ValueError('registered source must be separate from the learning center')
    binding = canonical(dict(body=body, registered_source=str(source))).decode()
    with center.lock, center.connect() as db:
        db.execute('BEGIN IMMEDIATE')
        center._refresh(db)
        old = db.execute('SELECT document,request FROM runs WHERE request_id=?', (body['request_id'],)).fetchone()
        if old:
            if old[1] != binding:
                raise ValueError('request identity already used with different inputs')
            return json.loads(old[0])
        if not center.methods['act']['available']:
            raise ValueError('learner environment unavailable')
        if any(json.loads(row[0])['status'] in ('launching', 'running', 'stopping')
               for row in db.execute('SELECT document FROM runs')):
            raise ValueError('one owned learning job may run at a time')
        review = center.reviews.for_export(body['review_id'], prepared) if 'review_id' in body else None
        request, fields = prepare_request(body, prepared, review=review, segments=segments,
                                          tasks=center.tasks, host_id=center.host_id)
        rid = str(uuid.uuid4())
        root = center.root/'runs'/rid
        root.mkdir()
        write_json(root/'request.json', request)
        row = dict(id=rid, status='launching', created_at=time.time(), **fields)
        return launch(center, db, body['request_id'], binding, row, process_stamp)


def run(request, output):
    required = {'schema', 'prepared_root', 'prepared_id', 'source_revision', 'steps', 'batch_size'}
    if (not isinstance(request, dict) or request.get('schema') != SCHEMA
            or set(request) - {'learning_task'} not in (required | {'review'}, required | {'segments'})):
        raise ValueError('fixed native training worker request required')
    prepared = dict(id=request['prepared_id'], path=request['prepared_root'], kind='omx')
    identity = dict(review_id=request['review']['id']) if 'review' in request else dict(segment_version=request['segments']['version'])
    checked, _ = prepare_request(dict(prepared_id=request['prepared_id'], steps=request['steps'],
        batch_size=request['batch_size'], request_id=str(uuid.uuid4()), **identity), prepared,
        review=request.get('review'), segments=request.get('segments'))
    binding = request.get('learning_task')
    if 'learning_task' in request:
        check_native_task(binding, prepared)
        checked['learning_task'] = binding
    if checked != request:
        raise ValueError('native source changed after training admission')
    output = cycle.native._new_output(output, Path(request['prepared_root']))
    output.mkdir(parents=True)
    write_json(output/'source-request.json', request)
    write_json(output/'progress.json', dict(phase='splitting'))
    source = Reviews.source(prepared)
    splits = output/'splits'
    if 'segments' in request:
        native_segments.export_segments(source['root'], source['inspection'], request['segments']['document'], splits)
    else:
        cycle.native.split_reviewed(source['root'], source['inspection'], request['review']['decisions'], splits)
    write_json(output/'progress.json', dict(phase='training'))
    result = cycle.run_cycle(splits, output/'training', steps=request['steps'],
                             batch_size=request['batch_size'], device='cpu')
    if Reviews.source(prepared)['source_revision'] != request['source_revision']:
        raise ValueError('native source changed during training')
    result = dict(result, execution_mode='native_train', source_revision=request['source_revision'],
                  split_receipt_sha256=hashlib.sha256((splits/'split-receipt.json').read_bytes()).hexdigest(),
                  cycle_receipt_sha256=hashlib.sha256((output/'training/cycle-receipt.json').read_bytes()).hexdigest(),
                  request_sha256=hashlib.sha256((output/'source-request.json').read_bytes()).hexdigest(),
                  physical_learning_verified=False, policy_activation=False)
    if binding is not None:
        result['learning_task'] = binding
    write_json(output/'result.json', result)
    write_json(output/'progress.json', dict(phase='finished'))
    return result


def archive(output, result, *, learning_task=_UNSET):
    model = output/'training/trainer/checkpoints/last/pretrained_model'
    if (model.resolve().is_relative_to(output.resolve()) is False
            or cycle._artifact_files(model) != result['artifact_files']):
        raise ValueError('completed native model bytes changed')
    files = {f'model/{name}': model/name for name in result['artifact_files']}
    files.update({'source-request.json': output/'source-request.json', 'result.json': output/'result.json',
                  'split-receipt.json': output/'splits/split-receipt.json',
                  'cycle-receipt.json': output/'training/cycle-receipt.json',
                  'evaluation.json': output/'training/evaluation.json'})
    if any(path.is_symlink() or not path.is_file() for path in files.values()):
        raise ValueError('regular native artifacts required')
    if sum(path.stat().st_size for path in files.values()) > 256*1024*1024:
        raise ValueError('native model archive exceeds 256 MiB')
    data = {name: path.read_bytes() for name, path in files.items()}
    if (json.loads(data['result.json']) != result
            or json.loads(data['evaluation.json']) != result['evaluation']
            or hashlib.sha256(data['source-request.json']).hexdigest() != result['request_sha256']
            or hashlib.sha256(data['split-receipt.json']).hexdigest() != result['split_receipt_sha256']
            or hashlib.sha256(data['cycle-receipt.json']).hexdigest() != result['cycle_receipt_sha256']
            or any(hashlib.sha256(data['model/'+name]).hexdigest() != digest
                   for name, digest in result['artifact_files'].items())):
        raise ValueError('native artifact evidence changed')
    request = json.loads(data['source-request.json'])
    binding = request.get('learning_task')
    if (binding != result.get('learning_task')
            or (learning_task is not _UNSET and binding != learning_task)):
        raise ValueError('native artifact task lineage changed')
    if binding is not None:
        native_inputs_api().check_binding(binding, resolved=True)
        if binding['source_revision'] != result['source_revision']:
            raise ValueError('native artifact source association changed')
    stream = io.BytesIO()
    with zipfile.ZipFile(stream, 'w', zipfile.ZIP_DEFLATED) as archive:
        for name, raw in data.items():
            archive.writestr(name, raw)
    return stream.getvalue()


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--request', type=Path, required=True)
    parser.add_argument('--out', type=Path, required=True)
    args = parser.parse_args(argv)
    request = read_json(args.request, max_bytes=REQUEST_LIMIT)
    output = cycle.native._new_output(args.out, Path(request['prepared_root']))
    try:
        run(request, output)
    except Exception as exc:
        output.mkdir(parents=True, exist_ok=True)
        write_json(output/'error.json', dict(error=f'{type(exc).__name__}: {str(exc)[:500]}', status='failed'))
        raise


if __name__ == '__main__':
    main()
