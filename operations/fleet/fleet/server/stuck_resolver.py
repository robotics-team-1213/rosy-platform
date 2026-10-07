"""D-438 Fleet stuck resolver core: rules first, then (phase 2) a model, then a human.

Pure: the caller feeds console snapshot rows and a monotonic clock, sends the returned
Answers and reports CORE's reply with `result`. CORE re-checks every answer (D-407 §2);
nothing here widens a robot's local-recovery settings.
"""

from __future__ import annotations

import logging
import math
from dataclasses import dataclass, field
from typing import Callable, Iterable, Mapping, Optional, Union

#: CORE codes that mean "this answer was judged and refused": try the next candidate.
REFUSED = "STUCK_DECISION_REFUSED"
#: The stuck changed under us: drop this answer, re-read state.
MISMATCH = "STUCK_ID_MISMATCH"
#: Transport failures: one resend, then a human; uncertain YIELD is never replayed.
TRANSPORT = ("ROBOT_UNREACHABLE", "STUCK_DECISION_OUTCOME_UNKNOWN")


@dataclass(frozen=True)
class ResolverConfig:
    poll_s: float = 1.0
    restuck_s: float = 30.0
    rule_budget: int = 2
    escalate_after_s: float = 60.0
    peer_reach_m: float = 0.30
    # Own URDF half width (0.057 m) + a peer's rotation radius (0.083 m), rounded up.
    # ponytail: one body size for every robot; read per-robot geometry when kinds differ.
    peer_band_half_width_m: float = 0.15
    peer_radius_m: float = 0.083          # reach is measured to the peer's body, not its centre


@dataclass(frozen=True)
class Answer:
    robot_id: str
    stuck_id: str
    decision: str
    rule: str
    # D-453: one yield segment. None on WAIT / BACK_AND_RETRY / RESUME.
    yield_m: Optional[float] = None
    yield_turn_rad: Optional[float] = None


@dataclass(frozen=True)
class Escalate:
    robot_id: str
    stuck_id: str
    reason: str


Action = Union[Answer, Escalate]


@dataclass
class _Chain:
    started_at: float
    mode: str
    stuck_id: Optional[str] = None
    closed_at: Optional[float] = None
    rule_answers: int = 0
    # Phase 2 (model tier) only: phase-1 rules never answer RESUME, so this stays None.
    resume_id: Optional[str] = None                  # stuck id the resolver answered RESUME
    retired: set = field(default_factory=set)
    answered: set = field(default_factory=set)       # stuck ids with an answer in flight/done
    retries: dict = field(default_factory=dict)      # stuck id -> transport resends
    escalated: set = field(default_factory=set)      # stuck ids already escalated


def _stuck_of(row: Mapping) -> Optional[dict]:
    lf = (row.get("state") or {}).get("line_follow") or {}
    stuck = lf.get("stuck")
    return stuck if isinstance(stuck, dict) and stuck.get("stuck_id") else None


def _mode_of(row: Mapping) -> str:
    return str(((row.get("state") or {}).get("line_follow") or {}).get("mode") or "")


def _pose_of(row: Mapping) -> Optional[tuple[float, float, float]]:
    pose = (row.get("state") or {}).get("pose") or {}
    try:
        return float(pose["x"]), float(pose["y"]), float(pose.get("yaw", 0.0))
    except (KeyError, TypeError, ValueError):
        return None


def _map_pose(row: Mapping) -> Optional[tuple[float, float, float]]:
    """Painted-map xy. A legacy snapshot has no localization block (D-395).

    LOCALIZED + map is the same xy. An odom-frame pose is not the painted track,
    and the twist integrator in body_stop is the command, not this pose.
    """
    from fleet.localization.trust import LEGACY, TRUSTED, classify

    state = row.get("state")
    if not row.get("online", True) or not isinstance(state, Mapping):
        return None
    verdict = classify(state)
    if verdict not in (LEGACY, TRUSTED):
        return None
    if "localization" in row:
        # Console owns the D-395 restart grace. Null raw localization is not
        # legacy while its current badge says the map pose is untrusted.
        badge = row["localization"]
        if not isinstance(badge, Mapping) or badge.get("trusted") is not True:
            return None
        if (badge.get("legacy") is True) != (verdict == LEGACY):
            return None
    return _pose_of(row)


def _hold_xy(plan, painted):
    room = next((item for item in painted.rooms if item.id == plan.room_id), None)
    return None if room is None else room.hold_xy


def _door_xy(plan, painted):
    if plan.s_m is None:
        return None
    x, y, _tangent = painted.line(plan.edge_id).point_at(plan.s_m)
    return (x, y)


def _gap_target(plan, painted, x: float, y: float):
    """Off the paint while still entering: the hold if the door is the nearest point, else the line."""
    from fleet.meet.place import ALONG_FIRST_M, MAX_OFF_M

    line = painted.line(plan.edge_id)
    _dist, s_m, _tangent = line.project(x, y)
    near_door = plan.s_m is not None and abs(s_m - plan.s_m) <= ALONG_FIRST_M + MAX_OFF_M
    if plan.action == "sidestep" and near_door:
        hold = _hold_xy(plan, painted)
        if hold is not None:
            return hold
    px, py, _tangent = line.point_at(s_m)
    return (px, py)


class _YieldPlan:
    """Policy direction of a yielder. The manoeuvre yaw is not a new meet heading."""

    def __init__(self, edge_id: str, direction: int, action: str,
                 room_id: Optional[str], s_m: Optional[float]) -> None:
        self.edge_id, self.direction, self.action = edge_id, direction, action
        self.room_id, self.s_m = room_id, s_m
        self.returning = False


class StuckResolver:
    def __init__(self, config: ResolverConfig, *, painted: Optional[Callable[[], object]] = None) -> None:
        """``painted()`` is the active site map's ``Painted`` (D-488) or None: no meet rules."""
        self.config = config
        self._painted = painted or (lambda: None)
        self._warned_no_map = False
        self._chains: dict[str, _Chain] = {}
        self._claims: set[tuple[str, str]] = set()
        self._pins: dict[str, str] = {}
        self._plans: dict[str, _YieldPlan] = {}
        self._sent_yield: dict[str, tuple] = {}

    # ---- inputs -----------------------------------------------------------------------

    def claim(self, robot_id: str, stuck_id: str) -> None:
        """A human opened this stuck's decision (D-438 §1): the resolver stays silent."""
        self._claims.add((robot_id, stuck_id))

    def sent(self, answer: Answer, now: float) -> None:
        chain = self._chains.get(answer.robot_id)
        if chain is None:
            chain = self._chains[answer.robot_id] = _Chain(started_at=now, mode="")
        chain.answered.add(answer.stuck_id)
        if answer.decision == "YIELD" and answer.yield_m is not None:
            self._sent_yield[answer.robot_id] = (
                answer.stuck_id, round(answer.yield_turn_rad or 0.0, 3), round(answer.yield_m, 3))
        if answer.rule.startswith("R") and chain.retries.get(answer.stuck_id, 0) == 0:
            chain.rule_answers += 1                   # a transport resend is the same answer
        if answer.decision == "RESUME" and answer.rule != "meet":
            chain.resume_id = answer.stuck_id

    def result(self, answer: Answer, *, code: Optional[str]) -> Optional[Escalate]:
        """CORE's reply: None code = accepted. Returns an escalation when one is due."""
        chain = self._chains.get(answer.robot_id)
        if chain is None:
            return None
        if code is None:
            if answer.decision == "RESUME" and answer.rule == "meet":
                chain.resume_id = answer.stuck_id
                self._plans.pop(answer.robot_id, None)
                self._pins = {edge: yielder for edge, yielder in self._pins.items()
                              if yielder != answer.robot_id}
            return None
        if code == MISMATCH:
            return None
        if answer.stuck_id != chain.stuck_id and answer.stuck_id not in chain.answered:
            return None                               # late reply from an older chain
        if code == REFUSED:
            # The robot is still in YIELDED. Retry the return on the next poll.
            if answer.decision == "RESUME" and answer.rule == "meet":
                return None
            chain.retired.add(answer.rule)
            chain.answered.discard(answer.stuck_id)
            return None
        if code == "STUCK_DECISION_OUTCOME_UNKNOWN" and answer.decision == "YIELD":
            # CORE may already have completed this segment. A replay can restart motion.
            return self._escalate(chain, answer.robot_id, answer.stuck_id, f"core:{code}")
        if code in TRANSPORT and chain.retries.get(answer.stuck_id, 0) == 0:
            chain.retries[answer.stuck_id] = 1
            chain.answered.discard(answer.stuck_id)
            return None
        chain.escalated.add(answer.stuck_id)
        return Escalate(answer.robot_id, answer.stuck_id, f"core:{code}")

    # ---- decision ---------------------------------------------------------------------

    def step(self, now: float, rows: Iterable[Mapping]) -> list[Action]:
        rows = [r for r in rows if isinstance(r, Mapping) and r.get("robot_id")]
        present = {str(r["robot_id"]) for r in rows}         # rows are the full roster
        for rid in set(self._chains) - present:
            del self._chains[rid]
        self._claims = {c for c in self._claims if c[0] in present}
        actions: list[Action] = []
        for row in rows:
            action = self._one(now, row, rows)
            if action is not None:
                actions.append(action)
        return actions

    def _one(self, now: float, row: Mapping, rows: list) -> Optional[Action]:
        rid = str(row["robot_id"])
        if not row.get("online", True):
            return None
        stuck, mode = _stuck_of(row), _mode_of(row)
        chain = self._chains.get(rid)
        if chain is not None and (mode and chain.mode and mode != chain.mode
                                  or (chain.closed_at is not None
                                      and now - chain.closed_at > self.config.restuck_s)):
            del self._chains[rid]                  # mode changed or the window passed
            if chain.closed_at is not None:        # a human's claim lives while its stuck is open
                self._claims = {c for c in self._claims if c[0] != rid}
            chain = None
        if stuck is None:
            self._plans.pop(rid, None)
            if chain is not None and chain.closed_at is None:
                chain.closed_at, chain.stuck_id = now, None
            return None
        sid = str(stuck["stuck_id"])
        if chain is None:
            chain = self._chains[rid] = _Chain(started_at=now, mode=mode)
        elif not chain.mode:
            chain.mode = mode
        if chain.stuck_id != sid:
            chain.stuck_id, chain.closed_at = sid, None
            if chain.resume_id is not None and sid != chain.resume_id:
                return self._escalate(chain, rid, sid, "restuck_after_resume")
        if (rid, sid) in self._claims or sid in chain.escalated:
            return None
        state = row.get("state") or {}
        if (state.get("safety") or {}).get("estop"):
            return self._escalate(chain, rid, sid, "estop")
        if state.get("activity"):                  # attended calibration lease (D-321)
            return self._escalate(chain, rid, sid, "calibration")
        if now - chain.started_at > self.config.escalate_after_s:
            return self._escalate(chain, rid, sid, "deadline")
        if sid in chain.answered:
            return self._next_segment(row, rows)
        rule = self._rule(row, stuck, rows, chain)
        if rule is not None and rule[1] == "ESCALATE":
            return self._escalate(chain, rid, sid, "meet")
        if rule is not None and rule[1] == "RESUME":
            rule = ("meet", "WAIT")                   # resume only after a finished segment
        if rule is None:
            return self._escalate(chain, rid, sid, "no_rule")
        # §5: the one transport resend repeats an answer already counted; never block it.
        if chain.rule_answers >= self.config.rule_budget and chain.retries.get(sid) != 1:
            return self._escalate(chain, rid, sid, "rule_budget")
        if len(rule) == 4:
            return Answer(rid, sid, rule[1], rule[0], yield_m=rule[3], yield_turn_rad=rule[2])
        return Answer(rid, sid, rule[1], rule[0])

    def _escalate(self, chain: _Chain, rid: str, sid: str, reason: str) -> Escalate:
        chain.escalated.add(sid)
        return Escalate(rid, sid, reason)

    # ---- rules (D-438 §2) -------------------------------------------------------------

    def _rule(self, row, stuck, rows, chain) -> Optional[tuple[str, str]]:
        cause = stuck.get("cause")
        can_back = (bool(stuck.get("local_enabled"))
                    and int(stuck.get("attempts") or 0) < int(stuck.get("max_attempts") or 0))
        peer = cause == "obstacle_ahead" and self._peer_ahead(row, rows)
        if peer and "meet" not in chain.retired:
            meet = self._meet(row, rows)
            if meet is not None:
                return meet
        candidates = []
        if peer:
            candidates.append(("R1", "WAIT"))
        if cause == "obstacle_ahead" and not peer and can_back:
            candidates.append(("R2", "BACK_AND_RETRY"))
        if cause == "lane_lost" and can_back:
            candidates.append(("R3", "BACK_AND_RETRY"))
        if peer and can_back:
            candidates.append(("R2", "BACK_AND_RETRY"))      # after a refused WAIT
        for rule in candidates:
            if rule[0] not in chain.retired:
                return rule
        return None

    def _next_segment(self, row, rows) -> Optional[Answer]:
        """The robot finished one segment and is holding off the resume path."""
        stuck = _stuck_of(row)
        if stuck is None or stuck.get("phase") != "YIELDED":
            return None
        meet = self._meet(row, rows)
        if meet is None:
            return None
        rid = str(row["robot_id"])
        sid = str(stuck["stuck_id"])
        if meet[1] == "RESUME":
            return Answer(rid, sid, "RESUME", "meet")
        if len(meet) != 4:
            return None
        key = (sid, round(meet[2], 3), round(meet[3], 3))
        if self._sent_yield.get(rid) == key:
            return None
        return Answer(rid, sid, "YIELD", "meet", yield_m=meet[3], yield_turn_rad=meet[2])

    def _meet(self, row, rows):
        """room_hold for poses on the painted track. None keeps R1/R2/R3."""
        from fleet.meet import decide
        from fleet.meet.place import project, yield_move
        from fleet.meet.scene import Action, Order, Pin, Robot

        me = _map_pose(row)
        if me is None:
            return None
        painted = self._painted()
        if painted is None:  # no active site map (D-488): R1/R2/R3 only
            if not self._warned_no_map:
                self._warned_no_map = True
                logging.getLogger(__name__).warning("stuck resolver: no active site map; meet rules off")
            return None
        self._warned_no_map = False
        rid = str(row["robot_id"])
        placed: dict[str, object] = {}
        robots: list[Robot] = []
        for other in rows:
            if not other.get("online", True):
                continue
            pose = _map_pose(other)
            if pose is None:
                continue
            place = project(painted, pose[0], pose[1], pose[2])
            if place is None:
                continue
            oid = str(other["robot_id"])
            placed[oid] = place
            plan = self._plans.get(oid)
            if place.room_id:
                if plan is not None and plan.room_id == place.room_id:
                    plan.returning = True
                else:
                    self._plans.pop(oid, None)
                    plan = None
            if plan is not None and place.edge_id == plan.edge_id and not plan.returning:
                direction, trusted = plan.direction, True
            else:
                direction, trusted = place.direction, place.trusted
            robots.append(Robot(oid, place.edge_id, place.s_m, direction, trusted, room_id=place.room_id))
        mine = placed.get(rid)
        plan = self._plans.get(rid)
        if mine is None:
            if plan is None:
                return None
            return self._off_paint(me, plan, painted, rows, rid)
        if plan is not None and plan.returning:
            return self._rejoin(row, mine, plan, painted, rows, rid)
        if not any(other != rid for other in placed):
            return None
        pins = tuple(Pin(edge_id, yielder) for edge_id, yielder in self._pins.items())
        scene = painted.scene(tuple(robots), pins)
        orders = decide("room_hold", scene)
        self._keep_pins(scene, orders)
        order = next(item for item in orders if item.robot_id == rid)
        if order.action is Action.ESCALATE:
            self._plans.pop(rid, None)
            return ("meet", "ESCALATE")
        plan = self._plans.get(rid)
        if order.action in (Action.SIDESTEP, Action.RETREAT):
            robot = next(item for item in robots if item.id == rid)
            self._plans[rid] = _YieldPlan(
                order.edge_id or robot.edge_id or "", robot.direction, order.action.value,
                order.room_id, order.s_m)
            move = yield_move(mine, order, painted)
        elif plan is not None and mine.edge_id == plan.edge_id and not plan.returning:
            move = yield_move(mine, Order(
                rid, Action(plan.action), room_id=plan.room_id, edge_id=plan.edge_id, s_m=plan.s_m,
            ), painted)
        else:
            self._plans.pop(rid, None)
            move = None
        if move is None:
            return ("meet", "WAIT")
        return ("meet", "YIELD", move[0], move[1])

    def _off_paint(self, pose, plan, painted, rows, rid):
        """A usable pose that project() rejected. The timer already ended; this xy is the rest."""
        from fleet.meet.place import steer_toward

        x, y, yaw = pose
        if plan.returning:
            clear = self._door_clear(plan, painted, rows, rid)
            target = _door_xy(plan, painted) if clear else _hold_xy(plan, painted)
        else:
            target = _gap_target(plan, painted, x, y)
        if target is None:
            return ("meet", "WAIT")
        move = steer_toward(x, y, yaw, target)
        if move is None:
            return ("meet", "WAIT")
        return ("meet", "YIELD", move[0], move[1])

    def _rejoin(self, row, mine, plan, painted, rows, rid):
        """Back to the door, then face the stored travel direction. RESUME only on the paint."""
        from fleet.meet.place import ALONG_FIRST_M, along_to, steer_toward

        if not self._door_clear(plan, painted, rows, rid):
            if mine.room_id:
                return ("meet", "WAIT")
            hold = _hold_xy(plan, painted)
            if hold is None:
                return ("meet", "WAIT")
            move = steer_toward(mine.x, mine.y, mine.yaw, hold)
            if move is None:
                return ("meet", "WAIT")
            return ("meet", "YIELD", move[0], move[1])
        if mine.room_id or mine.edge_id != plan.edge_id:
            target = _door_xy(plan, painted)
            if target is None:
                return ("meet", "WAIT")
            move = steer_toward(mine.x, mine.y, mine.yaw, target)
            if move is None:
                return ("meet", "WAIT")
            return ("meet", "YIELD", move[0], move[1])
        if plan.s_m is None or abs(mine.s_m - plan.s_m) > ALONG_FIRST_M:
            if plan.s_m is None:
                return ("meet", "WAIT")
            move = along_to(mine, painted, plan.s_m)
            if move is None:
                return ("meet", "WAIT")
            return ("meet", "YIELD", move[0], move[1])
        if mine.trusted and mine.direction == plan.direction:
            if self._peer_ahead(row, rows):
                return ("meet", "WAIT")
            return ("meet", "RESUME")
        line = painted.line(plan.edge_id)
        hop = 0.15 if plan.direction > 0 else -0.15
        target_s = min(max(mine.s_m + hop, 0.0), line.length_m)
        move = along_to(mine, painted, target_s)
        if move is None:
            return ("meet", "WAIT")
        return ("meet", "YIELD", move[0], move[1])

    def _door_clear(self, plan, painted, rows, rid) -> bool:
        """The passer has gone past the door. An unusable pose blocks the return."""
        from fleet.meet.place import project

        if plan.s_m is None:
            return False
        door_x, door_y, _tangent = painted.line(plan.edge_id).point_at(plan.s_m)
        clearance = self.config.peer_reach_m + self.config.peer_radius_m
        for other in rows:
            if str(other.get("robot_id")) == rid:
                continue
            pose = _map_pose(other)
            if pose is None:
                return False
            place = project(painted, pose[0], pose[1], pose[2])
            if place is not None and place.edge_id == plan.edge_id:
                passed = (plan.s_m - place.s_m) * plan.direction
                if passed <= clearance:
                    return False
            elif place is not None and place.room_id == plan.room_id:
                return False
            elif math.hypot(pose[0] - door_x, pose[1] - door_y) <= clearance:
                return False
        return True

    def _keep_pins(self, scene, orders) -> None:
        from fleet.meet.scene import Action, closing

        kept: dict[str, str] = {}
        for line in scene.edges:
            group = [robot for robot in scene.robots if robot.edge_id == line.id]
            if len(group) != 2:
                continue
            pair = closing(group[0], group[1])
            if pair is None:
                continue
            ids = {pair[0].id, pair[1].id}
            chosen = next((order.robot_id for order in orders
                           if order.robot_id in ids and order.action in (Action.SIDESTEP, Action.RETREAT)), None)
            if chosen is None and self._pins.get(line.id) in ids:
                chosen = self._pins[line.id]
            if chosen is not None:
                kept[line.id] = chosen
        self._pins = kept

    def _peer_ahead(self, row, rows) -> bool:
        return bool(peer_ahead(row, rows, self.config))


def peer_ahead(row: Mapping, rows: Iterable[Mapping], config: ResolverConfig) -> Optional[bool]:
    """R1's judgement: an online peer inside the front band. None = this robot has no pose.

    Shared with the Fleet stuck-episode log, so the recorded value is what R1 would see."""
    me = _pose_of(row)
    if me is None:
        return None
    x0, y0, yaw = me
    c, s = math.cos(yaw), math.sin(yaw)
    for other in rows:
        if other is row or not other.get("online", True):
            continue
        pose = _pose_of(other)
        if pose is None:
            continue
        dx, dy = pose[0] - x0, pose[1] - y0
        ahead, side = c * dx + s * dy, -s * dx + c * dy
        if 0.0 < ahead <= config.peer_reach_m + config.peer_radius_m and abs(side) <= config.peer_band_half_width_m:
            return True
    return False
