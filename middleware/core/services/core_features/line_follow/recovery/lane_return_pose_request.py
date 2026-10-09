"""D-546 5: lane_return asks Fleet for a pose when it cannot go on without one.

`pose_stale` (after `POSE_STALE_ASK_S`) and the `fleet` phase open a request in CORE's
`PoseRequests` book; any other tick closes it. The robot holds meanwhile (the controller
already returns HOLD for both). An accepted Fleet decision calls `resume_after_pose`,
which re-opens verification of a `fleet` phase through the existing D-407 RESUME.
"""
from core_features.line_follow.recovery.stuck_recovery import AnswerRefused

#: A single missed odom sample is not a request: the pose must stay stale this long.
POSE_STALE_ASK_S = 1.0


class PoseRequestMixin:
    def _init_pose_request(self):
        self._pose_ask = self._pose_unask = None
        self._pose_stale_since = None

    def bind_pose_request(self, ask, unask):
        """ask(reason, evidence) -> request; unask(why) -> bool (both from `PoseRequests`)."""
        with self._lock:
            self._pose_ask, self._pose_unask = ask, unask

    def _drop_pose_request(self, why):
        self._pose_stale_since = None
        if self._pose_unask is not None:
            self._pose_unask(why)

    def _note_pose_request(self, now, action, view):
        stale = action.reason == 'pose_stale'
        if not stale:
            self._pose_stale_since = None
        elif self._pose_stale_since is None:
            self._pose_stale_since = now
        fleet = action.fleet_required or self._return_controller.phase == 'fleet'
        if fleet or (stale and now-self._pose_stale_since >= POSE_STALE_ASK_S):
            if self._pose_ask is not None:
                self._pose_ask('fleet_required' if fleet else 'pose_stale',
                               self._pose_evidence(now, view))
        elif not stale and self._pose_unask is not None:
            self._pose_unask('lane_return_resumed')

    def _pose_evidence(self, now, view):
        pose, obs = view.pose, self._observation
        return {
            'phase': self._return_controller.phase,
            'odom_pose': None if pose is None else {
                'x': pose.x, 'y': pose.y, 'yaw': pose.yaw, 'frame': pose.frame,
                'stamp_ns': pose.stamp_ns, 'age_s': now-pose.received_at},
            'lane': None if obs is None else {
                'visible': obs.visible, 'confidence': obs.confidence, 'error': obs.error,
                'quality_reason': obs.quality_reason, 'stamp': obs.stamp},
        }

    def resume_after_pose(self):
        """Fleet's pose was accepted: a `fleet` phase verifies the lane again (D-407 RESUME)."""
        with self._lock:
            stuck_id = self._recovery.stuck_id
            if self._return_controller is None or self._return_controller.phase != 'fleet' or stuck_id is None:
                return
            try:
                self.stuck_decision(stuck_id, 'RESUME', by='fleet_pose')
            except AnswerRefused:
                pass  # refused (scan): the fleet phase asks again on its next tick
