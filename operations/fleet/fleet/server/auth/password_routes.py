"""D-519/D-757 Fleet password login, session and profile HTTP routes."""

from __future__ import annotations

import sqlite3
import unicodedata
from typing import Optional

from fastapi import Body, Depends, HTTPException, Request, Response
from fastapi.responses import JSONResponse

from fleet.server.development_session import NO_STORE, client_address
from fleet.server.password_session import (
    COOKIE, REMEMBER_S, CurrentPasswordIncorrect, LoginRateLimited,
    PasswordSessions, SessionStorageUnavailable, StalePasswordCheck,
    _storage_unavailable, same_origin,
)
from fleet.server.site_auth import SitePrincipal
from fleet.server.site_users import _LOGIN


def _set_cookie(response: Response, value: str, *, remember: bool, managed: bool = False) -> None:
    response.set_cookie(COOKIE, value, max_age=int(REMEMBER_S) if remember else None,
                        path="/", secure=True, httponly=True, samesite="lax" if managed else "strict")


def _begin_audit(request: Request, task_service, principal: SitePrincipal) -> None:
    request.state.site_api_audit_id = task_service.store.begin_api_audit(
        principal_id=principal.principal_id, role=principal.role,
        method=request.method, path=request.url.path)


def install_password_routes(app, *, sessions: Optional[PasswordSessions], authorize, task_service,
                            trust_forwarded: bool) -> None:
    @app.get("/api/fleet/auth/session", tags=["fleet-auth"])
    def fleet_auth_session(request: Request, principal: SitePrincipal = Depends(authorize)) -> JSONResponse:
        managed = ({"account_id": principal.account_id, "site_resource": principal.site_resource,
                    "grants": [{"resource": resource, "capabilities": list(capabilities)}
                               for resource, capabilities in principal.grants]} if principal.account_id else {})
        if principal.account_id and not principal.password_change_required:
            try:
                context = sessions.account_context(request.cookies.get(COOKIE, ''))
            except SessionStorageUnavailable:
                raise _storage_unavailable() from None
            if not context:
                raise HTTPException(401, detail={'code':'ACCOUNT_CHANGED'})
            managed.update(session_family=context['session_family'], revision=context['revision'])
        return JSONResponse(headers=NO_STORE, content={
            "principal_id": principal.principal_id, "role": principal.role,
            "via": getattr(request.state, "site_auth_via", "bearer"),
            "expires_at": getattr(request.state, "site_auth_expires_at", None),
            "password_change_required": principal.password_change_required,
            **managed,
        })

    if sessions is None:
        return  # D-519: no login entries -> no login/logout routes, so both are 404

    @app.post("/api/fleet/auth/login", status_code=204, tags=["fleet-auth"])
    def fleet_auth_login(request: Request, payload: dict = Body(...)) -> Response:
        login, password, remember = payload.get("login"), payload.get("password"), payload.get("remember", False)
        if (not isinstance(login, str) or not isinstance(password, str) or len(password) > 1024
                or not isinstance(remember, bool)):
            raise HTTPException(status_code=422, detail={
                "code": "INVALID_REQUEST", "message": "login, password and remember are required"})
        if request.headers.get("origin") is not None and not same_origin(request):
            raise HTTPException(status_code=403, detail={
                "code": "CSRF_REJECTED", "message": "login must come from this console"})
        address = client_address(request, trust_forwarded=trust_forwarded)
        attempted = SitePrincipal(f"login:{login if _LOGIN.fullmatch(login) else '?'}", "viewer")
        try:
            principal = sessions.check(address, login, password)
        except SessionStorageUnavailable:
            raise _storage_unavailable() from None
        except LoginRateLimited:
            if sessions.audit_limit(address):
                try:
                    _begin_audit(request, task_service, attempted)
                except (OSError, sqlite3.Error, ValueError):
                    pass  # the 429 stands either way
            raise HTTPException(status_code=429, headers={"Retry-After": "60"}, detail={
                "code": "RATE_LIMITED", "message": "too many failed logins; wait a minute"}) from None
        try:
            # D-519 2: success under the principal, failure as login:<name>; the middleware closes it.
            _begin_audit(request, task_service, principal or attempted)
        except (OSError, sqlite3.Error, ValueError):
            raise HTTPException(status_code=503, detail={
                "code": "AUDIT_STORAGE_UNAVAILABLE", "message": "site command audit is unavailable",
            }) from None
        if principal is None:
            raise HTTPException(status_code=401, detail={
                "code": "LOGIN_FAILED", "message": "login or password is incorrect"})
        try:
            value = sessions.issue(login, remember=remember, verified=principal,
                                   replacing=request.cookies.get(COOKIE))
        except SessionStorageUnavailable:
            raise _storage_unavailable() from None
        except StalePasswordCheck:
            raise HTTPException(status_code=401, detail={
                "code": "LOGIN_FAILED", "message": "login or password is incorrect"}) from None
        response = Response(status_code=204, headers=NO_STORE)
        _set_cookie(response, value, remember=remember, managed=sessions._ledger.active)
        return response

    from fleet.server.account_routes import install_account_routes
    install_account_routes(app, sessions=sessions, authorize=authorize)

    @app.post("/api/fleet/auth/change-password", status_code=204, tags=["fleet-auth"])
    def fleet_auth_change_password(request: Request, payload: dict = Body(...),
                                   principal: SitePrincipal = Depends(authorize)) -> Response:
        if getattr(request.state, "site_auth_via", None) != "cookie":
            raise HTTPException(status_code=403, detail={
                "code": "PASSWORD_CHANGE_NOT_REQUIRED", "message": "a cookie session is required"})
        password = payload.get("password")
        fields = {"password"} if principal.password_change_required else {"password", "current_password"}
        current_password = payload.get("current_password")
        if (set(payload) != fields or not isinstance(password, str) or not 8 <= len(password) <= 1024
                or (not principal.password_change_required
                    and (not isinstance(current_password, str) or not 1 <= len(current_password) <= 1024))):
            raise HTTPException(status_code=422, detail={
                "code": "INVALID_REQUEST", "message": "a new password is required"})
        value = request.cookies[COOKIE]
        try:
            replacement, remember = sessions.change_password(value, password, current_password=current_password)
        except CurrentPasswordIncorrect:
            raise HTTPException(status_code=422, detail={
                "code": "CURRENT_PASSWORD_INCORRECT", "message": "current password is incorrect"}) from None
        except ValueError:
            raise HTTPException(status_code=422, detail={
                "code": "INVALID_REQUEST", "message": "choose a different password"}) from None
        except StalePasswordCheck:
            raise HTTPException(status_code=401, detail={
                "code": "UNAUTHORIZED", "message": "initial session expired"}) from None
        except LoginRateLimited:
            raise HTTPException(status_code=429, headers={"Retry-After": "1"}, detail={
                "code": "RATE_LIMITED", "message": "password service is busy"}) from None
        except SessionStorageUnavailable:
            raise _storage_unavailable() from None
        response = Response(status_code=204, headers=NO_STORE)
        _set_cookie(response, replacement, remember=remember, managed=sessions._ledger.active)
        return response

    def own_profile(request: Request, principal: SitePrincipal, display_name: Optional[str] = None) -> JSONResponse:
        if getattr(request.state, "site_auth_via", None) != "cookie":
            raise HTTPException(status_code=403, detail={
                "code": "COOKIE_SESSION_REQUIRED", "message": "a completed cookie login is required"})
        try:
            data = sessions.profile(request.cookies[COOKIE], display_name)
        except StalePasswordCheck:
            raise HTTPException(status_code=401, detail={"code": "UNAUTHORIZED", "message": "session expired"}) from None
        except SessionStorageUnavailable:
            raise _storage_unavailable() from None
        return JSONResponse(data, headers=NO_STORE)

    @app.get("/api/fleet/auth/profile", tags=["fleet-auth"])
    def fleet_auth_profile(request: Request, principal: SitePrincipal = Depends(authorize)) -> JSONResponse:
        return own_profile(request, principal)

    @app.patch("/api/fleet/auth/profile", tags=["fleet-auth"])
    def fleet_auth_profile_update(request: Request, payload: dict = Body(...),
                                  principal: SitePrincipal = Depends(authorize)) -> JSONResponse:
        name = payload.get("display_name")
        if (set(payload) != {"display_name"} or not isinstance(name, str)
                or not 1 <= len(name.strip()) <= 80
                or any(unicodedata.category(char) in {"Cc", "Cs"} for char in name)):
            raise HTTPException(status_code=422, detail={"code": "INVALID_REQUEST", "message": "invalid display name"})
        return own_profile(request, principal, name.strip())

    @app.post("/api/fleet/auth/logout", status_code=204, tags=["fleet-auth"])
    def fleet_auth_logout(request: Request) -> Response:
        value = request.cookies.get(COOKIE)
        if value and not same_origin(request):
            raise HTTPException(status_code=403, detail={
                "code": "CSRF_REJECTED", "message": "cookie requests must come from this console"})
        if value:
            try:
                sessions.revoke(value)
            except SessionStorageUnavailable:
                raise _storage_unavailable() from None
        response = Response(status_code=204, headers=NO_STORE)
        response.delete_cookie(COOKIE, path="/", secure=True, httponly=True, samesite="strict")
        return response
