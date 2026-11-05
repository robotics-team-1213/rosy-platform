"""Lightweight request-to-evaluation closure and bounded, path-redacted ZIPs."""
import hashlib
import io
import json
import math
from pathlib import Path
import zipfile

from experiment_io import read_json
import experiment_lerobot_source as source


def load(output, name):
    path = output/name
    if path.is_symlink() or not path.resolve().is_relative_to(output.resolve()):
        raise ValueError('evidence path escaped owned output')
    return read_json(path, max_bytes=32*1024**2)


def finite_vector(value, dimension):
    if (not isinstance(value, list) or len(value) != dimension
            or any(type(v) not in (int,float) or not math.isfinite(v) or v < 0 for v in value)):
        raise ValueError('finite nonnegative per-action metrics required')


def check_inspection(inspection, info):
    source.check_info(info)
    cameras = [dict(key=k,shape=v['shape'],dtype=v['dtype']) for k,v in sorted(info['features'].items())
               if k.startswith('observation.images.')]
    for key,expected in [('robot_type',info.get('robot_type')),('fps',info['fps']),
            ('total_episodes',info['total_episodes']),('total_frames',info['total_frames']),
            ('state',source.layout(info['features']['observation.state'])),
            ('action',source.layout(info['features']['action'])),('cameras',cameras),
            ('units','dataset-native/unverified'),('capture_session_independence','unknown')]:
        if inspection.get(key) != expected:
            raise ValueError('inspection differs from actual source metadata: '+key)
    episodes = inspection['episodes']
    if (not isinstance(episodes,list) or len(episodes) != info['total_episodes']
            or [row['index'] for row in episodes] != list(range(len(episodes)))
            or any(type(row['frames']) is not int or row['frames'] < 1 for row in episodes)
            or sum(row['frames'] for row in episodes) != info['total_frames']):
        raise ValueError('inspection episode/frame coverage differs')


def check_evaluation(evaluation, request, provenance):
    inspection, split = request['inspection'], request['split']
    dimension = inspection['action']['shape'][0]
    if (evaluation.get('model_reloaded_in_new_process') is not True
            or evaluation.get('physical_task_success') is not None
            or evaluation.get('physical_learning_verified') is not False
            or evaluation.get('joint_names') != inspection['action']['names']
            or evaluation.get('units') != 'dataset-native/unverified'):
        raise ValueError('fresh evaluation facts differ')
    for key, expected in [('inspection_revision', inspection['revision']),
            ('split_revision',split['revision']),('source_revision',request['source_revision']),
            ('study_id',request['study_id']),('project_id',request['project_id']),('compute_host',request['compute_host'])]:
        if evaluation.get(key) != expected:
            raise ValueError('evaluation request binding differs: '+key)
    if not isinstance(evaluation.get('splits'),dict) or set(evaluation['splits']) != {'validation','eval'}:
        raise ValueError('explicit validation/eval reports required')
    mapping = {m['source_episode']:m for m in provenance['episode_mapping']}
    for name in ('validation','eval'):
        rows = evaluation['splits'][name]
        if not isinstance(rows,list) or [r['episode'] for r in rows] != split[name]:
            raise ValueError('held-out episode evaluation coverage differs')
        for row in rows:
            expected = min(128,inspection['episodes'][row['episode']]['frames'])
            if (type(row['samples']) is not int or row['samples'] != expected
                    or row.get('policy_reset') is not True
                    or row.get('derived_episode') != mapping[row['episode']]['derived_episode']):
                raise ValueError('bounded per-episode evaluation/reset differs')
            for key in ('mae_per_joint','train_mean_baseline_mae_per_joint'):
                finite_vector(row[key],dimension)
            predictions = row.get('prediction_samples')
            if not isinstance(predictions,list) or len(predictions) != min(4,expected):
                raise ValueError('bounded prediction evidence required')
            for frame,prediction in enumerate(predictions):
                if prediction.get('frame') != frame:
                    raise ValueError('prediction frame sequence differs')
                for key in ('target','predicted'):
                    values = prediction.get(key)
                    if (not isinstance(values,list) or len(values) != dimension
                            or any(type(v) not in (float,int) or not math.isfinite(v) for v in values)):
                        raise ValueError('finite prediction vectors required')
    rows = evaluation['splits']['eval']
    count = sum(row['samples'] for row in rows)
    if type(evaluation.get('samples')) is not int or evaluation['samples'] != count:
        raise ValueError('evaluation aggregate sample count differs')
    for key in ('mae_per_joint','train_mean_baseline_mae_per_joint'):
        finite_vector(evaluation.get(key),dimension)
        expected = [sum(row[key][i]*row['samples'] for row in rows)/count for i in range(dimension)]
        if any(not math.isclose(a,b,rel_tol=1e-7,abs_tol=1e-9) for a,b in zip(evaluation[key],expected)):
            raise ValueError('sample-weighted evaluation aggregate differs')


def check_mapping(provenance, request):
    inspection, split = request['inspection'], request['split']
    selected = sorted(set(split['train']+split['validation']+split['eval']))
    offsets, offset = {}, 0
    for row in inspection['episodes']:
        offsets[row['index']] = offset
        offset += row['frames']
    mappings, derived, train = [], 0, 0
    for index, episode in enumerate(selected):
        frames = inspection['episodes'][episode]['frames']
        training = episode in split['train']
        mappings.append(dict(source_episode=episode, derived_episode=index,
            source_start=offsets[episode], derived_start=derived, frames=frames,
            train_episode=split['train'].index(episode) if training else None,
            train_start=train if training else None))
        derived += frames
        if training:
            train += frames
    if provenance.get('episode_mapping') != mappings:
        raise ValueError('source/derived/train frame mapping differs')


def _check(output, result, request):
    from experiment_lerobot_worker import check_request, configuration, model_files, INSPECT
    check_request(request)
    output = Path(output)
    if output.is_symlink() or not output.is_dir():
        raise ValueError('owned output directory required')
    if load(output,'source-request.json') != request or load(output,'result.json') != result:
        raise ValueError('stored request/result bytes differ')
    if source.verify_files(Path(request['source_root']),request['files']) != request['manifest_revision']:
        raise ValueError('uploaded source manifest differs')
    if load(output,'source-manifest.json') != source.validate_files(request['files']):
        raise ValueError('evidence source manifest differs')
    inspecting = request['schema'] == INSPECT
    schema = 'rosy.lerobot-inspect-result/1' if inspecting else 'rosy.lerobot-train-result/1'
    for key, expected in [('schema',schema),('study_id',request['study_id']),
            ('project_id',request['project_id']),('compute_host',request['compute_host']),('manifest_revision',request['manifest_revision']),
            ('source_revision',request['manifest_revision'])]:
        if result.get(key) != expected:
            raise ValueError('result request binding differs: '+key)
    inspection = load(output,'inspection.json')
    original_info = read_json(Path(request['source_root'])/'meta/info.json')
    check_inspection(inspection,original_info)
    if inspection.get('revision') != source.digest({k:v for k,v in inspection.items() if k != 'revision'}):
        raise ValueError('inspection evidence revision differs')
    evidence = {'source-request.json','source-manifest.json','inspection.json'}
    if inspecting:
        if result.get('inspection') != inspection:
            raise ValueError('inspection result differs from evidence')
    else:
        evidence |= {'provenance.json','split.json','train-config.json','evaluation.json'}
        if inspection != request['inspection'] or load(output,'split.json') != request['split']:
            raise ValueError('training inspection/split changed')
        for key,expected in [('inspection_revision',inspection['revision']),
                ('split_revision',request['split']['revision']),('steps',request['steps']),
                ('batch_size',request['batch_size']),('seed',request['seed']),
                ('physical_learning_verified',False),('policy_activation',False)]:
            if result.get(key) != expected:
                raise ValueError('training result configuration differs: '+key)
        if load(output,'train-config.json') != configuration(output,request):
            raise ValueError('official ACT configuration differs from fixed recipe')
        provenance = load(output,'provenance.json')
        for key,expected in [('study_id',request['study_id']),('project_id',request['project_id']),('compute_host',request['compute_host']),
                ('source_revision',request['source_revision']),('manifest_revision',request['manifest_revision']),
                ('inspection_revision',inspection['revision']),('split',request['split']),
                ('normalization_fit','train only'),('reader_verified',True)]:
            if provenance.get(key) != expected:
                raise ValueError('derivative provenance differs: '+key)
        if provenance.get('source_info') != original_info:
            raise ValueError('original metadata provenance differs')
        check_mapping(provenance,request)
        if (source.hashes(output/'dataset') != provenance['files']
                or source.hashes(output/'train-dataset') != provenance['train_files']):
            raise ValueError('derived dataset/statistics bytes changed')
        model,files = model_files(output)
        if files != result.get('artifact_files'):
            raise ValueError('model/processor artifact bytes changed')
        model_config = read_json(model/'config.json')
        if (model_config.get('type') != 'act'
                or model_config.get('input_features',{}).get('observation.state',{}).get('shape') != inspection['state']['shape']
                or model_config.get('output_features',{}).get('action',{}).get('shape') != inspection['action']['shape']):
            raise ValueError('trained ACT model dimensions differ from inspected layout')
        evaluation = load(output,'evaluation.json')
        if evaluation != result.get('evaluation'):
            raise ValueError('evaluation bytes differ from result')
        check_evaluation(evaluation,request,provenance)
    if not isinstance(result.get('evidence_files'),dict) or set(result['evidence_files']) != evidence:
        raise ValueError('complete fixed evidence file set required')
    for name,expected in result['evidence_files'].items():
        path = output/name
        load(output,name)
        if hashlib.sha256(path.read_bytes()).hexdigest() != expected:
            raise ValueError('evidence file bytes changed: '+name)
    return result


def check_result(output, result, request):
    try:
        return _check(output,result,request)
    except (OSError,KeyError,TypeError,AttributeError,ZeroDivisionError,IndexError) as exc:
        raise ValueError('incomplete uploaded LeRobot result closure') from exc


def archive(output, result, request):
    check_result(output,result,request)
    if request['schema'] != 'rosy.lerobot-train-request/1':
        raise ValueError('only completed training has a model archive')
    from experiment_lerobot_worker import model_files
    output = Path(output)
    model, files = model_files(output)
    paths = [model/name for name in files] + [output/name for name in result['evidence_files']] + [output/'result.json']
    if sum(path.stat().st_size for path in paths) > 256*1024**2:
        raise ValueError('uploaded model archive exceeds 256 MiB')
    entries = {f'model/{name}': (model/name).read_bytes() for name in files}
    for name in result['evidence_files']:
        value = load(output,name)
        if name == 'source-request.json':
            value = {k:v for k,v in value.items() if k != 'source_root'}
        elif name == 'train-config.json':
            value.pop('output_dir')
            value['dataset'].pop('root')
        entries[name] = json.dumps(value,ensure_ascii=False,allow_nan=False).encode()
    entries['result.json'] = (output/'result.json').read_bytes()
    redacted = []
    def redact(value):
        if isinstance(value,dict):
            return {k:redact(v) for k,v in value.items()}
        if isinstance(value,list):
            return [redact(v) for v in value]
        if isinstance(value,str):
            for prefix in (request['source_root'],str(output),str(output.resolve())):
                if value == prefix or value.startswith(prefix+'/') or value.startswith(prefix+'\\'):
                    return '[owned-local-path]'
        return value
    for name,raw in list(entries.items()):
        if name.endswith('.json'):
            value = json.loads(raw)
            sanitized = redact(value)
            if sanitized != value:
                entries[name] = json.dumps(sanitized,ensure_ascii=False,allow_nan=False).encode()
                redacted.append(name)
    entries['archive-manifest.json'] = json.dumps(dict(schema='rosy.lerobot-archive/1',
        redacted_fields=['source-request.json:source_root','train-config.json:output_dir','train-config.json:dataset.root'],
        redacted_json_files=redacted,
        files={name:hashlib.sha256(raw).hexdigest() for name,raw in entries.items()}),sort_keys=True).encode()
    if sum(len(raw) for raw in entries.values()) > 256*1024**2:
        raise ValueError('uploaded model archive exceeds 256 MiB')
    stream = io.BytesIO()
    with zipfile.ZipFile(stream,'w',zipfile.ZIP_DEFLATED) as zipped:
        for name,raw in entries.items():
            zipped.writestr(name,raw)
    if stream.tell() > 256*1024**2:
        raise ValueError('uploaded model archive exceeds 256 MiB')
    return stream.getvalue()
