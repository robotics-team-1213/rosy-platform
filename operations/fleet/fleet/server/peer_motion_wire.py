"""Track Fleet transport activity that invalidates stationary peer observations."""
from contextlib import contextmanager

from fleet.swarm.motion_ingress import PREPARED_GOALS, starts_or_sustains_motion


class PeerMotionWire:
    def __init__(self):
        super().__init__()
        self._wire_versions = {}
        self._wire_pending = {}

    def peer_wire_state(self, robots):
        """A pending request or a changed version invalidates an earlier stationary peer sample."""
        return {robot: (self._wire_versions.get(robot, 0), self._wire_pending.get(robot, 0)) for robot in robots}

    @contextmanager
    def motion_wire(self, robot_id, method, path, body):
        moving = starts_or_sustains_motion(method, path, body) or path in PREPARED_GOALS
        if moving:
            self._wire_versions[robot_id] = self._wire_versions.get(robot_id, 0) + 1
            self._wire_pending[robot_id] = self._wire_pending.get(robot_id, 0) + 1
        try:
            with self._check_motion_wire(robot_id, method, path, body) as unresolved:
                yield unresolved
        finally:
            if moving:
                self._wire_pending[robot_id] -= 1

