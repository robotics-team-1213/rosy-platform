"""Sign-up and access requests: unauthenticated intake, administrator decision (D-993).

A request never creates credentials or grants. Approval runs the ledger's own create/mutate in the same
transaction that closes the request, so there is no second user store and no half-approved state.
"""
import hashlib
import json
import re
import secrets

from rosy_account.site_users import _LOGIN

RESOURCE = re.compile(r'(site|robot|project):[A-Za-z0-9._-]{1,96}\Z')
MAX_PENDING = 200          # whole service
MAX_PENDING_PER_CLIENT = 5  # one address (stored only as a digest)
CAP_WINDOW_S = 86400.0      # older pending requests stay listed but stop counting toward either cap
LIST_LIMIT = 200


class RequestsFull(Exception):
    pass


def _text(value, limit, *, required=False):
    if value is None or value == '':
        value = ''
    if (not isinstance(value, str) or len(value.strip()) > limit
            or any(ord(c) < 32 and c != '\n' for c in value) or (required and not value.strip())):
        raise ValueError('invalid request field')
    return value.strip()


def _public(row):
    return {k: row[k] for k in ('request_id', 'kind', 'requester_name', 'username', 'account_id', 'resource',
                                'note', 'created_at', 'state', 'decided_by', 'decided_at', 'reason')}


class AccessRequests:
    def __init__(self, ledger):
        self.ledger, self._ready = ledger, False

    def _ensure(self, db):
        if not self._ready:
            db.execute('''CREATE TABLE IF NOT EXISTS rosy_access_requests (
                request_id TEXT PRIMARY KEY, kind TEXT NOT NULL, requester_name TEXT NOT NULL,
                username TEXT NOT NULL, account_id TEXT, resource TEXT NOT NULL, note TEXT NOT NULL,
                created_at REAL NOT NULL, state TEXT NOT NULL, decided_by TEXT, decided_at REAL,
                reason TEXT NOT NULL DEFAULT '', client_sha256 TEXT NOT NULL)''')
            self._ready = True

    def submit(self, *, client, name='', username='', resource='', note='', account=None):
        """Store one pending request. A repeat of a pending request is accepted silently (same answer)."""
        resource, note = _text(resource, 128), _text(note, 500)
        if resource and not RESOURCE.fullmatch(resource):
            raise ValueError('invalid resource')
        if account:  # signed-in: the session names the person, never the form
            kind, name, username, account_id = 'grant', account['display_name'], account['login'], account['account_id']
        else:
            kind, account_id = 'new_account', None
            name, username = _text(name, 64, required=True), _text(username, 32)
            if not _LOGIN.fullmatch(username):
                raise ValueError('invalid login id')
        digest = hashlib.sha256(client.encode()).hexdigest()
        with self.ledger.db(write=True) as db:
            self._ensure(db)
            if db.execute('SELECT 1 FROM rosy_access_requests WHERE state=? AND kind=? AND username=? AND resource=? '
                          'AND requester_name=?', ('pending', kind, username, resource, name)).fetchone():
                return
            counts = db.execute("SELECT COUNT(*), SUM(client_sha256=?) FROM rosy_access_requests "
                                "WHERE state='pending' AND created_at>=?",
                                (digest, self.ledger.sessions._clock() - CAP_WINDOW_S)).fetchone()
            if (counts[0] or 0) >= MAX_PENDING or (counts[1] or 0) >= MAX_PENDING_PER_CLIENT:
                raise RequestsFull()
            db.execute('INSERT INTO rosy_access_requests VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)', (
                secrets.token_urlsafe(12), kind, name, username, account_id, resource, note,
                self.ledger.sessions._clock(), 'pending', None, None, '', digest))

    def list(self, value):
        with self.ledger.db(write=True) as db:
            self._ensure(db)
            self.ledger.require_manager(db, value)
            rows = db.execute("SELECT * FROM rosy_access_requests ORDER BY state='pending' DESC, created_at DESC "
                              'LIMIT ?', (LIST_LIMIT,)).fetchall()
            taken = {r[0] for r in db.execute('SELECT login FROM rosy_accounts')}
            return [{**_public(r), 'login_taken': r['kind'] == 'new_account' and r['username'] in taken}
                    for r in rows]

    def _load(self, db, request_id):
        row = db.execute('SELECT * FROM rosy_access_requests WHERE request_id=?', (request_id,)).fetchone()
        if row is None:
            raise KeyError(request_id)
        if row['state'] != 'pending':
            raise ValueError('request already decided')
        return row

    def _close(self, db, actor, row, state, reason, target):
        """Close a pending request and audit the decision in the account audit trail."""
        now = self.ledger.sessions._clock()
        if not db.execute("UPDATE rosy_access_requests SET state=?,decided_by=?,decided_at=?,reason=? "
                          "WHERE request_id=? AND state='pending'", (state, actor, now, reason,
                                                                      row['request_id'])).rowcount:
            raise ValueError('request already decided')
        after = {**_public(row), 'state': state, 'decided_by': actor, 'decided_at': now, 'reason': reason}
        db.execute('INSERT INTO rosy_account_audit VALUES (?,?,?,?,?,?,?,?,?)', (
            actor, target, 'access-' + ('approve' if state == 'approved' else 'reject'), 0, 0, now,
            '{}', json.dumps(after), 'success'))

    def reject(self, value, request_id, *, reason):
        reason = _text(reason, 300, required=True)
        with self.ledger.db(write=True) as db:
            self._ensure(db)
            actor = self.ledger.require_manager(db, value)
            row = self._load(db, request_id)
            self._close(db, actor, row, 'rejected', reason, row['account_id'] or request_id)
            return {'request_id': request_id, 'state': 'rejected'}

    def approve(self, value, request_id, *, role, grants, password=None, principal_id=None, revision=None):
        """new_account: ledger.create with an administrator-set initial password (first login forces a change).
        grant: ledger.mutate of the requester's existing account at the revision the administrator reviewed."""
        with self.ledger.db(write=True) as db:
            self._ensure(db)
            self.ledger.require_manager(db, value)
            row = self._load(db, request_id)

        def close(db, actor, account_id):
            if row['kind'] == 'grant':  # inside the transaction: a disabled or removed account rolls everything back
                account = db.execute('SELECT enabled FROM rosy_accounts WHERE account_id=?',
                                     (row['account_id'],)).fetchone()
                if account is None or not account[0]:
                    raise ValueError('requester account is unavailable')
            self._close(db, actor, row, 'approved', '', account_id)
        if row['kind'] == 'new_account':
            created = self.ledger.create(value, login=row['username'], role=role, grants=grants, password=password,
                                         principal_id=principal_id or row['requester_name'], within=close)
        else:
            created = self.ledger.mutate(value, row['account_id'], revision, {'grants': grants},
                                         operation='update', within=close)
        return {'request_id': request_id, 'state': 'approved', 'account': created}
