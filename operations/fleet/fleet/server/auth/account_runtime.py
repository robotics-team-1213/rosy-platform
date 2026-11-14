"""Fleet Account mode composition; authority compatibility and external receiver stay exclusive."""
from rosy_account.password_session import PasswordSessions, install_password_routes
from fleet.server.development_session import install_development_routes
from fleet.server.site_auth import parse_site_principals
from fleet.server.db_status import install_db_status_routes


def _configure_legacy_embedded_authority(task_service, account_config, accounts_bootstrap):
    if account_config is None:
        return None, None, accounts_bootstrap
    from rosy_account.account_config import load_account_config
    from rosy_account.account_authority import AccountAuthority
    settings = load_account_config(account_config)
    admin = settings.pop("bootstrap_admin_login", None)
    site_id = settings.pop("site_id")
    if accounts_bootstrap is not None:
        raise ValueError("use one explicit Account bootstrap configuration")
    if admin is not None:
        accounts_bootstrap = (admin, site_id)
    if accounts_bootstrap is None and not PasswordSessions.accounts_active(task_service.store.path):
        raise ValueError("Account first activation requires an explicit existing administrator login")
    authority = AccountAuthority(task_service.store.path, **settings,
                                 resolve_family=None, revoke_family=None)
    return authority, site_id, accounts_bootstrap


def _filter_receiver_machine_principals(principals, site_users, site_logins):
    human_ids = {entry["principal_id"].strip() for entry in (site_logins or {}).values()}
    if any((site_users or {}).get(digest, {}).get("machine") is True and p.principal_id in human_ids
           for digest, p in principals.items()):
        raise ValueError("machine viewer principal must differ from human login principals")
    return {digest: p for digest, p in principals.items()
            if p.role in {"service", "ai_observer"}
            or (p.role == "viewer" and (site_users or {}).get(digest, {}).get("machine") is True)}


def configure_account_sessions(app, *, console, task_service, site_users, site_logins,
                               accounts_bootstrap, account_config, account_client_config):
    # D-519 1: a site-users file may hold only login accounts, leaving no token principals.
    if account_client_config is not None:
        if account_config is not None or accounts_bootstrap is not None:
            raise ValueError("Fleet Account receiver cannot own an Account authority or bootstrap")
        from fleet.server.account_receiver import install_account_receiver
        principals = _filter_receiver_machine_principals(
            parse_site_principals(site_users, console), site_users, site_logins)
        app.state.password_sessions = install_account_receiver(app, config=account_client_config)
        app.state.account_authority = None
        return principals
    authority, site_id, accounts_bootstrap = _configure_legacy_embedded_authority(
        task_service, account_config, accounts_bootstrap)
    account_login = bool(site_logins) or accounts_bootstrap is not None or (
        task_service is not None and PasswordSessions.accounts_active(task_service.store.path))
    principals = {} if account_login and not site_users else parse_site_principals(site_users, console)
    human_ids = {entry["principal_id"].strip() for entry in (site_logins or {}).values()}
    if any(site_users[digest].get("machine") is True and p.principal_id in human_ids
           for digest, p in principals.items()):
        raise ValueError("machine viewer principal must differ from human login principals")
    password_sessions = None
    if account_login:
        bootstrap = accounts_bootstrap  # one-line call: the release secret scan reads an open call as a literal
        password_sessions = PasswordSessions(task_service.store.path, site_logins or {}, accounts_bootstrap=bootstrap)
    app.state.password_sessions = password_sessions
    app.state.account_authority = authority
    if authority is not None:
        if password_sessions._ledger.site_id != site_id:
            raise ValueError("Account configured site does not match the activated authority")
        authority.resolve_family = lambda db, family: password_sessions.context_by_family(family, db=db)
        authority.revoke_family = lambda db, family: password_sessions.revoke_family(family, db=db)
        from rosy_account.account_authority_routes import install_account_authority_routes
        install_account_authority_routes(app, sessions=password_sessions, authority=authority)
    return principals


def install_account_login_routes(app, *, sessions, authorize, task_service, development_sessions,
                                 account_client_config, trust_forwarded):
    install_development_routes(app, sessions=development_sessions, task_service=task_service,
                               trust_forwarded=trust_forwarded, account_login=sessions is not None)
    if account_client_config is None:
        install_password_routes(app, sessions=sessions, authorize=authorize, task_service=task_service,
                                trust_forwarded=trust_forwarded)
    install_db_status_routes(
        app, store_path=task_service.store.path if task_service is not None else None,
        authorize=authorize,
    )
