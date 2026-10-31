"""E-stop release from the console with the robot's administrator screen code (user decision 2026-10-31).

CORE keeps `/api/v1/safety/release` administrator-only. Fleet does not gain that role: it
exchanges a code read off the robot's own screen once, releases, and logs the token out at
once. The token is never stored, logged or returned. A robot that is not latched is refused
before the code leaves Fleet, so a stray click does not burn it.

shortcut: a robot without a TLS binding gets the code and the short-lived administrator token
over plain HTTP on the LAN (revoked right after); require a TLS binding here once every robot has one.
"""

from __future__ import annotations

import asyncio

import httpx

from fleet.hub.hub import HubError

from fleet.server.enrollment_errors import EnrollmentError
from fleet.swarm.transport import RobotApiError


class SafetyReleaseMixin:
    """Methods of EnrollmentService that carry one administrator release to an enrolled robot."""

    async def release_estop(self, robot_id: str, *, code: object, principal_id: str) -> dict:
        from fleet.server.enrollment import normalize_code
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
            state = await client.state()
        except (RobotApiError, httpx.HTTPError, OSError, ValueError):
            self._store.audit(action="estop_release", outcome="unreachable", principal_id=principal_id,
                              target=robot_id)
            raise EnrollmentError("unreachable", 502, "the robot is not reachable") from None
        if (state.get("safety") or {}).get("estop") is not True:
            self._store.audit(action="estop_release", outcome="not_latched", principal_id=principal_id,
                              target=robot_id)
            raise EnrollmentError("not_latched", 409, "the robot is not in emergency stop; the code was not used")
        async with self._http(row["address"]) as http:
            try:
                paired = await self._exchange(http, normalized, principal_id, robot_id, action="estop_release")
            except ValueError:  # EnrollmentTlsError: the robot did not prove its binding; the code never left
                self._store.audit(action="estop_release", outcome="tls_binding_mismatch",
                                  principal_id=principal_id, target=robot_id)
                raise EnrollmentError("tls_binding_mismatch", 409,
                                      "the robot does not prove its approved TLS binding") from None
            try:
                answer = await self._release_with(http, paired, row)
            except EnrollmentError as exc:
                self._store.audit(action="estop_release", outcome=exc.reason or exc.code,
                                  principal_id=principal_id, target=robot_id)
                raise
            finally:
                # Shielded: a cancelled request must not leave an administrator token alive.
                if not await asyncio.shield(self._logout(http, paired["token"])):
                    self._store.audit(action="estop_release", outcome="admin_token_not_revoked",
                                      principal_id=principal_id, target=robot_id)
        self._store.audit(action="estop_release", outcome="released", principal_id=principal_id,
                          target=robot_id)
        return {"robot_id": robot_id, "estop": bool(answer.get("estop", False))}

    async def _release_with(self, http: httpx.AsyncClient, paired: dict, row: dict) -> dict:
        if paired.get("role") != "administrator":
            raise self._consumed("admin_required")
        headers = {"Authorization": f"Bearer {paired['token']}"}
        try:
            info = (await http.get("/api/v1/system/info", headers=headers)).raise_for_status().json()
        except (httpx.HTTPError, ValueError):
            raise self._consumed("verify_failed") from None
        if not (isinstance(info, dict) and info.get("robot_id") == row["robot_id"]
                and str(info.get("hostname") or "").lower() == row["hostname"]
                and info.get("serial_number") == row["serial_number"]):
            raise self._consumed("wrong_robot")
        try:
            response = await http.post("/api/v1/safety/release", headers=headers)
        except (httpx.HTTPError, ValueError):
            raise self._consumed("release_unreachable") from None
        if response.status_code != 200:
            try:
                why = str((response.json().get("error") or {}).get("message") or "")[:200]
            except (ValueError, AttributeError):
                why = ""
            raise self._consumed("release_refused", robot_status=response.status_code, robot_message=why)
        try:
            return response.json()
        except ValueError:
            return {}
