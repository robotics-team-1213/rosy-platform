"""D-519 / D-962: legacy SQLite session helpers, constants, and error types for ``password_session``."""

from __future__ import annotations

import secrets
import sqlite3
import threading
from contextlib import closing
from hashlib import sha256
from pathlib import Path
from typing import Any, Callable, Optional

from fastapi import HTTPException

from rosy_account.db_policy import enable_wal
from rosy_account.principal import SitePrincipal, legacy_grants
from rosy_account.site_users import hash_password

COOKIE = "rosy_fleet_session"
IDLE_S = 12 * 3600.0
REMEMBER_S = 30 * 86400.0
ABSOLUTE_S = 30 * 86400.0
ADDRESS_FAILURES_PER_MINUTE = 5
LOGIN_FAILURES_PER_MINUTE = 10
_RATE_WINDOW_S = 60.0
_TOUCH_EVERY_S = 60.0  # sliding-expiry writes at most once a minute per session, not per poll
_MAX_TRACKED = 1024
_AUTH_DB_TIMEOUT_S = 5.0  # D-962: WAL readers do not queue behind writers; this backstops a stuck one
_CACHE_S = 60.0  # a cookie validated this recently authenticates from memory
_CACHE_MAX = 256
_SCRYPT_WAIT_S = 1.0
#: Each scrypt holds about 33 MiB; at most two run at once.
_SCRYPT_SLOTS = threading.BoundedSemaphore(2)


def _digest(text: str) -> str:
    return sha256(text.encode("utf-8")).hexdigest()


class SessionStorageUnavailable(Exception):
    """The sessions table could not be read or written."""

class LoginRateLimited(Exception):
    """Too many failed logins, or too many password checks already running."""

class StalePasswordCheck(Exception):
    """The credential changed after verification, or this is not an initial session."""

class CurrentPasswordIncorrect(Exception):
    """The valid session remains usable after an incorrect current password."""


def _storage_unavailable() -> HTTPException:
    return HTTPException(status_code=503, detail={"code": "SESSION_STORAGE_UNAVAILABLE", "message": "console session storage is unavailable"})


def install_password_routes(app, *, sessions: Optional[Any], authorize, task_service, trust_forwarded: bool) -> None:
    """Preserve the session module entry point while HTTP routes live separately."""
    from rosy_account.password_routes import install_password_routes as install
    install(app, sessions=sessions, authorize=authorize, task_service=task_service, trust_forwarded=trust_forwarded)


def init_legacy_session_tables(sessions: Any, accounts_bootstrap, verify_password_fn: Callable[[str, str], bool]) -> None:
    with closing(sessions._connect(timeout=10)) as db, db:
        enable_wal(db)
        db.execute("""CREATE TABLE IF NOT EXISTS fleet_console_sessions (
            session_sha256 TEXT PRIMARY KEY, login TEXT NOT NULL, principal_id TEXT NOT NULL, role TEXT NOT NULL,
            password_sha256 TEXT NOT NULL, created_at REAL NOT NULL, last_used_at REAL NOT NULL, remember INTEGER NOT NULL)""")
        db.execute("CREATE TABLE IF NOT EXISTS fleet_console_passwords (login TEXT PRIMARY KEY, source_sha256 TEXT NOT NULL, password_scrypt TEXT NOT NULL)")
        db.execute("CREATE TABLE IF NOT EXISTS fleet_console_profiles (login TEXT PRIMARY KEY, principal_id TEXT NOT NULL, display_name TEXT NOT NULL)")
        if accounts_bootstrap is not None and not sessions._ledger.active:
            sessions.bootstrap_accounts(*accounts_bootstrap)
        if sessions._ledger.active:
            sessions._required = {}
            return
        for row in db.execute("SELECT * FROM fleet_console_passwords").fetchall():
            if sessions._sources.get(row["login"]) == row["source_sha256"]:
                sessions._logins[row["login"]]["password_scrypt"] = row["password_scrypt"]
            else:
                db.execute("DELETE FROM fleet_console_sessions WHERE login = ?", (row["login"],))
                db.execute("DELETE FROM fleet_console_passwords WHERE login = ?", (row["login"],))
    sessions._required = {
        login: (verify_password_fn(login, account["password_scrypt"])
                or verify_password_fn(login + "!", account["password_scrypt"]))
        for login, account in sessions._logins.items()
    }


def accounts_active_on_disk(path) -> bool:
    if not Path(path).is_file():
        return False
    try:
        with closing(sqlite3.connect(path, timeout=_AUTH_DB_TIMEOUT_S)) as db:
            if not db.execute("SELECT 1 FROM sqlite_master WHERE name='rosy_account_authority'").fetchone():
                return False
            return db.execute("SELECT 1 FROM rosy_account_authority WHERE singleton=1").fetchone() is not None
    except sqlite3.Error:
        raise SessionStorageUnavailable() from None


def rotate_legacy_password(
    sessions: Any, value: str, password: str, current_password: Optional[str], *,
    verify_password_fn: Callable[[str, str], bool],
) -> tuple[str, bool]:
    with sessions._lock:
        cached = sessions._cache.get(_digest(value))
        checked_hash = sessions._logins[cached["login"]]["password_scrypt"] if cached else None
    if checked_hash is None:
        if sessions.principal(value) is None:
            raise StalePasswordCheck()
        with sessions._lock:
            cached = sessions._cache.get(_digest(value))
            if cached is None:
                raise StalePasswordCheck()
            checked_hash = sessions._logins[cached["login"]]["password_scrypt"]
    if not _SCRYPT_SLOTS.acquire(timeout=_SCRYPT_WAIT_S):
        raise LoginRateLimited()
    try:
        current_ok = current_password is None or verify_password_fn(current_password, checked_hash)
        same_password = verify_password_fn(password, checked_hash)
        encoded = hash_password(password)
    finally:
        _SCRYPT_SLOTS.release()
    with sessions._lock:
        now, key = sessions._clock(), _digest(value)
        replacement = secrets.token_urlsafe(32)
        try:
            with closing(sessions._connect()) as db, db:
                db.execute("BEGIN IMMEDIATE")
                row = db.execute("SELECT * FROM fleet_console_sessions WHERE session_sha256 = ?", (key,)).fetchone()
                if (row is None or sessions._tombstoned(key) or sessions._expiry(row, now) is None
                        or row["password_sha256"] != _digest(checked_hash)):
                    raise StalePasswordCheck()
                login = row["login"]
                if not sessions._required[login] and current_password is None:
                    raise ValueError("current password required")
                if not current_ok:
                    raise CurrentPasswordIncorrect()
                if password in (login, login + "!") or same_password or not 8 <= len(password) <= 1024:
                    raise ValueError("invalid new password")
                db.execute("INSERT OR REPLACE INTO fleet_console_passwords VALUES (?,?,?)",
                           (login, sessions._sources[login], encoded))
                db.execute("DELETE FROM fleet_console_sessions WHERE login = ?", (login,))
                fresh = {**dict(row), "password_sha256": _digest(encoded),
                         "created_at": now, "last_used_at": now}
                db.execute("INSERT INTO fleet_console_sessions VALUES (?,?,?,?,?,?,?,?)", (
                    _digest(replacement), login, fresh["principal_id"], fresh["role"],
                    fresh["password_sha256"], now, now, fresh["remember"]))
        except sqlite3.Error:
            raise SessionStorageUnavailable() from None
        sessions._logins[login] = {**sessions._logins[login], "password_scrypt": encoded}
        sessions._required[login] = False
        for cached_key in [k for k, cached in sessions._cache.items() if cached["login"] == login]:
            sessions._forget(cached_key, revoked=True)
        sessions._forget(key, revoked=True)
        sessions._remember(_digest(replacement), fresh, now)
        return replacement, bool(fresh["remember"])


def resolve_legacy_principal(
    sessions: Any, value: str, allow_stale: bool, *, iso_fn: Callable[[float], str]
) -> Optional[tuple[SitePrincipal, str]]:
    key = _digest(value)
    now = sessions._clock()
    with sessions._lock:
        cached = dict(sessions._cache[key]) if key in sessions._cache else None
        if sessions._tombstoned(key):
            return None
    if cached is None or now - cached["validated_at"] >= _CACHE_S:
        try:
            with closing(sessions._connect()) as db:
                found = db.execute("SELECT * FROM fleet_console_sessions WHERE session_sha256 = ?", (key,)).fetchone()
        except sqlite3.Error:
            if not (allow_stale and cached is not None):
                raise SessionStorageUnavailable() from None
            found = None
        else:
            if found is None:
                sessions._forget(key)
                return None
            cached = {name: found[name] for name in (
                "login", "principal_id", "role", "password_sha256", "created_at", "last_used_at", "remember")}
            cached["validated_at"] = now
    if sessions._expiry(cached, now) is None:
        sessions._forget(key)
        sessions._best_effort("DELETE FROM fleet_console_sessions WHERE session_sha256 = ?", (key,))
        return None
    if now - cached["last_used_at"] >= _TOUCH_EVERY_S and sessions._best_effort(
            "UPDATE fleet_console_sessions SET last_used_at = ? WHERE session_sha256 = ?", (now, key)):
        cached["last_used_at"] = now
    sessions._remember(key, cached, cached["validated_at"])
    with sessions._lock:
        expiry = sessions._expiry(cached, now)
        if sessions._tombstoned(key) or expiry is None:
            return None
        return SitePrincipal(cached["principal_id"], cached["role"], sessions._required[cached["login"]],
                             grants=legacy_grants(sessions._logins.get(cached["login"], {}))), iso_fn(expiry)
