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

import asyncio
import logging
import time
from typing import Any, Callable

import httpx

from fleet.server.enrollment_errors import EnrollmentError  # noqa: F401  (re-exported)
from fleet.server.enrollment_helpers import (
    LEGACY_WARN_S,
    SITE_LIFETIME_S,
    SITE_WARN_S,
    STOP_PATHS,
    EnrolledRobotClient,
    EnrollmentAddressMixin,
    EnrollmentCandidateMixin,
    RobotGate,
    _AVAHI_SUFFIX,
    _PinnedTransport,
    _seconds_between,
)
from fleet.server.enrollment_hub import HubLinkMixin
from fleet.server.enrollment_idle import IDLE_REMOVAL_S, IdlePolicy
from fleet.server.enrollment_inputs import normalize_code, parse_manual_address
from fleet.server.enrollment_release import SafetyReleaseMixin
from fleet.server.enrollment_store import EnrollmentStore, SealError, seal, unseal
from fleet.swarm.robots import RobotEndpoint

_LOG = logging.getLogger(__name__)

__all__ = [
    "EnrolledRobotClient",
    "EnrollmentAddressMixin",
    "EnrollmentCandidateMixin",
    "EnrollmentError",
    "EnrollmentService",
    "LEGACY_WARN_S",
    "RobotGate",
    "SITE_LIFETIME_S",
    "SITE_WARN_S",
    "STOP_PATHS",
    "_AVAHI_SUFFIX",
    "_PinnedTransport",
    "_seconds_between",
    "normalize_code",
    "parse_manual_address",
]


class EnrollmentService(EnrollmentCandidateMixin, EnrollmentAddressMixin, HubLinkMixin, SafetyReleaseMixin):
    #: D-960: robots this Fleet's control unit owns (manifest); None = no control unit, any id.
    owned_robot_ids: frozenset | None = None

    def __init__(self, store: EnrollmentStore, roster, *, key: bytes | None,
                 key_error: str | None = None, fleet_name: str = "rosy-site",
                 discovery=None, transport: httpx.AsyncBaseTransport | None = None,
                 tls_bindings=None, hub_link: dict | None = None, account_link=None,
                 clock: Callable[[], float] = time.time, last_activity=None,
                 idle_removal_s: float = IDLE_REMOVAL_S) -> None:
        self._store = store
        self._idle = IdlePolicy(last_activity, idle_removal_s)  # D-1016 shown-only marking
        #: D-555: {expected_hostname, ca_pem} robots get with a hub credential; None = unavailable.
        self._hub_link = hub_link
        self._account_link = account_link
        self._roster = roster
        self._key = key
        self.unavailable_reason = (key_error or "robot credential key is not configured") if key is None else None
        self._fleet_name = fleet_name
        self._discovery = discovery
        self._transport = transport
        self._tls_bindings = tls_bindings
        if tls_bindings is not None:
            pending = tls_bindings.validate(store.rows())
            if pending:
                _LOG.warning("TLS bindings pending enrollment (D-565): %s", ", ".join(pending))
        self._clock = clock
        self._gates: dict[str, RobotGate] = {}
        self._tokens: dict[str, str] = {}
        self._hub_locks: dict[str, asyncio.Lock] = {}
        #: D-555: when Fleet last delivered each robot's credential (Fleet start for older links).
        self._hub_linked_at: dict[str, float] = {}
        self._started_at = clock()

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

    def _http(self, address: str, pending=None, renumber: bool = False) -> httpx.AsyncClient:
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
            if pending is not None or (rows and self._tls_bindings.binding(rows[0]["robot_id"]) is not None):
                from fleet.server.enrollment_tls import EnrollmentIdentityTransport
                from fleet.swarm.discovery_transport import DiscoveryTransport
                endpoint = self._endpoint(rows[0] if pending is None else {
                    "robot_id": pending.robot_id, "address": address}, "anonymous-bootstrap")
                base_url = endpoint.base_url
                kwargs["transport"] = DiscoveryTransport(endpoint, inner=EnrollmentIdentityTransport(
                    endpoint, self._tls_bindings, inner=self._transport, any_receiver=renumber))
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
        rows = self._store.rows()
        idle = self._idle.facts(rows, now)
        robots = []
        for row in rows:
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
                **idle[row["robot_id"]],  # D-1016: shown only; unenroll stays a named operator's call (D-456)
                **self._hub_fields(row),
            })
        return {"available": self.available, "unavailable_reason": self.unavailable_reason,
                "static_robot_ids": sorted(self._roster.static_ids), "robots": robots,
                "alarms": self._console().alarms()}

    # --- enroll ------------------------------------------------------------

    async def enroll(self, *, code: object, principal_id: str,
                     discovery_name: str | None = None, address: str | None = None) -> dict:
        self._require_available()
        if self.owned_robot_ids is not None:
            raise EnrollmentError("control_unit_enrollment_unavailable", 409, "this control unit has a fixed roster")
        normalized = normalize_code(code)
        target, row, pending = self._candidate(discovery_name, address)
        # D-580: a binding a robot enrolled through here (same hostname, CA, file row) may come back renumbered.
        renumber = pending is not None and self._tls_bindings.proven(pending)
        async with self._http(target, pending, renumber) as http:
            try:
                paired = await self._exchange(http, normalized, principal_id, target)
            except ValueError as exc:
                from fleet.server.enrollment_tls import EnrollmentTlsError
                if pending is None:
                    raise
                outcome = "tls_binding_mismatch" if isinstance(exc, EnrollmentTlsError) else "unreachable"
                self._store.audit(action="enroll", outcome=outcome, principal_id=principal_id, target=target)
                if outcome == "unreachable":
                    raise EnrollmentError(outcome, 502, "the approved TLS name is not reachable") from None
                raise EnrollmentError(outcome, 409, "the robot does not prove its approved TLS binding") from None
            token = paired["token"]
            try:
                return await self._bind_and_store(http, paired, row, target, principal_id, pending, renumber)
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

    async def _bind_and_store(self, http: httpx.AsyncClient, paired: dict, row: dict | None,
                              target: str, principal_id: str, pending=None, renumber: bool = False) -> dict:
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
        if (http.base_url.scheme != "https" and self._tls_bindings is not None
                and self._tls_bindings.claims({hostname}, {robot_id})):
            raise self._consumed("tls_binding_required")  # a bound identity answered over HTTP
        if robot_id in self._roster.robot_ids or self._store.get(robot_id) is not None:
            raise self._consumed("robot_id_conflict")
        if pending is not None and robot_id != pending.robot_id:
            if not renumber:
                raise self._consumed("tls_binding_mismatch")
            if self._tls_bindings.claims(set(), {robot_id}):
                raise self._consumed("robot_id_conflict")  # another approved binding owns that id
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
        renamed = None
        try:
            if pending is not None and robot_id != pending.robot_id:
                renamed = self._tls_bindings.renumber(pending, robot_id)
            if pending is not None:
                self._store.remember_tls([dict(robot_id=robot_id, origin=f"https://{pending.hostname}:{pending.port}",
                                               ca_sha256=pending.tls_ca_sha256)])
            gate = self._gate_for(record)
            endpoint = self._endpoint(record, token)
            self._roster.add(endpoint, self._client(endpoint, gate))
        except Exception:
            self._store.delete(robot_id)
            if renamed is not None:
                self._tls_bindings.renumber(renamed, pending.robot_id)
            raise
        if renamed is not None:
            self._store.audit(action="tls_renumber", outcome="renumbered", principal_id=principal_id,
                              target=f"{pending.robot_id}->{robot_id}")
        self._gates[robot_id] = gate
        self._tokens[robot_id] = token
        self._store.audit(action="enroll", outcome="enrolled", principal_id=principal_id,
                          target=robot_id)
        return next(item for item in self.listing()["robots"] if item["robot_id"] == robot_id)
