"""Subject: bounded navigation sessions measured in real elapsed seconds."""
import math

# Re-exported: wander node and tests import these from here; the shape lives in core_common so robot_web needs no drive import.
from core_common.navigation_options import STRATEGIES, validate_options  # noqa: F401


class NavigationSession:
    def __init__(self):
        self.options = None
        self.active = False
        self.reason = 'idle'
        self.started = self.updated = self.progress_at = 0.
        self.anchor = None
        self.translation_offset = (0., 0.)

    def start(self, options, now):
        options = validate_options(options)
        if self.active or not math.isfinite(now):
            return False
        self.options = options
        self.started = self.updated = self.progress_at = now
        self.anchor = None
        self.translation_offset = (0., 0.)
        self.active = True
        self.reason = 'running'
        return True

    def finish(self, reason):
        if self.active:
            self.active = False
            self.reason = reason

    def tick(self, now, pose=None, translating=False):
        if not self.active:
            return None
        if not math.isfinite(now) or now < self.updated:
            self.finish('clock_invalid')
            return self.reason
        self.updated = now
        if now - self.started >= self.options['duration_s']:
            self.finish('time_limit')
            return self.reason
        # Rotation alone is not progress. Current continuous odometry is
        # supplied by the node; missing samples cannot renew this deadline.
        valid_pose = pose is not None and len(pose) == 2 and all(math.isfinite(v) for v in pose)
        if not translating or not valid_pose:
            self.anchor = None
        else:
            if self.anchor is not None:
                # Keep net translation across short drives separated by turns.
                # Pivot motion and missing-pose intervals never add distance;
                # reversing over the same short segment cancels prior progress.
                self.translation_offset = tuple(
                    total+current-previous for total, current, previous in
                    zip(self.translation_offset, pose, self.anchor))
                if math.hypot(*self.translation_offset) >= .02:
                    self.translation_offset = (0., 0.)
                    self.progress_at = now
            self.anchor = tuple(pose)
        if now - self.progress_at >= self.options['stall_s']:
            self.finish('no_translation')
            return self.reason
        return None

    def snapshot(self):
        elapsed = max(0., self.updated-self.started) if self.options else 0.
        return {'active': self.active, 'reason': self.reason,
                'options': self.options, 'elapsed_s': elapsed,
                'remaining_s': max(0., self.options['duration_s']-elapsed) if self.options else 0.,
                'clock': 'wall_monotonic'}
