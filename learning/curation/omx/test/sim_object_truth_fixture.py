"""Synthetic unit fixture only; never evidence of a simulator or policy run."""
import hashlib
import io
import json
from pathlib import Path
import sys
from uuid import UUID

from PIL import Image
import yaml

ROOT = Path(__file__).resolve().parents[4]
sys.path[:0] = [str(ROOT/'middleware/devices/omx/adapter'), str(ROOT/'deploy/robot/omx')]
from omx_adapter.demonstration import DemonstrationRecorder
from sim_pick_place_demonstrations import camera_world


def write(path, value):
    path.write_text(json.dumps(value), encoding='utf-8')


def fixture(tmp_path):
    run = tmp_path/'run'
    run.mkdir()
    assets = {
        'cell': 'operations/processes/cell/examples/omx_sim/cell.yaml',
        'recipe': 'operations/processes/cell/examples/omx_sim/recipe.yaml',
        'profile': 'deploy/robot/omx/sim/cell_profile.yaml',
        'source_world': 'integrations/simulation/gazebo/worlds/omx_cell_workcell_sim_aid.sdf',
        'camera_source': 'integrations/simulation/gazebo/worlds/omx_pilot_workcell.sdf',
    }
    inventory = {name: hashlib.sha256((ROOT/name).read_bytes()).hexdigest() for name in assets.values()}
    native = {'revision': 'a'*40, 'experiment': 'pick-place-demonstrations', 'source_hashes': inventory}
    native_path = tmp_path/'native.json'
    write(native_path, native)
    camera_world(ROOT/assets['source_world'], ROOT/assets['camera_source'], run/'camera-world.sdf')
    world_hash = hashlib.sha256((run/'camera-world.sdf').read_bytes()).hexdigest()
    profile = yaml.safe_load((ROOT/assets['profile']).read_text())
    joints = list(profile['joints'])+[profile['gripper']['joint']]
    limits = {n: profile['joints'][n]['position'] for n in joints[:-1]}
    limits[joints[-1]] = profile['gripper']['position']
    source = {'simulation': True, 'instance_id': 'omx_cell_sim_01', 'source_revision': 'a'*40,
        'vendor_revision': '0a4af6a923b8b7d80b8c20506d1839c54d2e993e', 'world_sha256': world_hash,
        'source_tree_sha256': hashlib.sha256(json.dumps(inventory,sort_keys=True,separators=(',',':')).encode()).hexdigest(),
        'calibration_revision': 'omx-f-gazebo-only-v1', 'clock_domain': 'gazebo_sim',
        'joint_names': joints, 'position_limits_rad': limits, 'gripper_joint': joints[-1], 'fps': 10,
        'camera': {'name': 'front', 'identity': 'gazebo:omx_cell_workcell:front:'+world_hash,
                   'width': 320, 'height': 240,
                   'camera_info_sha256': 'd1b538c8a736b665e05433276033d8722519e8ff1533310f8d6ede6ae8ce00bc'}}
    recorder = DemonstrationRecorder(run/'recordings', source)
    episode = recorder.start('Lift infeed_block and place in fixed pallet A slot 1')
    image = io.BytesIO()
    Image.new('RGB', (320,240), (12,34,56)).save(image, format='PNG')
    commands, phases, observations = [], [], []
    commands.append(dict(command_id='home-before-recording',target=dict.fromkeys(joints,0.),
                         duration_s=.8,response={'state':'LOCAL_ACCEPTED'},sim_time=.1))
    for index, name in enumerate(['approach','grasp','transfer','release']):
        start, end = 1+index*.8, 1+(index+1)*.8
        command, goal = 'command-'+name, str(UUID(int=index+1))
        target = {joint: 0. for joint in joints}
        target['gripper_joint_1'] = .38 if name in ('grasp','transfer') else 1.
        accepted = round((start-.01)*1e9)
        recorder.event(dict(kind='GOAL_ACCEPTED',command_id=command,goal_id=goal,sequence=1,
                            status=None,result_code=None,accepted_sim_time_ns=accepted,target=target,duration_s=.8))
        recorder.event(dict(kind='TERMINAL_RESULT',command_id=command,goal_id=goal,sequence=2,status=4,result_code=0))
        commands.append(dict(command_id=command, target=target, duration_s=.8,
                             response={'state':'LOCAL_ACCEPTED'}, sim_time=start-.01))
        phase = dict(phase_id=name, started_sim_s=start,ended_sim_s=end,
                     started_owner_s=100+start,ended_owner_s=100+end)
        if name in ('grasp','release'):
            held = name == 'grasp'
            observation = dict(workcell_id='omx_cell_sim',instance_id='omx_cell_sim_01',
                sensor_revision='omx-sim-width-matched-position-v2',sequence=123 if held else 234,
                received_at=100+end-.01,state='CLOSED' if held else 'OPEN',
                object_present=held,object_id='box' if held else None,owner_generation=1)
            receipt = {key: observation[key] for key in ('workcell_id','instance_id','sensor_revision',
                        'sequence','received_at','owner_generation')}
            receipt['object_id'] = 'box'
            prefix = 'hold' if held else 'release'
            phase[prefix+'_receipt'] = receipt
            phase[prefix+'_evidence'] = dict(observation=observation,receipt=receipt,
                checked_owner_s=100+end-.005,max_age_s=.5)
            phase['attach' if held else 'detach'] = dict(model='infeed_block',
                command='attach (entity/system/add on omx_f)' if held else 'detach',
                sent_wall=1_700_000_000+end,state_echo='attached' if held else 'detached',confirmed=True)
            if held:
                phase['attach'].update(service_ok=True,re_commanded_after=dict(model='infeed_block',
                    command='detach',sent_wall=1_700_000_000+end+.01,state_echo='detached',confirmed=True))
        phases.append(phase)
    for index in range(56):
        stamp = 1_000_000_000+index*100_000_000
        phase_index = min(index//8,3)
        command = commands[phase_index+1]
        positions = dict(command['target'])
        if phase_index in (1,2): positions['gripper_joint_1'] = .42
        recorder.sample(capture_time_ns=stamp,state_time_ns=stamp-2_000_000,positions=positions,
            target=command['target'],state_sequence=index+1,command_id=command['command_id'],
            ros_goal_id=str(UUID(int=phase_index+1)),duration_s=.8,image_png=image.getvalue(),
            received_at_ns=1_700_000_000_000_000_000+stamp)
        xyz = (0.,.17,.015) if index < 16 else (0.,.17,.115) if index < 24 else (.2075,.0725,.025)
        observations.append(dict(model_id='infeed_block',clock=stamp/1e9,
            model_pose_base=dict(zip(('x_m','y_m','z_m'),xyz)),gripper_position=positions['gripper_joint_1']))
    observations.insert(0, {**observations[0], 'clock': .98})
    manifest = recorder.stop('success')
    assert manifest['status'] == 'complete'
    result = dict(episode_id=episode['episode_id'],source={k:source[k] for k in (
        'source_revision','source_tree_sha256','vendor_revision','world_sha256')},capture=manifest,
        sim_aid=True,goal_m=[.2075,.0725,.025],profile_revision=inventory[assets['profile']],
        recording_start_sim_s=.98,recording_end_sim_s=6.51,success=True,error=None)
    for name, value in [('teacher-result.json',result),('teacher-phases.json',phases),
                        ('teacher-commands.json',commands),('observations.json',observations)]:
        write(run/name,value)
    return run, native_path, run/'recordings'/episode['episode_id']
