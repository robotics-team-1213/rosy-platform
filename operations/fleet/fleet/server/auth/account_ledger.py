"""D-757 account and session transactions in Fleet's existing SQLite database."""
from __future__ import annotations

import json
import re
import secrets
import sqlite3
from contextlib import closing, contextmanager, nullcontext

from core_common.protocol.account_access import AccountGrant, RESOURCE_PATTERN

from fleet.server.site_auth import SitePrincipal
from fleet.server.site_users import _LOGIN, hash_password, verify_password

_RESOURCE = re.compile(RESOURCE_PATTERN)


def validate_grants(grants):
    if not isinstance(grants, list) or len(grants) > 256:
        raise ValueError("invalid grants")
    resources = set()
    for grant in grants:
        AccountGrant.model_validate(grant)
        if grant["resource"] in resources:
            raise ValueError("duplicate resource grant")
        resources.add(grant["resource"])
    return json.dumps(grants, separators=(",", ":"))


def public(row):
    return {"account_id": row["account_id"], "login": row["login"], "principal_id": row["principal_id"],
            "role": row["role"], "enabled": bool(row["enabled"]), "revision": row["revision"],
            "display_name": row["display_name"], "password_change_required": bool(row["change_required"]),
            "grants": json.loads(row["grants"])}


class AccountLedger:
    def __init__(self, sessions):
        self.sessions = sessions
        with self.db() as db:
            db.execute("""CREATE TABLE IF NOT EXISTS rosy_account_authority (
                singleton INTEGER PRIMARY KEY CHECK(singleton=1), site_id TEXT NOT NULL)""")
            db.execute("""CREATE TABLE IF NOT EXISTS rosy_accounts (
                account_id TEXT PRIMARY KEY, login TEXT NOT NULL UNIQUE, principal_id TEXT NOT NULL UNIQUE,
                role TEXT NOT NULL, password_scrypt TEXT NOT NULL, change_required INTEGER NOT NULL,
                enabled INTEGER NOT NULL, revision INTEGER NOT NULL, display_name TEXT NOT NULL,
                grants TEXT NOT NULL)""")
            db.execute("""CREATE TABLE IF NOT EXISTS rosy_account_sessions (
                session_sha256 TEXT PRIMARY KEY, account_id TEXT NOT NULL, revision INTEGER NOT NULL,
                session_family TEXT NOT NULL UNIQUE)""")
            db.execute("""CREATE TABLE IF NOT EXISTS rosy_account_audit (
                actor_account_id TEXT NOT NULL, target_account_id TEXT NOT NULL, operation TEXT NOT NULL,
                previous_revision INTEGER NOT NULL, next_revision INTEGER NOT NULL, created_at REAL NOT NULL)""")
            columns = {row[1] for row in db.execute("PRAGMA table_info(rosy_account_audit)")}
            for name, default in (("before_state", "{}"), ("after_state", "{}"), ("outcome", "legacy")):
                if name not in columns:
                    db.execute(f"ALTER TABLE rosy_account_audit ADD COLUMN {name} TEXT NOT NULL DEFAULT '{default}'")
            row = db.execute("SELECT site_id FROM rosy_account_authority WHERE singleton=1").fetchone()
            self.site_id = row[0] if row else None

    @property
    def active(self):
        return self.site_id is not None

    @contextmanager
    def db(self, *, write=False):
        from fleet.server.password_session import SessionStorageUnavailable
        try:
            with closing(self.sessions._connect()) as db, db:
                if write:
                    db.execute("BEGIN IMMEDIATE")
                yield db
        except sqlite3.IntegrityError:
            raise ValueError("account identity already exists") from None
        except sqlite3.Error:
            raise SessionStorageUnavailable() from None

    def bootstrap(self, admin_login, site_id):
        if (not isinstance(site_id, str) or not _RESOURCE.fullmatch("site:" + site_id)
                or admin_login not in self.sessions._logins):
            raise ValueError("explicit existing admin login and site id required")
        with self.db(write=True) as db:
            if db.execute("SELECT 1 FROM rosy_account_authority").fetchone():
                raise ValueError("account authority already activated")
            overrides = {r["login"]: dict(r) for r in
                         db.execute("SELECT * FROM fleet_console_passwords")}
            for login, source in self.sessions._logins.items():
                override = overrides.get(login)
                if override and override["source_sha256"] != self.sessions._sources[login]:
                    identities = {r[0] for r in db.execute(
                        "SELECT principal_id FROM fleet_console_sessions WHERE login=? UNION "
                        "SELECT principal_id FROM fleet_console_profiles WHERE login=?", (login, login))}
                    if identities != {source["principal_id"]}:
                        raise ValueError("ambiguous account identity during password migration")
                encoded = override["password_scrypt"] if override else source["password_scrypt"]
                profile = db.execute("SELECT display_name FROM fleet_console_profiles WHERE login=? "
                                     "AND principal_id=?", (login, source["principal_id"])).fetchone()
                capabilities = ["fleet.read"]
                if source["role"] == "operator":
                    capabilities.append("fleet.operate")
                elif source["role"] == "policy-admin":
                    capabilities.append("fleet.policy")
                if login == admin_login:
                    capabilities.append("accounts.manage")
                grants = [{"resource": "site:" + site_id, "capabilities": capabilities}]
                account_id = secrets.token_urlsafe(24)
                db.execute("INSERT INTO rosy_accounts VALUES (?,?,?,?,?,?,?,?,?,?)", (
                    account_id, login, source["principal_id"], source["role"], encoded,
                    int(verify_password(login, encoded) or verify_password(login + "!", encoded)),
                    1, 1, profile[0] if profile else login,
                    validate_grants(grants)))
            actor = db.execute("SELECT account_id FROM rosy_accounts WHERE login=?", (admin_login,)).fetchone()[0]
            for row in db.execute("SELECT account_id FROM rosy_accounts").fetchall():
                self.audit(db, actor, row[0], "migrate", 0, 1)
            db.execute("INSERT INTO rosy_account_authority VALUES (1,?)", (site_id,))
            db.execute("DELETE FROM fleet_console_sessions")
        self.site_id = site_id
        self.sessions._cache.clear()

    def account(self, login):
        with self.db() as db:
            row = db.execute("SELECT * FROM rosy_accounts WHERE login=? AND enabled=1", (login,)).fetchone()
            return dict(row) if row else None

    def principal_for(self, row, *, fingerprint="", site_id=None):
        return SitePrincipal(row["principal_id"], row["role"], bool(row["change_required"]), fingerprint,
                             row["account_id"], tuple((g["resource"], tuple(g["capabilities"]))
                                                      for g in json.loads(row["grants"])), "site:" + (site_id or self.site_id))

    @staticmethod
    def credential_revision(row):
        from fleet.server.password_session import _digest
        return _digest(row["password_scrypt"] + "\0" + str(row["revision"]))

    def session_row(self, db, key):
        from fleet.server.password_session import ABSOLUTE_S, IDLE_S, REMEMBER_S, _digest
        row = db.execute("""SELECT a.*, s.created_at, s.last_used_at, s.remember, s.password_sha256,
            x.session_family, x.revision AS session_revision FROM fleet_console_sessions s
            JOIN rosy_account_sessions x ON x.session_sha256=s.session_sha256
            JOIN rosy_accounts a ON a.account_id=x.account_id WHERE s.session_sha256=?""", (key,)).fetchone()
        if row is None:
            return None
        row = dict(row)
        row["expires"] = min(row["created_at"] + ABSOLUTE_S,
                             row["last_used_at"] + (REMEMBER_S if row["remember"] else IDLE_S))
        if (not row["enabled"] or row["revision"] != row["session_revision"]
                or row["password_sha256"] != _digest(row["password_scrypt"])
                or self.sessions._clock() >= row["expires"]):
            return None
        return row

    def insert_session(self, db, row, remember):
        from fleet.server.password_session import _digest
        value, family, now = secrets.token_urlsafe(32), secrets.token_urlsafe(24), self.sessions._clock()
        db.execute("INSERT INTO fleet_console_sessions VALUES (?,?,?,?,?,?,?,?)", (
            _digest(value), row["login"], row["principal_id"], row["role"],
            _digest(row["password_scrypt"]), now, now, int(remember)))
        db.execute("INSERT INTO rosy_account_sessions VALUES (?,?,?,?)", (
            _digest(value), row["account_id"], row["revision"], family))
        return value

    def issue(self, login, remember, verified, replacing=None):
        from fleet.server.password_session import StalePasswordCheck, _digest
        with self.db(write=True) as db:
            row = db.execute("SELECT * FROM rosy_accounts WHERE login=? AND enabled=1", (login,)).fetchone()
            if (row is None or verified is None or verified.account_id != row["account_id"]
                    or verified.password_fingerprint != self.credential_revision(row)):
                raise StalePasswordCheck()
            previous = self.session_row(db, _digest(replacing)) if replacing else None
            if previous:
                self.revoke_family(previous["session_family"], db=db)
            return self.insert_session(db, row, remember)

    def principal(self, value, allow_stale=False):
        from fleet.server.password_session import SessionStorageUnavailable, _digest, _iso, _TOUCH_EVERY_S
        key, now = _digest(value), self.sessions._clock()
        try:
            with self.db() as db:
                row = self.session_row(db, key)
                if row and now - row["last_used_at"] >= _TOUCH_EVERY_S:
                    db.execute("UPDATE fleet_console_sessions SET last_used_at=? WHERE session_sha256=?", (now, key))
        except SessionStorageUnavailable:
            cached = self.sessions._cache.get(key)
            if not (allow_stale and cached and cached.get("account_id") and now < cached["expires"]):
                raise
            row = cached
        if row is None:
            self.sessions._forget(key)
            return None
        if self.sessions._tombstoned(key):
            return None
        self.sessions._remember(key, row, now)
        return self.principal_for(row), _iso(row["expires"])

    def context(self, value=None, *, family=None, db=None):
        from fleet.server.password_session import _digest
        with nullcontext(db) if db is not None else self.db() as db:
            key = _digest(value) if value else None
            if family is not None:
                found = db.execute("SELECT session_sha256 FROM rosy_account_sessions WHERE session_family=?",
                                   (family,)).fetchone()
                key = found[0] if found else None
            row = self.session_row(db, key)
            if not row or row["change_required"]:
                return None
            return {**public(row), "session_family": row["session_family"]}

    def revoke_family(self, family, db=None):
        with nullcontext(db) if db is not None else self.db(write=True) as db:
            keys = db.execute("SELECT session_sha256 FROM rosy_account_sessions WHERE session_family=?",
                              (family,)).fetchall()
            db.execute("DELETE FROM fleet_console_sessions WHERE session_sha256 IN "
                       "(SELECT session_sha256 FROM rosy_account_sessions WHERE session_family=?)", (family,))
            db.execute("DELETE FROM rosy_account_sessions WHERE session_family=?", (family,))
            for key in keys:
                self.sessions._forget(key[0], revoked=True)

    def audit(self, db, actor, target, operation, previous, following, *, before=None):
        after = db.execute("SELECT * FROM rosy_accounts WHERE account_id=?", (target,)).fetchone()
        db.execute("INSERT INTO rosy_account_audit VALUES (?,?,?,?,?,?,?,?,?)", (
            actor, target, operation, previous, following, self.sessions._clock(),
            json.dumps(public(before) if before is not None else {}), json.dumps(public(after)), "success"))

    def list_audit(self, value):
        with self.db() as db:
            self.require_manager(db, value)
            rows = []
            for record in db.execute("SELECT * FROM rosy_account_audit ORDER BY rowid"):
                row = dict(record)
                row["before"] = json.loads(row.pop("before_state"))
                row["after"] = json.loads(row.pop("after_state"))
                rows.append(row)
            return rows

    def require_manager(self, db, value):
        from fleet.server.password_session import _digest
        row = self.session_row(db, _digest(value))
        if (not row or row["change_required"] or not any(
                g["resource"] == "site:" + self.site_id and "accounts.manage" in g["capabilities"]
                for g in json.loads(row["grants"]))):
            raise PermissionError("accounts.manage cookie session required")
        return row["account_id"]

    def list_accounts(self, value):
        with self.db() as db:
            self.require_manager(db, value)
            return [public(row) for row in db.execute("SELECT * FROM rosy_accounts ORDER BY login")]

    def create(self, value, *, login, principal_id, role, password, grants):
        if (not isinstance(login, str) or not _LOGIN.fullmatch(login)
                or not isinstance(principal_id, str) or not 1 <= len(principal_id) <= 96
                or principal_id != principal_id.strip() or any(ord(c) < 32 for c in principal_id)
                or not isinstance(role, str) or role not in {"viewer", "operator", "policy-admin"}):
            raise ValueError("invalid account")
        encoded_grants = validate_grants(grants)
        with self.db() as db:
            self.require_manager(db, value)
        encoded = self.encode(password, login)
        with self.db(write=True) as db:
            actor = self.require_manager(db, value)
            account_id = secrets.token_urlsafe(24)
            db.execute("INSERT INTO rosy_accounts VALUES (?,?,?,?,?,?,?,?,?,?)", (
                account_id, login, principal_id, role, encoded, 1, 1, 1, login, encoded_grants))
            self.audit(db, actor, account_id, "create", 0, 1)
            return public(db.execute("SELECT * FROM rosy_accounts WHERE account_id=?", (account_id,)).fetchone())

    @staticmethod
    def encode(password, login=None):
        from fleet.server.password_session import LoginRateLimited, _SCRYPT_SLOTS, _SCRYPT_WAIT_S
        if (not isinstance(password, str) or password == login
                or not (8 <= len(password) <= 1024
                        or (isinstance(login, str) and password == login + "!"))):
            raise ValueError("invalid password")
        if not _SCRYPT_SLOTS.acquire(timeout=_SCRYPT_WAIT_S):
            raise LoginRateLimited()
        try:
            return hash_password(password)
        finally:
            _SCRYPT_SLOTS.release()

    def mutate(self, value, account_id, revision, changes, *, operation="update"):
        if (type(revision) is not int or revision < 1 or not changes and operation == "update"
                or set(changes) - {"role", "grants", "enabled", "password_scrypt", "change_required"}):
            raise ValueError("invalid changes or revision")
        changes = dict(changes)
        if "role" in changes and (not isinstance(changes["role"], str)
                                  or changes["role"] not in {"viewer", "operator", "policy-admin"}):
            raise ValueError("invalid role")
        if "enabled" in changes and type(changes["enabled"]) is not bool:
            raise ValueError("invalid enabled")
        if "grants" in changes:
            changes["grants"] = validate_grants(changes["grants"])
        with self.db(write=True) as db:
            actor = self.require_manager(db, value)
            before = db.execute("SELECT * FROM rosy_accounts WHERE account_id=?", (account_id,)).fetchone()
            if before is None:
                raise KeyError(account_id)
            if before["revision"] != revision:
                raise ValueError("account revision conflict")
            updated = {**dict(before), **changes, "revision": revision + 1}
            columns = ("role", "grants", "enabled", "password_scrypt", "change_required", "revision", "account_id")
            db.execute("UPDATE rosy_accounts SET role=?,grants=?,enabled=?,password_scrypt=?,change_required=?,"
                       "revision=? WHERE account_id=?", tuple(updated[k] for k in columns))
            managers = [r for r in db.execute("SELECT grants FROM rosy_accounts WHERE enabled=1")
                        if any(g["resource"] == "site:" + self.site_id and "accounts.manage" in g["capabilities"]
                               for g in json.loads(r[0]))]
            if not managers:
                raise ValueError("cannot remove last active account manager")
            self.delete_sessions(db, account_id)
            self.audit(db, actor, account_id, operation, revision, revision + 1, before=before)
            return public(updated)

    def delete_sessions(self, db, account_id):
        db.execute("DELETE FROM fleet_console_sessions WHERE session_sha256 IN "
                   "(SELECT session_sha256 FROM rosy_account_sessions WHERE account_id=?)", (account_id,))
        db.execute("DELETE FROM rosy_account_sessions WHERE account_id=?", (account_id,))
        with self.sessions._lock:
            for key in [k for k, row in self.sessions._cache.items() if row.get("account_id") == account_id]:
                self.sessions._forget(key, revoked=True)

    def reset_password(self, value, account_id, revision, password):
        with self.db() as db:
            self.require_manager(db, value)
            row = db.execute("SELECT login FROM rosy_accounts WHERE account_id=?", (account_id,)).fetchone()
            if not row:
                raise KeyError(account_id)
        return self.mutate(value, account_id, revision,
                           {"password_scrypt": self.encode(password, row[0]), "change_required": 1}, operation="reset")

    def change_password(self, value, password, current_password):
        from fleet.server.password_session import (
            CurrentPasswordIncorrect, LoginRateLimited, StalePasswordCheck, _digest, _SCRYPT_SLOTS, _SCRYPT_WAIT_S)
        key = _digest(value)
        with self.db() as db:
            snapshot = self.session_row(db, key)
        if snapshot is None:
            raise StalePasswordCheck()
        if not snapshot["change_required"] and current_password is None:
            raise ValueError("current password required")
        if not _SCRYPT_SLOTS.acquire(timeout=_SCRYPT_WAIT_S):
            raise LoginRateLimited()
        try:
            if current_password is not None and not verify_password(current_password, snapshot["password_scrypt"]):
                raise CurrentPasswordIncorrect()
            if (not isinstance(password, str) or not 8 <= len(password) <= 1024
                    or password in (snapshot["login"], snapshot["login"] + "!")
                    or verify_password(password, snapshot["password_scrypt"])):
                raise ValueError("invalid new password")
            encoded = hash_password(password)
        finally:
            _SCRYPT_SLOTS.release()
        with self.db(write=True) as db:
            row = self.session_row(db, key)
            if not row or row["revision"] != snapshot["revision"]:
                raise StalePasswordCheck()
            updated = {**row, "password_scrypt": encoded, "change_required": 0, "revision": row["revision"] + 1}
            db.execute("UPDATE rosy_accounts SET password_scrypt=?,change_required=0,revision=? WHERE account_id=?",
                       (encoded, updated["revision"], row["account_id"]))
            self.delete_sessions(db, row["account_id"])
            self.audit(db, row["account_id"], row["account_id"], "password", row["revision"],
                       updated["revision"], before=row)
            return self.insert_session(db, updated, row["remember"]), bool(row["remember"])

    def profile(self, value, display_name=None):
        from fleet.server.password_session import StalePasswordCheck, _digest
        with self.db(write=display_name is not None) as db:
            row = self.session_row(db, _digest(value))
            if not row or row["change_required"]:
                raise StalePasswordCheck()
            if display_name is not None:
                db.execute("UPDATE rosy_accounts SET display_name=? WHERE account_id=?",
                           (display_name, row["account_id"]))
                self.audit(db, row["account_id"], row["account_id"], "profile", row["revision"],
                           row["revision"], before=row)
                row["display_name"] = display_name
            principal = row["principal_id"]
            return {"login": row["login"], "principal_id": principal, "role": row["role"],
                    "display_name": row["display_name"], "grants": json.loads(row["grants"]),
                    "email": principal if principal.count("@") == 1 and all(principal.split("@")) else None}
