import hashlib
import json
from pathlib import Path
import sys

import pytest

ROOT = Path(__file__).resolve().parents[4]
sys.path[:0] = [str(ROOT/'middleware/execution/local/src'), str(ROOT/'contracts/learning/src'),
               str(ROOT/'contracts/skill/src'), str(ROOT/'test')]
from rosy.execution.local.policy_install import InstallBinding, load_policy
from rosy.contracts.learning import seal
from test_learning_artifact_contracts import policy


def installed(tmp_path, candidate_changes=None, **changes):
    blob = b'model snapshot'
    file = tmp_path/'weights.bin'
    file.write_bytes(blob)
    ref = dict(path=file.name, bytes=len(blob), sha256=hashlib.sha256(blob).hexdigest())
    doc = policy()
    doc.update(files=[ref], normalization=ref, evaluations=[ref])
    doc.update(candidate_changes or {})
    doc = seal(doc)
    (tmp_path/'policy-artifact.json').write_text(json.dumps(doc), encoding='utf-8')
    values = dict(policy_revision=doc['revision'], profile=doc['profile'],
                  robot_type=doc['robot_type'], environment=doc['environment'],
                  device_profile_revision=doc['device_profile_revision'],
                  camera_profile_revision=doc['camera_profile_revision'],
                  owner=doc['owner'], cameras=doc['cameras'],
                  normalization_sha256=ref['sha256'], action_names=('j1','j2'),
                  action_limits=((-1,1),(-2,2)), timing=doc['timing'])
    values.update(changes)
    return doc, InstallBinding(**values)


def test_load_and_recheck_preserve_fixed_revision(tmp_path):
    doc, binding = installed(tmp_path)
    loaded = load_policy(tmp_path, binding)
    assert loaded.recheck()['revision'] == doc['revision']
    doc['owner']['controller_revision'] = 'changed'
    assert loaded.recheck()['owner']['controller_revision'] == 'controller-1'


@pytest.mark.parametrize('change', [dict(policy_revision='b'*64), dict(environment='real'),
    dict(device_profile_revision='other'), dict(camera_profile_revision=None),
    dict(owner=dict(kind='omx_local_controller',controller_revision='other',envelope_revision='envelope-1')),
    dict(normalization_sha256='b'*64), dict(action_names=('j2','j1')),
    dict(action_limits=((-0.5,0.5),(-2,2))),
    dict(timing=dict(period_ns=200000000,max_observation_age_ns=50000000,max_action_age_ns=50000000)),
    dict(timing=dict(period_ns=100000000,max_observation_age_ns=1,max_action_age_ns=50000000))])
def test_install_scope_mismatch_rejected(tmp_path, change):
    _, binding = installed(tmp_path, **change)
    with pytest.raises(ValueError):
        load_policy(tmp_path, binding)


def test_owner_binding_is_not_mutable_via_input_dict(tmp_path):
    _, binding = installed(tmp_path)
    owner = binding.owner
    owner['controller_revision'] = 'changed'
    assert load_policy(tmp_path, binding).recheck()['owner']['controller_revision'] == 'controller-1'


def test_file_change_after_load_rejected(tmp_path):
    _, binding = installed(tmp_path)
    loaded = load_policy(tmp_path,binding)
    (tmp_path/'weights.bin').write_bytes(b'changed')
    with pytest.raises(ValueError, match='hash/size'):
        loaded.recheck()


def test_recheck_hashes_each_distinct_installed_file_once(tmp_path,monkeypatch):
    _,binding=installed(tmp_path)
    loaded=load_policy(tmp_path,binding)
    opened=[]
    original=Path.open
    def capture(file,*args,**kwargs):
        if file.name=='weights.bin' and args==('rb',):opened.append(file)
        return original(file,*args,**kwargs)
    monkeypatch.setattr(Path,'open',capture)
    loaded.recheck()
    # Shared references still have identical canonical size/SHA metadata;
    # the same bytes need not be rehashed for each declared semantic role.
    assert opened==[tmp_path/'weights.bin']


@pytest.mark.parametrize('field',['normalization','evaluations'])
def test_shared_install_reference_cannot_have_conflicting_metadata(tmp_path,field):
    doc,binding=installed(tmp_path)
    ref=dict(doc['files'][0],sha256='b'*64)
    doc[field]=[ref] if field=='evaluations' else ref
    (tmp_path/'policy-artifact.json').write_text(json.dumps(seal(doc)),encoding='utf-8')
    with pytest.raises(ValueError):load_policy(tmp_path,binding)


def test_manifest_reseal_cannot_replace_installed_revision(tmp_path):
    doc,binding = installed(tmp_path)
    loaded = load_policy(tmp_path,binding)
    doc['tool_revision'] = 'different-source'
    (tmp_path/'policy-artifact.json').write_text(json.dumps(seal(doc)),encoding='utf-8')
    with pytest.raises(ValueError):
        loaded.recheck()


@pytest.mark.parametrize('field,value', [('scale', True), ('source_shape', [3,True,2])])
def test_camera_bool_cannot_alias_installed_number(tmp_path,field,value):
    camera=dict(name='front',identity='camera-1',calibration_sha256='a'*64,
                source_shape=[3,1,2],model_shape=[3,1,2],color='rgb',scale=1)
    expected=dict(camera)
    expected[field]=value
    _, binding = installed(tmp_path,candidate_changes=dict(cameras=[camera]),cameras=[expected])
    with pytest.raises(ValueError):
        load_policy(tmp_path,binding)


def test_camera_profile_revision_must_be_immutable_identifier(tmp_path):
    with pytest.raises(ValueError):
        installed(tmp_path,camera_profile_revision=['profile'])
