"""D-757 central identity bridge; existing provider connections retain their owner."""
import re
from learning_accounts import Accounts, AccountError, CAPABILITIES


class RosyAccounts(Accounts):
    central_account = True
    def __init__(self, *args, receiver, **kwargs):
        super().__init__(*args, **kwargs)
        self.receiver = receiver
        if receiver.resource != 'project:' + self.project_id:
            raise AccountError('Account resource does not match project')
        with self._db() as db:
            db.execute('CREATE TABLE IF NOT EXISTS rosy_account_owners (subject TEXT PRIMARY KEY,user_id TEXT UNIQUE)')
            db.execute('''CREATE TABLE IF NOT EXISTS rosy_connection_authority (
                connection_id TEXT PRIMARY KEY,generation INTEGER,subject TEXT,session_id TEXT)''')

    def _user(self, user_id):
        user = next((u for u in self.config()['users'] if u['user_id'] == user_id), None)
        if not user:
            raise AccountError('Account owner mapping unavailable')
        return user

    def _save_connection(self, db, principal, *args, **kwargs):
        connection_id = super()._save_connection(db, principal, *args, **kwargs)
        generation = db.execute('SELECT generation FROM learning_connections WHERE id=?', (connection_id,)).fetchone()[0]
        db.execute('INSERT OR REPLACE INTO rosy_connection_authority VALUES(?,?,?,?)',
            (connection_id, generation, principal['account_id'], principal['_session_id']))
        return connection_id

    def _owner_capabilities(self, row, principal):
        if row['sharing'] == 'personal':
            return principal['capabilities'] if principal['user_id'] == row['owner'] else []
        with self._db() as db:
            binding = db.execute('SELECT * FROM rosy_connection_authority WHERE connection_id=?', (row['id'],)).fetchone()
        if not binding or binding['generation'] != row['generation']:
            raise AccountError('Shared connection needs owner reauthorization')
        owner = self._authenticate_id(binding['session_id'])
        if owner['account_id'] != binding['subject'] or owner['user_id'] != row['owner']:
            raise AccountError('Connection owner changed')
        return owner['capabilities']

    def _authenticate_id(self, session_id):
        claims = self.receiver.resolve_session_id(session_id)
        if claims is None:
            raise AccountError('Account session expired')
        mappings = self.config().get('account_subjects', {})
        if (not isinstance(mappings, dict)
                or any(not isinstance(k, str) or not re.fullmatch('[A-Za-z0-9._-]{1,128}', k)
                       or not isinstance(v, str) for k, v in mappings.items())
                or len(set(mappings.values())) != len(mappings)):
            raise AccountError('Invalid Account subject mapping')
        user_id = mappings.get(claims.sub)
        if user_id is None:
            # Account grants decide access; a learning-side invitation is not a second gate.
            if any(u['user_id'] == claims.sub for u in self.config()['users']):
                raise AccountError('Account subject matches an unmapped learning owner')
            user = {'user_id': claims.sub, 'username': claims.sub}
        else:
            user = self._user(user_id)
        # Only an explicit mapping pins ownership, so a legacy owner can still be mapped
        # after that person's first unmapped sign-in.
        with self._db() as db:
            old = db.execute('SELECT user_id FROM rosy_account_owners WHERE subject=?', (claims.sub,)).fetchone()
            if old and old['user_id'] != user['user_id']:
                raise AccountError('Account owner cannot be reassigned')
            occupied = db.execute('SELECT subject FROM rosy_account_owners WHERE user_id=?', (user['user_id'],)).fetchone()
            if occupied and occupied['subject'] != claims.sub:
                raise AccountError('Learning owner already belongs to another Account')
            if old is None and user_id is not None:
                db.execute('INSERT OR IGNORE INTO rosy_account_owners VALUES(?,?)', (claims.sub, user['user_id']))
                bound = db.execute('SELECT user_id FROM rosy_account_owners WHERE subject=?', (claims.sub,)).fetchone()
                if not bound or bound['user_id'] != user['user_id']:
                    raise AccountError('Learning owner already belongs to another Account')
        return {'user_id':user['user_id'], 'username':user['username'],
            'display_name':user.get('display_name', user['username']), 'project_id':self.project_id,
            'capabilities':sorted(cap for cap in CAPABILITIES if claims.permits(claims.aud, 'learning.' + cap)),
            'account_id':claims.sub, '_session_id':session_id}

    def logout(self, token):
        self.receiver.logout(token)
