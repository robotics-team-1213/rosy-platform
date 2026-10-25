"""Bind declared capture lineage to inspected bytes; never grants motion or task success."""
import copy
import re


SCHEMA = 'rosy.omx-native-capture.v1'
ACTION = 'absolute_joint_position_target_normalized'


def _text(value):
    return isinstance(value, str) and bool(value.strip()) and value == value.strip()


def bind_capture(episodes, files, *, source_mode, body_units, rig_revision,
                 calibration_revision, provenance):
    """Missing provenance stays unknown; automatic captures require byte-bound lineage.

    Metadata is a declaration by the recorder, not independent physical acceptance.
    The caller has already read every frame and hashed the dataset files.
    """
    if source_mode not in (None, 'leader_native', 'scripted_teacher'):
        raise ValueError('unsupported native source mode')
    if source_mode is None or (source_mode == 'leader_native' and provenance is None):
        if provenance is not None:
            raise ValueError('capture provenance requires an explicit source mode')
        return dict(source_mode=source_mode or 'unverified_native', episodes=copy.deepcopy(episodes))
    if not isinstance(provenance, dict):
        raise ValueError('scripted_teacher requires capture provenance')
    expected = dict(schema=SCHEMA, source_mode=source_mode, action_semantics=ACTION,
                    body_units=body_units, gripper_units='normalized_0_100',
                    rig_revision=rig_revision, calibration_revision=calibration_revision)
    if body_units != 'normalized_-100_100':
        raise ValueError('bound native captures require normalized native units')
    for key, value in expected.items():
        if provenance.get(key) != value:
            raise ValueError(f'capture provenance differs: {key}')
    teacher = provenance.get('teacher_sha256')
    # D-848: a sealed leader recording has no teacher; its lineage is the sealed session instead.
    if source_mode == 'scripted_teacher' and (not isinstance(teacher, str) or not re.fullmatch('[0-9a-f]{64}', teacher)):
        raise ValueError('capture teacher_sha256 must identify a fixed teacher')
    if source_mode == 'leader_native' and (teacher is not None or not re.fullmatch(
            '[0-9a-f]{64}', str(provenance.get('collection_manifest_sha256', '')))):
        raise ValueError('leader capture must name its sealed collection manifest, not a teacher')
    if provenance.get('files') != files:
        raise ValueError('capture provenance no longer matches dataset bytes')
    groups = provenance.get('episodes')
    if not isinstance(groups, list) or len(groups) != len(episodes):
        raise ValueError('capture provenance must cover every episode')
    bound = copy.deepcopy(episodes)
    for episode, group in zip(bound, groups):
        if (not isinstance(group, dict) or type(group.get('episode_index')) is not int
                or group['episode_index'] != episode['episode_index']):
            raise ValueError('capture episode identity or order differs')
        for key in ('session_id', 'cycle_id'):
            if not _text(group.get(key)):
                raise ValueError(f'capture requires a nonempty {key}')
            episode[key] = group[key]
    return dict(source_mode=source_mode, capture_provenance=copy.deepcopy(provenance), episodes=bound)


def check_capture_groups(episodes, decisions):
    """Keep a session and all attempts/segments of a parent cycle in one split."""
    if len(episodes) != len(decisions):
        raise ValueError('capture review must cover every episode')
    assigned = {'session_id': {}, 'cycle_id': {}}
    for source, decision in zip(episodes, decisions):
        split = decision.get('split')
        if split == 'exclude':
            continue
        for key, groups in assigned.items():
            if key not in source:
                continue  # Legacy declared leader captures do not have collection grouping.
            group = source[key]
            if group in groups and groups[group] != split:
                raise ValueError(f'capture {key} crosses dataset splits')
            groups[group] = split
