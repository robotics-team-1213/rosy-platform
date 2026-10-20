"""Offline byte-bound truth for the fixed assisted OMX pallet-A-slot-1 SIM task."""
import hashlib
import json
import math
from pathlib import Path
import xml.etree.ElementTree as ET

from .artifacts import _fields, _ref

SCHEMA = 'rosy.omx-sim-object-truth/1'
TASK = 'omx-assisted-infeed-to-pallet-a-slot-1/v1'
GOAL = (.2075, .0725, .025)
PINNED = {
    'cell': '1184a692e42486436acb2ba30fdb01489144b9bc9424779d28999d2e3a02160f',
    'recipe': '9e05cd3758833d18c7d634276539d3c0c96a8b69d9acf05752d6d046661a8b10',
    'profile': 'b7f124cf067b915da61fc259c185c147328e7152acf3db1a5b4edb0d88a7ba19',
    'source_world': '6bef11e3a9eb12879b17f3cda7fd9d392b9dcddeb31dbefb6a2a6a90bce79913',
    'camera_source': '3974f855b61c852c933772929112ff06104ba1a8f5e8bde034b9ebe13d64c61c',
}


def judge_episode(samples, *, model, initial_z, goal, released_at, released):
    result = {'success': False, 'lift_m': 0., 'stable_sim_s': 0.,
              'xy_error_m': None, 'z_error_m': None}
    previous, stable_since = None, None
    try:
        if not all(type(x) in (float, int) and math.isfinite(x) for x in (initial_z, *goal, released_at)):
            raise ValueError('nonfinite task inputs')
        for sample in samples:
            pose = sample['model_pose_base']
            clock = sample['clock']
            xyz = tuple(pose[key] for key in ('x_m', 'y_m', 'z_m'))
            finger = sample['gripper_position']
            if (sample['model_id'] != model or
                    not all(type(x) in (float, int) and math.isfinite(x) for x in (*xyz, clock, finger))
                    or clock < 0 or previous and clock <= previous[0]):
                raise ValueError('invalid object identity, clock or measurement')
            result['lift_m'] = max(result['lift_m'], xyz[2] - initial_z)
            result['xy_error_m'] = math.hypot(xyz[0] - goal[0], xyz[1] - goal[1])
            result['z_error_m'] = abs(xyz[2] - goal[2])
            if clock >= released_at:
                good = (result['xy_error_m'] <= .01 and result['z_error_m'] <= .005
                        and abs(finger - 1.) <= .05)
                if previous and previous[0] >= released_at:
                    dt = clock - previous[0]
                    good = good and dt <= .5 and math.dist(xyz, previous[1]) / dt <= .01
                stable_since = (clock if stable_since is None else stable_since) if good else None
                result['stable_sim_s'] = 0. if stable_since is None else clock - stable_since
            previous = clock, xyz
    except (KeyError, TypeError, ValueError, OverflowError) as error:
        result['reason'] = str(error)
        return result
    result['success'] = bool(released and result['lift_m'] >= .03 and result['stable_sim_s'] >= 2.)
    return result


def _validate(path, validated, source):
    path = Path(path).resolve()
    document = json.loads(path.read_bytes())
    _fields(document, 'schema task episode_id instance_id source files sim_aid')
    if document['schema'] != SCHEMA or document['task'] != TASK or document['sim_aid'] is not True:
        raise ValueError('fixed assisted SIM object truth required')
    manifest, rows = validated['manifest'], validated['samples']
    provenance = manifest['provenance']
    if (document['episode_id'] != manifest['episode_id'] or document['instance_id'] != provenance['instance_id']
            or document['source'] != provenance):
        raise ValueError('SIM truth recording identity differs')
    files = document['files']
    _fields(files, 'manifest samples events cell recipe profile source_world camera_source world observations phases commands result native_manifest')
    payloads = {}
    for ref in files.values():
        _ref(ref, path.parent)
        target = path.parent/ref['path']
        if any(p.is_symlink() for p in (target, *target.parents) if p.is_relative_to(path.parent)):
            raise ValueError('SIM truth symlink refused')
        if ref['path'] in payloads:
            raise ValueError('duplicate SIM proof path')
        payloads[ref['path']] = target.read_bytes()
    data = {key: payloads[ref['path']] for key, ref in files.items()}
    if source is not None:
        for name, filename in [('manifest','manifest.json'),('samples','samples.jsonl'),('events','events.jsonl')]:
            if data[name] != (Path(source)/filename).read_bytes():
                raise ValueError('SIM truth original bytes differ')
    if json.loads(data['manifest']) != manifest:
        raise ValueError('SIM truth original manifest differs')
    for name in ('samples', 'events'):
        if hashlib.sha256(data[name]).hexdigest() != manifest[name+'_sha256']:
            raise ValueError('SIM truth original stream differs')
    for name, digest in PINNED.items():
        if hashlib.sha256(data[name]).hexdigest() != digest:
            raise ValueError('fixed SIM task input differs: '+name)
    if hashlib.sha256(data['world']).hexdigest() != provenance['world_sha256']:
        raise ValueError('SIM camera world differs')
    original, derived = (ET.fromstring(data[name]).find('world') for name in ('source_world', 'world'))
    if (derived.attrib != original.attrib or derived.attrib.get('name') != 'omx_cell_workcell'
            or [ET.tostring(n) for n in list(derived)[:len(original)]] != [ET.tostring(n) for n in original]):
        raise ValueError('fixed task world geometry differs')
    camera = derived.find("model[@name='workcell_camera']/link/sensor")
    pilot = ET.fromstring(data['camera_source']).find('world')
    expected_camera = [pilot.find("plugin[@name='gz::sim::systems::Sensors']"),
                       pilot.find("model[@name='workcell_camera']")]
    if (len(derived) != len(original)+2 or camera is None
            or camera.findtext('camera/image/width') != '320'
            or camera.findtext('camera/image/height') != '240'
            or camera.findtext('topic') != '/workcell_camera/image'):
        raise ValueError('fixed SIM camera differs')
    if [ET.tostring(n) for n in list(derived)[len(original):]] != [ET.tostring(n) for n in expected_camera]:
        raise ValueError('SIM camera geometry differs from pinned source')
    joints = ['joint'+str(i) for i in range(1,6)] + ['gripper_joint_1']
    limits = dict(zip(joints, [[-2.6,2.6],[-1.7,1.2],[-1.3,1.7],[-.3,2.3],[-2.,2.],[-.1,1.1]]))
    if (provenance['fps'] != 10 or provenance['instance_id'] != 'omx_cell_sim_01'
            or provenance['calibration_revision'] != 'omx-f-gazebo-only-v1'
            or provenance['joint_names'] != joints or provenance['position_limits_rad'] != limits
            or provenance['camera']['identity'] != 'gazebo:omx_cell_workcell:front:'+provenance['world_sha256']
            or (provenance['camera']['width'], provenance['camera']['height']) != (320,240)):
        raise ValueError('SIM rig identity differs')
    result = json.loads(data['result'])
    native = json.loads(data['native_manifest'])
    inventory_hash = hashlib.sha256(json.dumps(native['source_hashes'], sort_keys=True,
                                               separators=(',', ':')).encode()).hexdigest()
    if (native['revision'] != provenance['source_revision'] or inventory_hash != provenance['source_tree_sha256']
            or native.get('experiment') != 'pick-place-demonstrations'):
        raise ValueError('SIM native source inventory differs')
    phases, commands, observations = (json.loads(data[name]) for name in ('phases','commands','observations'))
    if (result['episode_id'] != manifest['episode_id'] or result['source'] != {
            key: provenance[key] for key in ('source_revision','source_tree_sha256','vendor_revision','world_sha256')}
            or result['capture'] != manifest or result['sim_aid'] is not True
            or result['profile_revision'] != PINNED['profile']
            or len(result['goal_m']) != 3
            or any(type(a) not in (int,float) or not math.isfinite(a) or abs(a-b) > 1e-12
                   for a,b in zip(result['goal_m'], GOAL))):
        raise ValueError('SIM execution receipt differs')
    if [p['phase_id'] for p in phases] != ['approach','grasp','transfer','release']:
        raise ValueError('SIM transfer phase evidence missing')
    times = [p[k] for p in phases for k in ('started_sim_s','ended_sim_s')]
    times += [result['recording_start_sim_s'], result['recording_end_sim_s']]
    if any(type(t) not in (int,float) or not math.isfinite(t) or t < 0 for t in times):
        raise ValueError('SIM execution time invalid')
    if any(p['started_sim_s'] > p['ended_sim_s'] for p in phases):
        raise ValueError('SIM phase clock reversed')
    for left, right in zip(phases, phases[1:]):
        if not left['started_sim_s'] <= left['ended_sim_s'] <= right['started_sim_s']:
            raise ValueError('SIM phases out of order')
    grasp, release = phases[1], phases[-1]
    for name, phase in [('hold_receipt',grasp), ('release_receipt',release)]:
        if (phase[name]['instance_id'] != provenance['instance_id'] or phase[name]['object_id'] != 'box'):
            raise ValueError('SIM gripper receipt identity differs')
    for name, phase in [('attach',grasp), ('detach',release)]:
        if phase[name]['confirmed'] is not True or phase[name]['model'] != 'infeed_block':
            raise ValueError('SIM object attachment state unproven')
    indexed = {command['command_id']: command for command in commands}
    if len(indexed) != len(commands):
        raise ValueError('duplicate SIM command identity')
    for row in rows:
        command = indexed[row['command_id']]
        if (command['response']['state'] not in {'LOCAL_ACCEPTED','ROS_ACCEPTED','RUNNING','SUCCEEDED'}
                or row['duration_s'] != command['duration_s']
                or row['action'] != [command['target'][n] for n in provenance['joint_names']]):
            raise ValueError('recorded SIM action differs from actual command')
    first, last = rows[0]['capture_time_ns']/1e9, rows[-1]['capture_time_ns']/1e9
    if (not observations or observations[0]['clock'] > first or observations[-1]['clock'] < last
            or first < result['recording_start_sim_s'] or last > result['recording_end_sim_s']
            or not 0 <= phases[0]['started_sim_s']-observations[0]['clock'] <= .5
            or abs(last-observations[-1]['clock']) > .5
            or release['ended_sim_s'] > last):
        raise ValueError('SIM observer and recording time ranges differ')
    start = observations[0]['model_pose_base']
    if math.dist((start['x_m'],start['y_m'],start['z_m']), (0.,.17,.015)) > .005:
        raise ValueError('SIM object did not start at fixed infeed')
    metrics = judge_episode(observations, model='infeed_block',
        initial_z=observations[0]['model_pose_base']['z_m'], goal=GOAL,
        released_at=release['ended_sim_s'], released=True)
    if 'reason' in metrics or manifest['task_outcome'] != ('success' if metrics['success'] else 'failure'):
        raise ValueError('recorded task outcome contradicts measured SIM truth')
    return {'document': document, 'payloads': payloads, 'metrics': metrics}


def validate_truth(path, validated, *, source=None):
    try:
        return _validate(path, validated, source)
    except (KeyError, TypeError, AttributeError, IndexError, OverflowError, ET.ParseError) as error:
        raise ValueError('malformed SIM object truth') from error
