"""D-468 arbitration inside the existing manager lock and command generation.

Motion proof provider must verify fresh calibrated floor and the complete swept
candidate, including downstream transformations. Its absence is not permission.
"""
from dataclasses import replace
import math

from core_features.line_follow.lane_bridge import LaneBridgeMixin
from core_features.line_follow.lane_return import Footprint, ReturnController, ReturnInput
from core_features.line_follow.model import LineFollowMode

_LOCAL_REASONS = {'following','lane_departure','line_not_visible','observation_stale',
    'no_observation','low_confidence','reselection_required','camera_reselection_required',
    'lane_recovery','invalid_observation'}


class LaneReturnDecisionMixin(LaneBridgeMixin):
    def bind_return_motion(self, provider):
        """Internal qualified sensor/swept-space probe (now, linear, angular) -> strict bool.

        Even a (0,0) probe requires floor validity and fresh sensor provenance.
        A true value establishes neither control authority nor camera calibration.
        """
        if not callable(provider):
            raise ValueError('return motion proof must be callable')
        with self._lock:
            self._return_motion=provider
            self._evidence_revision += 1

    def _return_probe(self, now, linear, angular):
        if self._return_motion is None:
            return False
        try:
            return self._return_motion(now,linear,angular) is True
        except Exception:
            return False

    def _return_submission_valid(self, now, decision):
        # A tick is not guaranteed between candidate creation and submission.
        if self._hold_until is not None and now>self._hold_until:
            return False
        obs=self._observation
        if (self._provided('calibration_active') is not False or self._below_lane_auto_level()
                or (obs and (obs.quality_reason or (obs.ground=='NOMINAL' and self._hold_s is None)))):
            return False
        view=self.return_evidence(now=now)
        if view.pose is None or not 0<=now-view.pose.received_at<=.3:
            return False
        ceiling=self._provided('linear_ceiling')
        if (type(ceiling) not in (int,float) or not math.isfinite(ceiling) or ceiling<=0
                or self._angular_cap()<=0
                or abs(decision.linear)>min(self._config.max_linear,ceiling)
                or abs(decision.angular)>self._angular_cap()):
            return False
        return self._return_probe(now,decision.linear,decision.angular)

    def _apply_lane_return(self, now, decision):
        c=self._config
        bridge_state=self._bridge
        self._end_bridge()  # D-476: continues only if this tick bridges again
        if self._mode is not LineFollowMode.CAMERA_LINE or not c.recovery_local_enabled:
            return None
        obs=self._observation
        if self._return_controller is None:
            if obs is None or obs.containment is None:
                return None  # Existing legacy observations retain their contract.
            if None in (c.body_front_x_m,c.body_rear_x_m,c.body_half_width_m):
                return self._stop_decision('HOLD','lane_return_body_unknown')
            self._return_controller=ReturnController(Footprint(
                c.body_front_x_m,c.body_rear_x_m,c.body_half_width_m))
        # Existing console decisions have precedence once escalation has opened.
        if self._recovery.stuck_id is not None:
            # An accepted console YIELD owns the normal CORE recovery decision path until
            # its turn/crawl/held phases finish. Fleet-required lane return must not
            # overwrite a separately authorized operator action with its autonomous HOLD.
            if (self._return_controller.phase!='fleet'
                    or self._recovery.phase in ('TURNING','CRAWLING','YIELDED')):
                return None
        reason=(self._status.reason or '').removeprefix('camera_')
        if (self._status.state!='TRACKING' and reason not in _LOCAL_REASONS) or (obs and obs.quality_reason):
            return decision
        view=self.return_evidence(now=now)
        ceiling=self._provided('linear_ceiling')
        linear=(min(c.max_linear,float(ceiling)) if type(ceiling) in (int,float)
                and math.isfinite(ceiling) else 0.)
        angular=self._angular_cap()
        authority=(self._provided('calibration_active') is False and linear>0 and angular>0
            and (obs is None or obs.ground!='NOMINAL' or self._hold_s is not None))
        floor=self._return_probe(now,0.,0.)
        speed=min(.03,max(0.,linear))
        turn=min(.15,max(0.,angular))
        bridge=self._bridge_step(now,bridge_state,view,authority,max(0.,linear),decision)
        action=self._return_controller.tick(ReturnInput(now=now,pose=view.pose,
            corridor=view.corridor,corridor_at=view.received_at,
            corridor_stamp_ns=view.source_stamp_ns,epoch=view.epoch,
            clearance_at=now if floor else None,floor_safe=floor,authorized=authority and bridge is None,
            front_clear=self._return_probe(now,speed,0.),
            rear_clear=self._return_probe(now,-speed,0.),
            turn_clear=self._return_probe(now,0.,turn) and self._return_probe(now,0.,-turn),
            linear_limit=max(0.,linear),angular_limit=max(0.,angular)))
        if bridge is not None:
            return bridge  # D-468 only measured this tick; the bridge owns the twist.
        if (c.bridge_enabled and action.phase=='tracking' and self._status.state=='TRACKING'
                and self._return_controller.checkpoint is not None):
            self._bridge='armed'
        if action.phase=='tracking' and not action.recovered:
            return decision
        if action.recovered:
            self._release_stuck(now)
            return self._stop_decision('HOLD','lane_return_corridor_verified')
        if action.fleet_required:
            # Reuse the existing stuck-id/event/API, without a second autonomous
            # back-off after the D-468 candidates have already been exhausted.
            inp=replace(self._stuck_input(now),cause='lane_lost',lane_visible=False)
            self._recovery.require_operator(inp)
            held=self._stop_decision('HOLD','lane_return_fleet_required')
            self._status=self._status.model_copy(update={'stuck':self._stuck_status(now)})
            return held
        if (action.linear or action.angular) and not self._return_probe(now,action.linear,action.angular):
            return self._stop_decision('HOLD','lane_return_motion_unconfirmed')
        self._status=self._status.model_copy(update={
            'state':'RECOVERING' if action.linear or action.angular else 'HOLD',
            'reason':'lane_return_'+action.reason,'linear':action.linear,'angular':action.angular})
        return replace(decision,linear=action.linear,angular=action.angular)
