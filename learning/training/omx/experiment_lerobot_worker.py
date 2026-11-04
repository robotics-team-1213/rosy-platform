"""Owned offline uploaded-demonstration inspection and ACT worker."""
import argparse
import hashlib
import os
from pathlib import Path
import subprocess
import sys

from experiment_io import identifier, read_json, write_json
import experiment_lerobot_source as source

INSPECT = 'rosy.lerobot-inspect-request/1'
TRAIN = 'rosy.lerobot-train-request/1'


def offline_environment(output):
    output = Path(output)
    allowed = {'PATH', 'SystemRoot', 'SYSTEMROOT', 'WINDIR', 'LANG', 'LC_ALL', 'TEMP', 'TMP', 'TMPDIR'}
    env = {k: v for k, v in os.environ.items() if k in allowed}
    cache = output/'cache'
    return dict(env, HOME=str(cache/'home'), USERPROFILE=str(cache/'home'),
        HF_HOME=str(cache/'huggingface'), HF_TOKEN_PATH=str(cache/'no-token'),
        HF_HUB_CACHE=str(cache/'huggingface'/'hub'), HF_DATASETS_CACHE=str(cache/'datasets'),
        XDG_CACHE_HOME=str(cache), HF_HUB_OFFLINE='1', HF_DATASETS_OFFLINE='1',
        HF_HUB_DISABLE_IMPLICIT_TOKEN='1', HF_HUB_DISABLE_TELEMETRY='1',
        OMP_NUM_THREADS='2', MKL_NUM_THREADS='2', OPENBLAS_NUM_THREADS='2',
        TOKENIZERS_PARALLELISM='false', PYTHONUNBUFFERED='1', PYTHONNOUSERSITE='1')


def check_request(request):
    base = {'schema','study_id','project_id','compute_host','source_root','files','manifest_revision'}
    if not isinstance(request, dict) or request.get('schema') not in (INSPECT, TRAIN):
        raise ValueError('uploaded LeRobot worker request schema required')
    expected = base if request['schema'] == INSPECT else base | {
        'source_revision','inspection','split','steps','batch_size','seed'}
    if set(request) != expected:
        raise ValueError('uploaded LeRobot worker fields differ')
    identifier(request['study_id'])
    if request['compute_host'] not in ('model', 'ai'):
        raise ValueError('trusted compute host binding required')
    if (not isinstance(request['project_id'], str) or not 1 <= len(request['project_id']) <= 256
            or any(ord(c) < 32 for c in request['project_id'])):
        raise ValueError('bounded project binding required')
    if not isinstance(request['source_root'], str) or not Path(request['source_root']).is_absolute():
        raise ValueError('owned absolute source path required')
    if request['manifest_revision'] != source.manifest_revision(request['files']):
        raise ValueError('source manifest revision differs')
    if request['schema'] == TRAIN:
        inspection = request['inspection']
        if (request['source_revision'] != request['manifest_revision']
                or inspection.get('revision') != source.digest({k:v for k,v in inspection.items() if k != 'revision'})):
            raise ValueError('source/inspection revision differs')
        split = request['split']
        if source.validate_split({k:v for k,v in split.items() if k != 'revision'}, inspection) != split:
            raise ValueError('confirmed split revision differs')
        for key, lower, upper in [('steps',1,100000),('batch_size',1,8),('seed',0,2147483647)]:
            if type(request[key]) is not int or not lower <= request[key] <= upper:
                raise ValueError('training integer outside allowed range: '+key)
    return request


def invoke(command, log, environment):
    with log.open('x', encoding='utf-8') as stream:
        result = subprocess.run(command, env=environment, stdout=stream,
            stderr=subprocess.STDOUT, timeout=86400, check=False)
    if result.returncode:
        raise ValueError('uploaded LeRobot subprocess failed; inspect owned worker log')


def configuration(output, request):
    config = read_json(Path(__file__).with_name('native-act.example.json'))
    config['dataset'].update(root=str(output/'train-dataset'), repo_id=source.REPO)
    config.update(output_dir=str(output/'trainer'), job_name='uploaded-demonstration-act',
        seed=request['seed'], steps=request['steps'], save_freq=request['steps'], log_freq=1,
        batch_size=request['batch_size'])
    return config


def model_files(output):
    # LeRobot's last checkpoint is a local symlink to the numbered checkpoint.
    model = (output/'trainer/checkpoints/last/pretrained_model').resolve()
    if not model.is_relative_to(output.resolve()) or not model.is_dir():
        raise ValueError('trained model escaped owned output')
    files = source.hashes(model)
    required = {'config.json','model.safetensors','policy_preprocessor.json','policy_postprocessor.json'}
    if not required <= files.keys():
        raise ValueError('complete model and processors required')
    return model, files


def run(request, output):
    check_request(request)
    output = Path(output)
    if not output.is_absolute() or output.exists() or output.is_symlink():
        raise ValueError('new absolute uploaded LeRobot output required')
    output.mkdir(parents=True)
    environment = offline_environment(output)
    os.environ.clear()
    os.environ.update(environment)
    write_json(output/'source-request.json', request)
    write_json(output/'source-manifest.json', source.validate_files(request['files']))
    write_json(output/'progress.json', dict(phase='validating'))
    root = Path(request['source_root'])
    source.verify_files(root, request['files'])
    write_json(output/'progress.json', dict(phase='inspecting'))
    inspection = source.inspect(root, request['files'])
    write_json(output/'inspection.json', inspection)
    result = dict(schema='rosy.lerobot-inspect-result/1', study_id=request['study_id'],
        compute_host=request['compute_host'],
        project_id=request['project_id'], manifest_revision=request['manifest_revision'],
        source_revision=request['manifest_revision'], inspection=inspection)
    evidence = ['source-request.json','source-manifest.json','inspection.json']
    if request['schema'] == TRAIN:
        if inspection != request['inspection']:
            raise ValueError('sealed source inspection changed before training')
        write_json(output/'progress.json', dict(phase='preparing'))
        provenance = source.derive(root, output, inspection, request['split'])
        provenance.update(study_id=request['study_id'], project_id=request['project_id'], compute_host=request['compute_host'],
            source_revision=request['source_revision'], manifest_revision=request['manifest_revision'])
        write_json(output/'provenance.json', provenance)
        write_json(output/'split.json', request['split'])
        write_json(output/'train-config.json', configuration(output, request))
        write_json(output/'progress.json', dict(phase='training', steps=request['steps']))
        invoke([sys.executable,str(Path(__file__).with_name('experiment_lerobot_entry.py')),
                '--config_path='+str(output/'train-config.json')], output/'train.log', environment)
        model, files = model_files(output)
        write_json(output/'progress.json', dict(phase='evaluating'))
        invoke([sys.executable,str(Path(__file__).with_name('experiment_lerobot_eval.py')),
                '--root',str(output),'--model',str(model)], output/'reload.log', environment)
        if model_files(output)[1] != files:
            raise ValueError('model changed during fresh evaluation')
        evaluation = read_json(output/'evaluation.json', max_bytes=32*1024**2)
        result = dict(schema='rosy.lerobot-train-result/1', study_id=request['study_id'],
            compute_host=request['compute_host'],
            project_id=request['project_id'], manifest_revision=request['manifest_revision'],
            source_revision=request['source_revision'], inspection_revision=inspection['revision'],
            split_revision=request['split']['revision'], steps=request['steps'],
            batch_size=request['batch_size'], seed=request['seed'], artifact_files=files,
            evaluation=evaluation, physical_learning_verified=False, policy_activation=False)
        evidence += ['provenance.json','split.json','train-config.json','evaluation.json']
    result['evidence_files'] = {name: hashlib.sha256((output/name).read_bytes()).hexdigest() for name in evidence}
    write_json(output/'result.json', result)
    check_result(output, result, request)
    write_json(output/'progress.json', dict(phase='finished', steps=request.get('steps'), step=request.get('steps')))
    return result


def check_result(output, result, request):
    from experiment_lerobot_artifact import check_result as check
    return check(output, result, request)


def archive(output, result, request):
    from experiment_lerobot_artifact import archive as build
    return build(output, result, request)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--request', type=Path, required=True)
    parser.add_argument('--out', type=Path, required=True)
    args = parser.parse_args()
    try:
        run(read_json(args.request, max_bytes=32*1024**2), args.out)
    except Exception as exc:
        if args.out.is_dir() and not args.out.is_symlink():
            write_json(args.out/'error.json', dict(error='Uploaded LeRobot study failed: '+type(exc).__name__))
        raise


if __name__ == '__main__':
    main()
