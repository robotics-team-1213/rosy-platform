"""Pinned-address transport, client gate, and re-exported mixins for enrollment."""

from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Callable

import httpx

from fleet.server.enrollment_inputs import (
    LEGACY_WARN_S,
    SITE_LIFETIME_S,
    SITE_WARN_S,
     EnrollmentCandidateMixin,
    _AVAHI_SUFFIX,
    _seconds_between,
)
from fleet.server.enrollment_release import EnrollmentAddressMixin
from fleet.swarm.robots import RobotEndpoint
from fleet.swarm.transport import HttpRobotClient, RobotApiError

#: The only requests allowed to a pinned address whose identity is in doubt.
STOP_PATHS = frozenset({"/api/v1/safety/stop", "/api/v1/navigation/cancel",
                        "/api/v1/swarm/cancel"})

__all__ = [
    "EnrolledRobotClient",
    "EnrollmentAddressMixin",
    "EnrollmentCandidateMixin",
    "LEGACY_WARN_S",
    "RobotGate",
    "SITE_LIFETIME_S",
    "SITE_WARN_S",
    "STOP_PATHS",
    "_AVAHI_SUFFIX",
    "_PinnedTransport",
    "_seconds_between",
]


@dataclass
class RobotGate:
    """Held = the pinned address is unverified: stop requests only (D-361 3)."""

    held: str | None = None
    #: Fleet-clock expiry; past it the token is dead and only stop requests go out.
    expires_at: float | None = None


class _PinnedTransport(httpx.AsyncBaseTransport):
    def __init__(self, inner: httpx.AsyncBaseTransport, robot_id: str, gate: RobotGate,
                 on_unauthorized: Callable[[str], None],
                 clock: Callable[[], float] = time.time) -> None:
        self._inner = inner
        self._robot_id = robot_id
        self._gate = gate
        self._on_unauthorized = on_unauthorized
        self._clock = clock

    def admit(self, request: httpx.Request) -> None:
        if (self._gate.held is None and self._gate.expires_at is not None
                and self._clock() >= self._gate.expires_at):
            self._on_unauthorized(self._robot_id)  # expired: treated as a 401, nothing sent
        if self._gate.held and request.url.path not in STOP_PATHS:
            raise RobotApiError(self._robot_id, 409, "ADDRESS_UNVERIFIED",
                                "pinned address is unverified; only stop requests are sent")

    async def handle_async_request(self, request: httpx.Request) -> httpx.Response:
        self.admit(request)
        response = await self._inner.handle_async_request(request)
        if response.status_code == 401:
            self._on_unauthorized(self._robot_id)
        return response

    async def aclose(self) -> None:
        await self._inner.aclose()


class EnrolledRobotClient(HttpRobotClient):
    """Operational client for an enrolled robot, bound to its pinned address."""

    def __init__(self, endpoint: RobotEndpoint, gate: RobotGate, *,
                 transport: httpx.AsyncBaseTransport | None = None,
                 tls_bindings=None,
                 on_unauthorized: Callable[[str], None] = lambda _robot_id: None,
                 clock: Callable[[], float] = time.time) -> None:
        self._tls_identity = None
        if endpoint.discovery:
            from fleet.server.enrollment_tls import EnrollmentIdentityTransport
            from fleet.swarm.discovery_transport import DiscoveryTransport
            self._tls_identity = EnrollmentIdentityTransport(endpoint, tls_bindings, inner=transport)
            inner = DiscoveryTransport(endpoint, inner=self._tls_identity)
        else:
            inner = transport if transport is not None else httpx.AsyncHTTPTransport()
        pinned = _PinnedTransport(inner, endpoint.robot_id, gate, on_unauthorized, clock)
        if self._tls_identity is not None:
            self._tls_identity.before_send = pinned.admit
        http = httpx.AsyncClient(
            base_url=endpoint.base_url, timeout=5.0, trust_env=False,
            transport=pinned)
        super().__init__(endpoint, http=http)
        self._owns_http = True
        self._gate = gate
        self._clock = clock

    def _refuse_socket(self) -> None:
        if self._gate.expires_at is not None and self._clock() >= self._gate.expires_at:
            self._gate.held = self._gate.held or "needs_new_code"
        if self._gate.held:
            raise RobotApiError(self.robot_id, 409, "ADDRESS_UNVERIFIED",
                                "pinned address is unverified; sockets stay closed")

    async def _socket_admission(self, address: str, port: int) -> None:
        if self._tls_identity is not None:
            from urllib.parse import urlsplit
            host = urlsplit(self._ep.base_url).hostname
            await self._tls_identity.identity(httpx.URL(f"https://{address}:{port}"),
                                              {"sni_hostname": host, "timeout": {
                                                  "connect": 3.0, "read": 5.0, "write": 5.0, "pool": 5.0}})
        self._refuse_socket()

    def _socket_auth_admission(self) -> None:
        self._refuse_socket()

    def _socket_context(self):
        return self._tls_identity.context if self._tls_identity is not None else super()._socket_context()

    async def pose_stream(self):
        self._refuse_socket()
        async for frame in super().pose_stream():
            yield frame

    async def open_reference_sink(self):
        self._refuse_socket()
        return await super().open_reference_sink()

    async def events(self, types):
        self._refuse_socket()
        async for event in super().events(types):
            yield event
