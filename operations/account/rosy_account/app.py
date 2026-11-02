"""Independent Account composition: authority, sessions, profile, administration and audit."""
from pathlib import Path
import sqlite3
from types import SimpleNamespace

from fastapi import FastAPI, HTTPException, Request

from .account_authority import AccountAuthority
from .account_authority_routes import install_account_authority_routes
from .account_config import load_account_config
from .audit import AccountAudit, install_audit
from .http import NO_STORE
from .migration import validate_database
from .password_session import PasswordSessions
from .password_routes import install_password_routes
from .static import install_static


def create_app(*, config, db, web_root, web_common):
    settings = load_account_config(config)
    site_id = settings.pop('site_id')
    admin = settings.pop('bootstrap_admin_login', None)
    # Production starts with an explicitly migrated authority; never bootstrap a second user store.
    if admin is not None or not PasswordSessions.accounts_active(db):
        raise ValueError('standalone Account requires an activated migrated database without bootstrap configuration')
    validate_database(db)
    password_sessions = PasswordSessions(Path(db), {})
    if password_sessions._ledger.site_id != site_id:
        raise ValueError('Account configured site does not match the activated authority')
    authority = AccountAuthority(db, **settings,
        resolve_family=lambda connection, family: password_sessions.context_by_family(family, db=connection),
        revoke_family=lambda connection, family: password_sessions.revoke_family(family, db=connection))
    store = AccountAudit(db)
    app = FastAPI(title='Rosy Account')
    app.state.account_authority = authority
    app.state.password_sessions = password_sessions
    install_audit(app, store)

    def authorize(request: Request):
        principal = password_sessions.authenticate(request)
        if principal is None:
            raise HTTPException(401, detail={'code': 'UNAUTHORIZED'}, headers=NO_STORE)
        request.state.site_principal, request.state.site_auth_via = principal, 'cookie'
        if (principal.password_change_required and request.url.path not in {
                '/api/fleet/auth/session', '/api/fleet/auth/logout', '/api/fleet/auth/change-password'}):
            raise HTTPException(403, detail={'code': 'PASSWORD_CHANGE_REQUIRED'}, headers=NO_STORE)
        if request.method not in {'GET', 'HEAD', 'OPTIONS'}:
            try:
                request.state.site_api_audit_id = store.begin_api_audit(
                    principal_id=principal.principal_id, role=principal.role,
                    method=request.method, path=request.url.path)
            except (OSError, sqlite3.Error, ValueError):
                raise HTTPException(503, detail={'code': 'AUDIT_STORAGE_UNAVAILABLE'}, headers=NO_STORE) from None
        return principal

    install_password_routes(app, sessions=password_sessions, authorize=authorize,
                            task_service=SimpleNamespace(store=store), trust_forwarded=True)
    install_account_authority_routes(app, sessions=password_sessions, authority=authority)
    install_static(app, web_root, web_common)

    @app.get('/api/fleet/auth/connection')
    def connection():
        return {'mode': 'paired', 'password_login': True}

    @app.get('/healthz')
    def health():
        return {'status': 'ok'}

    return app
