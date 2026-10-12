"""Camera admission and sampling guards for the native simulation diagnostic."""
from dataclasses import replace
import math


class CameraLearningWindow:
    """Select once per acquired image; credit only the executed interval."""

    def __init__(self):
        self.stamp = None
        self.action = 1
        self.previous = None
        self.pending = None
        self.reward = 0.
        self.ended = False
        self.last_update = None

    def choose(self, policy, state, stamp, *, frame, train, baseline=False):
        self.pending = None
        if self.ended or state is None:
            return 1
        if (type(stamp) not in (int, float) or not math.isfinite(stamp)
                or (self.stamp is not None and stamp < self.stamp)):
            raise ValueError('Finite nondecreasing camera source stamp required')
        if self.stamp is None or stamp > self.stamp:
            self.stamp = stamp
            self.action = 1 if baseline else policy.choose(state, explore=train)
            self.pending = (state, self.action, frame)
        return self.action

    def learn(self, policy, state, result, *, credit):
        self.last_update = None
        if self.ended:
            return 'episode_closed'
        reward = result['reward']
        if not math.isfinite(reward):
            raise ValueError('Finite measured reward required')
        eligible = (credit is not None and self.previous is not None
                    and (credit['state'], credit['action']) == self.previous[:2]
                    and credit['frame'] >= self.previous[2])
        self.reward = self.reward + reward if eligible else 0.
        done = result['terminated'] or result['truncated']
        status = 'waiting_camera'
        if done or self.pending is not None:
            previous = self.previous[:2] if eligible else None
            total = self.reward
            if done and state is None and credit is not None:
                previous = (credit['state'], credit['action'])
                total = self.reward if eligible else reward
            status = learn_transition(policy, previous, state, dict(result, reward=total))
            if status in ('updated', 'terminal_camera_loss'):
                self.last_update = dict(previous=previous, reward=total, next_state=state, terminated=done)
            self.previous = self.pending
            self.reward = 0.
        if done:
            self.ended = True
            self.previous = None
        return status


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
    if warnings:
        return None
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


def camera_snapshot_due(camera_frames, last, captured):
    key = (last.get('reason'), last.get('strategy'))
    return camera_frames == 0 or (bool(key[0]) and key not in captured and len(captured) < 8)
