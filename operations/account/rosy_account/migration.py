"""Explicit offline extraction: stop the old authority before copying its identity tables."""
from contextlib import closing
import json
import os
from pathlib import Path
import re
import sqlite3
import time
from types import SimpleNamespace

AUTHORITY_TABLES = (
    'fleet_console_sessions', 'fleet_console_passwords', 'fleet_console_profiles',
    'rosy_account_authority', 'rosy_accounts', 'rosy_account_sessions', 'rosy_account_audit',
    'account_oauth_codes', 'account_oauth_refresh', 'account_oauth_access',
)


def validate_authority(db, *, now=None):
    """Reject incomplete authority; classify retained revoked/expired artifacts without deleting them."""
    from .account_ledger import AccountLedger, validate_grants
    from .site_users import _LOGIN, _parse_password_hash
    from core_common.protocol.account_access import grants_for
    now = time.time() if now is None else now
    original_factory, db.row_factory = db.row_factory, sqlite3.Row
    tables = {row[0] for row in db.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    if not set(AUTHORITY_TABLES) <= tables:
        raise ValueError('source does not contain all ten Account authority tables')
    authority = db.execute('SELECT singleton,site_id FROM rosy_account_authority').fetchall()
    if (len(authority) != 1 or authority[0]['singleton'] != 1
            or not re.fullmatch(r'[A-Za-z0-9._-]{1,96}', authority[0]['site_id'])):
        raise ValueError('Account migration requires one valid activated authority')
    site_id, managers = authority[0]['site_id'], 0
    for row in db.execute('SELECT * FROM rosy_accounts'):
        grants = json.loads(row['grants'])
        validate_grants(grants)
        _parse_password_hash(row['password_scrypt'])
        if (not re.fullmatch(r'[A-Za-z0-9._-]{1,128}', row['account_id'])
                or not _LOGIN.fullmatch(row['login']) or row['role'] not in {'viewer', 'operator', 'policy-admin'}
                or row['revision'] < 1 or row['enabled'] not in (0, 1) or row['change_required'] not in (0, 1)):
            raise ValueError('invalid Account revision or state')
        managers += bool(row['enabled'] and any(g['resource'] == 'site:' + site_id
                         and 'accounts.manage' in g['capabilities'] for g in grants))
    if not managers:
        raise ValueError('Account authority must retain an enabled account manager')
    # Reuse the actual runtime family validator without its schema-creating constructor.
    ledger = object.__new__(AccountLedger)
    ledger.sessions, ledger.site_id = SimpleNamespace(_clock=lambda: now), site_id
    contexts, orphan_sessions = {}, 0
    for row in db.execute('''SELECT x.*, s.session_sha256 AS console_id, a.account_id AS account_exists
            FROM rosy_account_sessions x LEFT JOIN fleet_console_sessions s USING(session_sha256)
            LEFT JOIN rosy_accounts a ON a.account_id=x.account_id'''):
        orphan_sessions += row['console_id'] is None or row['account_exists'] is None
        contexts[row['session_family']] = ledger.context(family=row['session_family'], db=db)
    report = {'active_families': sum(value is not None for value in contexts.values()),
              'inactive_families': sum(value is None for value in contexts.values()),
              'orphan_session_links': orphan_sessions, 'inactive_oauth_rows': 0}
    for table in ('account_oauth_codes', 'account_oauth_refresh', 'account_oauth_access'):
        for row in db.execute(f'SELECT * FROM {table}'):
            context = contexts.get(row['family'])
            if (context is None or context['revision'] != row['revision'] or row['expires'] <= now
                    or not grants_for(context['grants'], row['resource'])
                    or (table == 'account_oauth_refresh' and row['spent'])):
                report['inactive_oauth_rows'] += 1
    db.row_factory = original_factory
    return report


def validate_database(path):
    with closing(sqlite3.connect(Path(path).resolve(strict=True).as_uri() + '?mode=ro', uri=True)) as db:
        db.execute('BEGIN')
        return validate_authority(db)


def migrate_authority(source, target):
    """Copy one consistent snapshot, preserve schemas/rows/indexes, refuse existing targets."""
    source, target = Path(source).resolve(strict=True), Path(target).resolve()
    descriptor = os.open(target, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
    os.close(descriptor)
    try:
        with closing(sqlite3.connect(source.as_uri() + '?mode=ro', uri=True)) as old:
            old.execute('BEGIN')
            now = time.time()
            validation = validate_authority(old, now=now)
            schemas = {row[0]: row[1] for row in old.execute(
                "SELECT name,sql FROM sqlite_master WHERE type='table'")}
            if not set(AUTHORITY_TABLES) <= schemas.keys():
                raise ValueError('source does not contain all ten Account authority tables')
            counts = {}
            with closing(sqlite3.connect(target)) as new, new:
                for table in AUTHORITY_TABLES:
                    new.execute(schemas[table])
                    rows = old.execute(f'SELECT * FROM {table}').fetchall()
                    columns = len(old.execute(f'PRAGMA table_info({table})').fetchall())
                    new.executemany(f'INSERT INTO {table} VALUES ({",".join("?" for _ in range(columns))})', rows)
                    copied = new.execute(f'SELECT * FROM {table}').fetchall()
                    if sorted(map(repr, rows)) != sorted(map(repr, copied)):
                        raise ValueError('Account migration row verification failed')
                    counts[table] = len(rows)
                for table, sql in old.execute(
                        "SELECT tbl_name,sql FROM sqlite_master WHERE type='index' AND sql IS NOT NULL"):
                    if table in AUTHORITY_TABLES:
                        new.execute(sql)
                if new.execute('PRAGMA integrity_check').fetchone()[0] != 'ok':
                    raise ValueError('Account migration integrity check failed')
                if validate_authority(new, now=now) != validation:
                    raise ValueError('Account migration relationship verification failed')
            return counts
    except BaseException:
        target.unlink(missing_ok=True)
        raise
