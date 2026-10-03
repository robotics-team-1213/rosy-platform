"""관제 쪽 모음/흩뿌림. 최종 cmd_vel과 Image를 다루지 않는다 (D-59)."""

from __future__ import annotations

import hmac
import logging
import sqlite3
from typing import Optional, Sequence
from collections.abc import Callable, Mapping

from core_common.protocol.schemas import (
    Envelope,
    EnvelopeType,
    EventMessage,
    HeartbeatPayload,
    HelloPayload,
    PROTOCOL_VERSION,
    SwarmFollowParams,
    SwarmReferenceSource,
    WelcomePayload,
)
from fleet.hub.registry import RobotRegistry
from fleet.swarm.robots import RobotEndpoint
from fleet.swarm.transport import RobotClient
from fleet.server.core_event_store import CoreEventStore, EventRejected

_FORBIDDEN_PAYLOAD_KEYS = frozenset({"cmd_vel", "image", "twist"})
_LOGGER = logging.getLogger(__name__)


def _protocol_major(value: str) -> int | None:
    parts = value.split(".")
    if len(parts) != 2 or not all(part.isdecimal() for part in parts):
        return None
    return int(parts[0])


class HubError(Exception):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


class HubSession:
    """One `/ws/robots` socket. HELLO binds it to exactly one robot (D-382 F6)."""

    __slots__ = ("robot_id",)

    def __init__(self) -> None:
        self.robot_id: str | None = None


def _error(code: str, message: str) -> Envelope:
    return Envelope(type=EnvelopeType.ERROR, payload={"code": code, "message": message})


class SiteHub:
    def __init__(
        self,
        endpoints: Sequence[RobotEndpoint],
        clients: Optional[dict[str, RobotClient]] = None,
        fleet_name: str = "rosy-site",
        event_store: CoreEventStore | None = None,
        event_callback: Callable[[Mapping[str, object]], object] | None = None,
    ) -> None:
        # CORE REST control tokens and FleetAgent pairing credentials have
        # distinct authority. Missing pairing credentials leave the agent
        # link unavailable for that robot; never fall back to the REST token.
        self._tokens = {e.robot_id: e.fleet_pairing_token for e in endpoints
                        if e.fleet_pairing_token is not None}
        self._clients = clients if clients is not None else {}
        self._paired: set[str] = set()
        # robot_id -> the socket session that last completed HELLO for it.
        self._sessions: dict[str, HubSession] = {}
        self.registry = RobotRegistry()
        self._fleet_name = fleet_name
        self.event_store = event_store
        self.event_callback = event_callback
        self._event_projection_cursor = 0

    def set_event_callback(self, callback: Callable[[Mapping[str, object]], object]) -> None:
        self.event_callback = callback

    def set_client(self, robot_id: str, client: RobotClient) -> None:
        """SiteRoster only: a robot joined the roster after start (D-361 5)."""
        self._clients[robot_id] = client

    def set_pairing_token(self, robot_id: str, token: str) -> None:
        """SiteRoster only: accept this robot's FleetAgent HELLO from now on."""
        if not token:
            raise ValueError("pairing token must be non-empty")
        self._tokens[robot_id] = token

    def drop(self, robot_id: str) -> None:
        """SiteRoster only: forget the robot's client, pairing and live session."""
        self._clients.pop(robot_id, None)
        self._tokens.pop(robot_id, None)
        self._paired.discard(robot_id)
        self._sessions.pop(robot_id, None)
        self.registry.record(robot_id).online = False

    def open_session(self) -> HubSession:
        return HubSession()

    def close_session(self, session: HubSession) -> None:
        """Socket closed: unpair its robot unless a newer socket already took over."""
        robot_id = session.robot_id
        if robot_id is None or self._sessions.get(robot_id) is not session:
            return
        del self._sessions[robot_id]
        self._paired.discard(robot_id)
        self.registry.record(robot_id).online = False

    def handle(self, envelope: Envelope, *, session: HubSession | None = None) -> Envelope:
        """Route one envelope.

        Network code must pass the socket's session. Without one, HEARTBEAT/EVENT
        fall back to the global paired set, which is only safe in-process (D-382 F6).
        """
        if _protocol_major(envelope.protocol_version) != _protocol_major(PROTOCOL_VERSION):
            return _error("PROTOCOL_UNSUPPORTED", "protocol major is not supported")
        if envelope.type is EnvelopeType.HELLO:
            return self._hello(envelope, session)
        if envelope.type is EnvelopeType.COMMAND:
            return _error("ROLE_VIOLATION", "robots do not command the hub")
        keys = {str(k).lower() for k in envelope.payload}
        if keys & _FORBIDDEN_PAYLOAD_KEYS:
            return _error("ROLE_VIOLATION", "hub does not accept cmd_vel, image, or twist")
        if envelope.type is EnvelopeType.HEARTBEAT:
            return self._heartbeat(envelope, session)
        if envelope.type is EnvelopeType.EVENT:
            return self._event(envelope, session)
        return _error("SESSION_NOT_PAIRED", "hello first")

    def assert_scatterable(self, params: SwarmFollowParams) -> None:
        if params.source is SwarmReferenceSource.PEER:
            raise HubError("ROLE_VIOLATION", "peer source is not scatterable")

    async def scatter_estop(self, robot_id: str) -> dict:
        client = self._clients.get(robot_id)
        if client is None:
            raise HubError("UNKNOWN_ROBOT", robot_id)
        return await client.estop()

    async def scatter_swarm_cancel(self, robot_id: str) -> dict:
        """D-421 전체 주행 취소의 추종 단계. 로봇 REST 원자 액션이지 twist 가 아니다."""
        client = self._clients.get(robot_id)
        if client is None:
            raise HubError("UNKNOWN_ROBOT", robot_id)
        return await client.swarm_cancel()

    def _bound(self, robot_id: str, session: HubSession | None) -> bool:
        if session is None:
            return robot_id in self._paired
        return session.robot_id == robot_id and self._sessions.get(robot_id) is session

    def _hello(self, envelope: Envelope, session: HubSession | None) -> Envelope:
        try:
            hello = HelloPayload.model_validate(envelope.payload)
        except Exception:
            return _error("PAIRING_INVALID", "bad hello")
        if _protocol_major(hello.protocol_version) != _protocol_major(PROTOCOL_VERSION):
            return _error("PROTOCOL_UNSUPPORTED", "hello protocol major is not supported")
        if session is not None and session.robot_id not in (None, hello.robot_id):
            return _error("PAIRING_INVALID", "session is bound to another robot")
        expected = self._tokens.get(hello.robot_id)
        if expected is None or not hmac.compare_digest(
                expected.encode(), hello.pairing_token.encode()):
            return _error("PAIRING_INVALID", "unknown robot or token")
            
        # Check UUID duplicates
        if hello.device_uid:
            for other_id in self.registry.online_ids():
                if other_id != hello.robot_id:
                    other_row = self.registry.record(other_id)
                    if other_row.device_uid == hello.device_uid:
                        return _error("DUPLICATE_IDENTITY", "UUID in use")
        
        row = self.registry.record(hello.robot_id)
        
        # Check Hardware serial drift
        if row.hardware_serial and hello.hardware_serial and row.hardware_serial != hello.hardware_serial:
            return _error("IDENTITY_DRIFT", "hardware serial changed")
            
        row.device_uid = hello.device_uid
        row.device_name = hello.device_name
        row.model = hello.model
        row.hardware_serial = hello.hardware_serial
        
        row.online = True
        self._paired.add(hello.robot_id)
        if session is not None:
            session.robot_id = hello.robot_id
            self._sessions[hello.robot_id] = session
        welcome = WelcomePayload(
            robot_id=hello.robot_id,
            fleet_name=self._fleet_name,
            last_event_seq=row.last_event_seq,
        )
        return Envelope(type=EnvelopeType.WELCOME, payload=welcome.model_dump())

    def _heartbeat(self, envelope: Envelope, session: HubSession | None) -> Envelope:
        try:
            payload = HeartbeatPayload.model_validate(envelope.payload)
        except Exception:
            return _error("SESSION_NOT_PAIRED", "hello first")
        robot_id = payload.state_snapshot.robot_id
        if session is not None and session.robot_id is None:
            return _error("SESSION_NOT_PAIRED", "hello first")
        if not self._bound(robot_id, session):
            if session is None:
                return _error("SESSION_NOT_PAIRED", "hello first")
            return _error("PAIRING_INVALID", "robot mismatch")
        if not self._recover_event_projections():
            return _error("TASK_PROJECTION_UNAVAILABLE", "durable event projection is pending")
        row = self.registry.record(robot_id)
        row.snapshot = payload.state_snapshot
        return Envelope(type=EnvelopeType.HEARTBEAT, payload={})

    def _event(self, envelope: Envelope, session: HubSession | None) -> Envelope:
        try:
            event = EventMessage.model_validate(envelope.payload)
        except Exception:
            return _error("SESSION_NOT_PAIRED", "hello first")
        if not self._paired or (session is not None and session.robot_id is None):
            return _error("SESSION_NOT_PAIRED", "hello first")
        if not self._bound(event.robot_id, session):
            return _error("PAIRING_INVALID", "robot mismatch")
        is_new = True
        if self.event_store is not None:
            try:
                is_new = self.event_store.append_event(event.model_dump(mode="json"))
            except EventRejected:
                return _error("EVENT_NOT_AUDITABLE", "event is outside the safe audit contract")
            except (OSError, sqlite3.Error):
                return _error("EVENT_STORAGE_UNAVAILABLE", "event was not durably accepted")
        if self.event_callback is not None and not self._recover_event_projections():
            return _error("TASK_PROJECTION_UNAVAILABLE", "event task projection is pending")
        row = self.registry.record(event.robot_id)
        if is_new:
            row.events.append(event)
        row.last_event_seq = max(row.last_event_seq, event.seq)
        return Envelope(type=EnvelopeType.EVENT, payload={"accepted": True})

    def _recover_event_projections(self) -> bool:
        """Replay durable CORE events after transient task projection failures."""
        if self.event_callback is None or self.event_store is None:
            return True
        if not hasattr(self.event_store, "read_events"):
            return False
        try:
            rows = self.event_store.read_events(
                after_id=self._event_projection_cursor, limit=100,
            )
            for row in rows[:100]:
                self.event_callback(row["event"])
                self._event_projection_cursor = row["audit_id"]
            return True
        except Exception:
            _LOGGER.exception("Could not project durable CORE event into Fleet task history")
            return False
