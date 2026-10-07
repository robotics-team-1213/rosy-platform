"""D-472 LED identity: ask one robot to blink, let Vision find the blob, keep the binding.

One request at a time, at most ``window_s`` (6 s), only for a moving robot without a
confirmed identity. Fleet calls the robot's CORE ``POST /host/lamp/identify`` (the robot's
own colour; rosy-face may refuse), names the window and colour to every Vision source that
watches that robot (``identity_challenge`` in the detections config), and takes the first
``matched`` verdict whose revisions are current. The binding then follows the nearest
anonymous detection of that source frame by frame (addendum 4) and drops to UNKNOWN when:
no continuation for ``track_lost_s`` (lost, occluded, merged), another detection within
``overlap_m`` (0.30 m, D-457 gate), a map or calibration revision change on that source,
or ``identity_ttl_s`` since confirmation.

Use (addendum 3): ``confirmed_track_pose`` is a D-511 lane-compliance *input* and a console
display. It is never a MapPoseService arbitrated pose, a trip input, an initialpose or a
command (test_boundaries.py). Nothing here moves a robot.
"""

from __future__ import annotations

import asyncio
import math
import time
from dataclasses import dataclass, field
from typing import Any, Callable, Mapping, Optional

LAMP_IDENTIFY_COLORS = ("blue", "amber")  # CORE LampIdentifyRequest.color values (D-472 4)


class IdentityError(Exception):
    def __init__(self, status_code: int, code: str, message: str) -> None:
        super().__init__(message)
        self.status_code = status_code
        self.code = code


@dataclass(frozen=True)
class IdentityConfig:
    """Site settings (sightings YAML ``identity:``). Values are provisional until measured."""

    window_s: float = 6.0            # D-472 4: request to end of blink
    verdict_grace_s: float = 2.0     # Vision answers after the window closes
    identity_ttl_s: float = 60.0     # addendum 4: site sets it after measurement
    overlap_m: float = 0.30          # D-457 gate
    track_step_m: float = 0.25       # one detection frame's continuation distance
    track_lost_s: float = 1.0
    moving_linear_mps: float = 0.02
    moving_angular_rps: float = 0.1
    retry_s: float = 10.0            # CORE lamp cooldown (HW_TEST_COOLDOWN_S)
    auto_request: bool = False       # off until the ceiling_north LED measurement passes

    def __post_init__(self) -> None:
        numbers = (self.window_s, self.verdict_grace_s, self.identity_ttl_s, self.overlap_m,
                   self.track_step_m, self.track_lost_s, self.moving_linear_mps,
                   self.moving_angular_rps, self.retry_s)
        if not all(isinstance(v, (int, float)) and not isinstance(v, bool) and math.isfinite(v) and v > 0
                   for v in numbers):
            raise ValueError("identity settings must be positive numbers")
        if self.window_s > 6.0:
            raise ValueError("identity window_s must be at most 6 s (D-472 4)")
        if not isinstance(self.auto_request, bool):
            raise ValueError("identity auto_request must be true or false")

    @classmethod
    def from_mapping(cls, raw: Optional[Mapping]) -> "IdentityConfig":
        if raw is None:
            return cls()
        if not isinstance(raw, Mapping) or set(raw) - set(cls.__dataclass_fields__):
            raise ValueError("identity config has unknown fields")
        return cls(**raw)


@dataclass
class _Pending:
    robot_id: str
    request_id: str
    color: str
    sources: tuple[str, ...]
    not_before: float
    not_after: float


@dataclass
class _Binding:
    robot_id: str
    source_id: str
    map_id: str
    calibration_revision: str
    x: float
    y: float
    seen_at: float        # capture time of the last continuing detection
    confirmed_at: float
    evidence: dict = field(default_factory=dict)


class IdentityService:
    def __init__(self, clients: Callable[[], Mapping[str, Any]], *, tracking=None,
                 config: IdentityConfig = IdentityConfig(), clock: Callable[[], float] = time.time) -> None:
        self._clients = clients
        self.tracking = tracking
        self.config = config
        self._clock = clock
        self._lock = asyncio.Lock()
        self._pending: Optional[_Pending] = None
        self._bindings: dict[str, _Binding] = {}
        self._last: dict[str, dict] = {}       # robot_id -> last outcome (readback)
        self._asked_at: dict[str, float] = {}

    # --- request ---------------------------------------------------------------------

    def busy(self) -> bool:
        pending = self._pending
        return pending is not None and self._clock() <= pending.not_after + self.config.verdict_grace_s

    def moving(self, robot_id: str) -> bool:
        state = None if self.tracking is None else self.tracking.robot_state(robot_id)
        velocity = (state or {}).get("velocity")
        if not isinstance(velocity, Mapping):
            return False
        try:
            linear, angular = abs(float(velocity.get("linear", 0.0))), abs(float(velocity.get("angular", 0.0)))
        except (TypeError, ValueError):
            return False
        return linear >= self.config.moving_linear_mps or angular >= self.config.moving_angular_rps

    async def request(self, robot_id: str, color: Optional[str] = None) -> dict:
        client = self._clients().get(robot_id)
        if client is None:
            raise IdentityError(404, "UNKNOWN_ROBOT", robot_id)
        async with self._lock:
            if self.busy():
                raise IdentityError(409, "IDENTIFY_BUSY", "다른 로봇의 LED 확인이 끝날 때까지 기다리세요")
            if self.confirmed_track_pose(robot_id)["state"] == "CONFIRMED":
                raise IdentityError(409, "IDENTIFY_ALREADY_CONFIRMED", "이미 확인된 트랙이 있습니다")
            if not self.moving(robot_id):
                raise IdentityError(409, "IDENTIFY_NOT_MOVING", "움직이는 로봇에만 LED 확인을 요청합니다")
            started = self._clock()
            self._asked_at[robot_id] = started
            # None: the robot's own configured colour (CORE lamp_identify.color / D-472 4 default).
            result = await client.identify_lamp(color)
            if not isinstance(result, Mapping):
                result = {}
            color = result.get("color")
            if result.get("accepted") is not True or color not in LAMP_IDENTIFY_COLORS:
                self._last[robot_id] = {"state": "UNKNOWN", "reason": "not_accepted", "at": started}
                raise IdentityError(502, "IDENTIFY_NOT_ACCEPTED", "로봇이 LED 확인을 수락하지 않았습니다")
            sources = () if self.tracking is None else tuple(
                s.source_id for s in self.tracking.sources if robot_id in s.robot_ids)
            self._pending = _Pending(robot_id, str(result.get("request_id")), color, sources,
                                     started, started + self.config.window_s)
            self._last[robot_id] = {"state": "PENDING", "reason": None, "at": started}
            return {"robot_id": robot_id, "request_id": self._pending.request_id, "color": color,
                    "not_after": self._pending.not_after, "sources": list(sources),
                    "state": "pending_visual_confirmation"}

    async def tick(self) -> Optional[dict]:
        """Auto mode: ask the next moving robot without a confirmed identity (sorted, one at a time)."""
        if not self.config.auto_request or self.busy():
            return None
        now = self._clock()
        for robot_id in sorted(self._clients()):
            if (now - self._asked_at.get(robot_id, -math.inf) < self.config.retry_s
                    or not self.moving(robot_id)
                    or self.confirmed_track_pose(robot_id)["state"] == "CONFIRMED"):
                continue
            try:
                return await self.request(robot_id)
            except IdentityError:
                continue
            except Exception:  # a robot that is down is asked again after retry_s
                continue
        return None

    async def run(self, interval_s: float = 1.0) -> None:
        while True:
            await self.tick()
            await asyncio.sleep(interval_s)

    # --- Vision side -----------------------------------------------------------------

    def challenge_for(self, source_id: str) -> Optional[dict]:
        pending = self._pending
        if pending is None or source_id not in pending.sources or not self.busy():
            return None
        return {"request_id": pending.request_id, "color": pending.color,
                "not_before": pending.not_before, "not_after": pending.not_after}

    def accept_verdict(self, source, body: Mapping) -> dict:
        pending = self._pending
        if pending is None or body.get("request_id") != pending.request_id or not self.busy():
            raise IdentityError(409, "IDENTIFY_NOT_PENDING", "no open identity request with this id")
        if source.source_id not in pending.sources or body.get("map_id") != source.map_id:
            raise IdentityError(409, "IDENTIFY_SOURCE_MISMATCH", "this source was not asked or is on another map")
        robot_id = pending.robot_id
        if body.get("state") != "matched":
            if self._last.get(robot_id, {}).get("state") == "PENDING":
                self._last[robot_id] = {"state": "UNKNOWN", "reason": body.get("reason"),
                                        "at": self._clock(), "source_id": source.source_id}
            return {"robot_id": robot_id, "state": "UNKNOWN", "reason": body.get("reason")}
        captured_at = body.get("captured_at")
        if (isinstance(captured_at, bool) or not isinstance(captured_at, (int, float))
                or not pending.not_before <= captured_at <= pending.not_after):
            raise IdentityError(422, "IDENTIFY_BAD_VERDICT", "matched verdict must lie in the request window")
        revision = body.get("calibration_revision")
        latest = self.tracking.latest(source.source_id)
        if latest is None or latest.calibration_revision != revision or latest.map_id != source.map_id:
            return self._unknown(robot_id, "calibration_changed", source.source_id)
        try:
            x, y = float(body["x"]), float(body["y"])
        except (KeyError, TypeError, ValueError):
            raise IdentityError(422, "IDENTIFY_BAD_VERDICT", "matched verdict needs x and y") from None
        if not (math.isfinite(x) and math.isfinite(y)):
            raise IdentityError(422, "IDENTIFY_BAD_VERDICT", "matched verdict needs finite x and y")
        now = self._clock()
        found = self._continue(latest, x, y)
        if isinstance(found, str):
            return self._unknown(robot_id, found, source.source_id)
        for other in self._bindings.values():
            if other.robot_id != robot_id and other.source_id == source.source_id and math.hypot(
                    other.x - found[0], other.y - found[1]) <= self.config.overlap_m:
                return self._unknown(robot_id, "overlap", source.source_id)
        self._bindings[robot_id] = _Binding(robot_id, source.source_id, source.map_id, revision,
                                            found[0], found[1], latest.captured_at, now,
                                            dict(body.get("evidence") or {}))
        self._last[robot_id] = {"state": "CONFIRMED", "reason": None, "at": now, "source_id": source.source_id}
        self._pending = None  # done: the next robot may be asked
        return {"robot_id": robot_id, "state": "CONFIRMED", "source_id": source.source_id}

    def on_detections(self, source_id: str, payload) -> None:
        """Follow every binding on this source to its continuing detection, or drop it."""
        for robot_id, binding in list(self._bindings.items()):
            if binding.source_id != source_id:
                continue
            if payload.map_id != binding.map_id or payload.calibration_revision != binding.calibration_revision:
                self._drop(robot_id, "calibration_changed")
                continue
            found = self._continue(payload, binding.x, binding.y)
            if found == "overlap":
                self._drop(robot_id, "overlap")
            elif isinstance(found, tuple):
                binding.x, binding.y, binding.seen_at = found[0], found[1], payload.captured_at
        # Review 2026-10-08: A's blob hidden, B's within track_step_m of A's last position -> A
        # would follow B. Two bindings within overlap_m can no longer tell who is who: drop both.
        followed = [b for b in self._bindings.values() if b.source_id == source_id]
        crowded: set[str] = set()
        for i, first in enumerate(followed):
            for second in followed[i + 1:]:
                if math.hypot(first.x - second.x, first.y - second.y) <= self.config.overlap_m:
                    crowded |= {first.robot_id, second.robot_id}
        for robot_id in sorted(crowded):
            self._drop(robot_id, "overlap")

    def _continue(self, payload, x: float, y: float):
        """(x, y) of the one anonymous detection continuing (x, y), or a reason string."""
        if payload.status != "OK":
            return "track_lost"
        seen = [(d.x, d.y) for d in payload.detections if d.marker_id is None]
        near = sorted((math.hypot(dx - x, dy - y), dx, dy) for dx, dy in seen)
        if not near or near[0][0] > self.config.track_step_m:
            return "track_lost"
        _, cx, cy = near[0]
        if any(math.hypot(dx - cx, dy - cy) <= self.config.overlap_m for _, dx, dy in near[1:]):
            return "overlap"
        return cx, cy

    def _unknown(self, robot_id: str, reason: str, source_id: str) -> dict:
        self._last[robot_id] = {"state": "UNKNOWN", "reason": reason, "at": self._clock(), "source_id": source_id}
        return {"robot_id": robot_id, "state": "UNKNOWN", "reason": reason}

    def _drop(self, robot_id: str, reason: str) -> None:
        binding = self._bindings.pop(robot_id, None)
        if binding is not None:
            self._unknown(robot_id, reason, binding.source_id)

    # --- readback (D-511 input) ------------------------------------------------------

    def confirmed_track_pose(self, robot_id: str) -> dict:
        """Map-frame pose of the robot's confirmed track, or UNKNOWN with the reason.

        Observation only (addendum 3): D-511 lane compliance and the console. ``yaw`` is None:
        the blob tracker reports no heading.
        """
        now = self._clock()
        binding = self._bindings.get(robot_id)
        if binding is not None:
            if now - binding.confirmed_at > self.config.identity_ttl_s:
                self._drop(robot_id, "ttl")
            elif now - binding.seen_at > self.config.track_lost_s:
                self._drop(robot_id, "track_lost")
            elif self.tracking is not None and not self._source_current(binding):
                self._drop(robot_id, "calibration_changed")
        binding = self._bindings.get(robot_id)
        if binding is None:
            last = self._last.get(robot_id, {})
            return {"robot_id": robot_id, "state": "UNKNOWN", "reason": last.get("reason"),
                    "x": None, "y": None, "yaw": None, "age_s": None, "source_id": last.get("source_id"),
                    "map_id": None, "calibration_revision": None, "confirmed_at": None,
                    "use": "observation-only"}
        return {"robot_id": robot_id, "state": "CONFIRMED", "reason": None,
                "x": binding.x, "y": binding.y, "yaw": None, "age_s": round(max(0.0, now - binding.seen_at), 3),
                "source_id": binding.source_id, "map_id": binding.map_id,
                "calibration_revision": binding.calibration_revision,
                "confirmed_at": binding.confirmed_at, "use": "observation-only"}

    def _source_current(self, binding: _Binding) -> bool:
        source = next((s for s in self.tracking.sources if s.source_id == binding.source_id), None)
        return (source is not None and source.map_id == binding.map_id
                and binding.calibration_revision in self.tracking.revisions(source))

    def snapshot(self) -> dict:
        pending = self._pending if self.busy() else None
        robots = sorted(set(self._clients()) | set(self._bindings) | set(self._last))
        return {
            "ts": self._clock(),
            "use": "observation-only",
            "pending": None if pending is None else {
                "robot_id": pending.robot_id, "request_id": pending.request_id, "color": pending.color,
                "sources": list(pending.sources), "not_before": pending.not_before,
                "not_after": pending.not_after},
            "robots": [{**self.confirmed_track_pose(rid), "last": self._last.get(rid)} for rid in robots],
            "config": {"window_s": self.config.window_s, "identity_ttl_s": self.config.identity_ttl_s,
                       "overlap_m": self.config.overlap_m, "auto_request": self.config.auto_request},
        }
