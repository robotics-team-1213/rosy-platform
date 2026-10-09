"""D-550 10: Fleet navigation goal leases — send ``lease_ttl_s`` and renew it (default off).

Kept out of ``console.py`` (size budget). ``GoalLeases`` is the console's ``robot_id -> lease``
table: ``{"state": "leased", "correlation_id", "ttl_s", "source", "task_id"}`` or
``{"state": "unbounded"}`` (leases on, robot without the capability: Rule M display).

One renewer per goal source (D-550 10), each only while its reason to move holds:

- ``operator`` (console goal, intent, D-463 route, queued release): the console loop, only while a
  named operator console sent ``POST /api/fleet/goal-lease/presence`` within the last ttl.
- ``dispatch`` (D-316 attempt): the console loop, only while that attempt is open in the task store.
- ``yield`` (bay goal of ``_make_room``): the console loop, only while that robot is still yielding.
- ``trip``: the trip loop, each step.

Renewal of a goal stops on a console cancel (also the internal route/trust/hold cancels), an
E-stop, or CORE's 409. Fleet stopping stops it all: CORE cancels each goal within ttl.
"""

from __future__ import annotations

import logging
import time
import uuid
from typing import Callable, Optional

logger = logging.getLogger("fleet.goal_lease")

SOURCES = ("operator", "dispatch", "yield", "trip")


def goal_lease_supported(caps: Optional[dict]) -> bool:
    """The robot's rosy.controls/1 base announces ``goal_lease: true``. An older CORE would
    ignore ``lease_ttl_s``, so without it a Fleet goal is unbounded."""
    items = (((caps or {}).get("controls") or {}).get("items") or []) if isinstance(caps, dict) else []
    return any(isinstance(item, dict) and item.get("kind") == "base_velocity"
               and item.get("goal_lease") is True for item in items)


class GoalLeases(dict):
    def __init__(self, ttl_s: float, clients: dict, clock: Callable[[], float] = time.monotonic,
                 yielding: Callable[[str], bool] = lambda _robot_id: False) -> None:
        super().__init__()
        #: ``fleet.goal_lease_ttl_s``; 0 = off: no lease field is ever sent, nothing is shown.
        self.ttl_s = ttl_s
        self._clients = clients  # the console's live roster dict
        self._clock = clock
        self._yielding = yielding
        #: ``(task_id, attempt_id) -> bool``: the D-316 attempt is still open. Set by app.py when
        #: there is a task store; without one a dispatch lease is never renewed (it expires).
        self.attempt_open: Optional[Callable[[str, str], bool]] = None
        self._present_at: Optional[float] = None

    def operator_present(self) -> None:
        """A named operator's console is open (``POST /api/fleet/goal-lease/presence``)."""
        self._present_at = self._clock()

    def view(self, robot_id: str, goal: Optional[dict]) -> Optional[dict]:
        """The console goal record with today's lease state (``goal_lease``); as is when none."""
        lease = self.get(robot_id)
        return goal if goal is None or lease is None else {**goal, "goal_lease": lease["state"]}

    async def send(self, robot_id: str, client, caps: Optional[dict], x: float, y: float, yaw: float,
                   correlation_id: Optional[str], source: Optional[str] = None,
                   task_id: Optional[str] = None) -> dict:
        """Send one navigation goal; leased with the capability (a lease is renewed by correlation
        id, so a goal without an attempt id gets one), otherwise exactly as before. ``source``
        defaults to ``dispatch`` with an attempt id, else ``operator``."""
        source = source or ("dispatch" if correlation_id is not None else "operator")
        if source not in SOURCES:
            raise ValueError(f"unknown goal lease source {source!r}")
        self.pop(robot_id, None)
        if self.ttl_s > 0 and goal_lease_supported(caps):
            correlation_id = correlation_id or f"fleet-lease-{uuid.uuid4().hex}"
            result = await client.navigation_goal(x, y, yaw, correlation_id=correlation_id,
                                                  lease_ttl_s=self.ttl_s)
            self[robot_id] = {"state": "leased", "correlation_id": correlation_id,
                              "ttl_s": self.ttl_s, "source": source, "task_id": task_id}
            return result
        if correlation_id is None:
            result = await client.navigation_goal(x, y, yaw)
        else:
            result = await client.navigation_goal(x, y, yaw, correlation_id=correlation_id)
        if self.ttl_s > 0:
            self[robot_id] = {"state": "unbounded"}
        return result

    async def cancel(self, robot_id: str, client) -> dict:
        """``navigation_cancel`` for the console: the lease stops first, whether the cancel lands or not."""
        self.pop(robot_id, None)
        return await client.navigation_cancel()

    def _due(self, robot_id: str, lease: dict, renewer: str) -> bool:
        source = lease["source"]
        if renewer == "trip":
            return source == "trip"
        if source == "operator":
            return self._present_at is not None and self._clock() - self._present_at <= self.ttl_s
        if source == "dispatch":
            check = self.attempt_open
            return (check is not None and lease["task_id"] is not None
                    and check(lease["task_id"], lease["correlation_id"]))
        if source == "yield":
            return self._yielding(robot_id)
        return False

    async def renew(self, renewer: str = "console", robot_id: Optional[str] = None) -> None:
        """Renew each leased goal of ``renewer`` (``console``: operator, dispatch and yield goals;
        ``trip``: trip goals; only ``robot_id`` when given) whose source still holds. A 409 means
        the goal ended on the robot (arrived, failed, cancelled, replaced, expired): renewal stops.
        Any other failure is left to CORE, which cancels the goal when its lease runs out."""
        for rid, lease in list(self.items()):
            if lease["state"] != "leased" or robot_id not in (None, rid):
                continue
            client = self._clients.get(rid)
            try:
                if client is None or not self._due(rid, lease, renewer):
                    continue
                await client.navigation_goal_lease(lease["correlation_id"], lease["ttl_s"])
            except Exception as exc:  # RobotApiError carries .status; no import (D-430 §3 rule 1)
                if getattr(exc, "status", None) == 409 and self.get(rid) is lease:
                    self.pop(rid, None)
                else:
                    logger.warning("goal lease renewal for %s failed: %s", rid, exc)
