"""D-468 arbitration inside the existing manager lock and command generation.

Motion proof provider must verify fresh calibrated floor and the complete swept
candidate, including downstream transformations. Its absence is not permission.
"""
from dataclasses import replace
import math

from core_features.line_follow.recovery.lane_bridge import LaneBridgeMixin
from core_features.line_follow.recovery.lane_return import Footprint, ReturnController, ReturnInput
from core_features.line_follow.model import LineFollowMode

_LOCAL_REASONS = {'following','lane_departure','line_not_visible','observation_stale',
    'no_observation','low_confidence','reselection_required','camera_reselection_required',
    'lane_recovery','invalid_observation'}


class LaneReturnDecisionMixin(LaneBridgeMixin):
    def bind_return_motion(self, provider, *, floor_proof_live=None, proof_configured=None):
        """Internal qualified sensor/swept-space probe (now, linear, angular) -> strict bool.

        Even a (0,0) probe requires floor validity and fresh sensor provenance.
        A true value establishes neither control authority nor camera calibration.
        floor_proof_live () -> bool: False only when the worker floor proof cannot exist
        (sensor adapter not enforce); D-476 then rests on its own basis. None = always live.
        proof_configured () -> bool: the provider can say yes at all (D-495 junction_turn
        capability); None = unknown, which reports no junction turn.
        """
        if not callable(provider) or any(f is not None and not callable(f)
                                         for f in (floor_proof_live, proof_configured)):
            raise ValueError('return motion proof must be callable')
        with self._lock:
            self._return_motion=provider
            self._floor_proof_live=floor_proof_live
            self._return_proof_configured=proof_configured
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
        if isinstance(self._bridge,dict):
            return (self._bridge_body_clear(now)
                    and self.motion_admitted(now,decision.linear,decision.angular,'bridge'))
        kind='retrace' if self._return_controller.phase=='retrace' else 'return'
        return self.motion_admitted(now,decision.linear,decision.angular,kind)

    def _apply_lane_return(self, now, decision):
        # D-476: a bridge continues only if this tick bridges again; any return path that
        # does not (obstacle, stuck, mode) hands it back to D-468 once. An armed anchor lives
        # one tick: only a tick that is itself confident following re-arms.
        bridge_state,self._bridge=self._bridge,None
        self._bridge_open=isinstance(bridge_state,dict)
        try:
            return self._lane_return_step(now,decision,bridge_state)
        finally:
            self._hand_back_bridge()
            self._arm_bridge(now)

    def _return_limits(self):
        """(linear limit, angular cap, autonomous authority) for D-468 and D-476."""
        c,obs=self._config,self._observation
        ceiling=self._provided('linear_ceiling')
        linear=(min(c.max_linear,float(ceiling)) if type(ceiling) in (int,float)
                and math.isfinite(ceiling) else 0.)
        angular=self._angular_cap()
        authority=(self._provided('calibration_active') is False and linear>0 and angular>0
            and (obs is None or obs.ground!='NOMINAL' or self._hold_s is not None))
        return max(0.,linear),max(0.,angular),authority

    def _bridge_alone(self, now, decision, state):
        """D-476 without a D-468 controller (recovery_local_enabled false, or no containment):
        bridge or None, and None falls through to today's HOLD/LOST path."""
        if state is None:
            return None
        linear,_,authority=self._return_limits()
        return self._bridge_step(now,state,self.return_evidence(now=now),authority,linear,decision)

    def _lane_return_step(self, now, decision, bridge_state):
        c=self._config
        if self._mode is not LineFollowMode.CAMERA_LINE:
            return None
        if not c.recovery_local_enabled:
            return self._bridge_alone(now,decision,bridge_state)
        obs=self._observation
        if self._return_controller is None:
            if obs is None or obs.containment is None:
                # Existing legacy observations retain their contract.
                return self._bridge_alone(now,decision,bridge_state)
            if None in (c.body_front_x_m,c.body_rear_x_m,c.body_half_width_m):
                # D-507 7: no body geometry = containment unprovable = as recovery off.
                self._status=self._status.model_copy(update={'lane_return_containment':'unknown'})
                return self._bridge_alone(now,decision,bridge_state)
            self._return_controller=ReturnController(Footprint(
                c.body_front_x_m,c.body_rear_x_m,c.body_half_width_m),
                c.lane_return_body_margin_m,c.lane_return_checkpoint_fraction)
        # Existing console decisions have precedence once escalation has opened.
        if self._recovery.stuck_id is not None:
            # An accepted console YIELD owns the normal CORE recovery decision path until
            # its turn/crawl/held phases finish. Fleet-required lane return must not
            # overwrite a separately authorized operator action with its autonomous HOLD.
            if (self._return_controller.phase!='fleet'
                    or self._recovery.phase in ('TURNING','CRAWLING','YIELDED')):
                if self._return_controller.phase=='tracking':  # D-507 7: D-468 idle
                    self._status=self._status.model_copy(update={'lane_return_containment':'unknown'})
                return None
        reason=(self._status.reason or '').removeprefix('camera_')
        if (self._status.state!='TRACKING' and reason not in _LOCAL_REASONS) or (obs and obs.quality_reason):
            if self._return_controller.phase!='tracking':
                return decision
            # D-507 7: an idle D-468 leaves the tick to today's path, recovery included.
            self._status=self._status.model_copy(update={'lane_return_containment':'unknown'})
            return None
        view=self.return_evidence(now=now)
        linear,angular,authority=self._return_limits()
        floor=self.motion_admitted(now,0.,0.,'return')  # D-507 6
        speed=min(.03,max(0.,linear))
        turn=min(.15,max(0.,angular))
        bridge=self._bridge_step(now,bridge_state,view,authority,linear,decision)
        if bridge is None:
            self._hand_back_bridge()  # before D-468 plans its retrace this tick
        action=self._return_controller.tick(ReturnInput(now=now,pose=view.pose,
            corridor=view.corridor,corridor_at=view.received_at,
            corridor_stamp_ns=view.source_stamp_ns,epoch=view.epoch,
            clearance_at=now if floor else None,floor_safe=floor,authorized=authority and bridge is None,
            front_clear=self.motion_admitted(now,speed,0.,'return'),
            rear_clear=self.motion_admitted(now,-speed,0.,'retrace'),
            turn_clear=(self.motion_admitted(now,0.,turn,'return')
                        and self.motion_admitted(now,0.,-turn,'return')),
            linear_limit=linear,angular_limit=angular))
        if bridge is not None:
            return bridge  # D-468 only measured this tick; the bridge owns the twist.
        if action.phase=='tracking' and not action.recovered:
            # D-507 7: unknown = today's following, shown so the operator sees D-468 is idle.
            unknown=action.reason=='containment_unknown'
            self._status=self._status.model_copy(update={'lane_return_containment':
                'unknown' if unknown else 'contained'})
            # Unknown = as recovery off: None lets today's path (incl. D-407 stuck) own the tick.
            return None if unknown else decision
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
        kind='retrace' if action.phase=='retrace' else 'return'
        if (action.linear or action.angular) and not self.motion_admitted(
                now,action.linear,action.angular,kind):
            return self._stop_decision('HOLD','lane_return_motion_unconfirmed')
        self._status=self._status.model_copy(update={
            'state':'RECOVERING' if action.linear or action.angular else 'HOLD',
            'reason':'lane_return_'+action.reason,'linear':action.linear,'angular':action.angular})
        return replace(decision,linear=action.linear,angular=action.angular)
