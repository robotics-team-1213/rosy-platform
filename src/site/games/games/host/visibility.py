"""D-96 stair 1 checklist. No OpenCV. ready is not FIELD GO."""

from __future__ import annotations

from typing import Iterable, Mapping

from games.game import Observation
from games.host.robots import MatchSetup

NOTE = "not FIELD GO"


def stair1_expect(setup: MatchSetup) -> dict:
    return {
        "corners": [int(v) for v in setup.camera.corner_ids],
        "robots": [int(robot.aruco_id) for robot in setup.robots],
        "goals": [int(setup.goals.home_id), int(setup.goals.away_id)],
        "ball": False,
        "ready": False,
        "note": NOTE,
    }


def stair1_visibility(
    setup: MatchSetup,
    markers: Iterable[int],
    obs: Observation,
) -> dict:
    seen = {int(v) for v in markers}
    corners = [int(v) for v in setup.camera.corner_ids if int(v) in seen]
    robots = [int(robot.aruco_id) for robot in setup.robots if int(robot.aruco_id) in seen]
    goals = [
        int(v)
        for v in (setup.goals.home_id, setup.goals.away_id)
        if int(v) in seen
    ]
    ball = obs.ball is not None and not obs.lost_ball
    hsv = setup.goals.hsv_low is not None and setup.goals.hsv_high is not None
    ready = (
        set(corners) == {int(v) for v in setup.camera.corner_ids}
        and len(robots) == len(setup.robots)
        and ball
        and (len(goals) == 2 or hsv)
    )
    return {
        "corners": corners,
        "robots": robots,
        "goals": goals,
        "ball": ball,
        "ready": ready,
        "note": NOTE,
    }


def format_visibility(report: Mapping[str, object], *, expect: bool = False) -> str:
    corners = ",".join(str(v) for v in report["corners"])
    robots = ",".join(str(v) for v in report["robots"])
    goals = ",".join(str(v) for v in report["goals"])
    if expect:
        return (
            f"stair 1 expect corners={corners} robots={robots} goals={goals} ({NOTE})"
        )
    ball = "yes" if report.get("ball") else "no"
    ready = "yes" if report.get("ready") else "no"
    return (
        f"stair 1 visibility corners={corners} robots={robots} goals={goals} "
        f"ball={ball} ready={ready} ({NOTE})"
    )
