"""D-955 step 2: registered apps live in the Account database; only accounts.manage changes them."""
from __future__ import annotations

import json
import re
from urllib.parse import urlsplit

SCHEMA = '''
    CREATE TABLE IF NOT EXISTS account_clients (
        client_id TEXT PRIMARY KEY,redirect_uris TEXT NOT NULL,resources TEXT NOT NULL,
        enabled INTEGER NOT NULL,revision INTEGER NOT NULL);
    CREATE TABLE IF NOT EXISTS account_client_audit (
        actor_account_id TEXT NOT NULL,client_id TEXT NOT NULL,operation TEXT NOT NULL,
        previous_revision INTEGER NOT NULL,following_revision INTEGER NOT NULL,at REAL NOT NULL,
        before_state TEXT NOT NULL,after_state TEXT NOT NULL);
'''


def https_url(value):
    parsed = urlsplit(value)
    return (parsed.scheme == 'https' and bool(parsed.hostname) and not parsed.username
            and not parsed.password and not parsed.fragment)


def validate_client(client_id, redirect_uris, resources):
    """No wildcard resource: an issued token names one concrete resource (D-955 2)."""
    if (not isinstance(client_id, str) or not re.fullmatch(r'[A-Za-z0-9._-]{1,96}', client_id)
            or not isinstance(redirect_uris, list) or not 1 <= len(redirect_uris) <= 16
            or not isinstance(resources, list) or not 1 <= len(resources) <= 256
            or len(set(map(repr, redirect_uris))) != len(redirect_uris) or len(set(map(repr, resources))) != len(resources)
            or any(not isinstance(uri, str) or len(uri) > 2048 or not https_url(uri) or urlsplit(uri).query
                   for uri in redirect_uris)
            or any(not isinstance(resource, str) or not re.fullmatch(r'(site|robot|project):[A-Za-z0-9._-]{1,96}', resource)
                   for resource in resources)):
        raise ValueError('invalid account client registration')


def import_first(db, clients):
    """The protected JSON seeds an empty registry once; after that it is ignored so a stopped app stays stopped."""
    if db.execute('SELECT 1 FROM account_clients LIMIT 1').fetchone():
        return
    db.executemany('INSERT INTO account_clients VALUES (?,?,?,1,1)', [
        (name, json.dumps(settings['redirect_uris']), json.dumps(settings['resources']))
        for name, settings in clients.items()])


def public(row):
    return {'client_id': row['client_id'], 'redirect_uris': json.loads(row['redirect_uris']),
            'resources': json.loads(row['resources']), 'enabled': bool(row['enabled']), 'revision': row['revision']}


def list_clients(db):
    return [public(row) for row in db.execute('SELECT * FROM account_clients ORDER BY client_id')]


class ClientRegistry:
    def __init__(self, ledger, clock):
        self.ledger, self.clock = ledger, clock

    def _audit(self, db, actor, operation, before, after):
        db.execute('INSERT INTO account_client_audit VALUES (?,?,?,?,?,?,?,?)', (
            actor, after['client_id'], operation, before['revision'] if before else 0, after['revision'], self.clock(),
            json.dumps(before or {}), json.dumps(after)))

    def create(self, value, *, client_id, redirect_uris, resources):
        validate_client(client_id, redirect_uris, resources)
        with self.ledger.db(write=True) as db:
            actor = self.ledger.require_manager(db, value)
            if db.execute('SELECT 1 FROM account_clients WHERE client_id=?', (client_id,)).fetchone():
                raise ValueError('account client already registered')
            db.execute('INSERT INTO account_clients VALUES (?,?,?,1,1)',
                       (client_id, json.dumps(redirect_uris), json.dumps(resources)))
            after = public(db.execute('SELECT * FROM account_clients WHERE client_id=?', (client_id,)).fetchone())
            self._audit(db, actor, 'create', None, after)
            return after

    def update(self, value, client_id, *, revision, **changes):
        if type(revision) is not int or revision < 1 or not changes:
            raise ValueError('invalid changes or revision')
        if 'enabled' in changes and type(changes['enabled']) is not bool:
            raise ValueError('invalid enabled')
        with self.ledger.db(write=True) as db:
            actor = self.ledger.require_manager(db, value)
            row = db.execute('SELECT * FROM account_clients WHERE client_id=?', (client_id,)).fetchone()
            if row is None:
                raise KeyError(client_id)
            before = public(row)
            if before['revision'] != revision:
                raise ValueError('account client revision conflict')
            after = {**before, **changes, 'revision': revision + 1}
            validate_client(client_id, after['redirect_uris'], after['resources'])
            db.execute('UPDATE account_clients SET redirect_uris=?,resources=?,enabled=?,revision=? WHERE client_id=?', (
                json.dumps(after['redirect_uris']), json.dumps(after['resources']), int(after['enabled']), revision + 1, client_id))
            self._audit(db, actor, 'update', before, after)
            return after
