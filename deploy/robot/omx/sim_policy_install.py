"""Fixed object-task SIM compatibility; grants no operating or promotion authority."""
import hashlib
import json
from pathlib import Path

from act_inference import _configuration
from omx_adapter.command_owner import ArmCommandOwner
from omx_adapter.pose_plan import CellPlanningProfile
from rosy.contracts.learning import seal, validate_policy
from rosy.contracts.learning.sim_object_truth import ASSETS, PINNED
from rosy.execution.local.omx_policy import owner_binding
from rosy.execution.local.policy_install import InstallBinding, load_policy

ROOT = Path(__file__).resolve().parents[3]
WORLD = '181ebcc7f8357098b7c48552048c454611d1e92cdf938ef0eb37bb8186c7ec83'
CAMERA_INFO = 'd1b538c8a736b665e05433276033d8722519e8ff1533310f8d6ede6ae8ce00bc'
TIMING = dict(period_ns=800_000_000, max_observation_age_ns=500_000_000,
              max_action_age_ns=500_000_000)


def prepare_install(parent_root, parent_revision, output, owner, *, normalization_sha256):
    parent_root, output = Path(parent_root).resolve(), Path(output).absolute()
    raw = (parent_root/'policy-artifact.json').read_bytes()
    parent = validate_policy(json.loads(raw), root=parent_root)
    for kind, relative in ASSETS.items():
        if hashlib.sha256((ROOT/relative).read_bytes()).hexdigest() != PINNED[kind]:
            raise ValueError('fixed task asset differs: '+kind)
    profile = CellPlanningProfile.load(ROOT/ASSETS['profile'])
    config = profile.arm_command_config(workcell_id='omx_cell_sim', instance_id='omx_cell_sim_01',
        calibration_revision='omx-f-gazebo-only-v1', allowed_owners=('learned_policy',))
    expected_owner = owner_binding(ArmCommandOwner(config, None))
    cameras = [dict(name='front', identity='gazebo:omx_cell_workcell:front:'+WORLD,
                    calibration_sha256=CAMERA_INFO, source_shape=[3,240,320],
                    model_shape=[3,64,64], color='rgb', scale=1/255)]
    names = list(config.joint_names)
    limits = [list(config.position_limits[name]) for name in names]
    if (parent['revision'] != parent_revision or type(owner) is not ArmCommandOwner
            or owner_binding(owner) != expected_owner
            or parent['profile'] != 'omx_joint_target_v1' or parent['robot_type'] != 'omx_sim_ros'
            or parent['environment'] != 'sim' or parent['device_profile_revision'] != 'sim-world:'+WORLD
            or parent['camera_profile_revision'] is not None or parent['cameras'] != cameras
            or parent['joint_names'] != names or parent['action']['limits'] != limits
            or parent['normalization']['sha256'] != normalization_sha256
            or parent['owner'] != dict(kind='omx_local_controller',controller_revision='unregistered-act-study',
                                      envelope_revision='unregistered-source-limits-study')):
        raise ValueError('research parent differs from independent fixed SIM installation')
    payloads = {ref['path']:(parent_root/ref['path']).read_bytes()
                for ref in [*parent['files'],parent['normalization'],*parent['evaluations']]}
    for ref in [*parent['files'],parent['normalization'],*parent['evaluations']]:
        data=payloads[ref['path']]
        if len(data)!=ref['bytes'] or hashlib.sha256(data).hexdigest()!=ref['sha256']:
            raise ValueError('research file changed during installation')
    steps, stats = _configuration(parent, payloads)
    report = json.loads(payloads['offline-report.json'])
    train, validation = report['train_episodes'], report['eval_episodes']
    if (steps != 1 or stats['fixed_source_duration_s'] != .8 or report['verdict'] != 'offline_only'
            or len(train)!=20 or len(set(train))!=20 or len(validation)!=5 or len(set(validation))!=5
            or set(train)&set(validation) or set(report['per_episode'])!=set(validation)
            or stats['fit_episodes']!=train):
        raise ValueError('fixed training split, duration or fresh-per-step ACT differs')
    if (parent_root/'policy-artifact.json').read_bytes()!=raw:
        raise ValueError('research manifest changed during installation')
    output.mkdir(mode=0o700)
    for relative, data in payloads.items():
        target=output/relative
        target.parent.mkdir(parents=True,exist_ok=True)
        target.write_bytes(data)
    receipt=dict(schema='rosy.omx-sim-installation/1',parent=parent,
        parent_manifest_sha256=hashlib.sha256(raw).hexdigest(),
        source_sha256=hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
        owner=expected_owner,task_assets=PINNED,timing=TIMING,max_target_step_rad=.04,
        minimum_submission_interval_ns=TIMING['period_ns'],trajectory_duration_ns=TIMING['period_ns'],
        operating_authority='none',independent_task_evaluation=False)
    data=json.dumps(receipt,sort_keys=True,allow_nan=False).encode()
    (output/'sim-installation.json').write_bytes(data)
    ref=dict(path='sim-installation.json',bytes=len(data),sha256=hashlib.sha256(data).hexdigest())
    doc=seal(dict(parent,owner=expected_owner,timing=TIMING,camera_profile_revision='sim-camera-info:'+CAMERA_INFO,
                  evaluations=[*parent['evaluations'],ref]))
    (output/'policy-artifact.json').write_text(json.dumps(doc),encoding='utf-8')
    binding=InstallBinding(policy_revision=doc['revision'],profile='omx_joint_target_v1',robot_type='omx_sim_ros',
        environment='sim',device_profile_revision='sim-world:'+WORLD,
        camera_profile_revision='sim-camera-info:'+CAMERA_INFO,owner=expected_owner,cameras=cameras,
        normalization_sha256=normalization_sha256,action_names=names,action_limits=limits,timing=TIMING)
    return load_policy(output,binding)
