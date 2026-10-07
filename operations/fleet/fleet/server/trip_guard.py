"""D-491 5: a robot on a running trip takes motion only from the trip loop.

Installed on the console by ``app.py`` so the safety-tagged ``console.py`` stays as it is:
``goal``, ``formation_start`` and ``line_follow_mode`` are wrapped on the instance, and
``trip_busy`` (``console_view.TripAware``) makes ``_make_room`` find no bay for a trip robot and
keeps it out of the degraded-capability reassignment. ``line_follow_mode(OFF)`` stays allowed:
it is a stop request, and it cancels the trip (``operator_line_follow_off``). Before a trip
starts, ``engaged`` names any console motion the robot already has.
"""

from __future__ import annotations

from typing import Optional

from fleet.hub.hub import HubError


def _busy(robot_ids) -> HubError:
    return HubError("TRIP_ROBOT_BUSY", f"{', '.join(robot_ids)} is on a running trip; cancel the trip first")


def install_trip_guard(console, runner) -> None:
    console.trip_busy = runner.robot_busy
    goal, formation_start, line_follow_mode = console.goal, console.formation_start, console.line_follow_mode

    async def guarded_goal(robot_id, *args, trip: bool = False, **kwargs):
        if not trip and runner.robot_busy(robot_id):
            raise _busy([robot_id])
        return await goal(robot_id, *args, **kwargs)

    async def guarded_formation_start(leader_id, *args, members=None, **kwargs):
        chosen = [leader_id, *(console.robot_ids if members is None else members)]
        busy = [robot_id for robot_id in dict.fromkeys(chosen) if runner.robot_busy(robot_id)]
        if busy:
            raise _busy(busy)
        return await formation_start(leader_id, *args, members=members, **kwargs)

    async def guarded_line_follow_mode(robot_id, mode):
        if runner.robot_busy(robot_id):
            if mode != "OFF":
                raise _busy([robot_id])
            result = await line_follow_mode(robot_id, mode)  # the operator's stop goes first
            await runner.cancel_robot(robot_id, "operator_line_follow_off")
            return result
        return await line_follow_mode(robot_id, mode)

    console.goal = guarded_goal
    console.formation_start = guarded_formation_start
    console.line_follow_mode = guarded_line_follow_mode


def engaged(console, robot_id: str) -> Optional[str]:
    """Why the robot already moves for someone else, or None (a trip start refuses then)."""
    if robot_id in console._goals and (console._seen.get(robot_id) or {}).get("navigation") == "NAVIGATING":
        return "goal"  # the console keeps the last goal after arrival; only a running one counts
    if robot_id in console._queued:
        return "queued"
    if robot_id in console._yielding:
        return "yielding"
    if robot_id in console._formation_members() or (
            console._formation_members() and robot_id == console._formation_leader):
        return "formation"
    return None


def release_queue(console, robot_id: str) -> None:
    """A free trip that ended leaves no console mission behind for its robot."""
    console._queued.pop(robot_id, None)
    console._goals.pop(robot_id, None)
