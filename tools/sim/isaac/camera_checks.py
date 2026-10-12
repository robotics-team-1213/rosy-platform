"""Camera admission and sampling guards for the native simulation diagnostic."""
from dataclasses import replace


def learn_transition(policy, previous, state, result):
    if state is None:
        if (previous is not None and previous[0] is not None and result['terminated']
                and not result['truncated'] and result.get('reason') == 'camera_lane_lost'
                and result.get('camera_failure_reason') == 'camera_target_unavailable'):
            policy.update(*previous, result['reward'], None, terminated=True)
            return 'terminal_camera_loss'
        return 'invalid_camera_observation'
    if previous is None or previous[0] is None:
        return 'no_previous_observation'
    policy.update(*previous, result['reward'], state,
                  terminated=result['terminated'] or result['truncated'])
    return 'updated'


def remember_camera_action(previous, state, action, frame, candidate, receipts, warnings, halted):
    # A normal CORE return may have sent fallback ZERO; credit only confirmed dispatch.
    if not any(any(twist) for twist in receipts):
        return previous
    if (state is not None and not halted and not warnings and any(candidate)
            and receipts == [candidate]):
        return dict(state=state, action=action, frame=frame, twist=candidate)
    return None  # Unlearned motion (including held-path motion) breaks the credit chain.


def camera_tick(lane, now, *, gain):
    held = lane.last.get('camera_provenance') == 'odom_expected_path'
    decision = lane.manager.tick_gain(now, gain=1. if held else gain)
    state = lane.state()
    if state is None and not (held and lane.current()):
        decision = replace(decision, linear=0., angular=0.)
    return decision, state


def camera_episode_usable(phase, visible_frames):
    usable = visible_frames > 0
    if not usable and phase != 'train':
        raise RuntimeError('existing model produced no usable camera lane; candidate not accepted')
    return usable


def camera_admission_error(phase, visible_frames, learned_steps):
    try:
        camera_episode_usable(phase, visible_frames)
    except RuntimeError as exc:
        return str(exc)
    if phase == 'eval' and learned_steps == 0:
        return 'evaluation visited no learned state'
    return None


def camera_sample_due(frame, episode_start_frame):
    return (frame - episode_start_frame) % 24 == 0
