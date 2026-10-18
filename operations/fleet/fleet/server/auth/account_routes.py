"""D-757 cookie-only account administration; authorization is repeated in each transaction."""
from fastapi import Body, Depends, HTTPException, Request
from fastapi.responses import JSONResponse

from fleet.server.development_session import NO_STORE
from fleet.server.password_session import (
    COOKIE, LoginRateLimited, SessionStorageUnavailable, _storage_unavailable, same_origin)
from fleet.server.site_auth import SitePrincipal


def install_account_routes(app, *, sessions, authorize):
    @app.get("/api/fleet/auth/setup", tags=["fleet-auth"])
    def setup(request: Request, principal: SitePrincipal = Depends(authorize)):
        if (getattr(request.state, "site_auth_via", None) != "cookie"
                or principal.password_change_required
                or not principal.permits_site("accounts.manage", {"policy-admin"})
                or not (same_origin(request) or (
                    request.headers.get("origin") is None
                    and request.headers.get("sec-fetch-site") == "same-origin"))):
            raise HTTPException(403, detail={"code": "ACCOUNT_ADMIN_REQUIRED"}, headers=NO_STORE)
        authority = app.state.account_authority
        return JSONResponse({
            "configured": authority is not None,
            "issuer": authority.issuer if authority else None,
            "clients": [{"client_id": name, "redirect_uris": list(settings["redirect_uris"]),
                         "resources": list(settings["resources"])}
                        for name, settings in sorted(authority.clients.items())] if authority else [],
        }, headers=NO_STORE)

    def manager(request: Request, principal: SitePrincipal = Depends(authorize)):
        local_read = (request.method in {"GET", "HEAD"} and request.headers.get("origin") is None
                      and request.headers.get("sec-fetch-site") == "same-origin")
        if getattr(request.state, "site_auth_via", None) != "cookie" or not (local_read or same_origin(request)):
            raise HTTPException(403, detail={"code": "ACCOUNT_ADMIN_REQUIRED",
                                             "message": "same-origin account manager cookie required"})
        expected = request.headers.get('x-rosy-session')
        if expected is not None:
            try:
                current = sessions.account_context(request.cookies[COOKIE])
            except SessionStorageUnavailable:
                raise _storage_unavailable() from None
            if not current or current['session_family'] != expected:
                raise HTTPException(403, detail={'code':'ACCOUNT_CHANGED', 'message':'browser account changed'})
        return request.cookies[COOKIE]

    def call(operation, *args, status=200, **kwargs):
        try:
            return JSONResponse(operation(*args, **kwargs), status_code=status, headers=NO_STORE)
        except PermissionError:
            raise HTTPException(403, detail={"code": "ACCOUNT_ADMIN_REQUIRED", "message": "accounts.manage required"})
        except KeyError:
            raise HTTPException(404, detail={"code": "ACCOUNT_NOT_FOUND", "message": "account not found"})
        except ValueError as exc:
            code = "REVISION_CONFLICT" if "revision conflict" in str(exc) else "INVALID_REQUEST"
            raise HTTPException(409 if code == "REVISION_CONFLICT" else 422,
                                detail={"code": code, "message": str(exc)}) from None
        except LoginRateLimited:
            raise HTTPException(429, headers={"Retry-After": "1"}, detail={"code": "RATE_LIMITED"}) from None
        except SessionStorageUnavailable:
            raise _storage_unavailable() from None

    def fields(payload, required, optional=()):
        if not required <= set(payload) or set(payload) - required - set(optional):
            raise HTTPException(422, detail={"code": "INVALID_REQUEST", "message": "invalid account fields"})

    @app.get("/api/fleet/auth/accounts", tags=["fleet-auth"])
    def accounts(value=Depends(manager)):
        return call(sessions.list_accounts, value)

    @app.post("/api/fleet/auth/accounts", tags=["fleet-auth"], status_code=201)
    def create(payload: dict = Body(...), value=Depends(manager)):
        fields(payload, {"login", "principal_id", "role", "password", "grants"})
        return call(sessions.create_account, value, status=201, **payload)

    @app.patch("/api/fleet/auth/accounts/{account_id}", tags=["fleet-auth"])
    def update(account_id: str, payload: dict = Body(...), value=Depends(manager)):
        fields(payload, {"revision"}, {"role", "grants", "enabled"})
        return call(sessions.update_account, value, account_id, **payload)

    @app.post("/api/fleet/auth/accounts/{account_id}/reset-password", tags=["fleet-auth"])
    def reset(account_id: str, payload: dict = Body(...), value=Depends(manager)):
        fields(payload, {"revision", "password"})
        return call(sessions.reset_account_password, value, account_id, **payload)

    @app.post("/api/fleet/auth/accounts/{account_id}/revoke-sessions", tags=["fleet-auth"])
    def revoke(account_id: str, payload: dict = Body(...), value=Depends(manager)):
        fields(payload, {"revision"})
        return call(sessions.revoke_account_sessions, value, account_id, **payload)
