"""Camera admission and sampling guards for the native simulation diagnostic."""
from dataclasses import replace


def camera_tick(lane, now, *, gain):
    decision = lane.manager.tick_gain(now, gain=gain)
    state = lane.state()
    if state is None:
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
