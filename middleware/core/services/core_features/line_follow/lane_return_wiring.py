"""D-468 line manager's synchronized evidence seam; motion arbitration follows separately."""
from core_features.line_follow.crosswalk_zone import CrosswalkZones
from core_features.line_follow.lane_return import Footprint
from core_features.line_follow.lane_return_evidence import LaneReturnEvidence
from core_features.line_follow.lane_return_decision import LaneReturnDecisionMixin


class LaneReturnMixin(LaneReturnDecisionMixin):
    def _init_lane_return(self):
        self._return_evidence = LaneReturnEvidence()
        self._crosswalks = CrosswalkZones()  # D-491
        self._return_controller = None
        self._return_motion = None
        self._init_bridge()  # D-476 (lane_bridge.py)

    def _reset_lane_return(self):
        self._return_evidence.reset()
        self._crosswalks.clear()
        self._return_controller = None
        self._bridge = None
        self._bridge_hint = None  # a hint belongs to one line-follow session
        self._confident_frames = 0
        self._rearm = None

    def observe_return_pose(self, **sample):
        with self._lock:
            self._evidence_revision += 1
            return self._return_evidence.observe_pose(**sample)

    def invalidate_return_pose(self):
        with self._lock:
            self._evidence_revision += 1
            self._return_evidence.reset()

    def _observe_return_lane(self, observation, received_at):
        if observation.containment is None or not observation.visible or observation.quality_reason:
            self._return_evidence.invalidate_lane()
            accepted = True
        else:
            accepted = self._return_evidence.observe_lane(observation.containment, received_at=received_at)
            if accepted:
                self._crosswalks.observe(observation.containment, epoch=self._return_evidence.epoch,
                                         received_at=received_at)
        if accepted:  # D-476 arming streak: consecutive accepted confident frames
            confident = observation.visible and observation.confidence >= self._config.bridge_arm_confidence
            self._confident_frames = self._confident_frames+1 if confident else 0
        return accepted

    def _crosswalk_rest(self, now, guard):
        """D-491: called every guarded tick; True when the firing IR guard may rest in a crosswalk."""
        c = self._config
        return c.ir_row_x_m is not None and self._crosswalks.holds(
            self._return_evidence, now=now, guard=guard, ir_x=c.ir_row_x_m,
            max_length=c.crosswalk_zone_max_m, odom_error_fraction=c.crosswalk_odom_error_fraction)

    def return_evidence(self, *, now=None):
        with self._lock:
            c = self._config
            body = (None if None in (c.body_front_x_m, c.body_rear_x_m, c.body_half_width_m)
                    else Footprint(c.body_front_x_m, c.body_rear_x_m, c.body_half_width_m))
            return self._return_evidence.snapshot(now=self._clock() if now is None else now, body=body)
