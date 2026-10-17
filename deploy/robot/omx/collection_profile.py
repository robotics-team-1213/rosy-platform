"""Explicit collection envelope; no hardware discovery or inferred mechanical limits."""
import hashlib
import json
import math
import time


def digest(document):
    return hashlib.sha256(json.dumps(document, sort_keys=True, separators=(',', ':'),
                                     allow_nan=False).encode()).hexdigest()


def number(value):
    return type(value) in (int, float) and math.isfinite(value)


def require(value, message):
    if not value:
        raise ValueError(message)


def validate_profile(profile, *, mode, acceptance=None, teacher=None):
    require(mode in ('hardware', 'rehearsal'), 'explicit collection mode required')
    require(profile.get('schema') == 'rosy.omx-collection-profile.v1', 'collection profile schema differs')
    for key in ('workcell_id', 'instance_id', 'rig_revision', 'calibration_revision', 'task'):
        require(isinstance(profile.get(key), str) and bool(profile[key].strip()) and '<' not in profile[key],
                'explicit '+key+' required')
    for key in ('max_image_age_s', 'max_sample_gap_s', 'max_state_age_s', 'max_reference_age_s', 'max_session_s'):
        require(number(profile.get(key)) and 0 < profile[key] <= (3600 if key == 'max_session_s' else 2),
                'invalid '+key)
    require(type(profile.get('fps')) is int and 1 <= profile['fps'] <= 30, 'fps must be 1..30')
    require(type(profile.get('free_disk_bytes')) is int and profile['free_disk_bytes'] > 0, 'disk reserve required')
    names, ranges = profile.get('joint_names'), profile.get('normalization')
    require(isinstance(names, list) and len(names) == 6 and all(isinstance(n, str) and n for n in names)
            and len(set(names)) == 6, 'explicit ordered six joints required')
    require(isinstance(ranges, list) and len(ranges) == 6 and all(
        isinstance(pair, list) and len(pair) == 2 and all(number(v) for v in pair) and pair[0] < pair[1]
        for pair in ranges), 'measured native-radian normalization endpoints required')
    reach = profile.get('reach_tolerance_rad')
    require(isinstance(reach, list) and len(reach) == 6 and all(number(v) and 0 < v <= .2 for v in reach),
            'measured per-joint reach tolerance required; Action success is not motion (D-793)')
    shapes = profile.get('camera_shapes')
    require(isinstance(shapes, dict) and set(shapes) == {'top', 'front'} and all(
        isinstance(s, list) and len(s) == 3 and s[2] == 3
        and all(type(v) is int and 0 < v <= 4096 for v in s) for s in shapes.values()), 'two RGB shapes required')
    if 'camera_mounts' in profile:
        validate_camera_mounts(profile['camera_mounts'])
    if mode == 'hardware':
        require(profile.get('enabled') is True, 'hardware collection profile is disabled')
        require(isinstance(acceptance, dict), 'field acceptance receipt required')
        require(acceptance.get('schema') == 'rosy.omx-collection-acceptance.v1'
                and acceptance.get('profile_sha256') == digest(profile)
                and acceptance.get('rig_revision') == profile['rig_revision']
                and acceptance.get('calibration_revision') == profile['calibration_revision'],
                'field acceptance does not match profile')
        require(type(acceptance.get('expires_ns')) is int and acceptance['expires_ns'] > time.time_ns(),
                'field acceptance has expired')
        for key in ('physical_stop_verified', 'workspace_verified', 'gripper_verified',
                    'load_support_verified', 'camera_visibility_verified', 'independent_watchdog_verified'):
            require(acceptance.get(key) is True, 'field acceptance missing '+key)
        if teacher is not None:
            require(acceptance.get('teacher_sha256') == digest(teacher), 'field acceptance teacher differs')
        require(number(profile.get('max_skew_s')) and 0 < profile['max_skew_s'] <= 2,
                'measured capture/reference skew bound required')
        require(number(profile.get('max_frame_jitter_s'))
                and 0 <= profile['max_frame_jitter_s'] <= 1/profile['fps'], 'measured frame cadence bound required')
        ros = profile.get('ros')
        require(isinstance(ros, dict), 'native ROS placement required')
        for key in ('namespace', 'joint_state_topic', 'reference_topic', 'hardware_topic',
                    'trajectory_action', 'environment_state'):
            require(isinstance(ros.get(key), str) and ros[key].startswith('/') and '<' not in ros[key],
                    'explicit ROS '+key+' required')
        require(isinstance(ros.get('owner_config'), dict)
                and ros['owner_config'].get('enabled') is True, 'accepted owner config required')
        require(ros.get('motor_ids') == list(range(11,17)) and isinstance(ros.get('expected_torque'), list)
                and ros['expected_torque'] == [True]*6, 'confirmed powered follower status required')
        require(set(ros.get('image_topics', {})) == {'top', 'front'}
                and set(ros.get('publishers', {})) == {'top','front','joints','reference','hardware'},
                'explicit original producer identities required')
        if 'camera_info_topics' in ros:
            topics = ros['camera_info_topics']
            require(isinstance(topics, dict) and set(topics) == {'top', 'front'} and all(
                isinstance(t, str) and t.startswith('/') and '<' not in t for t in topics.values()),
                'explicit camera_info topics for both cameras required')
    return profile


def validate_camera_mounts(mounts):
    """Declared camera-to-arm placement. A measurement record, not a calibration proof."""
    require(isinstance(mounts, dict) and set(mounts) == {'top', 'front'}, 'camera mounts for both cameras required')
    for role, mount in mounts.items():
        require(isinstance(mount, dict) and set(mount) == {'parent_frame', 'translation_m', 'rotation_xyzw',
                                                           'method'}, role+' camera mount fields differ')
        require(all(isinstance(mount[k], str) and mount[k].strip() and '<' not in mount[k]
                    for k in ('parent_frame', 'method')), role+' camera mount frame and method required')
        translation, rotation = mount['translation_m'], mount['rotation_xyzw']
        require(isinstance(translation, list) and len(translation) == 3 and all(
            number(v) and abs(v) <= 5 for v in translation), role+' camera translation must be three metres')
        require(isinstance(rotation, list) and len(rotation) == 4 and all(number(v) for v in rotation)
                and abs(math.sqrt(sum(v*v for v in rotation))-1) <= 1e-3, role+' camera rotation must be unit xyzw')
    return mounts


def validate_teacher(teacher, profile):
    require(teacher.get('schema') == 'rosy.omx-collection-teacher.v1', 'teacher schema differs')
    steps = teacher.get('steps')
    require(isinstance(steps, list) and 0 < len(steps) <= 100, 'explicit bounded teacher steps required')
    for step in steps:
        require(isinstance(step, dict) and number(step.get('duration_s')) and 0 < step['duration_s'] <= 30,
                'bounded step duration required')
        values = step.get('positions')
        require(isinstance(values, list) and len(values) == 6 and all(number(v) for v in values),
                'six finite native-radian targets required')
        require(all(low <= value <= high for value, (low, high) in zip(values, profile['normalization'])),
                'teacher target outside declared normalization envelope')
    require(sum(step['duration_s'] for step in steps) < profile['max_session_s'], 'teacher exceeds session budget')
    return teacher


def normalize(values, profile):
    require(len(values) == 6 and all(number(v) for v in values), 'six finite native positions required')
    result = []
    for index, (value, (low, high)) in enumerate(zip(values, profile['normalization'])):
        require(low <= value <= high, 'native position outside normalization calibration')
        fraction = (value-low)/(high-low)
        result.append(fraction*100 if index == 5 else fraction*200-100)
    return result
