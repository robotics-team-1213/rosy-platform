"""Track Fleet transport activity that invalidates stationary peer observations."""
from contextlib import contextmanager

from fleet.server.uncertain_motion import UncertainMotion
from fleet.swarm.motion_ingress import MOTION_TIMEOUT_S, PREPARED_GOALS, starts_or_sustains_motion


class PeerMotionWire(UncertainMotion):
    def __init__(self):
        super().__init__()
        self._wire_versions = {}
        self._wire_pending = {}

    def peer_wire_state(self, robots):
        """A pending request or a changed version invalidates an earlier stationary peer sample."""
        return {robot: (self._wire_versions.get(robot, 0), self._wire_pending.get(robot, 0)) for robot in robots}

    def idle_wire_epoch(self, robot):
        if (self._wire_pending.get(robot) or self.pending.get(robot) or robot in self._uncertain_motion
                or robot in self or self._named_stop_motion and self._named_stop_motion.robot_id == robot):
            return None
        return self._wire_versions.get(robot, 0)

    @contextmanager
    def motion_wire(self, robot_id, method, path, body, *, timeout_s=MOTION_TIMEOUT_S):
        moving = starts_or_sustains_motion(method, path, body) or path in PREPARED_GOALS
        if moving:
            self._wire_versions[robot_id] = self._wire_versions.get(robot_id, 0) + 1
            self._wire_pending[robot_id] = self._wire_pending.get(robot_id, 0) + 1
        try:
            sent_at = self._clock()
            with self._check_motion_wire(robot_id, method, path, body,
                                         sent_at=sent_at, timeout_s=timeout_s) as unresolved:
                yield unresolved
        finally:
            if moving:
                self._wire_pending[robot_id] -= 1


