"""Choose actual per-arm model inputs while retaining immutable source provenance."""
from experiment_dataset import ARM_SIGNALS, Episode, ExperimentDataset
from experiment_profile import policy_cameras, profile_revision, validate_profile


def select_dataset(dataset, arm_id=None, *, method='act'):
    if method not in ('act', 'hilserl'):
        raise ValueError('unknown learning method')
    profile = validate_profile(dataset.profile)
    arms = profile['arms']
    if profile['mode'] == 'cooperative' and arm_id is not None:
        raise ValueError('cooperative learning uses all arms; individual arm target refused')
    if arm_id is not None and (not isinstance(arm_id, str) or arm_id not in [arm['id'] for arm in arms]):
        raise ValueError('unknown arm target')
    if profile['mode'] == 'independent' and len(arms) > 1 and arm_id is None:
        raise ValueError('independent multi-arm learning requires an explicit arm target')
    start, columns = 0, []
    for arm in arms:
        end = start + len(arm['joint_names'])
        if arm_id is None or arm['id'] == arm_id:
            columns.extend(range(start, end))
        start = end
    original_revision = profile_revision(profile)
    if arm_id is not None:
        profile['arms'] = [arm for arm in arms if arm['id'] == arm_id]
        profile['cameras'] = [camera for camera in profile['cameras'] if camera['arm_id'] in (None, arm_id)]
        profile = validate_profile(profile)
    scope = dict(mode=profile['mode'], arm_ids=[arm['id'] for arm in profile['arms']],
                 source_profile_revision=original_revision, action_indices=columns,
                 camera_keys=policy_cameras(profile))
    if profile['mode'] == 'cooperative':
        return dataset, scope
    target = profile['arms'][0]['id']
    camera_keys = {camera['input_key'] for camera in profile['cameras']}
    camera_keys.update('next.' + key for key in tuple(camera_keys))
    episodes = []
    for episode in dataset.episodes:
        arrays = episode.arrays
        transitioned = 'next_state' in arrays
        per_arm = any(key.startswith('arms.') for key in arrays)
        if transitioned and len(arms) > 1 and not per_arm:
            raise ValueError('independent arm transitions require explicit per-arm signals')
        if not transitioned and (method == 'hilserl' or dataset.source == 'robot_rollout'):
            raise ValueError('independent arm rollout requires explicit per-arm transition signals')
        values = {key: value for key, value in arrays.items() if key in camera_keys}
        for key in ('observation.state', 'action', *(('next_state',) if transitioned else ())):
            values[key] = arrays[key][:, columns]
        if transitioned:
            prefix = 'arms.' + target + '.' if per_arm else ''
            if any(prefix + signal not in arrays for signal in ARM_SIGNALS):
                raise ValueError('missing independent arm signals')
            values.update({signal: arrays[prefix + signal] for signal in ARM_SIGNALS})
        episodes.append(Episode(dict(episode.metadata), values))
    return ExperimentDataset(profile, dataset.source, episodes, dataset.revision), scope
