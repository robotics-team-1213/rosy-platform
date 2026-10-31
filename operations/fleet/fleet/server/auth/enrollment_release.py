"""E-stop release from the console with the robot's screen release code (user decision 2026-10-31).

While CORE is latched, the robot's own screen shows a one-time release code (API v1.337). A
teammate standing at the robot reads it and enters it in the console; Fleet hands it to CORE
`POST /api/v1/safety/release-code` over the enrolled operator connection. The code can only
release that latch: it logs nobody in, and Fleet never stores or logs it. CORE checks the
latch before the code, so a robot that is not stopped does not use it up.
"""

from __future__ import annotations

import httpx

from fleet.hub.hub import HubError
from fleet.server.enrollment_errors import EnrollmentError
from fleet.swarm.transport import RobotApiError

#: CORE's answer -> (Fleet code, HTTP status, message). Anything else is robot_error.
_REFUSALS = {
    "NOT_LATCHED": ("not_latched", 409, "the robot is not in emergency stop; the code was not used"),
    "UNAUTHORIZED": ("code_rejected", 401, "the release code is wrong, used or expired"),
    "RATE_LIMITED": ("rate_limited", 429, "too many attempts at this robot"),
    "FORBIDDEN": ("lan_forbidden", 403, "the robot sees this server as outside its LAN"),
    "MODE_CONFLICT": ("release_refused", 409, "the robot used the code but refused to leave emergency"),
}


class SafetyReleaseMixin:
    """Methods of EnrollmentService that carry one screen-code release to an enrolled robot."""

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
            answer = await client.estop_release_code(normalized)
        except RobotApiError as exc:
            if exc.status == 404:
                outcome, status, message = "robot_too_old", 409, "this robot's CORE has no release code (before v1.337)"
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
