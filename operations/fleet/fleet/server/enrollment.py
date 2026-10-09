"""Site console enrolls a robot by its screen code (D-361 1-3, 6, 9, 10).

Fleet itself exchanges the code at the robot (`POST /api/v1/auth/pair`), reads
`whoami` and `system/info` with the new token to bind the identity, seals the token
in the register and adds the robot to the one roster. The browser never reaches the
robot and never sees the token. The address is pinned at enrollment; when the same
name shows up elsewhere Fleet sends only stop requests to the pinned address.
Moving to a new address is a re-pairing there with the robot's screen code: plain HTTP
cannot authenticate the new address, so the stored token never goes to it (D-361 3,
2026-10-01 note). The fields compared after the exchange (robot_id, hostname,
serial_number from `system/info`, readable by any viewer) are a consistency check, not
authentication; what binds identity is the operator reading the code and the IP off the
robot's own screen. Real authentication needs a robot-held key (TLS or nonce signing).
No request is ever retried automatically.
"""

from __future__ import annotations

import hashlib
import ipaddress
import logging
import re
import secrets
import time
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Callable, Optional

import httpx

from fleet.server.discovery import is_rfc1918
from fleet.server.enrollment_store import (
    EnrollmentStore,
    SealError,
    seal,
    unseal,
)
from fleet.swarm.robots import RobotEndpoint
from fleet.swarm.transport import HttpRobotClient, RobotApiError

_LOG = logging.getLogger(__name__)

CODE_ALPHABET = frozenset("23456789ABCDEFGHJKMNPQRSTUVWXYZ")
CODE_LENGTH = 8
DEFAULT_PORT = 8080
#: The only requests allowed to a pinned address whose identity is in doubt.
STOP_PATHS = frozenset({"/api/v1/safety/stop", "/api/v1/navigation/cancel",
                        "/api/v1/swarm/cancel"})
SITE_WARN_S = 14 * 86400.0
LEGACY_WARN_S = 48 * 3600.0
SITE_LIFETIME_S = 90 * 86400.0
_AVAHI_SUFFIX = re.compile(r"^(?P<base>.+)-\d+$")
#: The console applies the same RFC 1918 rule before sending (web/enrollment.js).
_RFC1918 = tuple(ipaddress.ip_network(net) for net in
                 ("10.0.0.0/8", "172.16.0.0/12", "192.168.0.0/16"))


class EnrollmentError(Exception):
    """A classified refusal; never carries a code or token."""

    def __init__(self, code: str, status: int, message: str, *, reason: str | None = None,
                 retry_after: int | None = None, detail: dict | None = None) -> None:
        super().__init__(message)
        self.code = code
        self.status = status
        self.reason = reason
        self.retry_after = retry_after
        self.detail = detail or {}

    def body(self) -> dict:
        out = {"code": self.code, "message": str(self)}
        if self.reason is not None:
            out["reason"] = self.reason
        if self.retry_after is not None:
            out["retry_after"] = self.retry_after
        out.update(self.detail)
        return out


def normalize_code(text: object) -> str:
    """Drop spaces and hyphens, uppercase, check the alphabet before any robot call."""
    if not isinstance(text, str):
        raise EnrollmentError("bad_format", 400, "a screen code is 8 characters like ABCD-EFGH")
    code = "".join(ch for ch in text if ch not in " -\t").upper()
    if len(code) != CODE_LENGTH or any(ch not in CODE_ALPHABET for ch in code):
        raise EnrollmentError("bad_format", 400, "a screen code is 8 characters like ABCD-EFGH")
    return code


def parse_manual_address(text: object) -> str:
    """Private LAN IPv4[:port] only; `.local`, hostnames and public addresses are refused."""
    if not isinstance(text, str) or not text.strip():
        raise EnrollmentError("bad_address", 400, "enter the robot's private LAN IPv4 address, optionally with :port")
    host, _, port_text = text.strip().partition(":")
    try:
        ip = ipaddress.ip_address(host)
        port = int(port_text) if port_text else DEFAULT_PORT
    except ValueError:
        raise EnrollmentError("bad_address", 400,
                              "enter the robot's private LAN IPv4 address, optionally with :port") from None
    if (ip.version != 4 or not any(ip in net for net in _RFC1918)
            or not 1 <= port <= 65535):
        raise EnrollmentError("bad_address", 400, "only private LAN IPv4 addresses are accepted")
    return f"{ip}:{port}"


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


class EnrollmentService:
    def __init__(self, store: EnrollmentStore, roster, *, key: bytes | None,
                 key_error: str | None = None, fleet_name: str = "rosy-site",
                 discovery=None, transport: httpx.AsyncBaseTransport | None = None,
                 tls_bindings=None, hub_link: dict | None = None,
                 clock: Callable[[], float] = time.time) -> None:
        self._store = store
        #: D-555: {expected_hostname, ca_pem} robots get with a hub credential; None = unavailable.
        self._hub_link = hub_link
        self._roster = roster
        self._key = key
        self.unavailable_reason = key_error if key is None else None
        if key is None and self.unavailable_reason is None:
            self.unavailable_reason = "robot credential key is not configured"
        self._fleet_name = fleet_name
        self._discovery = discovery
        self._transport = transport
        self._tls_bindings = tls_bindings
        if tls_bindings is not None:
            tls_bindings.validate(store.rows())
        self._clock = clock
        self._gates: dict[str, RobotGate] = {}
        self._tokens: dict[str, str] = {}

    def _tls_fence(self, row: dict) -> None:
        marker = self._store.tls_markers().get(row['robot_id'])
        if marker is not None:
            from fleet.server.enrollment_tls import EnrollmentTlsError
            binding = self._tls_bindings.binding(row['robot_id']) if self._tls_bindings else None
            if (binding is None or marker['origin'] != f'https://{binding.hostname}:{binding.port}'
                    or marker['ca_sha256'] != binding.tls_ca_sha256):
                raise EnrollmentTlsError('remembered TLS binding unavailable or changed; HTTP refused')

    # --- state -------------------------------------------------------------

    @property
    def available(self) -> bool:
        return self.unavailable_reason is None

    def _console(self):
        return self._roster._console

    def _http(self, address: str) -> httpx.AsyncClient:
        kwargs: dict[str, Any] = {}
        base_url = f"http://{address}"
        for row in self._store.rows():
            if row['address'] == address:
                self._tls_fence(row)
        if self._transport is not None:
            kwargs["transport"] = self._transport
        if self._tls_bindings is not None:
            rows = [row for row in self._store.rows() if row["address"] == address]
            if len(rows) > 1:
                raise EnrollmentError("conflict", 409, "several enrolled robots share that address")
            if rows and self._tls_bindings.binding(rows[0]["robot_id"]) is not None:
                from fleet.server.enrollment_tls import EnrollmentIdentityTransport
                from fleet.swarm.discovery_transport import DiscoveryTransport
                endpoint = self._endpoint(rows[0], "anonymous-bootstrap")
                base_url = endpoint.base_url
                kwargs["transport"] = DiscoveryTransport(endpoint, inner=EnrollmentIdentityTransport(
                    endpoint, self._tls_bindings, inner=self._transport))
        return httpx.AsyncClient(base_url=base_url, trust_env=False,
                                 follow_redirects=False,
                                 timeout=httpx.Timeout(10.0, connect=3.0), **kwargs)

    def _endpoint(self, row: dict, token: str) -> RobotEndpoint:
        self._tls_fence(row)
        if self._tls_bindings is not None:
            return self._tls_bindings.endpoint(row, token)
        return RobotEndpoint(row["robot_id"], f"http://{row['address']}", token)

    def _client(self, endpoint: RobotEndpoint, gate: RobotGate) -> EnrolledRobotClient:
        return EnrolledRobotClient(endpoint, gate, transport=self._transport, tls_bindings=self._tls_bindings,
                                   on_unauthorized=self._unauthorized, clock=self._clock)

    @staticmethod
    def _gate_for(row: dict) -> RobotGate:
        return RobotGate(expires_at=row.get("fleet_expires_at"))

    def _unauthorized(self, robot_id: str) -> None:
        """401 or Fleet-clock expiry: the token is dead; stop polling it (D-361 2)."""
        row = self._store.get(robot_id)
        if row is not None and row["state"] == "active":
            self._store.update(robot_id, state="needs_new_code")
        gate = self._gates.get(robot_id)
        if gate is not None and gate.held is None:
            self._hold(robot_id, "needs_new_code")

    def _open(self, row: dict) -> str:
        return unseal(self._key, self._store.ciphertext(row["robot_id"]), slot="rest",
                      robot_id=row["robot_id"], token_id=row["token_id"])

    def load(self) -> None:
        """Startup: put every non-retired enrolled robot back on the roster."""
        if not self.available:
            return
        rows = [row for row in self._store.rows() if row["state"] != "pending_logout"]
        for row in self._store.rows():
            self._tls_fence(row)
        try:
            opened = [(row, self._open(row)) for row in rows]
        except SealError:
            # A runtime state only; nothing about it is written to the database.
            self.unavailable_reason = "robot credential key does not open the register"
            return
        if self._tls_bindings is not None:
            markers = self._tls_bindings.markers(self._store.rows())
            self._store.remember_tls(markers)
        for row, token in opened:
            gate = self._gate_for(row)
            if row["state"] in ("address_changed", "needs_new_code"):
                gate.held = row["state"]
            self._gates[row["robot_id"]] = gate
            self._tokens[row["robot_id"]] = token
            self._roster.add(self._endpoint(row, token), self._client(self._endpoint(row, token), gate))
            if row.get("hub_digest"):
                self._console().hub.set_pairing_digest(row["robot_id"], row["hub_digest"])
            if gate.held:
                self._console().hold_robot(row["robot_id"], gate.held)

    def enrolled_names(self) -> dict[str, str]:
        """Lowercase discovery name -> robot_id for robots on the roster (D-361 8)."""
        return {self._name_of(row): row["robot_id"] for row in self._store.rows()
                if row["state"] != "pending_logout"}

    def _require_available(self) -> None:
        if not self.available:
            raise EnrollmentError("store_unavailable", 503, "robot credential key is unavailable",
                                  detail={"unavailable_reason": self.unavailable_reason})

    def listing(self) -> dict:
        now = self._clock()
        robots = []
        for row in self._store.rows():
            if (row["state"] == "active" and row["fleet_expires_at"] is not None
                    and now >= row["fleet_expires_at"]):
                row["state"] = "needs_new_code"  # shown only; the client records it on use
            lifetime = (row["fleet_expires_at"] - row["created_at"]
                        if row["fleet_expires_at"] is not None else None)
            gate = self._gates.get(row["robot_id"])
            robots.append({
                **{key: row[key] for key in (
                    "robot_id", "hostname", "serial_number", "device_uid", "discovery_name",
                    "address", "token_id", "role", "source", "expires_at", "fleet_expires_at",
                    "warn_at", "principal_id", "state", "created_at")},
                "origin": "enrolled",
                "hold": gate.held if gate is not None else None,
                "expiry_warning": row["warn_at"] is not None and now >= row["warn_at"],
                "legacy_lifetime": row["source"] != "pair-site",
                "lifetime_shortened": (row["source"] == "pair-site" and lifetime is not None
                                       and lifetime < SITE_LIFETIME_S - 86400.0),
                # D-555: never the digest itself.
                "hub_linked": bool(row.get("hub_digest")), "hub_host": row.get("hub_host"),
                "hub_online": bool(row.get("hub_digest")) and self._hub_online(row["robot_id"]),
                "hub_linkable": self._hub_link is not None and self._tls_bound(row["robot_id"]),
            })
        return {"available": self.available, "unavailable_reason": self.unavailable_reason,
                "static_robot_ids": sorted(self._roster.static_ids), "robots": robots,
                "alarms": self._console().alarms()}

    # --- enroll ------------------------------------------------------------

    def _candidate(self, discovery_name: str | None, address: str | None) -> tuple[str, dict | None]:
        if (discovery_name is None) == (address is None):
            raise EnrollmentError("bad_request", 400, "choose one discovered robot or one address")
        if address is not None:
            target = parse_manual_address(address)
            secure = [row for row in (self._discovery.rows() if self._discovery else [])
                      if f"{row['address']}:{row['port']}" == target and row.get("transport") == "https"]
            enrolled = [row for row in self._store.rows() if row["address"] == target]
            if secure and (len(enrolled) != 1 or self._tls_bindings is None
                           or self._tls_bindings.binding(enrolled[0]["robot_id"]) is None):
                raise EnrollmentError("tls_binding_required", 409, "HTTPS requires approved enrolled TLS binding")
            return target, None
        if self._discovery is None:
            raise EnrollmentError("not_discovered", 404, "that robot is not in the current scan")
        if any((row.get("discovery_name") or row["hostname"]).lower() == discovery_name.lower()
               for row in self._store.rows()):
            raise EnrollmentError("already_enrolled", 409, "that robot is already enrolled")
        console = self._console()
        snapshot = self._discovery.snapshot(console.registered_endpoints,
                                            console.hub.registry.identity_snapshot(),
                                            self.enrolled_names())
        rows = [row for row in snapshot["devices"] if row["name"] == discovery_name]
        if not rows:
            raise EnrollmentError("not_discovered", 404, "that robot is not in the current scan")
        if len({(row["address"], row["port"]) for row in rows}) > 1 or any(
                row["status"] == "conflict" for row in rows):
            raise EnrollmentError("conflict", 409, "that name is seen at several addresses")
        row = rows[0]
        if row.get("transport") == "https":
            registered = [r for r in self._store.rows() if r["address"] == f"{row['address']}:{row['port']}"]
            if (len(registered) != 1 or self._tls_bindings is None
                    or self._tls_bindings.binding(registered[0]["robot_id"]) is None):
                raise EnrollmentError("tls_binding_required", 409, "HTTPS requires approved enrolled TLS binding")
        if not row.get("enrollable"):
            raise EnrollmentError("not_enrollable", 409, "that row is not waiting for registration")
        return f"{row['address']}:{row['port']}", row

    async def enroll(self, *, code: object, principal_id: str,
                     discovery_name: str | None = None, address: str | None = None) -> dict:
        self._require_available()
        normalized = normalize_code(code)
        target, row = self._candidate(discovery_name, address)
        async with self._http(target) as http:
            paired = await self._exchange(http, normalized, principal_id, target)
            token = paired["token"]
            try:
                return await self._bind_and_store(http, paired, row, target, principal_id)
            except EnrollmentError as exc:
                await self._logout(http, token)
                self._store.audit(action="enroll", outcome=exc.reason or exc.code,
                                  principal_id=principal_id, target=target)
                raise
            except Exception:
                _LOG.exception("robot enrollment failed after the code was consumed")
                await self._logout(http, token)
                self._store.audit(action="enroll", outcome="store_failed",
                                  principal_id=principal_id, target=target)
                raise self._consumed("store_failed") from None

    async def _exchange(self, http: httpx.AsyncClient, code: str, principal_id: str,
                        target: str, action: str = "enroll") -> dict:
        body = {"code": code, "label": f"site:{self._fleet_name}", "purpose": "site"}
        try:
            response = await http.post("/api/v1/auth/pair", json=body)
        except httpx.HTTPError:
            self._store.audit(action=action, outcome="unreachable", principal_id=principal_id,
                              target=target)
            raise EnrollmentError("unreachable", 502, "the robot is not reachable (address, port)") from None
        status = response.status_code
        if status == 201:
            try:
                paired = response.json()
                if not isinstance(paired.get("token"), str) or not paired["token"]:
                    raise ValueError
                return paired
            except (ValueError, AttributeError):
                self._store.audit(action=action, outcome="robot_error",
                                  principal_id=principal_id, target=target)
                raise EnrollmentError("robot_error", 502, "the robot answered without a token") from None
        outcome = {401: "code_rejected", 429: "rate_limited", 403: "lan_forbidden",
                   400: "bad_format"}.get(status, "robot_error")
        detail = {}
        try:
            detail = (response.json().get("error") or {}).get("detail") or {}
        except (ValueError, AttributeError):
            pass
        if status == 401 and isinstance(detail, dict) and detail.get("burned"):
            outcome = "code_burned"
        self._store.audit(action=action, outcome=outcome, principal_id=principal_id, target=target)
        if outcome == "rate_limited":
            try:
                retry_after = max(1, int(response.headers.get("Retry-After", "60")))
            except ValueError:
                retry_after = 60
            raise EnrollmentError("rate_limited", 429, "too many attempts at this robot",
                                  retry_after=retry_after)
        messages = {
            "code_rejected": "the code is wrong, used or expired",
            "code_burned": "this robot's screen code was burned",
            "lan_forbidden": "the robot sees this server as outside its LAN",
            "bad_format": "the robot refused the code format",
            "robot_error": f"the robot answered {status}",
        }
        http_status = {"code_rejected": 401, "code_burned": 401, "lan_forbidden": 403,
                       "bad_format": 400}.get(outcome, 502)
        raise EnrollmentError(outcome, http_status, messages[outcome])

    @staticmethod
    def _consumed(reason: str, **detail) -> EnrollmentError:
        return EnrollmentError("code_consumed", 409,
                               "the code was consumed; restart the robot or get an administrator code",
                               reason=reason, detail=detail)

    async def _bind_and_store(self, http: httpx.AsyncClient, paired: dict, row: dict | None,
                              target: str, principal_id: str) -> dict:
        received_at = self._clock()
        token = paired["token"]
        role = paired.get("role")
        if role != "operator":
            raise self._consumed("admin_code_refused" if role == "administrator" else "role_too_low")
        headers = {"Authorization": f"Bearer {token}"}
        try:
            me = (await http.get("/api/v1/auth/whoami", headers=headers)).raise_for_status().json()
            info = (await http.get("/api/v1/system/info", headers=headers)).raise_for_status().json()
        except (httpx.HTTPError, ValueError):
            raise self._consumed("verify_failed") from None
        hostname = str(info.get("hostname") or "").lower()
        robot_id = info.get("robot_id")
        if row is not None:
            bridge_host = row["hostname"].lower().removesuffix(".local")
            if not hostname or hostname != bridge_host or hostname != row["name"].lower():
                renamed = _AVAHI_SUFFIX.match(bridge_host)
                raise self._consumed("wrong_robot", avahi_renamed=bool(
                    renamed and renamed.group("base") == row["name"].lower()))
        if not isinstance(robot_id, str) or not robot_id:
            raise self._consumed("wrong_robot", avahi_renamed=False)
        if robot_id in self._roster.robot_ids or self._store.get(robot_id) is not None:
            raise self._consumed("robot_id_conflict")
        token_id = str(paired.get("id") or me.get("id") or "")
        if not token_id:
            raise self._consumed("verify_failed")
        source = str(paired.get("source") or me.get("source") or "")
        lifetime = _seconds_between(me.get("created_at"), me.get("expires_at") or paired.get("expires_at"))
        fleet_expires_at = received_at + lifetime if lifetime is not None else None
        warn_before = SITE_WARN_S if source == "pair-site" else LEGACY_WARN_S
        record = {
            "robot_id": robot_id, "hostname": hostname or str(info.get("hostname") or ""),
            "serial_number": info.get("serial_number"), "device_uid": info.get("device_uid"),
            "discovery_name": row["name"] if row is not None else None, "address": target,
            "token_id": token_id, "role": role, "source": source,
            "expires_at": paired.get("expires_at") or me.get("expires_at"),
            "fleet_expires_at": fleet_expires_at,
            "warn_at": fleet_expires_at - warn_before if fleet_expires_at is not None else None,
            "principal_id": principal_id, "state": "active",
        }
        self._store.insert(record, seal(self._key, token, slot="rest", robot_id=robot_id,
                                        token_id=token_id))
        try:
            gate = self._gate_for(record)
            endpoint = self._endpoint(record, token)
            self._roster.add(endpoint, self._client(endpoint, gate))
        except Exception:
            self._store.delete(robot_id)
            raise
        self._gates[robot_id] = gate
        self._tokens[robot_id] = token
        self._store.audit(action="enroll", outcome="enrolled", principal_id=principal_id,
                          target=robot_id)
        return next(item for item in self.listing()["robots"] if item["robot_id"] == robot_id)

    @staticmethod
    async def _logout(http: httpx.AsyncClient, token: str) -> bool:
        """One logout attempt. True when the robot no longer holds the token."""
        from fleet.server.enrollment_tls import EnrollmentTlsError
        try:
            response = await http.post("/api/v1/auth/logout",
                                       headers={"Authorization": f"Bearer {token}"})
        except (httpx.HTTPError, EnrollmentTlsError):
            return False
        return response.status_code in (204, 401)

    # --- pinned address ------------------------------------------------------

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
        """Re-pair at the new address with the robot's screen code (D-361 3, 2026-10-01).

        1. Probe the pinned address (verified at enrollment; stop requests already go there
           with this token). If the robot still answers there, refuse: a name seen elsewhere
           is then not this robot moving — the usual shape of a relay.
        2. Exchange the code at the new address with no existing credential.
        3. Compare robot_id, hostname and serial_number read with the new token. This is a
           consistency check, not authentication (any viewer can read them, and a relay can
           pass them on); the operator's check of the code and IP on the robot's screen binds.
        4. Rebind to the new token. The old token is never sent anywhere: a site token cannot
           revoke itself, so the audit records `old_token_not_revoked` and the operator
           revokes it on the robot dashboard or lets it expire.
        """
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
        """Consistency check with the NEW token against the register row; returns token fields.

        device_uid is not compared: CORE's system/info does not return it, so the stored value
        is always None and the comparison would be decoration.
        """
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

    # --- hub link (D-555) ------------------------------------------------------

    def _tls_bound(self, robot_id: str) -> bool:
        return self._tls_bindings is not None and self._tls_bindings.binding(robot_id) is not None

    def _hub_online(self, robot_id: str) -> bool:
        record = self._console().hub.registry.find(robot_id)
        return record is not None and bool(record.online)

    def _hub_target(self, robot_id: str, principal_id: str, action: str) -> dict:
        """The enrolled row a hub credential may travel to: TLS-bound only (D-555 2)."""
        self._require_available()
        row = self._store.get(robot_id)
        if row is None or row["state"] == "pending_logout":
            raise EnrollmentError("not_enrolled", 404, "that robot is not enrolled")
        self._tls_fence(row)
        if not self._tls_bound(robot_id):
            self._store.audit(action=action, outcome="tls_binding_required",
                              principal_id=principal_id, target=robot_id)
            raise EnrollmentError("tls_binding_required", 409,
                                  "hub link needs a TLS-bound enrollment; over plain HTTP the "
                                  "credential would cross the LAN in clear")
        return row

    async def link_hub(self, robot_id: str, *, principal_id: str) -> dict:
        """Issue (or rotate) the robot's hub credential and deliver it once over TLS.

        Only the SHA-256 digest is stored. It is stored and applied before delivery so the
        robot's immediate HELLO is accepted, and rolled back if delivery fails.
        """
        row = self._hub_target(robot_id, principal_id, "hub_link")
        if self._hub_link is None:
            raise EnrollmentError("hub_link_unavailable", 409,
                                  "Fleet runs without --hub-link-hostname/--hub-link-ca, "
                                  "--events-db or a console token")
        if row["state"] != "active":
            raise EnrollmentError("not_active", 409, "the robot's enrollment is not active")
        client = self._console()._client(robot_id)
        if not client._ep.base_url.startswith("https://"):  # the binding chose TLS; never send otherwise
            raise EnrollmentError("tls_binding_required", 409, "the robot client is not on TLS")
        try:
            caps = await client.capabilities()
        except (RobotApiError, httpx.HTTPError, ValueError):  # ValueError: EnrollmentTlsError
            raise EnrollmentError("unreachable", 502, "the robot is not reachable") from None
        items = ((caps.get("controls") or {}).get("items") if isinstance(caps, dict) else None) or []
        if not any(isinstance(item, dict) and item.get("fleet_link_provisioning") is True
                   for item in items):
            raise EnrollmentError("robot_unsupported", 409,
                                  "this robot image cannot take a hub link (fleet_link_provisioning)")
        token = secrets.token_urlsafe(32)
        digest = hashlib.sha256(token.encode("utf-8")).hexdigest()
        host = self._hub_link["expected_hostname"]
        old = (row.get("hub_digest"), row.get("hub_host"))
        hub = self._console().hub
        self._store.update(robot_id, hub_digest=digest, hub_host=host)
        hub.set_pairing_digest(robot_id, digest)
        try:
            await client.fleet_link_put({"pairing_token": token, "expected_hostname": host,
                                         "ca_pem": self._hub_link["ca_pem"]})
        except Exception as exc:
            self._store.update(robot_id, hub_digest=old[0], hub_host=old[1])
            hub.set_pairing_digest(robot_id, old[0])
            code = exc.code if isinstance(exc, RobotApiError) else "unreachable"
            self._store.audit(action="hub_link", outcome=f"failed:{code}"[:64],
                              principal_id=principal_id, target=robot_id)
            # The robot's code only: a message could carry anything the request held.
            raise EnrollmentError("robot_refused", 502, f"the robot did not take the hub link ({code})",
                                  detail={"robot_code": code}) from None
        self._store.audit(action="hub_link", outcome="rotated" if old[0] else "linked",
                          principal_id=principal_id, target=robot_id)
        return next(item for item in self.listing()["robots"] if item["robot_id"] == robot_id)

    async def _clear_robot_link(self, robot_id: str) -> bool:
        """One DELETE /fleet/link attempt. True when the robot answered it."""
        try:
            await self._console()._client(robot_id).fleet_link_delete()
            return True
        except Exception:  # unreachable, held address, old image: Fleet's side is cleared anyway
            return False

    async def unlink_hub(self, robot_id: str, *, principal_id: str) -> dict:
        """Revoke: ask the robot to forget the link, then always clear the digest here."""
        row = self._hub_target(robot_id, principal_id, "hub_unlink")
        cleared = await self._clear_robot_link(robot_id)
        self._store.update(robot_id, hub_digest=None, hub_host=None)
        self._console().hub.set_pairing_digest(robot_id, None)
        self._store.audit(action="hub_unlink", outcome="cleared" if cleared else "robot_unreachable",
                          principal_id=principal_id, target=robot_id)
        return {**next(item for item in self.listing()["robots"] if item["robot_id"] == robot_id),
                "robot_cleared": cleared, "was_linked": bool(row.get("hub_digest"))}

    # --- unenroll ------------------------------------------------------------

    async def unenroll(self, robot_id: str, *, principal_id: str) -> dict:
        self._require_available()
        row = self._store.get(robot_id)
        if row is None:
            raise EnrollmentError("not_enrolled", 404, "that robot is not enrolled")
        self._endpoint(row, "anonymous-bootstrap")  # validate before changing the mounted roster
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
