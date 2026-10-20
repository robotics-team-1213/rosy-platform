"""D-494 3: feed accepted sightings and robot `odom_pose` into one map pose tracker per robot.

Sightings come only from `SightingService.accept` (source token bound to the robot id, lease,
order) and, when a map id provider is given, only for the active site map frame. Odom comes from
every state snapshot the console reads (hub heartbeat or REST) and from `refresh`.
`arbitrated_pose` is for the trip loop (D-494 5) and the D-511 lane-compliance monitor; `/route`, D-395 and traffic keep
`FleetConsole.trusted_map_pose`. D-457 tracking is not an input. D-593: a named operator's map
pin (`POST /api/fleet/robots/{id}/map-pin`) is the other anchor; it is a site map event.
"""

from __future__ import annotations

import asyncio
import logging
import math
import time
from dataclasses import asdict
from typing import Awaitable, Callable, Iterable, Mapping, Optional

import httpx
from fastapi import Depends, HTTPException
from pydantic import BaseModel, ConfigDict, Field

from fleet.hub.hub import HubError
from rosy.world.state.projections.map_pose import (MapPose, MapPoseConfig, MapPoseTracker,
                                         odom_from_snapshot, sighting_from_row)
from fleet.swarm.transport import RobotApiError

#: `refresh` (hub snapshot when fresh, else REST) shares a read that started less than this ago.
REFRESH_FRESH_S = 0.2
#: D-760 8: the trip loop's age for the shared REST read, under its 0.5 s period, so a read before a
#: link loss is never handed out after it and a robot is read at most 1/0.45 times a second.
TRIP_READ_AGE_S = 0.45

logger = logging.getLogger("fleet.map_pose")


class MapPoseService:
    def __init__(self, robot_ids: Callable[[], Iterable[str]], *,
                 config: MapPoseConfig = MapPoseConfig(),
                 gather: Optional[Callable[[str], Awaitable[Optional[Mapping]]]] = None,
                 gather_rest: Optional[Callable[[str], Awaitable[Optional[Mapping]]]] = None,
                 map_id: Optional[Callable[[], Optional[str]]] = None,
                 source_map_ids: Iterable[str] = (),
                 client_identity=None,
                 wall: Callable[[], float] = time.time,
                 clock: Callable[[], float] = time.monotonic) -> None:
        self.config = config
        self._robot_ids = robot_ids
        self._gather = gather              # hub snapshot when fresh, else REST
        self._gather_rest = gather_rest    # always the robot's REST state (trip loop)
        self._client_identity = client_identity
        #: The active site map frame id; None (or no provider) accepts any sighting map id.
        self._map_id = map_id
        self._bad_snapshot: set[str] = set()
        self._source_map_ids = frozenset(source_map_ids)
        self._warned_map_ids: set[str] = set()
        self._wall = wall           # sighting captured_at and odom stamps are UTC epoch seconds
        self._clock = clock         # D-760 8: a read's age, from its start
        self._trackers: dict[str, MapPoseTracker] = {}
        #: (robot_id, force_rest) -> the read in flight (task, number), the last read (start, number, state)
        #: and the number of reads started; hub and REST reads never share.
        self._refreshing: dict[tuple[str, bool], tuple[asyncio.Future, int]] = {}
        self._kept: dict[tuple[str, bool], tuple[float, int, tuple]] = {}
        self._numbers: dict[tuple[str, bool], int] = {}
        from fleet.server.map_pose_scope import MapPoseScopes
        self._source_scopes = MapPoseScopes(self)

    def begin_source_scope(self, robot_id, *, boot_id, odom_epoch, client):
        """Trusted, opt-in source declaration after native identity verification; no network API."""
        return self._source_scopes.begin(robot_id, boot_id=boot_id, odom_epoch=odom_epoch, client=client)

    def observe_qualified_state(self, scope, state):
        return self._source_scopes.observe(scope, state)

    def qualified_pose(self, scope):
        return self._source_scopes.pose(scope)

    def retire_source_scope(self, scope):
        self._source_scopes.retire(scope)

    def active_map_id(self) -> Optional[str]:
        """The active site map frame id; warns once per id that no sighting source reports."""
        active = self._map_id() if self._map_id is not None else None
        if (active is not None and self._source_map_ids and active not in self._source_map_ids
                and active not in self._warned_map_ids):
            self._warned_map_ids.add(active)
            logger.warning("map pose: active site map id %r matches no sighting source map_id %s; "
                           "every sighting is filtered and trip map poses stay UNKNOWN",
                           active, sorted(self._source_map_ids))
        return active

    def knows(self, robot_id: str) -> bool:
        return robot_id in set(self._robot_ids())

    def _tracker(self, robot_id: str) -> Optional[MapPoseTracker]:
        roster = set(self._robot_ids())
        self._source_scopes.prune(roster)
        for gone in set(self._trackers) - roster:     # a robot that left starts over if it returns
            del self._trackers[gone]
        for key in [key for key in self._kept if key[0] not in roster]:   # and its kept reads
            del self._kept[key]
        if robot_id not in roster:
            return None
        tracker = self._trackers.get(robot_id)
        if tracker is None:
            tracker = self._trackers[robot_id] = MapPoseTracker(robot_id, self.config)
        return tracker

    def observe_sighting(self, row: Mapping) -> None:
        sighting = sighting_from_row(row)
        if sighting is None:
            return
        if not self._source_scopes.sighting(sighting):
            return
        tracker = self._tracker(sighting.robot_id)
        if tracker is not None:
            tracker.add_sighting(sighting, self._wall(), self.active_map_id())

    def observe_state(self, robot_id: str, state: Optional[Mapping]) -> None:
        try:
            self._observe_state(robot_id, state)
        except Exception:           # a bad snapshot is logged once per robot, never raised
            if robot_id not in self._bad_snapshot:
                self._bad_snapshot.add(robot_id)
                logger.exception("map pose: snapshot of %s not usable", robot_id)

    def _observe_state(self, robot_id: str, state: Optional[Mapping]) -> None:
        if not self._source_scopes.unqualified(robot_id):
            return
        if not isinstance(state, Mapping) or state.get("odom_pose") is None:
            return                  # a robot before D-494 2: nothing to count
        tracker = self._tracker(robot_id)
        if tracker is None:
            return
        sample = odom_from_snapshot(state)
        if sample is None:
            tracker.refuse_odom("malformed")
        else:
            tracker.add_odom(sample, self._wall())

    async def state(self, robot_id: str, max_age_s: float = TRIP_READ_AGE_S, after: int = 0) -> Mapping:
        """D-760 8: the robot's REST state, one read per robot shared by every Fleet loop (app.py
        sets it as the console's `read_state`). A read that started within `max_age_s` (Fleet
        monotonic time) and is numbered above `after` (`read_number`) is returned; else the caller
        joins the read in flight or starts one. A read in flight numbered `after` or below is
        waited out first (review: the trip loop's read starts after its last step, send or loss).
        A failed read keeps nothing and raises its own exception to every waiter."""
        return await self._read((robot_id, True), self._gather_rest, max_age_s, after)

    async def state_with_source(self, robot_id, max_age_s=TRIP_READ_AGE_S, after=0):
        if self._client_identity is None:
            raise ValueError('MAP_STATE_TRANSPORT_IDENTITY_REQUIRED')
        return await self._read((robot_id, True), self._gather_rest, max_age_s, after, with_source=True)

    def read_number(self, robot_id: str) -> int:
        """The number of the robot's newest REST read started so far (0: none)."""
        return self._numbers.get((robot_id, True), 0)

    async def refresh(self, robot_id: str, *, force_rest: bool = False,
                      max_age_s: float = TRIP_READ_AGE_S, after: int = 0) -> None:
        """Read the robot's state and feed its odom: the hub snapshot when fresh, else REST, shared
        for 0.2 s. `force_rest` (the trip loop, lane compliance, the trail anchor) is `state`."""
        gather = self._gather_rest if force_rest else self._gather
        if gather is not None and self._tracker(robot_id) is not None:
            await self._read((robot_id, force_rest), gather, max_age_s if force_rest else REFRESH_FRESH_S,
                             after if force_rest else 0)

    def _read_result(self, key, pair, with_source):
        state, receipt = pair
        if receipt is not None and (receipt.client is not self._client_identity(key[0])
                or receipt.generation != self._source_scopes.generation(key[0])):
            raise ValueError('MAP_STATE_SOURCE_CHANGED')
        if with_source and receipt is None:
            raise ValueError('MAP_STATE_TRANSPORT_IDENTITY_REQUIRED')
        return receipt if with_source else state

    async def _read(self, key: tuple[str, bool], gather, max_age_s: float, after: int, with_source=False):
        while True:
            kept = self._kept.get(key)
            if kept is not None and kept[1] > after and 0 <= self._clock() - kept[0] <= max_age_s:
                try:
                    return self._read_result(key, kept[2], with_source)
                except ValueError:
                    self._kept.pop(key, None)
            running = self._refreshing.get(key)
            if running is not None and running[1] <= after:
                await asyncio.wait([running[0]])     # its outcome is its own waiters'; then a new read
                continue
            if running is None:
                number = self._numbers[key] = self._numbers.get(key, 0) + 1
                task = asyncio.ensure_future(self._fetch(key, gather, self._clock(), number))
                running = self._refreshing[key] = (task, number)
                task.add_done_callback(lambda done: self._refresh_done(key, done))
            return self._read_result(key, await asyncio.shield(running[0]), with_source)

    async def _fetch(self, key: tuple[str, bool], gather, started: float, number: int) -> tuple:
        generation = self._source_scopes.generation(key[0])
        receipt = None
        if key[1] and self._client_identity is not None:
            from fleet.server.map_state_read import StateSourceRead
            state, receipt = await StateSourceRead.capture(self._client_identity(key[0]),
                generation=generation, number=number, started_mono=started)
        else:
            state = await gather(key[0])
        pair = (state, receipt)
        if self._source_scopes.unqualified(key[0], generation):
            self.observe_state(key[0], state)    # once per read: odom_stamp stays the snapshot's own
        # Sharing a REST receipt is separate from admitting it to the World tracker.
        if (generation == self._source_scopes.generation(key[0])
                and (self._source_scopes.unqualified(key[0]) or receipt is not None)):
            self._read_result(key, pair, False)
            self._kept[key] = (started, number, pair)
        return pair

    def _refresh_done(self, key: tuple, done: asyncio.Future) -> None:
        if self._refreshing.get(key, (None,))[0] is done:
            self._refreshing.pop(key)
        # Retrieved here so a read whose waiters were all cancelled never logs "never retrieved".
        if not done.cancelled() and done.exception() is not None:
            logger.debug("map pose: state read for %s failed: %r", key[0], done.exception())

    def moved(self, robot_id: str, min_m: float, min_deg: float) -> bool:
        """D-511 2: the robot's odom moved beyond the deadband within the last `max_odom_age_s`."""
        tracker = self._tracker(robot_id)
        return tracker is not None and tracker.moved_since(
            self._wall() - self.config.max_odom_age_s, min_m, math.radians(min_deg))

    def odom_to_map(self, robot_id: str):
        """D-581 trail anchor: the tracker's (map <- odom, newest odom, anchor captured_at, epoch)."""
        tracker = self._tracker(robot_id)
        return tracker.odom_to_map() if tracker is not None else None

    def survey_odom(self, robot_id: str):
        """D-655 relative survey evidence; never creates an operational map pose or pin."""
        tracker = self._tracker(robot_id)
        return tracker.survey_odom(self._wall()) if tracker is not None else None

    async def pin(self, robot_id: str, pose: tuple[float, float, float]
                  ) -> tuple[Optional[str], Optional[MapPose]]:
        """D-593: anchor the robot's map pose on an operator pin at its newest odom.

        Reads the robot's state first so the pin pairs with fresh odom. Returns (refusal code or
        None, the pose after the pin); (`UNKNOWN_ROBOT`, None) off the roster."""
        try:
            await self.refresh(robot_id, force_rest=True)
        except (HubError, RobotApiError, OSError, httpx.HTTPError, asyncio.TimeoutError):
            pass    # pinned against the last odom, which must still be fresh
        tracker = self._tracker(robot_id)
        if tracker is None:
            return "UNKNOWN_ROBOT", None
        now, active = self._wall(), self.active_map_id()
        refused = tracker.add_pin(pose, now, active)
        return refused, tracker.pose(now, active)

    def arbitrated_pose(self, robot_id: str) -> Optional[MapPose]:
        """The robot's map pose for trip execution and the D-511 lane-compliance monitor
        (D-511 2 widens D-494 3); None for a robot not on the roster."""
        tracker = self._tracker(robot_id)
        return tracker.pose(self._wall(), self.active_map_id()) if tracker is not None else None

    def stuck_pose(self, robot_id: str) -> Optional[dict]:
        """D-577 1: R3's pose input. `sourced` = a sighting ever reached this robot's tracker, so an
        UNKNOWN is a lost pose rather than "Fleet has no map pose for it"."""
        tracker = self._tracker(robot_id)
        if tracker is None:
            return None
        pose = tracker.pose(self._wall(), self.active_map_id())
        return {"state": pose.state, "age_s": pose.age_s, "sourced": tracker.sourced,
                "x": pose.x, "y": pose.y, "yaw": pose.yaw}   # D-577 남은 항목 4: peer bands on the map pose


def install_map_pose_routes(app, *, service: MapPoseService, read_guard) -> None:
    unknown = HTTPException(status_code=404, detail={"code": "UNKNOWN_ROBOT",
                                                     "message": "robot is not on the roster"})

    @app.get("/api/fleet/robots/{robot_id}/map-pose", dependencies=read_guard, tags=["fleet"])
    async def robot_map_pose(robot_id: str) -> dict:
        if not service.knows(robot_id):
            raise unknown
        try:
            await service.refresh(robot_id)
        except (HubError, RobotApiError, OSError, httpx.HTTPError, asyncio.TimeoutError):
            pass    # an unreachable robot reads its last odom, which goes UNKNOWN after 3 s
        pose = service.arbitrated_pose(robot_id)
        if pose is None:            # removed from the roster while the read was in flight
            raise unknown
        return {"robot_id": robot_id, **asdict(pose)}


class MapPinRequest(BaseModel):
    """D-593: the robot's map pose as the operator placed it (map frame, metres, yaw in radians)."""
    model_config = ConfigDict(extra="forbid")
    x: float = Field(ge=-1000.0, le=1000.0, allow_inf_nan=False)
    y: float = Field(ge=-1000.0, le=1000.0, allow_inf_nan=False)
    yaw: float = Field(ge=-2 * math.pi, le=2 * math.pi, allow_inf_nan=False)


def install_map_pin_route(app, *, service: MapPoseService, require_named_operator,
                          record_event: Callable[[str, str, dict], None],
                          busy: Callable[[str], bool] = lambda robot_id: False) -> None:
    """D-593: a named operator pins a robot's map pose; refused while that robot runs a trip."""

    def refuse(status: int, code: str, message: str) -> HTTPException:
        return HTTPException(status_code=status, detail={"code": code, "message": message})

    @app.post("/api/fleet/robots/{robot_id}/map-pin", tags=["fleet"])
    async def robot_map_pin(robot_id: str, body: MapPinRequest,
                            principal=Depends(require_named_operator)) -> dict:
        if not service.knows(robot_id):
            raise refuse(404, "UNKNOWN_ROBOT", "robot is not on the roster")
        if busy(robot_id):
            raise refuse(409, "MAP_PIN_TRIP_ACTIVE", "the robot is on a trip; stop it before pinning")
        before = service.arbitrated_pose(robot_id)
        refused, pose = await service.pin(robot_id, (body.x, body.y, body.yaw))
        if refused == "UNKNOWN_ROBOT":
            raise refuse(404, "UNKNOWN_ROBOT", "robot is not on the roster")
        if refused is not None:
            raise refuse(409, f"MAP_PIN_{refused}", "no fresh robot odom to pin against"
                         if refused == "ODOM_STALE" else "pin pose is not usable")
        record_event("map_pin", principal.principal_id, {
            "robot_id": robot_id, "x": body.x, "y": body.y, "yaw": body.yaw, "map_id": pose.map_id,
            "before": None if before is None else {
                "state": before.state, "anchor_source": before.anchor_source,
                "x": before.x, "y": before.y, "yaw": before.yaw}})
        logger.info("map pose: %s pinned by %s at (%.3f, %.3f, %.3f) map %s",
                    robot_id, principal.principal_id, body.x, body.y, body.yaw, pose.map_id)
        return {"robot_id": robot_id, **asdict(pose)}
