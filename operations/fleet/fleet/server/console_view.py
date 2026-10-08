"""Presentation-only values exposed by the Fleet console."""

from __future__ import annotations

import asyncio
import copy
import math
from dataclasses import dataclass
from typing import Optional

import httpx

from fleet.swarm.transport import RobotApiError

# D-499: plain HTTP against a TLS-only CORE. Do not add SSLError or ConnectError here.
_PROTOCOL = (httpx.RemoteProtocolError,)


class TripAware:
    """D-494 5: ``trip_busy(robot_id)`` is True while the trip loop drives that robot.

    ``trip_guard.install_trip_guard`` replaces it on the console instance; a trip robot never
    yields (``_make_room`` finds it no bay) and is never a reassignment candidate. It also
    wraps the console's motion and stop methods per instance (goal, formation_*,
    line_follow_mode, cancel, estop_all): call them on the instance, not on the class.
    """

    @staticmethod
    def trip_busy(robot_id: str) -> bool:
        return False


class CapabilityDisplay:
    """Keep presentation readback bounded without changing dispatch admission."""

    def __init__(self, clients, clock, *, read_method="capabilities", schema=None):
        self.clients, self.clock = clients, clock
        self.read_method = read_method
        self.schema = schema
        self.cache = {}
        self.identities = {}
        self.pending = {}

    def invalidate(self, robot_id):
        self.cache.pop(robot_id, None)
        self.identities.pop(robot_id, None)
        task = self.pending.pop(robot_id, None)
        if task is not None:
            task.cancel()

    async def shown(self, robot_id, wait_s=0.05):
        client = self.clients.get(robot_id)
        if self.identities.get(robot_id) is not client:
            self.invalidate(robot_id)
            self.identities[robot_id] = client
        cached = self.cache.get(robot_id)
        if cached is not None and self.clock() - cached[0] < 5.0:
            return copy.deepcopy(cached[1])
        if client is None:
            return None
        task = self.pending.get(robot_id)
        if task is None:
            task = asyncio.create_task(self._refresh(robot_id, client))
            self.pending[robot_id] = task
        await asyncio.wait({task}, timeout=wait_s)
        cached = self.cache.get(robot_id)
        if self.clients.get(robot_id) is not client or cached is None:
            return None
        return copy.deepcopy(cached[1]) if self.clock() - cached[0] < 5.0 else None

    def age(self, robot_id):
        if self.identities.get(robot_id) is not self.clients.get(robot_id):
            return None
        cached = self.cache.get(robot_id)
        if cached is None or cached[1] is None or self.clock() - cached[0] >= 5.0:
            return None
        return round(max(0.0, self.clock() - cached[0]), 3)

    async def _refresh(self, robot_id, client):
        try:
            try:
                caps = await getattr(client, self.read_method)()
                if self.schema is not None:
                    caps = self.schema.model_validate(caps).model_dump(mode="json")
            except Exception:
                caps = None
            if self.clients.get(robot_id) is client:
                shown = copy.deepcopy(caps) if isinstance(caps, dict) else None
                self.cache[robot_id] = (self.clock(), shown)
                self.identities[robot_id] = client
        finally:
            if self.pending.get(robot_id) is asyncio.current_task():
                self.pending.pop(robot_id)

    async def aclose(self):
        tasks = list(self.pending.values())
        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)


@dataclass(frozen=True)
class TripCaps:
    """D-494 1: what a robot allows a Fleet trip (its rosy.controls/1 base_velocity)."""

    kind: str
    modes: frozenset
    max_speed: float
    #: D-495: the robot can turn at a junction on its own (bounded turn); absent means no.
    junction_turn: bool = False
    #: D-507 9: the map the robot's site floor declaration covers; None when absent (older CORE) or null.
    site_floor_map_id: Optional[str] = None
    #: D-507 2: CORE takes the junction expectation fields (map_id, expect_in_m, ...); absent means no.
    junction_pivot: bool = False
    #: D-507 addendum: CORE takes action ``bend`` (a site-map bend on odometry); absent means no.
    lane_bend: bool = False


def trip_caps(capabilities) -> Optional[TripCaps]:
    """The base's trip fields, or None for an older image or a malformed descriptor.

    Read field by field: a consumer ignores fields and drive modes it does not know
    (rosy.controls/1), so an unknown mode is dropped, not a reason to distrust the rest.
    """
    controls = capabilities.get("controls") if isinstance(capabilities, dict) else None
    items = controls.get("items") if isinstance(controls, dict) else None
    for item in items if isinstance(items, list) else ():
        if not isinstance(item, dict) or item.get("kind") != "base_velocity":
            continue
        kind, modes, speed = item.get("robot_kind"), item.get("drive_modes"), item.get("trip_max_linear")
        if (isinstance(kind, str) and kind and isinstance(modes, list)
                and isinstance(speed, (int, float)) and not isinstance(speed, bool)
                and math.isfinite(speed) and speed >= 0):
            known = frozenset(mode for mode in modes if mode in ("lane", "free"))
            floor = item.get("site_floor_map_id")
            return TripCaps(kind, known, float(speed), item.get("junction_turn") is True,
                            site_floor_map_id=floor if isinstance(floor, str) else None,
                            junction_pivot=item.get("junction_pivot") is True,
                            lane_bend=item.get("lane_bend") is True)
    return None


_INTERNAL_MISSION_KEYS = ("route", "settled_ticks")
STREAM_STALE_AFTER_S = 1.0
STREAM_RATE_FLOOR_HZ = 2.0


def _stream_evidence(age_s: Optional[float], *, connected: bool,
                     error: Optional[str], source: str,
                     rate_hz: Optional[float] = None, sample_count: int = 0) -> dict:
    """Judge relay observations on the server; send age is not robot receipt."""
    if error or not connected:
        state, reason = "disconnected", "stream_error" if error else "transport_down"
    elif age_s is None:
        state, reason = "unavailable", "no_sample"
    elif age_s > STREAM_STALE_AFTER_S:
        state, reason = "delayed", "sample_too_old"
    elif sample_count >= 2 and rate_hz is not None and rate_hz < STREAM_RATE_FLOOR_HZ:
        state, reason = "delayed", "rate_below_floor"
    else:
        state, reason = "fresh", "sample_within_limit"
    return {"state": state, "age_s": age_s, "reason": reason,
            "stale_after_s": STREAM_STALE_AFTER_S, "source": source}


def _formation_stream_evidence(stats, leader: str, assignment) -> dict:
    if stats is None:
        return {}
    evidence = {
        leader: _stream_evidence(
            stats.leader_age_s, connected=stats.leader_last_error is None,
            error=stats.leader_last_error, source="leader_rx",
            rate_hz=stats.leader_rx_hz, sample_count=stats.leader_frames,
        )
    }
    for rid in assignment:
        evidence[rid] = _stream_evidence(
            stats.follower_last_tx_age_s.get(rid),
            connected=stats.follower_connected.get(rid) is True,
            error=stats.follower_last_error.get(rid), source="follower_tx",
            rate_hz=stats.follower_tx_hz.get(rid),
            sample_count=stats.follower_tx.get(rid, 0),
        )
    return evidence


def _shown(mission: Optional[dict]) -> Optional[dict]:
    if mission is None:
        return None
    return {k: v for k, v in mission.items() if k not in _INTERNAL_MISSION_KEYS}


def _error_of(exc: BaseException) -> dict:
    """Show a robot refusal separately from a reachability failure."""
    if isinstance(exc, RobotApiError):
        return {"reachable": True, "code": exc.code, "message": str(exc)}
    return {"reachable": False, "code": type(exc).__name__, "message": str(exc) or type(exc).__name__}


def classify_link(exc: BaseException | None, *, scheme: str,
                  address_status: str | None) -> str | None:
    """D-499 robot link class: a closed link word, or None when the row must omit `link`.
    The browser reads the returned word and never an exception name."""
    if exc is None:
        return "up"
    if address_status == "seen_at_other_address":
        return "moved"
    if isinstance(exc, RobotApiError):
        if exc.status == 401:
            return "tls-refused"
        return None
    if scheme.lower() == "http" and isinstance(exc, _PROTOCOL):
        return "protocol"
    return "unreachable"
