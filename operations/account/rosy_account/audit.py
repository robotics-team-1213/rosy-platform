"""Account-owned durable HTTP audit, independent of Fleet task storage."""
from contextlib import closing
import sqlite3
import time


class AccountAudit:
    def __init__(self, path):
        self.path = path
        with closing(self.connect()) as db, db:
            db.execute('''CREATE TABLE IF NOT EXISTS account_http_audit (
                id INTEGER PRIMARY KEY, principal_id TEXT NOT NULL, role TEXT NOT NULL,
                method TEXT NOT NULL, path TEXT NOT NULL, started REAL NOT NULL, status_code INTEGER)''')

    def connect(self):
        return sqlite3.connect(self.path, timeout=1)

    def begin_api_audit(self, *, principal_id, role, method, path):
        with closing(self.connect()) as db, db:
            return db.execute('''INSERT INTO account_http_audit
                (principal_id,role,method,path,started) VALUES(?,?,?,?,?)''',
                (principal_id, role, method, path, time.time())).lastrowid

    def finish_api_audit(self, audit_id, *, status_code):
        with closing(self.connect()) as db, db:
            db.execute('UPDATE account_http_audit SET status_code=? WHERE id=?', (status_code, audit_id))


def install_audit(app, store):
    @app.middleware('http')
    async def finish(request, call_next):
        try:
            response = await call_next(request)
        except Exception:
            audit_id = getattr(request.state, 'site_api_audit_id', None)
            if audit_id is not None:
                store.finish_api_audit(audit_id, status_code=500)
            raise
        audit_id = getattr(request.state, 'site_api_audit_id', None)
        if audit_id is not None:
            store.finish_api_audit(audit_id, status_code=response.status_code)
        return response
