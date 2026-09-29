"""The one owner of the site robot list: robots.yaml plus enrolled robots (D-352 5).

Adding or removing a robot changes, in one synchronous step, every copy the site
keeps: console clients/order/endpoints/REST tokens, hub clients and pairing tokens,
the task service's robot ids and the sighting service's known robots. Console
loops copy the order before awaiting, so a change never misaligns a gather.
"""

from __future__ import annotations

from typing import Any

from fleet.hub.hub import HubError
from fleet.swarm.robots import RobotEndpoint
from fleet.swarm.transport import RobotClient


class RosterConflict(HubError):
    """Removal is refused until the operator ends the robot's work first."""

    def __init__(self, code: str, message: str, task_ids: list[str] | None = None) -> None:
        super().__init__(code, message)
        self.task_ids = task_ids or []


class SiteRoster:
    def __init__(self, console, *, task_service=None, sightings=None) -> None:
        self._console = console
        self._task_service = task_service
        self._sightings = sightings
        self.static_ids = frozenset(console.robot_ids)

    @property
    def robot_ids(self) -> list[str]:
        return self._console.robot_ids

    def source_of(self, robot_id: str) -> str:
        return "file" if robot_id in self.static_ids else "enrolled"

    def _sync(self) -> None:
        ids = frozenset(self._console.robot_ids)
        if self._task_service is not None:
            self._task_service.robot_ids = ids
        if self._sightings is not None:
            self._sightings.known_robot_ids = ids

    def add(self, endpoint: RobotEndpoint, client: RobotClient, *, source: str = "enrolled") -> None:
        if source != "enrolled":
            raise ValueError("only enrolled robots join after start")
        if endpoint.robot_id in self.static_ids or endpoint.robot_id in self._console.robot_ids:
            raise HubError("ROBOT_ID_CONFLICT", f"{endpoint.robot_id} is already on the roster")
        self._console._add_robot(endpoint, client)
        self._sync()

    def removal_blockers(self, robot_id: str) -> RosterConflict | None:
        if robot_id in self._console._formation_members() or (
                robot_id == self._console._formation_leader
                and self._console._formation_members()):
            return RosterConflict("FORMATION_ACTIVE",
                                  f"{robot_id} is in the running formation; stop it first")
        if self._task_service is not None:
            task_ids = self._task_service.store.unfinished_task_ids(robot_id)
            if task_ids:
                return RosterConflict("ACTIVE_TASKS",
                                      f"{robot_id} has unfinished tasks; cancel them first",
                                      task_ids)
        return None

    async def remove(self, robot_id: str) -> None:
        if robot_id in self.static_ids:
            raise HubError("STATIC_ROBOT", f"{robot_id} comes from robots.yaml")
        if robot_id not in self._console.robot_ids:
            raise HubError("UNKNOWN_ROBOT", robot_id)
        blocker = self.removal_blockers(robot_id)
        if blocker is not None:
            raise blocker
        client = self._console._remove_robot(robot_id)
        self._sync()
        closer: Any = getattr(client, "aclose", None)
        if closer is not None:
            await closer()

    async def replace_endpoint(self, endpoint: RobotEndpoint, client: RobotClient) -> None:
        """Same robot, confirmed new pinned address (D-352 3 "move address")."""
        if endpoint.robot_id in self.static_ids or endpoint.robot_id not in self._console.robot_ids:
            raise HubError("UNKNOWN_ROBOT", endpoint.robot_id)
        old = self._console._replace_client(endpoint, client)
        closer: Any = getattr(old, "aclose", None)
        if closer is not None:
            await closer()
