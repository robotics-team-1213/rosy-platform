"""Bounded in-process handoff from absorbed sensing to CORE policy."""
import math
import time

from .command_gate import CommandPolicy, GateInputs


class ControlPolicyProducer:
    """Publish one classified state with the clocks that produced it.

    This object has no ROS publisher and no motor authority. It is intended to
    be called from the sensor node's serialized callback/timer group.
    """

    def __init__(self, policy, observations, required, applied_revision):
        if not isinstance(policy, CommandPolicy):
            raise ValueError('A Control CommandPolicy is required')
        if not hasattr(observations, 'policy_window'):
            raise ValueError('Observation clock source is required')
        if (not isinstance(applied_revision, str) or not applied_revision.strip() or
                not isinstance(required, (tuple, list)) or not required or
                any(not isinstance(name, str) or not name for name in required)):
            raise ValueError('Required streams and applied revision are required')
        if applied_revision != policy.revision:
            raise ValueError('Applied revision must match the bound policy')
        self.policy = policy
        self.observations = observations
        self.required = tuple(required)
        self.applied_revision = applied_revision
        self.sequence = 0

    def publish(self, inputs, *, now=None, applied_revision=None, translation=None, tracking=None,
                linear_limit=None):
        """Attempt one snapshot; every attempt consumes a sequence number."""
        self.sequence += 1
        if now is None:
            now = time.monotonic()
        revision = self.applied_revision if applied_revision is None else applied_revision
        if (not isinstance(inputs, GateInputs) or type(now) not in (int, float) or
                not math.isfinite(now) or
                (linear_limit is not None and
                 (type(linear_limit) not in (int, float) or
                  not math.isfinite(linear_limit) or linear_limit < 0))):
            self.policy.invalidate()
            return False
        return self.policy.update_observations(
            self.observations, self.required, inputs, now, self.sequence, revision,
            translation=translation, tracking=tracking, linear_limit=linear_limit)
