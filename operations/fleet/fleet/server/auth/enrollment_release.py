"""E-stop release, pinned-address discovery reconciliation, address migration, and unenrollment."""

from __future__ import annotations

import logging
from typing import Optional

import httpx

from fleet.hub.hub import HubError
from fleet.server.discovery import is_rfc1918
from fleet.server.enrollment_errors import EnrollmentError
from fleet.server.enrollment_inputs import (
    LEGACY_WARN_S,
    SITE_WARN_S,
    _seconds_between,
    normalize_code,
)
from fleet.server.enrollment_store import SealError, seal
from fleet.swarm.robots import RobotEndpoint
from fleet.swarm.transport import RobotApiError

_LOG = logging.getLogger(__name__)

#: CORE's answer -> (Fleet code, HTTP status, message). Anything else is robot_error.
_REFUSALS = {
    "NOT_LATCHED": ("not_latched", 409, "the robot is not in emergency stop; the code was not used"),
    "CODE_REJECTED": ("code_rejected", 401, "the release code is wrong, used or expired"),
    # Fleet's own robot credential failed (the transport already marked it for a new code).
    "UNAUTHORIZED": ("robot_auth", 409, "Fleet's credential for this robot is no longer valid; re-enroll it"),
    "RATE_LIMITED": ("rate_limited", 429, "too many attempts at this robot"),
    "FORBIDDEN": ("lan_forbidden", 403, "the robot sees this server as outside its LAN"),
    "MODE_CONFLICT": ("release_refused", 409, "the robot used the code but refused to leave emergency"),
}


class SafetyReleaseMixin:
    """Methods of EnrollmentService that carry one screen-code release to an enrolled robot."""

    async def release_estop(self, robot_id: str, *, code: object, principal_id: str) -> dict:
        self._require_available()
        normalized = normalize_code(code)
        row = self._store.get(robot_id)
        if row is None or row["state"] != "active":
            raise EnrollmentError("not_enrolled", 404, "that robot is not an active enrolled robot")
        self._tls_fence(row)
        try:
            client = self._console()._client(robot_id)
        except HubError:
            raise EnrollmentError("not_enrolled", 404, "that robot is not on the roster") from None
        try:
            answer = await client.estop_release_code(normalized)
        except RobotApiError as exc:
            if exc.status == 404:
                outcome, status, message = "robot_too_old", 409, "this robot's CORE has no release code (before v1.343)"
            else:
                outcome, status, message = _REFUSALS.get(exc.code, ("robot_error", 502, f"the robot answered {exc.status}"))
                if outcome == "code_rejected" and (exc.detail or {}).get("burned"):
                    outcome, message = "release_burned", "the release code was burned; a new one shows after a minute"
            self._store.audit(action="estop_release", outcome=outcome, principal_id=principal_id, target=robot_id)
            raise EnrollmentError(outcome, status, message) from None
        except (httpx.HTTPError, OSError, ValueError):
            self._store.audit(action="estop_release", outcome="unreachable", principal_id=principal_id,
                              target=robot_id)
            raise EnrollmentError("unreachable", 502, "the robot is not reachable") from None
        self._store.audit(action="estop_release", outcome="released", principal_id=principal_id,
                          target=robot_id)
        return {"robot_id": robot_id, "estop": bool(answer.get("estop", False))}


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
            gate = self._gate_for(record)
            await self._roster.replace_endpoint(endpoint, self._client(endpoint, gate))
            self._gates[robot_id] = gate
            self._tokens[robot_id] = token
            self._console().release_robot(robot_id)
            self._store.audit(action="move_address", outcome="moved", principal_id=principal_id,
                              target=robot_id)
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
        gate = self._gates.pop(robot_id, None)
        token = self._tokens.pop(robot_id, None)
        if on_roster:
            await self._roster.remove(robot_id)
        done = False
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
