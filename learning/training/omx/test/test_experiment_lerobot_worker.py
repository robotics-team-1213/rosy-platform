"""File-level training closure rejects cross-study results and changed bytes."""
import copy
import hashlib
import io
import json
from pathlib import Path
import sys
import uuid
import zipfile

import pytest

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from experiment_io import write_json
import experiment_lerobot_source as source
import experiment_lerobot_worker as worker


def completed(tmp_path):
    root, output = tmp_path/'source', tmp_path/'out'
    (root/'meta').mkdir(parents=True)
    output.mkdir()
    info = dict(codebase_version='v3.0',fps=20,robot_type='custom',total_episodes=4,total_frames=8,
        data_path=source.DATA_PATH,features={
            'observation.state':dict(dtype='float32',shape=[7],names=None),
            'action':dict(dtype='float32',shape=[5],names=None),
            'observation.images.front':dict(dtype='image',shape=[32,48,3])})
    write_json(root/'meta/info.json',info)
    raw = (root/'meta/info.json').read_bytes()
    files = [dict(name='meta/info.json',size=len(raw),sha256=hashlib.sha256(raw).hexdigest())]
    inspection = dict(robot_type='custom',fps=20,total_episodes=4,total_frames=8,
        state=source.layout(info['features']['observation.state']),
        action=source.layout(info['features']['action']),
        cameras=[dict(key='observation.images.front',shape=[32,48,3],dtype='image')],
        episodes=[dict(index=i,frames=2,task='pick') for i in range(4)],
        units='dataset-native/unverified',capture_session_independence='unknown')
    inspection['revision'] = source.digest(inspection)
    split = source.validate_split(dict(train=[0,2],validation=[],eval=[3]),inspection)
    request = dict(schema=worker.TRAIN,study_id=str(uuid.uuid4()),project_id='project',compute_host='ai',
        source_root=str(root),files=files,manifest_revision=source.manifest_revision(files),
        source_revision=source.manifest_revision(files),inspection=inspection,split=split,
        steps=2,batch_size=1,seed=7)
    for name in ('dataset','train-dataset'):
        (output/name).mkdir()
        (output/name/'bytes').write_bytes(name.encode())
    mapping = [dict(source_episode=episode,derived_episode=i,source_start=episode*2,
        derived_start=i*2,frames=2,train_episode=i if episode != 3 else None,
        train_start=i*2 if episode != 3 else None) for i,episode in enumerate([0,2,3])]
    provenance = dict(reader_verified=True,source_info=info,episode_mapping=mapping,
        files=source.hashes(output/'dataset'),train_files=source.hashes(output/'train-dataset'),
        normalization_fit='train only',split=split,inspection_revision=inspection['revision'],
        study_id=request['study_id'],project_id='project',compute_host='ai',source_revision=request['source_revision'],
        manifest_revision=request['manifest_revision'])
    model = output/'trainer/checkpoints/last/pretrained_model'
    model.mkdir(parents=True)
    write_json(model/'config.json',dict(type='act',input_features={'observation.state':dict(shape=[7])},
        output_features={'action':dict(shape=[5])}))
    (model/'model.safetensors').write_bytes(b'unit-test-bytes-only')
    for name in ('policy_preprocessor.json','policy_postprocessor.json'):
        write_json(model/name,dict(relative_state='processor.safetensors'))
    (model/'processor.safetensors').write_bytes(b'processor-state')
    report = dict(episode=3,derived_episode=2,samples=2,mae_per_joint=[1.]*5,
        train_mean_baseline_mae_per_joint=[2.]*5,policy_reset=True,
        prediction_samples=[dict(frame=i,target=[0.]*5,predicted=[1.]*5) for i in range(2)])
    evaluation = dict(samples=2,mae_per_joint=[1.]*5,train_mean_baseline_mae_per_joint=[2.]*5,
        joint_names=inspection['action']['names'],units='dataset-native/unverified',
        model_reloaded_in_new_process=True,splits=dict(validation=[],eval=[report]),
        physical_task_success=None,physical_learning_verified=False,
        inspection_revision=inspection['revision'],split_revision=split['revision'],
        source_revision=request['source_revision'],study_id=request['study_id'],project_id='project',compute_host='ai')
    documents = {'source-request.json':request,'source-manifest.json':files,
        'inspection.json':inspection,'split.json':split,'provenance.json':provenance,
        'train-config.json':worker.configuration(output,request),'evaluation.json':evaluation}
    for name,value in documents.items():
        write_json(output/name,value)
    result = dict(schema='rosy.lerobot-train-result/1',study_id=request['study_id'],project_id='project',compute_host='ai',
        manifest_revision=request['manifest_revision'],source_revision=request['source_revision'],
        inspection_revision=inspection['revision'],split_revision=split['revision'],
        steps=2,batch_size=1,seed=7,artifact_files=source.hashes(model),evaluation=evaluation,
        physical_learning_verified=False,policy_activation=False,
        evidence_files={name:hashlib.sha256((output/name).read_bytes()).hexdigest() for name in documents})
    write_json(output/'result.json',result)
    return output,result,request


def test_a_stored_request_without_the_recipe_still_checks(tmp_path):
    output,result,request = completed(tmp_path)
    assert 'optimizer_lr' not in request and worker.check_request(request) == request
    assert worker.check_result(output,result,request) == result


def test_the_recipe_reaches_the_config_only_when_named_and_the_model_must_match(tmp_path):
    output,result,request = completed(tmp_path)
    shipped = worker.configuration(output,request)['policy']
    assert shipped['chunk_size'] == 4 and 'optimizer_lr' not in shipped
    tuned = dict(request,optimizer_lr=1e-4,chunk_size=20)
    policy = worker.configuration(output,tuned)['policy']
    assert policy['chunk_size'] == 20 and policy['optimizer_lr'] == policy['optimizer_lr_backbone'] == 1e-4
    assert worker.check_request(tuned) == tuned
    for bad in (dict(tuned,optimizer_lr=1.0),dict(tuned,chunk_size=0),dict(tuned,other=1)):
        with pytest.raises(ValueError):
            worker.check_request(bad)
    write_json(output/'train-config.json',worker.configuration(output,tuned))
    write_json(output/'source-request.json',tuned)
    for name in ('train-config.json','source-request.json'):
        result['evidence_files'][name] = hashlib.sha256((output/name).read_bytes()).hexdigest()
    model = output/'trainer/checkpoints/last/pretrained_model'
    config = json.loads((model/'config.json').read_text())
    for lr,accepted in ((1e-3,False),(1e-4,True)):
        write_json(model/'config.json',dict(config,chunk_size=20,optimizer_lr=lr))
        result['artifact_files'] = source.hashes(model)
        write_json(output/'result.json',result)
        if accepted:
            assert worker.check_result(output,result,tuned) == result
        else:
            with pytest.raises(ValueError,match='optimizer_lr'):
                worker.check_result(output,result,tuned)


def test_closed_model_archive_redacts_host_paths_and_tracks_exported_hashes(tmp_path):
    output,result,request = completed(tmp_path)
    assert worker.check_result(output,result,request) == result
    archive = worker.archive(output,result,request)
    with zipfile.ZipFile(io.BytesIO(archive)) as zipped:
        assert 'model/model.safetensors' in zipped.namelist()
        assert not any(name.startswith(('dataset/','train-dataset/','cache/')) for name in zipped.namelist())
        manifest = json.loads(zipped.read('archive-manifest.json'))
        for name,digest in manifest['files'].items():
            assert hashlib.sha256(zipped.read(name)).hexdigest() == digest
        assert 'source_root' not in json.loads(zipped.read('source-request.json'))
        assert str(tmp_path).encode() not in b''.join(zipped.read(name) for name in zipped.namelist())


@pytest.mark.parametrize('fault',['source','processor','derived','evaluation','project','split','config'])
def test_completed_closure_rejects_changed_bytes_or_binding(tmp_path,fault):
    output,result,request = completed(tmp_path)
    if fault == 'source':
        Path(request['source_root'],'meta/info.json').write_bytes(b'changed')
    elif fault == 'processor':
        (output/'trainer/checkpoints/last/pretrained_model/processor.safetensors').write_bytes(b'changed')
    elif fault == 'derived':
        (output/'train-dataset/bytes').write_bytes(b'changed')
    elif fault == 'evaluation':
        evaluation = copy.deepcopy(result['evaluation'])
        evaluation['model_reloaded_in_new_process'] = False
        write_json(output/'evaluation.json',evaluation)
    elif fault == 'project':
        request = dict(request,project_id='other-project')
    elif fault == 'split':
        request = dict(request,split=source.validate_split(dict(train=[0],validation=[],eval=[2]),request['inspection']))
    else:
        write_json(output/'train-config.json',dict(policy=dict(type='act',push_to_hub=True)))
    with pytest.raises(ValueError):
        worker.check_result(output,result,request)
    with pytest.raises(ValueError):
        worker.archive(output,result,request)
