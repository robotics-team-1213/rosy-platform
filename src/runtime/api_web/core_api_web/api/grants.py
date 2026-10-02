"""core_api_web.api.grants — named token capabilities on top of the three roles (D-395 P2-5).

Roles (AUTH-102) stay the rank model. A grant names one kind of write so a route
can say what it needs without meaning "any operator":

- `NAVIGATE`: a human puts the robot somewhere (goal, initial pose, `source: human`).
- `LOCALIZE_ASSIST`: Fleet's localization service reads candidates and sends
  decisions and suspects (contract docs/plans/2026-10-01-d395-phase2-interfaces.md §2).

Grants derive from the token's role. Fleet's robot token is an operator token
(robots.yaml `token`, or D-361 enrollment, which refuses any other role), so it
carries `LOCALIZE_ASSIST`. Viewers carry neither.
"""

from __future__ import annotations

from fastapi import Depends

from core_api_web.api.deps import AuthContext, auth_dependency
from core_api_web.api.errors import ApiError

NAVIGATE = "NAVIGATE"
LOCALIZE_ASSIST = "LOCALIZE_ASSIST"

ROLE_GRANTS: dict[str, frozenset[str]] = {
    "viewer": frozenset(),
    "operator": frozenset({NAVIGATE, LOCALIZE_ASSIST}),
    "administrator": frozenset({NAVIGATE, LOCALIZE_ASSIST}),
}


def grants(auth: AuthContext) -> frozenset[str]:
    return ROLE_GRANTS.get(auth.role, frozenset())


def check_grant(auth: AuthContext, name: str) -> None:
    if name not in grants(auth):
        raise ApiError("FORBIDDEN", 403, f"requires {name} capability",
                       detail={"capability": name})


def require_grant(name: str):
    def _dep(auth: AuthContext = Depends(auth_dependency)) -> AuthContext:
        check_grant(auth, name)
        return auth
    return _dep
