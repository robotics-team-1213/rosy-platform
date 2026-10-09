"""Hub link of an enrolled robot (D-555): issue, rotate and revoke its hub credential.

Moved out of enrollment.py, which is at its size cap (D-565 added the pending TLS
binding path there). It runs on the EnrollmentService state as a mixin.
"""

from __future__ import annotations

import asyncio
import hashlib
import secrets

import httpx

from core_common.config import FLEET_LINK_ARM_GRACE_S

from fleet.server.enrollment_errors import EnrollmentError
from fleet.swarm.transport import RobotApiError


class HubLinkMixin:
    """Methods of EnrollmentService that manage the robot's hub link."""

    def _tls_bound(self, robot_id: str) -> bool:
        return self._tls_bindings is not None and self._tls_bindings.binding(robot_id) is not None

    def _hub_state(self, row: dict) -> str | None:
        """`online`, `checking` (inside CORE's arm grace) or `failed` (CORE's SAF-003 counts the
        link as lost), mirroring FLEET_LINK_ARM_GRACE_S without asking the robot."""
        if not row.get("hub_digest"):
            return None
        if self._hub_online(row["robot_id"]):
            return "online"
        since = self._hub_linked_at.get(row["robot_id"], self._started_at)
        return "checking" if self._clock() - since < FLEET_LINK_ARM_GRACE_S else "failed"

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

    def _hub_lock(self, robot_id: str) -> asyncio.Lock:
        """One hub-link change per robot at a time (store, PUT and rollback stay together)."""
        return self._hub_locks.setdefault(robot_id, asyncio.Lock())

    def _tls_client(self, robot_id: str):
        """The enrolled client when the TLS fence and binding hold, else None (never raises)."""
        try:
            row = self._store.get(robot_id)
            if row is None or not self._tls_bound(robot_id):
                return None
            self._tls_fence(row)
            client = self._console()._client(robot_id)
        except Exception:  # EnrollmentTlsError (changed binding), HubError (not on the roster)
            return None
        return client if client._ep.base_url.startswith("https://") else None

    async def _refuse_during_fleet_goal(self, robot_id: str, client) -> None:
        """D-555 review: a relink or a dropped hub session during a Fleet goal arms SAF-003."""
        refused = EnrollmentError("fleet_goal_active", 409,
                                  "a Fleet goal is running on this robot; change the hub link after it ends")
        if robot_id in self._console()._goals:
            raise refused
        if client is None:
            return
        try:
            link = await client.fleet_link_get()
        except Exception:  # unreachable or old image: CORE's own 409 FLEET_GOAL_ACTIVE still guards PUT
            return
        if isinstance(link, dict) and link.get("fleet_goal_active") is True:
            raise refused

    async def link_hub(self, robot_id: str, *, principal_id: str) -> dict:
        """Issue (or rotate) the robot's hub credential and deliver it once over TLS.

        Only the SHA-256 digest is stored. It is stored and applied before delivery so the
        robot's immediate HELLO is accepted, and rolled back if delivery fails.
        """
        async with self._hub_lock(robot_id):
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
            if not (isinstance(caps, dict) and caps.get("fleet_link_provisioning") is True):
                raise EnrollmentError("robot_unsupported", 409,
                                      "this robot image cannot take a hub link (fleet_link_provisioning)")
            await self._refuse_during_fleet_goal(robot_id, client)
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
                if code == "FLEET_GOAL_ACTIVE":
                    raise EnrollmentError("fleet_goal_active", 409,
                                          "a Fleet goal is running on this robot; change the hub link "
                                          "after it ends") from None
                # The robot's code only: a message could carry anything the request held.
                raise EnrollmentError("robot_refused", 502, f"the robot did not take the hub link ({code})",
                                      detail={"robot_code": code}) from None
            self._hub_linked_at[robot_id] = self._clock()
            self._store.audit(action="hub_link", outcome="rotated" if old[0] else "linked",
                              principal_id=principal_id, target=robot_id)
            return next(item for item in self.listing()["robots"] if item["robot_id"] == robot_id)

    async def _clear_robot_link(self, robot_id: str) -> bool:
        """One DELETE /fleet/link attempt behind the TLS fence. True when the robot answered it."""
        client = self._tls_client(robot_id)
        if client is None:
            return False
        try:
            await client.fleet_link_delete()
            return True
        except Exception:  # unreachable, held address, old image: Fleet's side is cleared anyway
            return False

    async def unlink_hub(self, robot_id: str, *, principal_id: str, force: bool = False) -> dict:
        """Revoke: clear the digest here first (no TLS needed for that), then ask the robot.

        ``force`` (named operator, confirmed in the console) revokes during a Fleet goal too:
        the robot then sees a lost link and SAF-003 STOP/HOLD applies (the safe direction).
        """
        async with self._hub_lock(robot_id):
            self._require_available()
            row = self._store.get(robot_id)
            if row is None or row["state"] == "pending_logout":
                raise EnrollmentError("not_enrolled", 404, "that robot is not enrolled")
            if not force:
                await self._refuse_during_fleet_goal(robot_id, self._tls_client(robot_id))
            self._store.update(robot_id, hub_digest=None, hub_host=None)
            self._hub_linked_at.pop(robot_id, None)
            self._console().hub.set_pairing_digest(robot_id, None)
            cleared = await self._clear_robot_link(robot_id)
            outcome = "cleared" if cleared else "robot_not_cleared"
            self._store.audit(action="hub_unlink", outcome=f"forced_{outcome}" if force else outcome,
                              principal_id=principal_id, target=robot_id)
            return {**next(item for item in self.listing()["robots"] if item["robot_id"] == robot_id),
                    "robot_cleared": cleared, "was_linked": bool(row.get("hub_digest"))}
