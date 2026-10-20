"""D-494 5 start admission of the trip loop (``trip_runner``): the capability, line-follow and map
pose checks a trip start (and each D-517 2 lap) passes, moved out of ``trip_runner`` (2026-10-10 seam,
docs/plans/2026-10-07-fleet-site-map-web-server-seam.md); ``TripRunner`` mixes it in. D-601: the start
alignment against the first lane (``start_check``) and the plan-time line camera check. D-603: with
``fleet.trip.auto_align`` a heading mismatch on the first lane asks CORE ``rotate_to`` (``_start_pose``).
"""

from __future__ import annotations

import asyncio
import logging
import math
from types import SimpleNamespace

from core_common.protocol.line_authority import MAX_TTL_S as AUTHORITY_MAX_TTL_S
from core_common.robot_body import nominal_body_for
from fleet.routing.trip import ARRIVED_M
from rosy.world.state.projections.map_pose import OPERATOR_PIN
from fleet.routing.cost import wrap
from fleet.routing.execute import arc_id, unsupported
from fleet.server.trip_ports import MapPose, TripError
from fleet.traffic import rule_m
from fleet.site_map import _inside

_LOG = logging.getLogger(__name__)
LOCALIZED = "LOCALIZED"
#: CORE takes junction instructions only on CAMERA_LINE (IR_LINE: 409 JUNCTION_CAMERA_ONLY).
LINE_MODES = ("CAMERA_LINE",)
#: D-603: alignment turns per start at most; the second corrects odom's 6-11 % over-rotation (D-598).
ALIGN_TURNS = 2
#: Fleet waits this long for CORE's turn (CORE's own default bound is 10 s, at most 15 s) ...
ALIGN_WAIT_S = 12.0
#: ... and this long after it for a camera sighting newer than the turn's end.
ALIGN_SIGHTING_S = 3.0
#: D-763 rev 2 Q10 (b): a multi-step job's robot announces these (plus an authority enforced under the lease).
JOB_CAPS = ("trip_lease", "trip_lease_job", "goal_lease")
#: D-763 10 (c): sample step along the route's lanes for the crosswalk test (m).
CROSSWALK_STEP_M = 0.02


def crosswalks_on(graph, segments: list, crosswalks) -> list:
    """D-763 10 (c): ids of the site-map crosswalks (D-573 1) a lane segment of this route enters."""
    hit, polygons = set(), [(c.id, [tuple(p) for p in c.polygon]) for c in crosswalks]
    for seg in segments if polygons else ():
        arc = graph.arcs[arc_id(seg)]
        if arc.drive_mode != "lane":
            continue
        s0, s1 = seg.get("s_from", 0.0), seg.get("s_to", arc.length_m)
        points = [arc.point_at(min(s0 + k * CROSSWALK_STEP_M, s1)) for k in range(int((s1 - s0) / CROSSWALK_STEP_M) + 2)]
        hit |= {cid for cid, polygon in polygons if any(_inside((x, y), polygon) for x, y, _ in points)}
    return sorted(hit)


def signals_on(traffic, segments: list) -> list:
    """D-763 10 (c): ids of the D-525 signals whose zone this route crosses (the span walk of
    ``TrafficService.signal_refusal``, kept here so the traffic unit does not grow)."""
    zones = {plan.zone: signal_id for signal_id, plan in traffic._signals.items()}
    layout = traffic._layout_for(traffic._store.active()) if zones and segments else None
    spans = layout.route(traffic._store.active()[2], [arc_id(seg) for seg in segments]) if layout else ()
    return sorted({zones[span.unit] for span in spans if span.unit in zones})


def start_check(graph, segments: list, x: float, y: float, yaw, tol_deg: float) -> dict:
    """D-601 D: the robot against its plan's first lane (``code`` None: it may start). Off the lane is
    the trip loop's own rule (more than half the lane width, ``_locate``); the heading is compared
    with the lane's direction at the robot's projection (one-way or the planned way)."""
    arc = graph.arcs[arc_id(segments[0])] if segments else None
    if arc is None or arc.drive_mode != "lane":
        return {"code": None}
    dist, _s, tangent = arc.project(x, y)
    err = None if yaw is None else round(math.degrees(wrap(yaw - tangent)), 1)
    code = ("TRIP_START_OFF_LANE" if dist > arc.width_m / 2
            else "TRIP_START_HEADING_MISMATCH" if err is None or abs(err) > tol_deg else None)
    return {"code": code, "edge_id": arc.edge_id, "heading_err_deg": err, "tol_deg": tol_deg,
            "off_lane_m": round(max(0.0, dist - arc.width_m / 2), 3)}


class TripAdmission:
    def _check_engaged(self, robot_id):
        engaged = self._engaged(robot_id)
        if engaged is not None:
            raise TripError(409, 'TRIP_ROBOT_BUSY', {'reason': engaged})

    def return_endpoint_matches(self, row, approach):
        """Read-only route geometry port for the safety-tagged charging adapter."""
        active = self._store.active()
        segments = row['result']['plan'].get('segments') or ()
        if active is None or active[0] != row['map_version'] or not segments:
            return False
        end = active[2].arcs[arc_id(segments[-1])].point_at(segments[-1]['s_to'])
        return math.dist(end[:2], (approach.x, approach.y)) <= ARRIVED_M

    async def _guard_start(self, robot_id, token, guard):
        self._check_start_token(robot_id, token)
        if guard is not None:
            await guard()
            self._check_start_token(robot_id, token)

    async def hold_job(self, robot_id: str, job_id: str, operator: str, capabilities, *,
                       owner_kind='mission', trip_id=None, lease_id=None) -> dict:
        """D-763 6: at approval a multi-step job takes this robot's lease and holds it to its end (``lease.hold``).

        Gate: Rule M's verdict on each leg the robot drives (``reasons``), then rev 2 Q10 (a)(b) (``missing``):
        site trip lease and authority both on, the lease ttl above the 5 s authority
        (D-760 1) and the robot's base announcing JOB_CAPS and an authority enforced under the lease, else 422
        LINK_UNBOUNDED_MOTION (D-760 7). Q10 (c) waits for the crosswalk/signal capability names. Open (D-763
        open question 1): what a lease expiry stops during an arm step; no arm step may be held until decided.
        """
        items = ((capabilities or {}).get("controls") or {}).get("items") or ()
        base = next((i for i in items if isinstance(i, dict) and i.get("kind") == "base_velocity"), {})
        # D-760 6: the motion bound of each leg the robot drives is Rule M's own verdict, without the lease
        # (the job's lease answers who holds the robot, never how far it may move: D-763 4).
        trip = {"lease": None, "traffic_authority": self.authority.mode(
            SimpleNamespace(line_follow_authority=base.get("line_follow_authority") is True))}
        goal = {"goal_lease": "leased" if base.get("goal_lease") is True else None}
        modes = base.get("drive_modes")  # anything but a list is no modes: leg_unknown, never a 500
        legs = [leg for leg in (modes if isinstance(modes, (list, tuple)) else ()) if leg in ("lane", "free")] or [None]
        verdicts = [rule_m.verdict(trip=trip, leg=leg, goal=goal) for leg in legs]
        reasons = list(dict.fromkeys(v["reason"] for v in verdicts if v["state"] != "bounded"))
        missing = [name for name in JOB_CAPS if base.get(name) is not True] + [name for name, off in (
            ("line_follow_authority_under_lease", base.get("line_follow_authority_required") is not True
             and base.get("line_follow_authority_under_lease") is not True),
            ("fleet.trip_lease_required", not self.lease.required),
            ("fleet.traffic.authority", not self.authority.enabled),
            ("fleet.trip_lease_ttl_s", self.lease.ttl_s <= AUTHORITY_MAX_TTL_S)) if off]
        if reasons or missing:  # reasons: Rule M's words (hold_back, no_goal_lease, leg_unknown); missing: Q10
            raise TripError(422, "LINK_UNBOUNDED_MOTION", {"reasons": reasons, "missing": missing})
        if owner_kind not in ('mission', 'charge_session'):
            raise ValueError('TRIP_OWNER_KIND_INVALID')
        hook = self.lease.on_charge_lost if owner_kind == 'charge_session' else self.lease.on_job_lost
        if hook is None:  # rev 2 Q3: no HOLD that reaches no person
            raise RuntimeError("D-763: wire lease.on_job_lost (incident + HOLD) before a job holds a robot")
        def check_claim():
            claimed = self.lease.claimed_owner(robot_id)
            if ((owner_kind == 'charge_session' and not claimed) or claimed and (
                    claimed['owner_kind'] != owner_kind or claimed['owner_id'] != job_id)):
                raise TripError(409, 'TRIP_ROBOT_BUSY', {'reason': 'claim'})
        check_claim()
        async with self._lock_for(robot_id):  # a trip start on this robot runs wholly before or after this
            check_claim()
            old = self.lease.jobs.get(robot_id)
            if old is not None and (old.view["job_id"] != job_id
                                    or old.view.get('owner_kind', 'mission') != owner_kind):
                raise TripError(409, "TRIP_ROBOT_BUSY", {"reason": "job", "owner_kind": "mission"})
            if old is not None and old.view["lease"]["state"] == "held":
                if lease_id is not None and (old.view['lease']['lease_id'] != lease_id
                                              or old.view['trip_id'] != trip_id):
                    raise ValueError('CHARGE_RETURN_LEASE_CONFLICT')
                return old.view["lease"]
            if old is not None and owner_kind == 'charge_session':
                raise ValueError('CHARGE_RETURN_LEASE_LOST')
            busy = ("trip" if self.robot_busy(robot_id) else None) or self._engaged(robot_id)
            if busy is not None:  # it already moves for someone else (a trip, a console goal, formation ...)
                raise TripError(409, "TRIP_ROBOT_BUSY", {"reason": busy})
            self.lease.jobs.pop(robot_id, None)  # a lost one: re-approval opens a new lease (rev 2 Q3)
            view = {"robot_id": robot_id, "trip_id": trip_id or job_id, "job_id": job_id,
                    "started_by": operator, 'owner_kind': owner_kind}
            view["lease"] = await self.lease.open(robot_id, view, SimpleNamespace(trip_lease=True), lease_id=lease_id)
            try:
                check_claim()
            except Exception:
                await self.lease.delete(robot_id, view['lease']['lease_id'])
                raise
            self.lease.jobs[robot_id] = SimpleNamespace(open=True, job=True, view=view)
            return view["lease"]

    def release_job(self, robot_id: str, job_id: str) -> None:
        """The job ended (done, operator cancel): its lease goes (DELETE). Its step trip ends first."""
        job = self.lease.jobs.get(robot_id)
        if job is not None and job.view["job_id"] == job_id:
            if self.robot_busy(robot_id):  # the step trip shares the lease: never leave it driving lease-less
                raise TripError(409, "TRIP_BUSY", {"trip_id": self._live[robot_id].view["trip_id"]})
            del self.lease.jobs[robot_id]
            self.lease.close(job)

    async def stop_job(self, robot_id: str, reason: str) -> None:
        """A person's stop sent through Fleet carries the lease owner's token, so CORE keeps the lease: Fleet
        gives it up itself, and the job HOLDs through the incident path (rev 2 Q3); no step runs on after it."""
        try:  # a step trip still open ends first (it shares the lease)
            await self.cancel_robot(robot_id, reason)
        except Exception:  # noqa: BLE001 - the lease is given up all the same
            _LOG.exception("could not end the step trip of %s", robot_id)
        job = self.lease.jobs.get(robot_id)
        if job is not None and job.view["lease"]["state"] == "held":
            lease_id = job.view["lease"]["lease_id"]
            await self.lease.lose(job, reason)
            await self.lease.delete(robot_id, lease_id)

    def _start_token(self, robot_id):
        return self._stop_epoch, self._start_cancels.get(robot_id, 0)

    def _check_start_token(self, robot_id, token):
        if token != self._start_token(robot_id):
            raise TripError(409, "TRIP_START_CANCELED")

    async def _caps_checks(self, robot_id: str, graph, segments: list, repeat: bool, final_place=None, detail=None):
        """D-494 start checks on the robot's capabilities; the caps, or ``TripError``. ``detail``: the trip's
        detail dict that takes the D-763 10 (c) ``regulation_caps_unknown`` warning."""
        map_id = self._store.active()[1].map_id
        lane = any(graph.arcs[arc_id(seg)].drive_mode == "lane" for seg in segments)
        caps = await self._call(self._caps(robot_id), "TRIP_ROBOT_CAPS_UNKNOWN")
        if caps is None:
            raise TripError(422, "TRIP_ROBOT_CAPS_UNKNOWN")
        refused = unsupported(graph, segments, kind=caps.kind, modes=caps.modes,
                              junction_turn=caps.junction_turn, config=self._routing,
                              max_turn_deg=self.config.max_turn_deg, repeat=repeat,
                              final_place=final_place)
        if refused is not None:
            raise TripError(422, "TRIP_MODE_UNSUPPORTED", refused)
        floor = caps.site_floor_map_id  # D-507 9: absent (older CORE) or null declares no floor
        if lane and floor is not None and floor != map_id:
            raise TripError(422, "TRIP_SITE_FLOOR_MISMATCH", {"site_floor_map_id": floor, "map_id": map_id})
        # D-517 4: no first-authority gap after a restart; D-760 2: or enforced while the lease Fleet opens is held
        bounded = caps.line_follow_authority_required is True or (
            self.lease.required and getattr(caps, "line_follow_authority_under_lease", False) is True)
        if lane and self.authority.mode(caps) == "core" and not bounded:
            raise TripError(422, "TRIP_AUTHORITY_NOT_REQUIRED")
        if lane and self.authority.mode(caps) != "core" and bounded:
            raise TripError(422, "TRIP_AUTHORITY_SITE_OFF")  # D-517 M5: no authority goes out, so CORE never moves
        # D-763 10 (c): a lane route over a crosswalk or a signalled zone needs CORE's matching rule on, else
        # the rule would silently not run there. A CORE announcing it off is refused.
        need = {"lane_crosswalk_gate": crosswalks_on(graph, segments, getattr(self._store.active()[1], "crosswalks", ())),
                "lane_junction_signal": signals_on(self.traffic, segments)} if lane else {}
        missing = {cap: ids for cap, ids in need.items() if ids and getattr(caps, cap, None) is False}
        if missing:
            raise TripError(422, "TRIP_REGULATION_CAPS_MISSING", {"missing": missing})
        # ponytail: an older CORE (field absent) only warns; refuse it like False once every robot runs v1.237+.
        unknown = {cap: ids for cap, ids in need.items() if ids and getattr(caps, cap, None) is None}
        if unknown:
            _LOG.warning("trip of %s crosses regulation its CORE does not announce: %s", robot_id, unknown)
        if detail is not None:  # set, or cleared by a later clean check
            detail.pop("regulation_caps_unknown", None)
            detail.update({"regulation_caps_unknown": unknown} if unknown else {})
        return caps

    async def _admit_replan(self, live, hold: dict, principal_id: str) -> None:
        """The operator-confirmed replan path only (``confirm_replan``): the D-763 10 (c) capability checks as
        at a start, then the switch; a changed map is left to ``_apply_replan`` (409 ``TRIP_MAP_CHANGED``).
        The AI path (``_ai_confirm``) calls ``_caps_checks`` and ``_pose_checks`` itself. This path runs no
        ``_pose_checks``; that gap predates D-763 10 (c) and is not closed here."""
        active = self._store.active()
        if active is not None and active[0] == hold["map_version"]:
            await self._caps_checks(live.view["robot_id"], active[2], hold["plan"]["segments"], bool(live.repeat),
                                    detail=live.view["detail"])
        self._apply_replan(live, hold, principal_id)

    async def _pose_checks(self, robot_id: str, graph, segments: list, *, start: bool = False, start_at=None, caps=None):
        """D-494 start checks on line following and the map pose: ``(pose, enable)`` or ``TripError``.
        D-601 A: at a start (not a lap) a robot with line following OFF passes, ``enable`` True: the
        trip turns the camera line on itself once it is open. D-601 D: a start also checks alignment."""
        enable = False
        if any(graph.arcs[arc_id(seg)].drive_mode == "lane" for seg in segments):
            mode = await self._call(self._junction.line_follow_mode(robot_id), "TRIP_LINE_FOLLOW_NOT_ACTIVE")
            # review HIGH 1: only a trip that starts on a lane; a free first segment keeps the refusal
            enable = start and mode == "OFF" and graph.arcs[arc_id(segments[0])].drive_mode == "lane"
            if mode not in LINE_MODES and not enable:
                raise TripError(422, "TRIP_LINE_FOLLOW_NOT_ACTIVE", {"mode": mode})
        pose = await self.map_pose(robot_id)
        anchor_age = getattr(pose, "anchor_age_s", None)
        if pose is None or pose.state != LOCALIZED or anchor_age is None or (
                anchor_age > self.config.start_anchor_age_s and not self._still_on_pin(pose)):
            raise TripError(422, "TRIP_POSE_UNTRUSTED", {"pose_state": pose.state if pose else None,
                                                         "anchor_age_s": anchor_age})
        if start_at is not None:
            distance = math.dist((pose.x, pose.y), graph.place_xy(start_at))
            if distance > ARRIVED_M:
                raise TripError(422, "TRIP_START_PLACE_MISMATCH",
                                {"place": start_at, "distance_m": round(distance, 3), "limit_m": ARRIVED_M})
            body = nominal_body_for(caps.kind)
            if body is None:
                raise TripError(422, "TRIP_BODY_UNKNOWN", {"kind": caps.kind})
            if not segments:
                raise TripError(422, "TRIP_NO_ROUTE")
            first = graph.arcs[arc_id(segments[0])]
            offset = first.project(pose.x, pose.y)[0]
            margin = first.width_m / 2 - offset - body.half_width_m
            if margin < 0:
                raise TripError(422, "TRIP_START_BODY_OUTSIDE_ROUTE",
                                {"edge_id": first.edge_id, "body_margin_m": round(margin, 3)})
        if start:
            check = start_check(graph, segments, pose.x, pose.y, pose.yaw, self.config.start_heading_tol_deg)
            if check["code"] is not None:
                raise TripError(422, check["code"], check)
        return pose, enable

    async def _link_back(self, live) -> bool:
        """D-760 4: the robot answered again after ``link_wait`` and its pose was read LOCALIZED. As at a start, the
        plan's map version and, with a lane ahead, CORE's line mode must hold, else the trip ends as that refusal.
        A robot call that fails here raises, so the trip waits on. True: it runs again."""
        index = live.view["segment_index"]
        if (live.view.get("lease") or {}).get("renewed_at", -math.inf) < live.view["wait"]["lease_at"]:
            return False  # Safety-Review minor: no lease renew confirmed since the loss yet; it waits on
        try:
            self._graph_for(live.view["map_version"])
            if any(live.arc(i).drive_mode == "lane" for i in range(index, len(live.segments))):
                mode = await self._call(self._junction.line_follow_mode(live.view["robot_id"]))
                if mode not in LINE_MODES:
                    raise TripError(422, "TRIP_LINE_FOLLOW_NOT_ACTIVE", {"mode": mode})
        except TripError as exc:
            await self._stop(live, "failed", exc.code, {**exc.detail, "link_wait": live.view["wait"]["kind"]})
            return False
        if not live.open:  # canceled or the lease lost meanwhile
            return False
        live.view["state"] = "running"  # ``wait`` stays until this step ends without a link fault
        live.last_goal = None  # its goal lease was not renewed while waiting: a free robot gets its goal again
        return True

    async def _start_pose(self, robot_id: str, graph, segments: list, operator_name: str, *,
                          start_at=None, caps=None, start_token=None, start_guard=None):
        """``_pose_checks(start=True)`` plus D-603: with ``fleet.trip.auto_align`` a TRIP_START_HEADING_MISMATCH
        (on the lane: off-lane is judged first) asks CORE to turn by the error, then checks again from a
        fresh sighting. ``(pose, enable, turns)``; a refused or aborted turn refuses the start."""
        turns: list = []
        start_token = self._start_token(robot_id) if start_token is None else start_token
        for attempt in range(ALIGN_TURNS + 1):
            try:
                result = await self._pose_checks(robot_id, graph, segments, start=True,
                                                 start_at=start_at, caps=caps)
                await self._guard_start(robot_id, start_token, start_guard)
                return (*result, turns)
            except TripError as exc:
                err = exc.detail.get("heading_err_deg") if exc.code == "TRIP_START_HEADING_MISMATCH" else None
                if not self.config.auto_align or err is None or attempt == ALIGN_TURNS:
                    raise
            await self._guard_start(robot_id, start_token, start_guard)
            turns.append(await self._align(robot_id, round(-err, 1), operator_name))

    async def _align(self, robot_id: str, delta_deg: float, operator_name: str) -> dict:
        """One CORE turn, waited for, then a sighting newer than its end. Polls are counted, not timed,
        so a stuck clock still ends the wait; a turn still running then is stopped."""
        try:
            await self._call(self._junction.rotate_to(robot_id, delta_deg, operator_name), "TRIP_ALIGN_REFUSED")
        except TripError as exc:  # CORE's refusal (ROTATE_CLEARANCE {nearest_m, need_m}, MOTION_BUSY, ...)
            exc.detail.update(delta_deg=delta_deg, core=getattr(exc.__cause__, "detail", None))
            raise
        status: dict = {}
        for _ in range(math.ceil(ALIGN_WAIT_S / self.config.period_s)):
            await asyncio.sleep(self.config.period_s)
            try:
                status = await self._call(self._junction.rotate_status(robot_id)) or {}
            except Exception:  # noqa: BLE001 - an unreadable turn is stopped and refuses the start
                status = {"state": "running", "reason": "status_unreadable"}
                break
            if status.get("state") != "running":
                break
        if status.get("state") != "done":
            if status.get("state") == "running":
                await self._call(self._junction.rotate_stop(robot_id))  # CORE's timeout bounds it anyway
            raise TripError(422, "TRIP_ALIGN_ABORTED", {"delta_deg": delta_deg, "reason": status.get("reason") or
                                                        "fleet_timeout", "final_err_deg": status.get("final_err_deg")})
        done_at = self._clock()
        for _ in range(math.ceil(ALIGN_SIGHTING_S / self.config.period_s)):
            pose = await self.map_pose(robot_id)
            age = getattr(pose, "anchor_age_s", None)
            if age is not None and self._clock() - age > done_at:
                return {"delta_deg": delta_deg, "final_err_deg": status.get("final_err_deg")}
            await asyncio.sleep(self.config.period_s)
        raise TripError(422, "TRIP_POSE_UNTRUSTED", {"after_align": True, "delta_deg": delta_deg})

    async def camera_check(self, robot_id: str, caps=None) -> None:
        """D-601 B (plan time, lane plans): the robot's front camera, the line camera, must be live
        (CORE ``vision/front/status`` ``available``); else 422 ``TRIP_LANE_CAMERA_UNAVAILABLE``. Off with
        ``fleet.trip.lane_camera_check: false`` (Gazebo SIM publishes no front preview). D-604: the
        capabilities' ``line_follow.camera`` (same evidence) answers it without a call; an older CORE
        (no such field) is still asked over ``front/status``."""
        if not self.config.lane_camera_check:
            return
        status = getattr(caps, "line_camera", None)
        if status is not None:
            if status.get("available") is not True:
                raise TripError(422, "TRIP_LANE_CAMERA_UNAVAILABLE", {
                    "stale": status.get("source") not in (None, "NONE"), "age_ms": status.get("age_ms"),
                    "source": status.get("source")})
            return
        status = await self._call(self._junction.front_camera(robot_id), "TRIP_LANE_CAMERA_UNAVAILABLE") or {}
        if status.get("available") is not True:
            raise TripError(422, "TRIP_LANE_CAMERA_UNAVAILABLE", {"stale": status.get("stale"),
                                                                    "age_ms": status.get("age_ms")})

    def _still_on_pin(self, pose: MapPose) -> bool:
        """D-593 7: a LOCALIZED operator-pin pose (its anchor is then <= max_anchor_age_s old) whose
        odom has not moved since the pin. An odom reset drops the anchor, so it is never still."""
        return (getattr(pose, "anchor_source", None) == OPERATOR_PIN
                and pose.dead_reckon_m <= self.config.pin_start_still_m
                and getattr(pose, "bridge_turn_deg", math.inf) <= self.config.pin_start_still_deg)
