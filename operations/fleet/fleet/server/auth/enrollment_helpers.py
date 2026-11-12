"""Pinned-address transport, client gate, and address/unenroll mixins for enrollment."""

from __future__ import annotations

import logging
import re
import time
from dataclasses import dataclass
from datetime import datetime
from typing import Callable, Optional

import httpx

from fleet.server.auth.enrollment_inputs import normalize_code
from fleet.server.discovery import is_rfc1918
from fleet.server.enrollment_errors import EnrollmentError
from fleet.server.enrollment_store import SealError, seal
from fleet.swarm.robots import RobotEndpoint
from fleet.swarm.transport import HttpRobotClient, RobotApiError

_LOG = logging.getLogger(__name__)

#: The only requests allowed to a pinned address whose identity is in doubt.
STOP_PATHS = frozenset({"/api/v1/safety/stop", "/api/v1/navigation/cancel",
                        "/api/v1/swarm/cancel"})
SITE_WARN_S = 14 * 86400.0
LEGACY_WARN_S = 48 * 3600.0
SITE_LIFETIME_S = 90 * 86400.0

_AVAHI_SUFFIX = re.compile(r"^(?P<base>.+)-\d+$")


def _seconds_between(start: object, end: object) -> float | None:
    try:
        return (datetime.fromisoformat(str(end)) - datetime.fromisoformat(str(start))).total_seconds()
    except (TypeError, ValueError):
        return None


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


class EnrollmentAddressMixin:
    """Pinned-address discovery reconciliation, address migration, and unenrollment."""

    def _name_of(self, row: dict) -> str:
        return (row.get("discovery_name") or row["hostname"]).lower()

    async def on_discovery(self, rows: list[dict]) -> None:
        seen: dict[str, set[str]] = {}
        for item in rows:
            seen.setdefault(item["name"].lower(), set()).add(f"{item['address']}:{item['port']}")
        for row in self._store.rows():
            if self._tls_bindings is not None and self._tls_bindings.binding(row["robot_id"]) is not None:
                # TLS discovery authenticates locations during transport admission; scan hints
                # never rewrite the encrypted record or release expiry/revocation holds.
                if row["state"] == "pending_logout" and seen.get(self._name_of(row)):
                    await self._retry_pending_logout(row)
                continue
            addresses = seen.get(self._name_of(row))
            if not addresses:
                continue
            robot_id = row["robot_id"]
            if row["state"] == "pending_logout":
                if addresses == {row["address"]}:
                    await self._retry_pending_logout(row)
                continue
            if len(addresses) > 1:
                self._hold(robot_id, "conflict")
            elif addresses == {row["address"]}:
                if row["state"] == "address_changed":
                    self._store.update(robot_id, state="active")
                if row["state"] == "needs_new_code":
                    self._hold(robot_id, "needs_new_code")  # the token stays dead
                else:
                    self._release(robot_id)
            else:
                if row["state"] == "active":
                    self._store.update(robot_id, state="address_changed")
                self._hold(robot_id, "address_changed")

    def _hold(self, robot_id: str, reason: str) -> None:
        gate = self._gates.get(robot_id)
        if gate is None:
            return
        first = gate.held is None
        gate.held = reason
        self._console().hold_robot(robot_id, reason)
        if first:
            _LOG.warning("robot %s pinned address unverified (%s): stop requests only",
                         robot_id, reason)

    def _release(self, robot_id: str) -> None:
        gate = self._gates.get(robot_id)
        if gate is not None and gate.held is not None:
            gate.held = None
            self._console().release_robot(robot_id)

    async def settle_holds(self) -> None:
        """After a hold: stop formation members at the pinned address, then dissolve."""
        await self._console().stop_held_formation()

    async def _retry_pending_logout(self, row: dict) -> None:
        if row.get("logout_attempted"):
            return
        self._store.update(row["robot_id"], logout_attempted=1)
        try:
            token = self._open(row)
        except SealError:
            return
        async with self._http(row["address"]) as http:
            done = await self._logout(http, token)
        if done:
            self._store.delete(row["robot_id"])
        self._store.audit(action="logout_retry", outcome="removed" if done else "failed",
                          principal_id=None, target=row["robot_id"])

    def _current_other_address(self, row: dict) -> Optional[str]:
        rows = self._discovery.rows() if self._discovery is not None else []
        # discovery.py already keeps RFC 1918 rows only; checked again because this address
        # is about to receive a screen code.
        addresses = {f"{item['address']}:{item['port']}" for item in rows
                     if item["name"].lower() == self._name_of(row) and is_rfc1918(item["address"])}
        addresses.discard(row["address"])
        return addresses.pop() if len(addresses) == 1 else None

    async def move_address(self, robot_id: str, *, code: object, principal_id: str) -> dict:
        """Re-pair at the new address with the robot's screen code (D-361 3, 2026-10-01)."""
        self._require_available()
        normalized = normalize_code(code)
        row = self._store.get(robot_id)
        if row is None:
            raise EnrollmentError("not_enrolled", 404, "that robot is not enrolled")
        self._tls_fence(row)
        if self._tls_bindings is not None and self._tls_bindings.binding(robot_id) is not None:
            raise EnrollmentError("tls_bound", 409, "TLS-bound identity reconnects without address re-pairing")
        if row["state"] != "address_changed":
            raise EnrollmentError("address_unchanged", 409, "the robot is not at a new address")
        gate = self._gates.get(robot_id)
        if gate is not None and gate.held == "conflict":
            raise EnrollmentError("conflict", 409, "that name is seen at several addresses")
        new_address = self._current_other_address(row)
        if new_address is None:
            raise EnrollmentError("no_new_address", 409, "no single new address is in the scan")
        if await self._still_at_pinned(row):
            self._store.audit(action="move_address", outcome="still_at_pinned_address",
                              principal_id=principal_id, target=robot_id)
            raise EnrollmentError("still_at_pinned_address", 409,
                                  "the robot still answers at its pinned address; nothing to move")
        async with self._http(new_address) as http:
            paired = await self._exchange(http, normalized, principal_id, new_address,
                                          action="move_address")
            token = paired["token"]
            try:
                record = await self._verify_moved(http, paired, row)
            except EnrollmentError as exc:
                await self._logout(http, token)
                self._store.audit(action="move_address", outcome=exc.reason or exc.code,
                                  principal_id=principal_id, target=robot_id)
                raise
            except Exception:
                _LOG.exception("moving a robot failed after the code was consumed")
                await self._logout(http, token)
                self._store.audit(action="move_address", outcome="store_failed",
                                  principal_id=principal_id, target=robot_id)
                raise self._consumed("store_failed") from None
            self._store.rebind(robot_id, seal(self._key, token, slot="rest", robot_id=robot_id,
                                              token_id=record["token_id"]),
                               address=new_address, state="active", **record)
            endpoint = RobotEndpoint(robot_id, f"http://{new_address}", token)
            gate = RobotGate(expires_at=record["fleet_expires_at"])
            await self._roster.replace_endpoint(endpoint, self._client(endpoint, gate))
            self._gates[robot_id] = gate
            self._tokens[robot_id] = token
            self._console().release_robot(robot_id)
            self._store.audit(action="move_address", outcome="moved", principal_id=principal_id,
                              target=robot_id)
        # Never sent anywhere, so never revoked by Fleet (a relay could pass step 3).
        self._store.audit(action="move_address", outcome="old_token_not_revoked",
                          principal_id=principal_id, target=robot_id)
        listed = next(item for item in self.listing()["robots"] if item["robot_id"] == robot_id)
        return {**listed, "old_token_revoked": False}

    async def _still_at_pinned(self, row: dict) -> bool:
        """True when the pinned address still answers `system/info` as this robot."""
        token = self._tokens.get(row["robot_id"])
        if token is None:
            return False
        async with self._http(row["address"]) as http:
            try:
                response = await http.get("/api/v1/system/info",
                                          headers={"Authorization": f"Bearer {token}"})
                info = response.json() if response.status_code == 200 else None
            except (httpx.HTTPError, ValueError):
                return False
        return isinstance(info, dict) and info.get("robot_id") == row["robot_id"]

    async def _verify_moved(self, http: httpx.AsyncClient, paired: dict, row: dict) -> dict:
        """Consistency check with the NEW token against the register row; returns token fields."""
        received_at = self._clock()
        role = paired.get("role")
        if role != "operator":
            raise self._consumed("admin_code_refused" if role == "administrator" else "role_too_low")
        headers = {"Authorization": f"Bearer {paired['token']}"}
        try:
            me = (await http.get("/api/v1/auth/whoami", headers=headers)).raise_for_status().json()
            info = (await http.get("/api/v1/system/info", headers=headers)).raise_for_status().json()
        except (httpx.HTTPError, ValueError):
            raise self._consumed("verify_failed") from None
        same = (isinstance(info, dict) and info.get("robot_id") == row["robot_id"]
                and str(info.get("hostname") or "").lower() == row["hostname"]
                and info.get("serial_number") == row["serial_number"])
        if not same:
            raise EnrollmentError(
                "identity_mismatch", 409,
                "the device at the new address is not the enrolled robot; "
                "no stored credential was sent to it", reason="identity_mismatch")
        token_id = str(paired.get("id") or me.get("id") or "")
        if not token_id:
            raise self._consumed("verify_failed")
        source = str(paired.get("source") or me.get("source") or "")
        lifetime = _seconds_between(me.get("created_at"),
                                    me.get("expires_at") or paired.get("expires_at"))
        fleet_expires_at = received_at + lifetime if lifetime is not None else None
        warn_before = SITE_WARN_S if source == "pair-site" else LEGACY_WARN_S
        return {"token_id": token_id, "role": role, "source": source,
                "expires_at": paired.get("expires_at") or me.get("expires_at"),
                "fleet_expires_at": fleet_expires_at,
                "warn_at": fleet_expires_at - warn_before if fleet_expires_at is not None else None}

    async def unenroll(self, robot_id: str, *, principal_id: str) -> dict:
        self._require_available()
        row = self._store.get(robot_id)
        if row is None:
            raise EnrollmentError("not_enrolled", 404, "that robot is not enrolled")
        self._endpoint(row, "anonymous-bootstrap")  # validate before changing the mounted roster
        if self._tls_bindings is not None:
            self._tls_bindings.remember(robot_id)  # D-580: this binding may come back renumbered
        on_roster = robot_id in self._roster.robot_ids
        if on_roster:
            blocker = self._roster.removal_blockers(robot_id)
            if blocker is not None:
                raise blocker
        if row.get("hub_digest") and on_roster:
            await self._clear_robot_link(robot_id)  # D-555: the digest leaves with the row
        # Popped before the first await so no concurrent path reuses them.
        gate = self._gates.pop(robot_id, None)
        token = self._tokens.pop(robot_id, None)
        if on_roster:
            await self._roster.remove(robot_id)
        done = False
        # An address in doubt gets no Bearer; a dead token may still log out at a sure one.
        if token is not None and (gate is None or gate.held in (None, "needs_new_code")):
            async with self._http(row["address"]) as http:
                done = await self._logout(http, token)
        if done:
            self._store.delete(robot_id)
            outcome = "removed"
        else:
            self._store.update(robot_id, state="pending_logout")
            outcome = "pending_logout"
        self._store.audit(action="unenroll", outcome=outcome, principal_id=principal_id,
                          target=robot_id)
        return {"robot_id": robot_id, "state": "removed" if done else "pending_logout",
                "expires_at": row["expires_at"]}
