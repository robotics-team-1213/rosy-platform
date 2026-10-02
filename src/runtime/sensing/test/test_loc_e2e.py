"""D-395 Phase 1 host end-to-end: robot pure logic + wire models + Fleet arbiter, no ROS.

Two simulated robots on the checked-in map_v2_fleet map (180-degree symmetric).
Each robot searches, reports candidates over the D-395 wire model, Fleet
arbitrates, the robot injects and runs the 3 s check. Every case must end
LOCALIZED at the true pose with zero human input: no decision ever carries
source 'human' and nothing outside this loop touches the robots.
"""
import itertools
import math
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[3] / "site" / "fleet"))

from core_common.protocol.localization import CandidateReport, DecisionSource  # noqa: E402
from fleet.localization import cues  # noqa: E402
from fleet.localization.arbiter import Arbiter, Context  # noqa: E402

from control.sensing.loc_candidates import (  # noqa: E402
    global_candidates, merge, sensor_from_base, slot_candidates)
from control.sensing.loc_objects import unmapped_objects  # noqa: E402
from control.sensing.loc_state import LocalizationStateMachine, LocState  # noqa: E402
from control.sensing.perception.paint_hypothesis import paint_score  # noqa: E402
from loc_world import MOUNT, SQUARES, field, mirror, paint_map, paint_points, scan  # noqa: E402

RADIUS, DT, LIMIT_S = .105, .25, 12.


class SimRobot:
    """One robot: truth for the world, pure D-395 logic for everything it decides."""

    def __init__(self, robot_id, truth, camera=False, mirror_first=False):
        self.robot_id, self.truth, self.camera, self.mirror_first = robot_id, truth, camera, mirror_first
        ids = itertools.count(1)
        self.machine = LocalizationStateMachine(lambda: f"{robot_id}-{next(ids)}")
        self.report, self.injected = None, None

    def others(self, robots):
        return [r.truth[:2] for r in robots if r is not self]

    def search(self, now, robots):
        ranges, angles = scan(self.truth, peers=self.others(robots))
        found = merge(slot_candidates(field(), SQUARES, ranges, angles, RADIUS, MOUNT),
                      global_candidates(field(), ranges, angles, RADIUS, MOUNT))
        if self.mirror_first:   # the forced mirror: the wrong twin is reported first
            found.sort(key=lambda c: math.dist((c.x, c.y), mirror(self.truth)[:2]))
        self.machine.offer(found, now)
        first = found[0]
        objects = unmapped_objects(field(), sensor_from_base((first.x, first.y, first.yaw), MOUNT),
                                   ranges, angles, MOUNT)
        points = paint_points(self.truth) if self.camera else None
        self.report = CandidateReport.model_validate({
            "robot_id": self.robot_id, "request_id": self.machine.request_id, "stamp": now,
            "pickup": self.machine.pickup,
            "candidates": [{"x": c.x, "y": c.y, "yaw": c.yaw, "scan_fit": c.scan_fit,
                            "paint_score": None if points is None else
                            paint_score(paint_map(), points, (c.x, c.y, c.yaw))} for c in found],
            "unmapped_objects": [{"x": x, "y": y} for x, y in objects]})

    def apply(self, decision, now):
        step = self.machine.decide(decision.request_id, now, candidate_index=decision.candidate_index,
                                   source=decision.source.value, cues=[c.value for c in decision.cues],
                                   received_s=now, ttl_s=decision.ttl_s)
        if "inject_pose" in step.actions:
            self.injected = step.pose

    def tick(self, now, robots):
        if self.injected is not None and self.machine.state is not LocState.LOCALIZED:
            ranges, angles = scan(self.truth, peers=self.others(robots))
            fit = field().score(sensor_from_base(self.injected, MOUNT), ranges, angles)
            self.machine.observe_fit(now, fit)


def context(robot, robots):
    """Fleet's view: only LOCALIZED robots are peers, at the pose they reported."""
    peers = [r.injected[:2] for r in robots
             if r is not robot and r.machine.state is LocState.LOCALIZED]
    return Context(peers=peers, slots=[cues.Slot(s.x, s.y, s.axis_rad) for s in SQUARES],
                   squares=[(s.x, s.y) for s in SQUARES])


def localize(robots):
    arbiter, decisions = Arbiter(), []
    for k in range(int(LIMIT_S / DT) + 1):
        now = k * DT
        for robot in robots:
            if robot.machine.state is LocState.LOCALIZED:
                continue
            if robot.report is None:
                robot.search(now, robots)
            decision = arbiter.observe(robot.report, context(robot, robots), now)
            if decision is not None:
                decisions.append(decision)
                robot.apply(decision, now)
            robot.tick(now, robots)
        if all(r.machine.state is LocState.LOCALIZED for r in robots):
            break
    return decisions


def assert_at_truth(robot):
    assert robot.machine.state is LocState.LOCALIZED, robot.robot_id
    x, y, yaw = robot.injected
    assert math.dist((x, y), robot.truth[:2]) < .03
    assert abs(math.atan2(math.sin(yaw - robot.truth[2]), math.cos(yaw - robot.truth[2]))) < math.radians(4)


def test_on_square_and_off_slot_robots_power_on_together_without_a_camera():
    """r1 on square A facing -y (axis + 180): the scan picks the heading, the slot prior
    beats the mirror. r2 off-slot has no prior until r1 is LOCALIZED; then r1 in r2's
    scan lands on r1 only under the true hypothesis."""
    r1 = SimRobot("r1", (-1.26, .49, -math.pi / 2))
    r2 = SimRobot("r2", (-.9, -.509, 0.))
    decisions = localize([r1, r2])
    assert_at_truth(r1)
    assert_at_truth(r2)
    assert {d.source for d in decisions} == {DecisionSource.CANDIDATE}
    assert len(decisions) == 2


@pytest.mark.parametrize("truth", [(0., .51, 0.), (.86, -.52, math.pi)],
                         ids=["off-slot", "on-square-B"])
def test_a_lone_robot_with_the_mirror_reported_first_still_localizes_on_paint(truth):
    robot = SimRobot("r3", truth, camera=True, mirror_first=True)
    decisions = localize([robot])
    assert_at_truth(robot)
    assert [d.source for d in decisions] == [DecisionSource.CANDIDATE]
    assert decisions[0].candidate_index != 0     # index 0 was the mirror


def test_a_lone_off_slot_robot_without_cues_is_left_to_the_ladder():
    """No camera, no peer, no slot: the twins tie, so Fleet decides nothing (D-395 §6, step 2+)."""
    robot = SimRobot("r4", (-.9, -.509, 0.))
    assert localize([robot]) == []
    assert robot.machine.state is LocState.CANDIDATES and robot.injected is None
