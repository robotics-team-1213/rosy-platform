"""Owned public demonstration ACT study; no capture, promotion, or device authority."""
import argparse
import hashlib
import io
import json
import os
from pathlib import Path
import subprocess
import sys
import time
import uuid
import zipfile

from experiment_io import identifier, read_json, write_json
from experiment_jobs import launch
from experiment_process import process_stamp
import experiment_public_source as source

SCHEMA = 'rosy.public-act-request/1'


def check_request(body):
    required = {'request_id', 'repo_id', 'revision', 'steps', 'batch_size', 'confirmed_source'}
    if not isinstance(body, dict) or set(body) != required:
        raise ValueError('fixed public training request required')
    identifier(body['request_id'])
    if (body['repo_id'] != source.REPO or body['revision'] != source.REVISION
            or body['confirmed_source'] is not True):
        raise ValueError('explicit confirmation of the fixed public source required')
    for key, upper in [('steps', 100000), ('batch_size', 8)]:
        if type(body[key]) is not int or not 1 <= body[key] <= upper:
            raise ValueError('public training budget outside allowed range: ' + key)
    return dict(schema=SCHEMA, **body)


def public_environment():
    allowed = {'PATH', 'HOME', 'USER', 'LOGNAME', 'LANG', 'LC_ALL', 'TMPDIR', 'TEMP', 'TMP',
               'SystemRoot', 'SYSTEMROOT', 'WINDIR', 'SSL_CERT_FILE', 'SSL_CERT_DIR', 'REQUESTS_CA_BUNDLE'}
    env = {key: value for key, value in os.environ.items() if key in allowed}
    return dict(env, HF_HUB_OFFLINE='0', HF_DATASETS_OFFLINE='0', HF_HUB_DISABLE_IMPLICIT_TOKEN='1',
                OMP_NUM_THREADS='2', MKL_NUM_THREADS='2', OPENBLAS_NUM_THREADS='2',
                TOKENIZERS_PARALLELISM='false', PYTHONUNBUFFERED='1')


def describe(python):
    try:
        result = subprocess.run([python, str(Path(__file__).resolve()), '--probe'],
            env=public_environment(), capture_output=True, timeout=45, check=False)
        if result.returncode:
            raise ValueError('Pinned public source metadata probe failed')
        checked = json.loads(result.stdout)
        source.check_info(checked['source_info'])
        if any(checked.get(key) != value for key, value in source.descriptor().items()):
            raise ValueError('Pinned public source descriptor differs')
        return checked
    except (OSError, ValueError, KeyError, subprocess.TimeoutExpired):
        return dict(source.descriptor(), available=False, reason='Pinned public source metadata probe unavailable')


def start(center, body):
    request = check_request(body)
    binding = json.dumps(dict(body, execution_mode='public_train'), sort_keys=True)
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
        checked = center.public_source()
        if not checked['available']:
            raise ValueError(checked['reason'])
        rid = str(uuid.uuid4())
        root = center.root/'runs'/rid
        root.mkdir()
        write_json(root/'request.json', request)
        row = dict(id=rid, status='launching', created_at=time.time(), method='act', device='cpu',
                   execution_mode='public_train', source=source.descriptor(), steps=body['steps'],
                   batch_size=body['batch_size'], offline_only=True, physical_learning_verified=False)
        return launch(center, db, body['request_id'], binding, row, process_stamp)


def invoke(command, logfile, env, timeout=86400):
    with logfile.open('x') as log:
        process = subprocess.run(command, stdout=log, stderr=subprocess.STDOUT, env=env, timeout=timeout)
    if process.returncode:
        # Detailed diagnostics remain in the owned log; API errors never echo host paths or environment.
        raise ValueError('public study subprocess failed; inspect the owned worker log')


def train(output, request):
    config = read_json(Path(__file__).with_name('native-act.example.json'))
    config['dataset'].update(root=str(output/'train-dataset'), repo_id=source.DERIVED_REPO)
    config.update(output_dir=str(output/'trainer'), job_name='public-so100-act-study',
                  steps=request['steps'], save_freq=request['steps'], log_freq=1,
                  batch_size=request['batch_size'])
    write_json(output/'train-config.json', config)
    env = dict(public_environment(), HF_HUB_OFFLINE='1', HF_DATASETS_OFFLINE='1',
               OMP_NUM_THREADS='2', MKL_NUM_THREADS='2', OPENBLAS_NUM_THREADS='2')
    invoke([sys.executable, '-m', 'lerobot.scripts.lerobot_train',
            f'--config_path={output/"train-config.json"}'], output/'train.log', env)
    model = (output/'trainer/checkpoints/last/pretrained_model').resolve()
    if not model.is_relative_to(output.resolve()):
        raise ValueError('public trained model escaped owned output')
    from native_cycle import _artifact_files
    files = _artifact_files(model)
    invoke([sys.executable, str(Path(__file__).with_name('experiment_public_eval.py')),
            '--root', str(output), '--model', str(model)], output/'reload.log', env)
    if _artifact_files(model) != files:
        raise ValueError('public model changed during fresh-process evaluation')
    return files


def run(request, output):
    if not isinstance(request, dict) or request.get('schema') != SCHEMA:
        raise ValueError('fixed public worker schema required')
    if check_request({key: value for key, value in request.items() if key != 'schema'}) != request:
        raise ValueError('public worker request differs')
    output = Path(output)
    if output.exists() or output.is_symlink() or not output.is_absolute():
        raise ValueError('new absolute public study output required')
    output.mkdir(parents=True)
    write_json(output/'source-request.json', request)
    write_json(output/'progress.json', dict(phase='downloading'))
    original = source.download(output/'source')
    write_json(output/'source-manifest.json', original)
    write_json(output/'progress.json', dict(phase='preparing'))
    derived = source.derive(output/'source', output)
    write_json(output/'provenance.json', derived)
    write_json(output/'progress.json', dict(phase='training', steps=request['steps']))
    model_files = train(output, request)
    if (source.hashes(output/'dataset') != derived['files']
            or source.hashes(output/'train-dataset') != derived['train_files']):
        raise ValueError('public derived dataset changed during training/evaluation')
    evaluation = read_json(output/'evaluation.json')
    evidence = {name: hashlib.sha256((output/name).read_bytes()).hexdigest() for name in
                ('source-request.json', 'source-manifest.json', 'provenance.json', 'evaluation.json')}
    result = dict(execution_mode='public_train', method='act', source=source.descriptor(),
        steps=request['steps'], batch_size=request['batch_size'], artifact_files=model_files,
        evidence_files=evidence, evaluation=evaluation, offline_only=True,
        units='dataset-native/unverified', physical_learning_verified=False, policy_activation=False,
        device_execution=False, promotion=False)
    write_json(output/'result.json', result)
    write_json(output/'progress.json', dict(phase='finished', step=request['steps'], steps=request['steps']))
    return result


def archive(output, result):
    output = Path(output)
    if result.get('execution_mode') != 'public_train' or read_json(output/'result.json') != result:
        raise ValueError('public result lineage changed')
    evidence_names = {'source-request.json', 'source-manifest.json', 'provenance.json', 'evaluation.json'}
    if set(result['evidence_files']) != evidence_names:
        raise ValueError('public evidence file set differs')
    request = read_json(output/'source-request.json')
    if (request != read_json(output.parent/'request.json')
            or check_request({key: value for key, value in request.items() if key != 'schema'}) != request
            or result.get('source') != source.descriptor()
            or any(result.get(key) != request[key] for key in ('steps', 'batch_size'))):
        raise ValueError('public artifact request lineage changed')
    from native_cycle import _artifact_files
    model = (output/'trainer/checkpoints/last/pretrained_model').resolve()
    if not model.is_relative_to(output.resolve()) or _artifact_files(model) != result['artifact_files']:
        raise ValueError('completed public model bytes changed')
    files = {f'model/{name}': model/name for name in result['artifact_files']}
    files.update({name: output/name for name in result['evidence_files']})
    files['result.json'] = output/'result.json'
    for name, digest in result['evidence_files'].items():
        if (output/name).is_symlink() or hashlib.sha256((output/name).read_bytes()).hexdigest() != digest:
            raise ValueError('public evidence bytes changed')
    if any(path.is_symlink() or not path.is_file() for path in files.values()):
        raise ValueError('regular public artifacts required')
    if sum(path.stat().st_size for path in files.values()) > 256*1024*1024:
        raise ValueError('public model archive exceeds 256 MiB')
    stream = io.BytesIO()
    with zipfile.ZipFile(stream, 'w', zipfile.ZIP_DEFLATED) as zipped:
        for name, path in files.items():
            zipped.writestr(name, path.read_bytes())
    return stream.getvalue()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--probe', action='store_true')
    parser.add_argument('--request', type=Path)
    parser.add_argument('--out', type=Path)
    args = parser.parse_args()
    if args.probe:
        print(json.dumps(source.probe()))
        return
    if args.request is None or args.out is None:
        parser.error('--request and --out required')
    try:
        run(read_json(args.request), args.out)
    except Exception as exc:
        args.out.mkdir(parents=True, exist_ok=True)
        write_json(args.out/'error.json', dict(error='Public study failed: ' + type(exc).__name__, status='failed'))
        raise


if __name__ == '__main__':
    main()
