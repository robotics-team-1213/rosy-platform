"""D-550 10: Fleet navigation goal leases — send ``lease_ttl_s`` and renew it (default off).

Kept out of ``console.py`` (size budget). ``GoalLeases`` is the console's
``robot_id -> lease`` table: ``{"state": "leased", "correlation_id", "ttl_s", "renewer"}`` or
``{"state": "unbounded"}`` (leases on, robot without the capability: Rule M display).
Renewers: ``"console"`` (operator, D-316 dispatch, yield bay goals; ``goal_lease_renew_loop``
every ttl/3) and ``"trip"`` (the trip loop, each step). Renewal of a goal stops on a console
cancel, an E-stop or CORE's 409; Fleet stopping stops it all and CORE cancels within ttl.
"""

from __future__ import annotations

import logging
import uuid
from typing import Optional

from fleet.swarm.transport import RobotApiError

logger = logging.getLogger("fleet.goal_lease")


def goal_lease_supported(caps: Optional[dict]) -> bool:
    """The robot's rosy.controls/1 base announces ``goal_lease: true``. An older CORE would
    ignore ``lease_ttl_s``, so without it a Fleet goal is unbounded."""
    items = (((caps or {}).get("controls") or {}).get("items") or []) if isinstance(caps, dict) else []
    return any(isinstance(item, dict) and item.get("kind") == "base_velocity"
               and item.get("goal_lease") is True for item in items)


class GoalLeases(dict):
    def __init__(self, ttl_s: float, clients: dict) -> None:
        super().__init__()
        #: ``fleet.goal_lease_ttl_s``; 0 = off: no lease field is ever sent, nothing is shown.
        self.ttl_s = ttl_s
        self._clients = clients  # the console's live roster dict

    def shown(self, robot_id: str) -> dict:
        """``{"goal_lease": state}`` for the console's goal record; ``{}`` while leases are off."""
        lease = self.get(robot_id)
        return {} if lease is None else {"goal_lease": lease["state"]}

    async def send(self, robot_id: str, client, caps: Optional[dict], x: float, y: float, yaw: float,
                   correlation_id: Optional[str], renewer: str = "console") -> dict:
        """Send one navigation goal; leased with the capability (a lease is renewed by correlation
        id, so a goal without an attempt id gets one), otherwise exactly as before."""
        self.pop(robot_id, None)
        if self.ttl_s > 0 and goal_lease_supported(caps):
            correlation_id = correlation_id or f"fleet-lease-{uuid.uuid4().hex}"
            result = await client.navigation_goal(x, y, yaw, correlation_id=correlation_id,
                                                  lease_ttl_s=self.ttl_s)
            self[robot_id] = {"state": "leased", "correlation_id": correlation_id,
                              "ttl_s": self.ttl_s, "renewer": renewer}
            return result
        if correlation_id is None:
            result = await client.navigation_goal(x, y, yaw)
        else:
            result = await client.navigation_goal(x, y, yaw, correlation_id=correlation_id)
        if self.ttl_s > 0:
            self[robot_id] = {"state": "unbounded"}
        return result

    async def renew(self, renewer: str = "console", robot_id: Optional[str] = None) -> None:
        """Renew each leased goal of ``renewer`` (only ``robot_id`` when given). A 409 means the
        goal ended on the robot (arrived, failed, cancelled, replaced, expired): renewal stops.
        Any other failure is left to CORE, which cancels the goal when its lease runs out."""
        for rid, lease in list(self.items()):
            if lease["state"] != "leased" or lease["renewer"] != renewer or robot_id not in (None, rid):
                continue
            client = self._clients.get(rid)
            if client is None:
                continue
            try:
                await client.navigation_goal_lease(lease["correlation_id"], lease["ttl_s"])
            except RobotApiError as exc:
                if exc.status == 409 and self.get(rid) is lease:
                    self.pop(rid, None)
                else:
                    logger.warning("goal lease renewal for %s failed: %s", rid, exc)
            except Exception as exc:
                logger.warning("goal lease renewal for %s failed: %s", rid, exc)
