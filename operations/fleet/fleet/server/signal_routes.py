"""D-443 signal HTTP surface, owned by the one SignalConsole supervisor."""

from typing import Optional

from fastapi import Depends, HTTPException
from pydantic import BaseModel

from fleet.hub.hub import HubError
from fleet.server.http_errors import http_error
from fleet.server.signals import SignalApiError
from fleet.server.site_auth import SitePrincipal


class SignalCommandRequest(BaseModel):
    mode: str
    lamps: Optional[dict[str, bool]] = None
    cycle: Optional[dict[str, int]] = None


def install_signal_routes(app, *, signals, require_viewer, require_operator,
                          auth_configured: bool) -> None:
    def configured():
        if signals is None:
            raise HubError("NO_SIGNALS", "signals are not configured")
        return signals

    def require_authenticated_operator():
        # The general dev console guard permits anonymous loopback operation.
        # D-443 presence and manual aspects require configured credentials.
        if not auth_configured:
            raise HTTPException(status_code=401, detail={
                "code": "UNAUTHORIZED", "message": "configure an operator credential for signals"})

    @app.get("/api/fleet/signals", dependencies=[Depends(require_viewer)], tags=["signals"])
    async def detail() -> dict:
        try:
            supervisor = configured()
            await supervisor.refresh()
            return {"signals": supervisor.snapshot()}
        except (HubError, OSError) as exc:
            raise http_error(exc) from exc

    @app.post("/api/fleet/signals/{signal_id}/command", tags=["signals"])
    async def command(signal_id: str, body: SignalCommandRequest,
                      principal: SitePrincipal = Depends(require_operator)) -> dict:
        if body.mode == "manual":
            require_authenticated_operator()
        try:
            return await configured().command(signal_id, body.model_dump(exclude_none=True),
                                              actor=principal.principal_id if auth_configured else None)
        except (HubError, SignalApiError, OSError) as exc:
            raise http_error(exc) from exc

    @app.post("/api/fleet/signals/presence", tags=["signals"])
    async def presence(principal: SitePrincipal = Depends(require_operator)) -> dict:
        require_authenticated_operator()
        try:
            configured().operator_presence(principal.principal_id)
            return {"present": True}
        except HubError as exc:
            raise http_error(exc) from exc
