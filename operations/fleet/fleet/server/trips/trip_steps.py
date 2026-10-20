"""D-494 5 / D-495 / D-520 per-period steps of the trip loop: lane junction instructions, bends, keeper
sighting dismissals, sends and free-segment goals. Moved out of ``trip_runner`` unchanged (D-798); ``TripRunner``
mixes it in.
"""

from __future__ import annotations

import asyncio
import logging
import math
from typing import Optional

import httpx

from fleet.hub.hub import HubError
from fleet.lane_route import STEP_M
from fleet.routing.cost import LEFT, RIGHT, STOP
from fleet.routing.execute import advance_m, exit_segment, lane_action, turn_target
from fleet.server.trip_admission import LOCALIZED
from fleet.server.charge_goal_gate import ready_free_goal
from fleet.server.trip_geometry import arc_newer, bend_fields, junction_fields, next_bend
from fleet.server.trip_halts import error_code as _code
from fleet.server.trip_laps import hold_back_m, lap_due, lap_retry_due
from fleet.server.trip_live import LiveTrip
from fleet.server.trip_ports import pose_diagnostics
from fleet.server.trip_progress import MANOEUVRE
from fleet.swarm.transport import RobotApiError
from fleet.traffic.route_guide import route_guided

_LOG = logging.getLogger("fleet.server.trip_runner")  # the trip loop's logger, as before the D-798 split

#: D-520 2: CORE's ``line_follow.arc.reason`` for an arc that ended with no instruction armed
#: (event ``nav.lane_arc_end_unarmed``); CORE then follows the lane as today.
ARC_END_UNARMED = "lane_arc_end_unarmed"
#: Keeper sightings without a map place that one trip answers with ``straight`` before it ends.
SIGHTING_DISMISSALS = 3
#: The dismissal ``straight`` lives this long and needs this much lane beyond the arm distance.
DISMISS_EXPIRES_S = 2.0
DISMISS_MARGIN_M = 0.3
#: CORE takes ``stop_after_m`` in [0, 2] (D-494 4).
MAX_STOP_AFTER_M = 2.0


class _GoalRefused(RuntimeError):
    """The console did not send the trip's goal (queued behind traffic, yielding, untrusted)."""


class _JunctionAborted(RuntimeError):
    """CORE answered our instruction by aborting its manoeuvre (D-495): never resent."""


class TripSteps:
    """``TripRunner``'s step methods; state and ports live on the runner."""

    async def _step(self, live: LiveTrip) -> None:
        robot_id = live.view["robot_id"]
        if self._renew_lease is not None and live.view["state"] != "link_wait":  # D-760 4: a free robot then stops
            # D-550 10: first, so a slow pose read does not starve it. Never ends the trip: a
            # renewal that fails lets CORE cancel the goal when its lease runs out.
            try:
                await asyncio.wait_for(self._renew_lease(robot_id), self.config.port_timeout_s)
            except Exception:
                _LOG.warning("goal lease renewal for %s failed", robot_id, exc_info=True)
        live.view["detail"].pop("bend_candidate", None)
        try:
            pose = await self.map_pose(robot_id)
        except RobotApiError as exc:  # D-760 8 review: the robot answered the state read, with an error
            return await self._stop(live, "failed", exc.code, {"status": exc.status})
        if not live.open:
            return
        live.see(pose); live.view["pose_observed_at"] = self._clock()
        if robot_id in self._unread and await self._link_wait(live, "state_unread"):
            return  # D-760 4: no state read, so nothing new goes out
        if pose is None or pose.state != LOCALIZED:
            if getattr(pose, "source", None) == "native_gazebo_sim" and await self._link_wait(live, "pose_stale"):
                return  # D-725 rev 1: a stale SIM pose is transient; D-760 4 waits on it, bounded by stall_s
            await self._stop(live, "stopped", "pose", {"pose_state": pose.state if pose else None, **pose_diagnostics(pose)}, halt_free=False)
            return
        try:
            if live.arc(live.view["segment_index"]).drive_mode == "lane":
                live.junction = await self._call(self._junction.junction_state(robot_id, **self._after(self._junction, robot_id))) or {}  # D-760 8: fenced
                # D-520 2: CORE's arc record; a CORE restart resets arc_seq (as the junction seq)
                sent, arc = live.sent, live.junction.get("arc")
                arc = arc if isinstance(arc, dict) else {}
                if sent is not None and (live.junction.get("seq") == sent["seq"] and live.junction.get("state") in (
                        *MANOEUVRE, "executing") or (arc.get("from_place_id") == sent["place"]
                                                     and arc_newer(arc.get("arc_seq"), sent.get("arc_before")))):
                    sent["carried"] = True  # CORE took it on (D-520 2: or opened its arc): never sent again
                if live.first_seq is not None and arc_newer(arc.get("arc_seq"), live.arc_base):
                    if arc.get("state") == "stopped":  # D-520 2: CORE holds and never reopens the arc
                        await self._stop(live, "stopped", "lane_arc", {
                            "arc_reason": arc.get("reason"), "arc_place": arc.get("from_place_id"),
                            "arc_end_place": arc.get("end_place_id")})
                        return
                    live.view["detail"].pop("arc_end_unarmed", None)
                    if arc.get("reason") == ARC_END_UNARMED:  # CORE follows on: shown, not an end
                        live.view["detail"]["arc_end_unarmed"] = {
                            "end_place_id": arc.get("end_place_id"), "travelled_m": arc.get("travelled_m")}
            else:  # a free segment: no stale lane ``waiting`` may end it
                live.junction = {}
            self._fence(robot_id)  # D-760 8 review: the next step reads after this step's pose and junction read
            if live.view["state"] == "link_wait" and not await self._link_back(live):
                return
            if not live.open:
                return
            index, s, off = self._locate(live, pose)
            live.at, live.at_stamp = (index, s), getattr(pose, "odom_stamp", None)  # one pose, one assignment
            remaining = live.segments[index]["s_to"] - s
            lane = live.arc(index).drive_mode == "lane"
            if lane and self.traffic.holds(live, index):  # CORE waits at the junction for the block
                live.waiting_since = None
            failed = live.junction_end(self._clock(), remaining if lane else None, self.config)
            if failed is not None and await self._dismiss_sighting(live, index, remaining, failed):
                failed = None
            if failed is not None:
                await self._stop(live, "stopped", *failed)
                return
            if off is not None:
                await self._stop(live, "stopped", "pose", {"off_lane_m": round(off, 3),
                                                           **pose_diagnostics(pose)})
                return
            if live.view["state"] == "started":
                live.view["state"] = "running"
            if index != live.view["segment_index"]:
                live.view["segment_index"] = index
                live.last_goal = None
            self.authority.record_guidance(live, pose, self._store.active(), index, s, self._clock())
            self._describe(live)
            last = index == len(live.segments) - 1
            resolver = (live.traffic or {}).get("resolver") or {}
            # D-517 5: a wait cycle; only before this place is instructed (review M1: a hold over a turn
            # CORE carries out would freeze ``_locate``), else the resolver's next period says human
            if (resolver.get("decision") == "replan" and live.view["hold"] is None and not last
                    and remaining <= self.config.arm_distance_m and not self._core_busy(live)
                    and (live.sent is None or live.sent["index"] != index)):
                self._replan(live, index, frozenset(resolver["blocked_edges"]))
                if resolver.get("ai") and await self._ai_confirm(live):
                    self._save(live)
                    return
            if not last and not live.replan_pending and self._needs_replan(live, index):
                live.replan_pending = True
            if (live.replan_pending and live.view["hold"] is None and not last
                    and remaining <= self.config.arm_distance_m):
                self._replan(live, index)
                self._describe(live)
            if robot_id in self.autonomous_robots and await self._ai_confirm(live, "fleet-rule"):
                self._save(live)
                return  # The next period locates the robot against the new plan.
            if live.repeat and live.view["hold"] is None and lap_due(live, index, remaining, self.config):
                await self._next_lap(live, index)
                index = live.view["segment_index"]  # finished laps may have been dropped
                self._describe(live)
                last = index == len(live.segments) - 1
            elif lap_retry_due(live, self._clock()):
                await self._retry_lap(live, index)
                index = live.view["segment_index"]
                self._describe(live)
                last = index == len(live.segments) - 1
            if lane:
                await self._step_lane(live, index, remaining, pose)
            else:
                await self._step_free(live, index, s)
        except _JunctionAborted as exc:
            await self._stop(live, "stopped", "junction", {"junction_state": "aborted",
                                                           "junction_seq": exc.args[0] if exc.args else None})
            return
        except _GoalRefused as exc:
            await self._stop(live, "failed", "TRIP_GOAL_REFUSED", {"goal_reason": str(exc) or None})
            return
        except RobotApiError as exc:
            lane = live.arc(live.view["segment_index"]).drive_mode == "lane"
            code = "TRIP_ROBOT_JUNCTION_UNSUPPORTED" if lane and exc.status == 404 else exc.code
            await self._stop(live, "failed", code, {"status": exc.status})
            return
        except (HubError, OSError, RuntimeError, ValueError, httpx.HTTPError) as exc:
            # D-760 4: a leased trip waits only on no answer (Safety-Review HIGH-1); any other error ends it
            if not (isinstance(exc, (HubError, OSError, httpx.TransportError)) and await self._link_wait(live, _code(exc))):
                await self._stop(live, "failed", "TRIP_ROBOT_UNREACHABLE", {"kind": _code(exc)})
            return
        if not live.open:
            return  # canceled while the step was in flight
        if (live.view.get("wait") or {}).get("reason") == "link_wait":
            del live.view["wait"]  # a whole step without a link fault: the link_wait ``since`` may start over
        # after the step, so the last place's stop has gone out before "arrived"
        if last and live.view["hold"] is None and self._arrived(live, index, remaining, lane, pose):
            live.view["state"] = "arrived"
            if lane and (live.sent or {}).get("action") == STOP:
                self.held_stops[robot_id] = (live.sent["seq"], live.sent["place"])
            if not lane:
                self._release_queue(robot_id)
            self._save(live)
            return
        if self._stalled(live, index, s):
            await self._stop(live, "stopped", "stall", {"stall_s": self.config.stall_s,
                                                        "progress_m": round(live.best_progress, 3)})
            return
        self._save(live)

    # ---- steps --------------------------------------------------------------------------

    async def _step_lane(self, live: LiveTrip, index: int, remaining: float, pose=None) -> None:
        if (live.view["caps"] or {}).get("lane_arc") and "arc" not in live.junction:
            return  # D-520 2: no arc baseline read yet; an old CORE arc would pass as this trip's (bends too)
        arc, sent, j = live.junction.get("arc") or {}, live.sent, live.junction
        if (live.view["hold"] is None and arc.get("state") == "running" and sent is not None
                and arc.get("end_place_id") == sent["place"] != live.place(index)
                and (j.get("state"), j.get("place_id"), j.get("seq")) == ("armed", sent["place"], sent["seq"])):
            return  # map pose can cross the boundary before CORE odom ends its arc: keep the armed end-place instruction
        if not route_guided(live) and await self._step_bend(live, index, live.segments[index]["s_to"] - remaining, pose):
            return  # D-507 addendum: a bend ahead on this lane comes before its place
        place = live.place(index)
        if place is None or remaining > self.config.arm_distance_m:
            return
        action = STOP if live.view["hold"] is not None else lane_action(live.graph, live.segments, index, self._routing)
        if action != STOP and (route_guided(live) or self.traffic.holds(live, index)):
            return  # route-guided: stops only; D-517 3 (M1): nothing tells the robot to drive into a refused block
        state, sent, now = live.junction.get("state"), live.sent, self._clock()
        same = sent is not None and (sent["index"], sent["action"], sent["place"]) == (index, action, place)
        if self._core_busy(live):
            return
        if same:
            if action == STOP or sent.get("carried") or sent.get("done"):
                return  # one stop per place (CORE measures it from receipt); a carried-out place is done
            ours = live.junction.get("seq") == sent["seq"] and live.junction.get("place_id") == place
            if state == "armed" and not ours:
                pass  # someone else's instruction: ours again
            elif state in ("armed", None) and now - sent["at"] < self.config.junction_expires_s / 2:
                return
            elif state not in ("armed", None, "idle", "waiting"):
                return
        back = (hold_back_m(self.traffic, live.segments[index]) or 0.0) if action == STOP else 0.0  # D-517 3: zone
        stop_after = min(max(remaining - back, 0.0), MAX_STOP_AFTER_M) if action == STOP else None
        expect = junction_fields(live, index, action, remaining, self._store.active(), self.config)
        arc = None  # D-520 1: only to a lane_arc robot, and only with the map_id
        if action != STOP and (live.view["caps"] or {}).get("lane_arc") and (expect or {}).get("map_id"):
            # D-744 2: the map anchor only to a lane_arc_map_anchor robot, from this step's pose and its odom stamp
            stamp = getattr(pose, "odom_stamp", None) if live.view["caps"].get("lane_arc_map_anchor") else None
            arc = exit_segment(live.graph, live.segments, index, fit_tol_m=self.config.arc_fit_tol_m,
                               outer_line_offset_m=self.config.arc_outer_line_offset_m,
                               map_pose=None if stamp is None else (pose.x, pose.y, pose.yaw, stamp))
        expect = {**expect, "exit_segment": arc} if arc is not None else expect
        # D-520 1 (lap SIM 3): the lane-heading turn either way (the 5 cm lead tangent is 12-17 deg off at SW); with an exit_segment no advance_m (CORE starts the arc there)
        turn = round(turn_target(live.graph, live.segments, index), 1) if action in (LEFT, RIGHT) else None
        advance = advance_m(live.graph, live.segments, index) if turn is not None and arc is None else None
        if turn is not None and expect and live.view["caps"].get("lane_turn_map_entry") and getattr(pose, "odom_stamp", None) is not None:
            expect = {**expect, "map_entry": {"yaw_rad": round(live.arc(index + 1).start_tangent, 4), "pose_yaw_rad": pose.yaw, "odom_stamp_s": pose.odom_stamp}}  # D-759 rev 1: the exit lane's map heading
        if not live.open:
            return
        if action in (LEFT, RIGHT) and (expect or {}).get("expect_in_m") is None:
            # D-507 2 (2026-10-08 user decision): without a window CORE could take any sighting,
            # a misread bend included, as this turn; stop the trip instead of sending it.
            await self._stop(live, "stopped", "junction_no_window",
                             {"junction_place": place, "junction_action": action, "junction_fields": expect})
            return
        await self._send(live, index, action, place, stop_after, turn_deg=turn, advance_m=advance, expect=expect)

    async def _step_bend(self, live: LiveTrip, index: int, s: float, pose=None) -> bool:
        """D-507 addendum: True while a site-map bend on this lane is ahead (its instruction, sent
        within ``arm_distance_m`` of the arc start to a ``lane_bend`` robot, owns CORE's one slot)."""
        arc = live.junction.get("arc") or {}
        if arc.get("state") == "running" and arc.get("end_place_id") == live.place(index):
            return False  # D-520: CORE drives this lane as an arc; its slot is for the end place's instruction
        bend = next_bend(live, index, s) if (live.view.get("caps") or {}).get("lane_bend") else None
        if bend is None:
            return False
        state, sent, seq = live.junction.get("state"), live.sent, live.junction.get("seq")
        ours = sent is not None and (sent["action"], sent["place"]) == ("bend", bend["place_id"])
        newer = ours and isinstance(seq, int) and isinstance(sent["seq"], int) and seq > sent["seq"]
        # CORE idle, or waiting at the next junction it sighted to end the pass (lap SIM D), same seq
        finished = ours and (sent.get("done") or (sent.get("carried") and (state in ("idle", "waiting") or newer)))
        if finished or (not ours and s >= bend["s_start"]):
            live.bends_done.add((index, bend["place_id"]))  # finished, or passed without one: never again on this segment
            return await self._step_bend(live, index, s, pose)
        if live.view["hold"] is not None or self.traffic.holds(live, index):
            # held (operator, replan, lap or D-517 traffic): only the place's stop may go out; a bend
            # passed while held counts as passed (at most one per lap)
            return False
        if self._core_busy(live) or bend["s_start"] - s > self.config.arm_distance_m or (
                ours and state == "armed" and self._clock() - sent["at"] < self.config.junction_expires_s / 2):
            return True
        fields = bend_fields(live, bend, s, self._store.active(), self.config, pose)  # D-759: this step's pose
        if fields is None:
            return True  # another map version: the bend is not sent and its place waits
        await self._send(live, index, "bend", bend["place_id"], None, turn_deg=round(bend["turn_deg"], 1),
                         expect=fields)
        return True

    async def _dismiss_sighting(self, live: LiveTrip, index: int, remaining: float, failed: tuple) -> bool:
        """Map vote (user 2026-10-13): CORE waits at a junction its keeper saw where the map has no
        place near. One keeper frame is not a junction against the map, so the answer is a
        short-lived ``straight`` (the lane goes on), at most SIGHTING_DISMISSALS times a trip; after
        that, or when CORE calls it ``unexpected`` itself, the trip ends as before (D-507 3).
        Never while Fleet holds the robot (traffic, operator, replan): CORE's wait is then wanted.
        The place must be beyond the arm distance by DISMISS_MARGIN_M (pose error, keeper look-ahead)
        and the instruction dies in DISMISS_EXPIRES_S, so a real junction does not consume it."""
        reason, detail = failed
        if (reason != "junction_unexpected" or detail.get("junction_state") != "waiting"
                or live.dismissed >= SIGHTING_DISMISSALS or live.view["hold"] is not None
                or self.traffic.holds(live, index)
                or remaining <= self.config.arm_distance_m + DISMISS_MARGIN_M):
            return False
        place = f"map-clear-{str(live.view['trip_id'])[:8]}-{live.dismissed + 1}"
        try:
            reply = await self._call(self._junction.send_junction(
                live.view["robot_id"], "straight", place, None, DISMISS_EXPIRES_S)) or {}
        except RobotApiError as exc:
            if exc.code != "JUNCTION_ALREADY_DONE":
                return False
            reply = {}
        if reply.get("accepted") is False:
            return False
        live.dismissed += 1
        live.waiting_since = None
        live.view["detail"]["sighting_dismissed"] = live.dismissed
        return True

    async def _send(self, live: LiveTrip, index: int, action: str, place: str, stop_after: Optional[float],
                    **kwargs) -> None:
        """Send one junction instruction to an open trip's robot and record it as ``live.sent``."""
        if not live.open:
            return
        now = self._clock()
        try:
            reply = await self._call(self._junction.send_junction(
                live.view["robot_id"], action, place, stop_after, self.config.junction_expires_s, **kwargs)) or {}
        except RobotApiError as exc:
            if exc.code in ("JUNCTION_ODOM_STALE", "INSTRUCTION_STAMP_UNUSABLE"):  # D-507 2 / D-767 A: next tick, fresh pose
                live.view["detail"]["junction_retry"] = " ".join(filter(None, (exc.code, (exc.detail or {}).get("reason"))))  # D-767 A: + why
                live.view["caps"]["lane_instruction_stamp"] = live.view["caps"].get("lane_instruction_stamp") and (exc.detail or {}).get("reason") != "disabled"
                return
            if exc.code != "JUNCTION_ALREADY_DONE":
                raise
            reply = {"already_done": True}  # CORE R1: this place's action already ran
        self._fence(live.view["robot_id"])  # D-760 8 review: the next step sees CORE after this send
        live.view["detail"].pop("junction_retry", None)
        await self._after_send(live)
        if reply.get("accepted") is False:  # CORE aborted a manoeuvre instead: an operator decides
            raise _JunctionAborted(reply.get("junction_seq"))
        seq, arc_before = reply.get("junction_seq"), (live.junction.get("arc") or {}).get("arc_seq")
        live.replaceable = None
        live.sent = {"index": index, "action": action, "place": place, "seq": seq, "at": now,
                     "done": bool(reply.get("already_done")), "arc_before": arc_before}
        if live.first_seq is None:
            live.first_seq, live.arc_base = (seq if isinstance(seq, int) else 0), arc_before

    async def _step_free(self, live: LiveTrip, index: int, s: float) -> None:
        segment = live.segments[index]
        if live.view["hold"] is not None:  # hold at the place: the goal is the place itself
            x, y, yaw = live.arc(index).point_at(segment["s_to"])
        elif s + STEP_M > segment["s_to"] and index + 1 < len(live.segments):
            nxt = live.segments[index + 1]
            x, y, yaw = live.arc(index + 1).point_at(min(nxt["s_from"] + s + STEP_M - segment["s_to"], nxt["s_to"]))
        else:
            x, y, yaw = live.arc(index).point_at(min(s + STEP_M, segment["s_to"]))
        if live.last_goal is not None and math.dist(live.last_goal, (x, y)) < self.config.goal_resend_m:
            return
        if not await ready_free_goal(self, live):  # D-772 charge-only native readiness
            return
        if not live.open:
            return
        reply = await self._call(self._goal(live.view["robot_id"], x, y, yaw)) or {}
        live.last_goal = (x, y)
        await self._after_send(live)
        if reply.get("accepted") is False or reply.get("queued"):
            raise _GoalRefused(reply.get("reason") or "")
