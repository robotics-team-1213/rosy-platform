"""Same HOST execution chain; synthetic model/driver, not device acceptance."""
import importlib
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

import pytest

from test_policy_parent_binding import setup_parent, mint
from omx_adapter.action_api import ActionApi
from omx_adapter.journal_identity import journal_identity
from omx_adapter.ros_goal_contract import RosGoalEvent


def setup(tmp_path):
    runner, grant, journal, commands, goal, runtime, _ = setup_parent(tmp_path)
    parent = mint(runner, grant)
    identity = journal_identity(runner.store.path)  # Actual owner setup, not verifier.
    api = ActionApi(runner, identity={'journal_id': identity})
    runtime._dispatch_goal_event(RosGoalEvent(
        'TERMINAL_RESULT', commands[0], None, goal, 10.01, 2, status=4, result_code=0))
    runner.record_terminal('action', 'attempt', driver_goal_id=goal, outcome='SUCCEEDED',
        result_source='host_fixture', result_observed_at=datetime.now(timezone.utc).isoformat(),
        result={}, peer_uid=1001)
    return parent, api, journal, commands[0], goal, identity


def produce(tmp_path):
    parent, api, journal, command, goal, identity = setup(tmp_path)
    module = importlib.import_module('rosy.execution.local.policy_episode')
    doc = module.publish(parent, api, journal, command, tmp_path/'episode')
    return doc, tmp_path/'episode', goal, identity


def test_original_native_execution_to_episode_to_fleet(tmp_path):
    doc, root, goal, identity = produce(tmp_path)
    assert doc['profile'] == 'omx_policy_execution_v1'
    assert doc['status'] == 'incomplete'
    assert doc['revisions']['policy'] is not None
    assert doc['outcome']['task'] == 'unknown'
    sys.path.insert(0, str(Path(__file__).resolve().parents[4]/'learning/registry/policy'))
    from fleet_join import export
    result = export(root/'manifest.json', root/'owner-receipts/000000.json', tmp_path/'fleet.json')
    assert result['status'] == 'matched'
    assert result['policy_revision'] == doc['revisions']['policy']
    assert result['binding']['journal_id'] == identity
    assert result['receipt']['driver_goal_id'] == goal
    assert result['episode_outcome']['task'] == 'unknown'


@pytest.mark.parametrize('mutation', ['missing', 'api_id', 'database_id', 'other_runner'])
def test_actual_owner_api_requires_existing_same_journal(tmp_path, mutation):
    parent, api, journal, command, _, _ = setup(tmp_path)
    runner = api.runner
    if mutation == 'missing':
        with runner.store._connect() as db:
            db.execute('DROP TABLE omx_journal_identity')
    elif mutation == 'api_id':
        api.identity['journal_id'] = 'invented-id'
    elif mutation == 'database_id':
        with runner.store._connect() as db:
            db.execute("UPDATE omx_journal_identity SET journal_id='other-id'")
    else:
        api.runner = object()
    from rosy.execution.local.policy_episode import publish
    with pytest.raises(PermissionError):
        publish(parent,api,journal,command,tmp_path/'reject')
    assert not (tmp_path/'reject'/'manifest.json').exists()


def test_publication_never_replaces_complete_or_incomplete_output(tmp_path):
    parent,api,journal,command,_,_ = setup(tmp_path)
    from rosy.execution.local.policy_episode import publish
    output = tmp_path/'episode'
    original = publish(parent,api,journal,command,output)
    raw = (output/'manifest.json').read_bytes()
    with pytest.raises(ValueError): publish(parent,api,journal,command,output)
    assert (output/'manifest.json').read_bytes() == raw
    assert original['status'] == 'incomplete'


@pytest.mark.parametrize('mutation', ['expiry', 'source', 'api_identity', 'native'])
def test_final_manifest_io_cannot_hide_current_change(tmp_path,monkeypatch,mutation):
    parent,api,journal,command,_,_ = setup(tmp_path)
    from rosy.execution.local.policy_episode import publish
    from datetime import timedelta
    old = Path.open
    class DelayedFile:
        def __init__(self, file): self.file=file
        def __enter__(self): return self.file.__enter__()
        def __exit__(self,*args):
            result = self.file.__exit__(*args)
            if mutation == 'expiry':
                api.runner.now = lambda: datetime.now(timezone.utc)+timedelta(days=1)
            elif mutation == 'api_identity': api.identity['journal_id']='changed'
            elif mutation == 'source':
                with journal._connect() as db:
                    db.execute("UPDATE policy_source_files SET payload=? WHERE path='policy/model.bin'",(b'changed',))
            else:
                with journal._connect() as db:
                    db.execute('UPDATE policy_commands SET driver_goal_id=? WHERE command_id=?',('changed',command))
            return result
    def altered(file,*args,**kwargs):
        stream=old(file,*args,**kwargs)
        return DelayedFile(stream) if file.name=='.manifest.pending' and args==('xb',) else stream
    monkeypatch.setattr(Path,'open',altered)
    with pytest.raises((PermissionError,ValueError)):
        publish(parent,api,journal,command,tmp_path/'episode')
    assert not (tmp_path/'episode'/'manifest.json').exists()


@pytest.mark.parametrize('mutation', ['policy', 'task', 'status', 'observation', 'journal', 'goal'])
def test_resealed_episode_does_not_promote_or_rebind_original_evidence(tmp_path,mutation):
    doc,root,_,_=produce(tmp_path)
    from rosy.contracts.learning import seal
    from rosy.contracts.learning.omx_execution import validate_profile
    if mutation == 'policy': doc['revisions']['policy']='c'*64
    elif mutation == 'task': doc['outcome']['task']='success'
    elif mutation == 'status': doc['status']='complete'
    else:
        import hashlib
        name = 'observation.json' if mutation=='observation' else 'owner-receipts/000000.json'
        data=json.loads((root/name).read_bytes())
        if mutation=='observation': data['evidence']['inference_consumption_verified']=True
        elif mutation=='journal': data['journal_id']='invented'
        else: data['driver_goal_id']='unrelated'
        raw=json.dumps(data).encode()
        (root/name).write_bytes(raw)
        newref=dict(path=name,bytes=len(raw),sha256=hashlib.sha256(raw).hexdigest())
        doc['sources']=[newref if ref['path']==name else ref for ref in doc['sources']]
        doc['streams']={k:newref if ref['path']==name else ref for k,ref in doc['streams'].items()}
        doc['outcome']['evidence']=[newref if ref['path']==name else ref for ref in doc['outcome']['evidence']]
    with pytest.raises(ValueError):validate_profile(seal(doc),root=root)


def test_fleet_same_action_goal_but_different_event_is_unmatched(tmp_path):
    doc,root,_,_=produce(tmp_path)
    from fleet_join import export
    receipt=json.loads((root/'owner-receipts/000000.json').read_bytes())
    receipt['journal_event_id']+=1
    file=tmp_path/'other.json'
    file.write_text(json.dumps(receipt))
    result=export(root/'manifest.json',file,tmp_path/'other-fleet.json')
    assert result['status']=='unmatched'
    assert result['reason']=='original_execution_receipt_mismatch'


def test_resealed_receipt_false_created_cannot_be_integer_zero(tmp_path):
    import hashlib
    from rosy.contracts.learning import seal
    from rosy.contracts.learning.omx_execution import validate_profile
    doc,root,_,_=produce(tmp_path)
    name='owner-receipts/000000.json'
    data=json.loads((root/name).read_bytes())
    assert data['created'] is False
    data['created']=0
    raw=json.dumps(data).encode()
    (root/name).write_bytes(raw)
    ref=dict(path=name,bytes=len(raw),sha256=hashlib.sha256(raw).hexdigest())
    doc['sources']=[ref if item['path']==name else item for item in doc['sources']]
    doc['outcome']['evidence']=[ref if item['path']==name else item for item in doc['outcome']['evidence']]
    with pytest.raises(ValueError):validate_profile(seal(doc),root=root)


def test_missing_raw_observation_execution_episode_is_not_training_dataset(tmp_path):
    from rosy.contracts.learning import seal
    doc,root,_,_=produce(tmp_path)
    import hashlib
    files=[]
    for file in sorted(root.rglob('*')):
        if file.is_file():
            raw=file.read_bytes()
            files.append(dict(path=file.relative_to(tmp_path).as_posix(),bytes=len(raw),
                              sha256=hashlib.sha256(raw).hexdigest()))
    dataset=seal(dict(schema='rosy.dataset-manifest/1',episodes=[doc['revision']],files=files,
                      transformation=dict(tool_revision='host-fixture',config_sha256='a'*64)))
    (tmp_path/'dataset-manifest.json').write_text(json.dumps(dataset))
    sys.path.insert(0, str(Path(__file__).resolve().parents[4]/'learning/registry/policy'))
    from dataset_store import closure
    with pytest.raises(ValueError,match='body profile'):closure(tmp_path)


def test_captured_source_hash_is_checked_after_first_manifest_verification(tmp_path,monkeypatch):
    doc,root,_,_=produce(tmp_path)
    from rosy.contracts.learning import omx_execution
    old=omx_execution.validate_episode
    def altered(*args,**kwargs):
        result=old(*args,**kwargs)
        file=root/'installed/policy/model.bin'
        file.write_bytes(file.read_bytes()+b'changed')
        return result
    monkeypatch.setattr(omx_execution,'validate_episode',altered)
    with pytest.raises(ValueError):omx_execution.validate_profile(doc,root=root)


@pytest.mark.parametrize('mutation', ['negative_time','duration','start_tolerance','observed_clock',
                                    'binding_normalization','binding_timing','native_clock','native_feedback',
                                    'binding_camera_scalar'])
def test_fully_resealed_invalid_original_intent_or_installation_rejects(tmp_path,monkeypatch,mutation):
    from rosy.contracts.learning import seal
    from rosy.contracts.learning.omx_execution import validate_profile,encoded,sha
    if mutation=='binding_camera_scalar':
        import test_policy_parent_binding as fixture
        attached,candidate=fixture.attached,fixture.candidate
        monkeypatch.setattr(fixture,'attached',lambda path:attached(path,camera=True))
        monkeypatch.setattr(fixture,'candidate',lambda session:candidate(session,camera_frames=('c'*64,)))
    doc,root,_,_=produce(tmp_path)
    native=json.loads((root/'native.json').read_bytes())
    intent=native['intent']
    if mutation=='negative_time':intent['command']['trajectory_points'][0]['time_from_start_s']=-1
    elif mutation=='duration':intent['command']['duration_s']=-1
    elif mutation=='start_tolerance':
        intent['command']['start_state_tolerances']['joint_1']=-1
    elif mutation=='observed_clock':intent['candidate']['observed_at_ns']=-1
    elif mutation=='native_clock':native['events'][0]['observed_at_monotonic_s']=False
    elif mutation=='native_feedback':native['events'][0]['feedback_sequence']=1
    else:
        file=root/'installed/installed/binding.json'
        binding=json.loads(file.read_bytes())
        if mutation=='binding_normalization':binding['normalization_sha256']='e'*64
        elif mutation=='binding_camera_scalar':binding['cameras'][0]['source_shape'][1]=2.0
        else:binding['timing']['period_ns']+=1
        file.write_bytes(encoded(binding))
        header=json.loads((root/'source-header.json').read_bytes())
        for ref in header['files']:
            raw=(root/'installed'/ref['path']).read_bytes()
            ref.update(bytes=len(raw),sha256=sha(raw))
        (root/'source-header.json').write_bytes(encoded(header))
        intent['source_revision']=sha(encoded(header))
    (root/'native.json').write_bytes(encoded(native))
    obs=json.loads((root/'observation.json').read_bytes());obs['intent']=intent
    (root/'observation.json').write_bytes(encoded(obs))
    proof=json.loads((root/'proof.json').read_bytes())
    proof['native_snapshot_sha256']=sha(encoded(native));proof['source_revision']=intent['source_revision']
    proof.pop('revision');proof['revision']=sha(encoded(proof))
    (root/'proof.json').write_bytes(encoded(proof))
    def update(value):
        if isinstance(value,dict):
            if set(value)=={'path','sha256','bytes'}:
                raw=(root/value['path']).read_bytes();value.update(bytes=len(raw),sha256=sha(raw))
            else:
                for item in value.values():update(item)
        elif isinstance(value,list):
            for item in value:update(item)
    update(doc)
    with pytest.raises(ValueError):validate_profile(seal(doc),root=root)
