"""D-494 5: a robot on a running trip takes motion only from the trip loop; every stop ends it.

Installed on the console by ``app.py`` so the safety-tagged ``console.py`` stays as it is: the
motion and stop methods are replaced on the console instance (``console_view.TripAware``).

- Motion for a trip robot is refused with ``TRIP_ROBOT_BUSY``: ``goal`` (unless the trip loop
  sends it), ``formation_start``/``formation_reform``/``formation_resume``, ``line_follow_mode``
  other than ``OFF``.
- Stops are never refused and always run first; afterwards the trip ends ``canceled``:
  ``cancel`` (per robot, cancel-all, intent cancel) -> ``operator_cancel``, ``estop_all`` ->
  ``operator_estop``, ``line_follow_mode(OFF)`` -> ``operator_line_follow_off``.
- ``trip_busy`` makes ``_make_room`` find no bay for a trip robot and keeps it out of the
  degraded-capability reassignment. The trip loop's own halt keeps the methods bound before
  this wrapping (no recursion).

Before a trip starts, ``engaged`` names any console motion the robot already has.
"""

from __future__ import annotations

import logging
import time
from typing import Optional

from fleet.hub.hub import HubError

_LOG = logging.getLogger(__name__)

#: A console goal this recent counts as running even before the robot reports NAVIGATING.
GOAL_FRESH_S = 2.0


def _busy(robot_ids) -> HubError:
    return HubError("TRIP_ROBOT_BUSY", f"{', '.join(robot_ids)} is on a running trip; cancel the trip first")


def install_trip_guard(console, runner, *, clock=time.monotonic) -> None:
    console.trip_busy = runner.robot_busy
    console.trip_goal_sent_at = {}
    goal, cancel, estop_all = console.goal, console.cancel, console.estop_all
    formation_start, line_follow_mode = console.formation_start, console.line_follow_mode
    formation_reform, formation_resume = console.formation_reform, console.formation_resume

    def refuse(robot_ids) -> None:
        busy = [robot_id for robot_id in dict.fromkeys(robot_ids) if runner.robot_busy(robot_id)]
        if busy:
            raise _busy(busy)

    async def end_trip(robot_id, reason) -> None:
        """After a stop: a trip store failure is logged, never in place of the stop's result."""
        try:
            await runner.cancel_robot(robot_id, reason)
        except Exception:
            _LOG.exception("could not end the trip of %s after %s", robot_id, reason)

    def formation_robots() -> list:
        return [*console._formation_members(), *([console._formation_leader] if console._formation_leader else [])]

    async def guarded_goal(robot_id, *args, trip: bool = False, **kwargs):
        if not trip:
            refuse([robot_id])
        result = await goal(robot_id, *args, **kwargs)
        console.trip_goal_sent_at[robot_id] = clock()
        return result

    async def guarded_formation_start(leader_id, *args, members=None, **kwargs):
        refuse([leader_id, *(console.robot_ids if members is None else members)])
        return await formation_start(leader_id, *args, members=members, **kwargs)

    async def guarded_formation_reform(*args, **kwargs):
        refuse(formation_robots())
        return await formation_reform(*args, **kwargs)

    async def guarded_formation_resume(*args, **kwargs):
        refuse(formation_robots())
        return await formation_resume(*args, **kwargs)

    async def guarded_line_follow_mode(robot_id, mode):
        if not runner.robot_busy(robot_id):
            return await line_follow_mode(robot_id, mode)
        if mode != "OFF":
            raise _busy([robot_id])
        try:
            return await line_follow_mode(robot_id, mode)  # the operator's stop goes first
        finally:
            await end_trip(robot_id, "operator_line_follow_off")

    async def guarded_cancel(robot_id, *args, **kwargs):
        try:
            return await cancel(robot_id, *args, **kwargs)
        finally:
            await end_trip(robot_id, "operator_cancel")

    async def guarded_estop_all(*args, **kwargs):
        running = [view["robot_id"] for view in runner.open_trips()]
        try:
            return await estop_all(*args, **kwargs)
        finally:
            for robot_id in running:  # D-517 1: every robot's trip ends
                await end_trip(robot_id, "operator_estop")

    console.goal, console.cancel, console.estop_all = guarded_goal, guarded_cancel, guarded_estop_all
    console.formation_start, console.line_follow_mode = guarded_formation_start, guarded_line_follow_mode
    console.formation_reform, console.formation_resume = guarded_formation_reform, guarded_formation_resume


def engaged(console, robot_id: str, *, clock=time.monotonic) -> Optional[str]:
    """Why the robot already moves for someone else, or None (a trip start refuses then)."""
    if robot_id in console._goals:
        sent_at = getattr(console, "trip_goal_sent_at", {}).get(robot_id)
        navigating = (console._seen.get(robot_id) or {}).get("navigation") == "NAVIGATING"
        if navigating or (sent_at is not None and clock() - sent_at < GOAL_FRESH_S):
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
