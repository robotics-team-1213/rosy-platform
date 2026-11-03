"""Development connection metadata; authentication always requires a site credential."""

from __future__ import annotations

from typing import Optional

from fastapi import HTTPException, Request
from fastapi.responses import JSONResponse

NO_STORE = {"Cache-Control": "no-store", "Pragma": "no-cache"}


def client_address(request: Request, *, trust_forwarded: bool) -> str:
    """The site proxy supplies the browser peer as the last forwarded address."""
    forwarded = request.headers.get("x-forwarded-for")
    if trust_forwarded and forwarded:
        return forwarded.split(",")[-1].strip()
    return request.client.host if request.client else ""


class DevelopmentSessions:
    """Compatibility mode marker; development mode never issues credentials."""


def install_development_routes(app, *, sessions: Optional[DevelopmentSessions], task_service,
                               trust_forwarded: bool, account_login: bool = False) -> None:
    @app.get("/api/fleet/auth/connection", tags=["fleet-auth"])
    def fleet_connection() -> JSONResponse:
        return JSONResponse(headers=NO_STORE, content={
            "mode": "development" if sessions is not None else "paired", "password_login": account_login})

    @app.post("/api/fleet/auth/development-session", tags=["fleet-auth"])
    def fleet_development_session() -> None:
        raise HTTPException(status_code=403, headers=NO_STORE, detail={
            "code": "FORBIDDEN", "message": "human login is required"})
