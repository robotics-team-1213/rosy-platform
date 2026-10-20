"""Synthetic file compatibility checks, never learned policy task evidence."""
import hashlib
import json
from pathlib import Path
import sys

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT/p) for p in ('learning/training/omx/test',
    'middleware/robot_execution/local/test', 'middleware/devices/omx/adapter/test',
    'deploy/robot/omx')]
from test_omx_policy_session import setup_session
from test_act_inference import artifact
from rosy.contracts.learning import seal
from omx_adapter.command_owner import ArmCommandOwner
from omx_adapter.pose_plan import CellPlanningProfile
from sim_policy_install import prepare_install

WORLD = '181ebcc7f8357098b7c48552048c454611d1e92cdf938ef0eb37bb8186c7ec83'
CAMERA = 'd1b538c8a736b665e05433276033d8722519e8ff1533310f8d6ede6ae8ce00bc'


def inputs(tmp_path):
    root, doc, _ = artifact(tmp_path)
    profile = CellPlanningProfile.load(ROOT/'deploy/robot/omx/sim/cell_profile.yaml')
    config = profile.arm_command_config(workcell_id='omx_cell_sim', instance_id='omx_cell_sim_01',
        calibration_revision='omx-f-gazebo-only-v1', allowed_owners=('learned_policy',))
    owner = ArmCommandOwner(config, None)
    names = list(config.joint_names)
    doc.update(robot_type='omx_sim_ros', device_profile_revision='sim-world:'+WORLD,
        camera_profile_revision=None, joint_names=names,
        observation=dict(names=names, units=['rad']*6, shape=[6]),
        action=dict(names=names, units=['rad']*6, limits=[list(config.position_limits[n]) for n in names],
                    semantics='absolute_joint_position_target_rad'),
        cameras=[dict(name='front', identity='gazebo:omx_cell_workcell:front:'+WORLD,
                      calibration_sha256=CAMERA, source_shape=[3,240,320], model_shape=[3,64,64],
                      color='rgb', scale=1/255)],
        owner=dict(kind='omx_local_controller',controller_revision='unregistered-act-study',
                   envelope_revision='unregistered-source-limits-study'))
    train=[str(i) for i in range(20)]
    validation=[str(i) for i in range(20,25)]
    for filename, change in [('policy/config.json',dict(n_action_steps=1,
        input_features={'observation.state':dict(type='STATE',shape=[6]),
                        'observation.images.front':dict(type='VISUAL',shape=[3,64,64])},
        output_features={'action':dict(type='ACTION',shape=[6])})),
                             ('normalization.json',dict(fixed_source_duration_s=.8,
                                 state_mean=[0]*6,state_std=[1]*6,action_mean=[0]*6,action_std=[1]*6,
                                 fit_episodes=train,image=dict(resize_hw=[64,64],color='rgb',scale=1/255))),
                             ('offline-report.json',dict(verdict='offline_only',
                                 train_episodes=train,eval_episodes=validation,
                                 per_episode={str(i):{} for i in range(20,25)}))]:
        value=json.loads((root/filename).read_text());value.update(change)
        (root/filename).write_text(json.dumps(value))
    def ref(path):
        raw=(root/path).read_bytes()
        return dict(path=path,bytes=len(raw),sha256=hashlib.sha256(raw).hexdigest())
    doc.update(files=[ref(x['path']) for x in doc['files']],normalization=ref('normalization.json'),
               evaluations=[ref('offline-report.json')])
    doc=seal(doc);(root/'policy-artifact.json').write_text(json.dumps(doc))
    return root,doc,owner


def test_parent_and_checkpoint_stay_unchanged_and_installation_is_separate(tmp_path):
    root, parent, owner=inputs(tmp_path)
    original=(root/'policy-artifact.json').read_bytes()
    installed=prepare_install(root,parent['revision'],tmp_path/'installed',owner,
                              normalization_sha256=parent['normalization']['sha256'])
    doc=installed.recheck()
    assert (root/'policy-artifact.json').read_bytes()==original
    assert doc['revision']!=parent['revision']
    assert doc['files']==parent['files']
    assert doc['timing']==dict(period_ns=800_000_000,max_observation_age_ns=500_000_000,
                               max_action_age_ns=500_000_000)
    receipt=json.loads((installed.root/'sim-installation.json').read_text())
    assert receipt['parent']==parent and receipt['operating_authority']=='none'
    assert receipt['independent_task_evaluation'] is False


@pytest.mark.parametrize('fault',['parent','normalization','camera','owner','duration','chunk'])
def test_mismatched_installation_cannot_derive_trust_from_candidate(tmp_path,fault):
    root,parent,owner=inputs(tmp_path)
    pin=parent['revision'];normalization=parent['normalization']['sha256']
    if fault=='parent':pin='a'*64
    elif fault=='normalization':normalization='a'*64
    elif fault=='camera':
        parent['cameras'][0]['identity']='another-camera'
        parent=seal(parent);pin=parent['revision']
        (root/'policy-artifact.json').write_text(json.dumps(parent))
    elif fault=='owner':owner=setup_session(tmp_path/'other')[0].owner
    else:
        path=root/('normalization.json' if fault=='duration' else 'policy/config.json')
        value=json.loads(path.read_text());value.update(
            {'fixed_source_duration_s':.1} if fault=='duration' else {'n_action_steps':4})
        path.write_text(json.dumps(value))
    with pytest.raises(ValueError):
        prepare_install(root,pin,tmp_path/'installed',owner,normalization_sha256=normalization)
    assert not (tmp_path/'installed').exists()
