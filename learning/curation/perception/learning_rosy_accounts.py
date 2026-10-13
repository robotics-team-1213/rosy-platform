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

    def login(self, *args, **kwargs):
        raise AccountError('Use Rosy Account to sign in')

    def login_subject(self, subject):
        raise AccountError('External identities do not replace Rosy Account login')

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
        user = self._user(mappings.get(claims.sub))
        with self._db() as db:
            old = db.execute('SELECT user_id FROM rosy_account_owners WHERE subject=?', (claims.sub,)).fetchone()
            if old and old['user_id'] != user['user_id']:
                raise AccountError('Account owner cannot be reassigned')
            occupied = db.execute('SELECT subject FROM rosy_account_owners WHERE user_id=?', (user['user_id'],)).fetchone()
            if occupied and occupied['subject'] != claims.sub:
                raise AccountError('Learning owner already belongs to another Account')
            if old is None:
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
