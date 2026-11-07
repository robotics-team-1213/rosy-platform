"""D-982 decision API judge: ``go`` / ``wait`` / ``refuse`` with a reason, from a hypothetical state.

Pure. Departure order and return call the functions the live path calls (``blocks.grant_order_key``,
``ChargeBays.plan``), so an answer asked beforehand and the live decision cannot drift apart. A
formation is judged with ``slots`` (the arming check) and the optional site limits; Fleet does not
enforce those limits at formation start yet (stage 3), so the answer says ``enforced: false``. Nothing here reaches a robot;
the answer is advice and CORE's own checks stay final (D-911).
"""

from __future__ import annotations

from typing import Literal, Optional

from pydantic import BaseModel, ConfigDict, Field

from fleet.charge_bays import Bay, ChargeBays, RobotView
from fleet.formation.geometry import slots
from fleet.site_rules import FOLLOW_SPEED_MPS, SiteRules
from fleet.swarm.api.types import DEFAULT_SPACING, Formation as Shape, FormationError
from fleet.traffic.blocks import grant_order_key


class _Body(BaseModel):
    model_config = ConfigDict(extra="forbid")


class Waiter(_Body):
    robot_id: str = Field(min_length=1, max_length=64)
    waiting_s: float = Field(default=0.0, ge=0.0, le=86400.0, allow_inf_nan=False)
    in_zone: bool = False
    localized: bool = True


class Departure(_Body):
    kind: Literal["departure"]
    robot_id: str = Field(min_length=1, max_length=64)
    #: How many robots the contested unit holds at once (a zone's capacity).
    capacity: int = Field(default=1, ge=1, le=16)
    robots: list[Waiter] = Field(max_length=32)


class Candidate(_Body):
    robot_id: str = Field(min_length=1, max_length=64)
    percent: Optional[float] = Field(default=None, ge=0.0, le=100.0)
    on_trip: bool = False
    online: bool = True


class Return(_Body):
    kind: Literal["return"]
    robot_id: str = Field(min_length=1, max_length=64)
    robots: list[Candidate] = Field(max_length=32)
    bays: list[str] = Field(max_length=16)
    #: bay id -> the robot standing in it (that robot must be in ``robots``)
    occupied: dict[str, str] = Field(default_factory=dict)


class Formation(_Body):
    kind: Literal["formation"]
    formation: str = "COLUMN"
    followers: int = Field(default=1, ge=0, le=16)
    spacing: Optional[float] = Field(default=None, gt=0.0, le=50.0, allow_inf_nan=False)
    max_speed: Optional[float] = Field(default=None, gt=0.0, le=5.0, allow_inf_nan=False)


State = Departure | Return | Formation


def _answer(verdict: str, reason: str, **detail) -> dict:
    return {"verdict": verdict, "reason": reason, "detail": detail}


def judge_departure(rules: SiteRules, state: Departure) -> dict:
    """Who is granted the contested unit first: the same fair order ``blocks.step`` sorts by."""
    subject = next((r for r in state.robots if r.robot_id == state.robot_id), None)
    if subject is None:
        return _answer("refuse", "unknown_robot")
    if not subject.localized:  # the table gives no new grant to a robot without a pose
        return _answer("wait", "pose_unknown")
    merge = rules.departure.merge_max_wait_s
    ranked = sorted((r for r in state.robots if r.localized),
                    key=lambda r: grant_order_key(r.robot_id, -r.waiting_s, 0.0, r.in_zone, merge))
    rank = [r.robot_id for r in ranked].index(state.robot_id)
    detail = {"rank": rank + 1, "capacity": state.capacity, "merge_max_wait_s": merge,
              "past_merge_bound": subject.waiting_s >= merge}
    if rank < state.capacity:
        return _answer("go", "first_in_order", **detail)
    return _answer("wait", "queued_behind", ahead=[r.robot_id for r in ranked[:rank]], **detail)


def judge_return(rules: SiteRules, state: Return) -> dict:
    """Charge return: ``ChargeBays.plan`` with bays laid far apart so only ``occupied`` robots are in one."""
    levels = (rules.return_.go_percent, rules.return_.leave_percent)
    bays = [Bay(name, 10.0 * index, 0.0) for index, name in enumerate(sorted(set(state.bays)))]
    at = {bay.id: (bay.x, bay.y) for bay in bays}
    standing = {robot: bay for bay, robot in state.occupied.items() if bay in at}
    views = [RobotView(r.robot_id, r.online, r.percent, None, at.get(standing.get(r.robot_id)),
                       r.on_trip) for r in state.robots]
    plan = ChargeBays(thresholds=lambda: levels)
    plan.observe(0.0, views, bays)
    action = next((a for a in plan.plan(views, bays)["actions"] if a["robot_id"] == state.robot_id), None)
    subject = next((r for r in state.robots if r.robot_id == state.robot_id), None)
    if subject is None:
        return _answer("refuse", "unknown_robot")
    if action is None:
        return _answer("refuse", "not_needed" if subject.online else "offline", go_percent=levels[0])
    verdict = "go" if action["action"] in ("go", "leave") else "wait"
    detail = {k: v for k, v in action.items() if k in ("bay", "action")}
    if action["reason"] == "no_free_bay" and rules.return_.when_full is not None:
        detail["wait_at"] = rules.return_.when_full.wait_at
    reason = "after_trip" if action["action"] == "after_trip" else action["reason"]
    return _answer(verdict, reason, go_percent=levels[0], leave_percent=levels[1], **detail)


def judge_formation(rules: SiteRules, state: Formation) -> dict:
    spacing = DEFAULT_SPACING if state.spacing is None else state.spacing
    speed = FOLLOW_SPEED_MPS if state.max_speed is None else state.max_speed
    detail = {"spacing": spacing, "max_speed": speed}
    try:
        slots(Shape(state.formation), state.followers, spacing)
    except (ValueError, FormationError) as exc:  # the arming checks the real start runs first
        return _answer("refuse", "invalid_formation", message=str(exc), **detail)
    refused = rules.formation.refusal(spacing, speed)
    if refused:
        return _answer("refuse", refused[0].lower(), message=refused[1], enforced=False, **detail)
    return _answer("go", "within_rules", enforced=False, **detail)


def judge(rules: SiteRules, state: State) -> dict:
    return {"departure": judge_departure, "return": judge_return,
            "formation": judge_formation}[state.kind](rules, state)
