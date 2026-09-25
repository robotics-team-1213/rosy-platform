"""관제 쪽 모음/흩뿌림. 최종 cmd_vel과 Image를 다루지 않는다 (D-59)."""

from __future__ import annotations

from typing import Optional, Sequence

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

_FORBIDDEN_PAYLOAD_KEYS = frozenset({"cmd_vel", "image", "twist"})


def _protocol_major(value: str) -> int | None:
    parts = value.split(".")
    if len(parts) != 2 or not all(part.isdecimal() for part in parts):
        return None
    return int(parts[0])


class HubError(Exception):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


def _error(code: str, message: str) -> Envelope:
    return Envelope(type=EnvelopeType.ERROR, payload={"code": code, "message": message})


class SiteHub:
    def __init__(
        self,
        endpoints: Sequence[RobotEndpoint],
        clients: Optional[dict[str, RobotClient]] = None,
        fleet_name: str = "rosy-site",
    ) -> None:
        # CORE REST control tokens and FleetAgent pairing credentials have
        # distinct authority. Missing pairing credentials leave the agent
        # link unavailable for that robot; never fall back to the REST token.
        self._tokens = {e.robot_id: e.fleet_pairing_token for e in endpoints
                        if e.fleet_pairing_token is not None}
        self._clients = clients or {}
        self._paired: set[str] = set()
        self.registry = RobotRegistry()
        self._fleet_name = fleet_name

    def handle(self, envelope: Envelope) -> Envelope:
        if _protocol_major(envelope.protocol_version) != _protocol_major(PROTOCOL_VERSION):
            return _error("PROTOCOL_UNSUPPORTED", "protocol major is not supported")
        if envelope.type is EnvelopeType.HELLO:
            return self._hello(envelope)
        if envelope.type is EnvelopeType.COMMAND:
            return _error("ROLE_VIOLATION", "robots do not command the hub")
        keys = {str(k).lower() for k in envelope.payload}
        if keys & _FORBIDDEN_PAYLOAD_KEYS:
            return _error("ROLE_VIOLATION", "hub does not accept cmd_vel, image, or twist")
        if envelope.type is EnvelopeType.HEARTBEAT:
            return self._heartbeat(envelope)
        if envelope.type is EnvelopeType.EVENT:
            return self._event(envelope)
        return _error("SESSION_NOT_PAIRED", "hello first")

    def assert_scatterable(self, params: SwarmFollowParams) -> None:
        if params.source is SwarmReferenceSource.PEER:
            raise HubError("ROLE_VIOLATION", "peer source is not scatterable")

    async def scatter_estop(self, robot_id: str) -> dict:
        client = self._clients.get(robot_id)
        if client is None:
            raise HubError("UNKNOWN_ROBOT", robot_id)
        return await client.estop()

    def _hello(self, envelope: Envelope) -> Envelope:
        try:
            hello = HelloPayload.model_validate(envelope.payload)
        except Exception:
            return _error("PAIRING_INVALID", "bad hello")
        if _protocol_major(hello.protocol_version) != _protocol_major(PROTOCOL_VERSION):
            return _error("PROTOCOL_UNSUPPORTED", "hello protocol major is not supported")
        expected = self._tokens.get(hello.robot_id)
        if expected is None or expected != hello.pairing_token:
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
        welcome = WelcomePayload(
            robot_id=hello.robot_id,
            fleet_name=self._fleet_name,
            last_event_seq=row.last_event_seq,
        )
        return Envelope(type=EnvelopeType.WELCOME, payload=welcome.model_dump())

    def _heartbeat(self, envelope: Envelope) -> Envelope:
        try:
            payload = HeartbeatPayload.model_validate(envelope.payload)
        except Exception:
            return _error("SESSION_NOT_PAIRED", "hello first")
        robot_id = payload.state_snapshot.robot_id
        if robot_id not in self._paired:
            return _error("SESSION_NOT_PAIRED", "hello first")
        row = self.registry.record(robot_id)
        row.snapshot = payload.state_snapshot
        return Envelope(type=EnvelopeType.HEARTBEAT, payload={})

    def _event(self, envelope: Envelope) -> Envelope:
        try:
            event = EventMessage.model_validate(envelope.payload)
        except Exception:
            return _error("SESSION_NOT_PAIRED", "hello first")
        if not self._paired:
            return _error("SESSION_NOT_PAIRED", "hello first")
        if event.robot_id not in self._paired:
            return _error("PAIRING_INVALID", "robot mismatch")
        row = self.registry.record(event.robot_id)
        row.events.append(event)
        row.last_event_seq = max(row.last_event_seq, event.seq)
        return Envelope(type=EnvelopeType.EVENT, payload={"accepted": True})
