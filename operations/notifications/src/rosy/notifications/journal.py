"""One process owns this private SQLite ledger, never a producer business DB."""

import fcntl
import json
import sqlite3
from contextlib import closing, contextmanager

from core_common.protocol.notification_delivery import DeliveryReceipt


class DeliveryError(Exception):
    def __init__(self, status, code):
        self.status, self.code = status, code
        super().__init__(code)


class Journal:
    def __init__(self, path):
        self._lock = open(str(path) + '.lock', 'a')
        try:
            fcntl.flock(self._lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError:
            self._lock.close()
            raise ValueError('DELIVERY_OWNER_ALREADY_ACTIVE') from None
        self.path = path
        try:
            with self.connect() as db:
                if db.execute('PRAGMA user_version').fetchone()[0] not in (0, 1):
                    raise ValueError('UNSUPPORTED_DELIVERY_SCHEMA')
                db.executescript('''
                    CREATE TABLE IF NOT EXISTS deliveries (
                        producer TEXT NOT NULL, notification_id TEXT NOT NULL, body TEXT NOT NULL,
                        channel TEXT NOT NULL, route_hash TEXT NOT NULL, state TEXT NOT NULL,
                        admitted REAL NOT NULL, expires REAL NOT NULL, due REAL NOT NULL,
                        attempts INTEGER NOT NULL DEFAULT 0,
                        PRIMARY KEY(producer, notification_id));
                    CREATE TABLE IF NOT EXISTS channel_attempts (
                        route_hash TEXT PRIMARY KEY, attempted REAL NOT NULL);
                ''')
                db.execute("UPDATE deliveries SET state='UNKNOWN' WHERE state='SENDING'")
                db.execute('PRAGMA user_version=1')
        except BaseException:
            self.close()
            raise

    @contextmanager
    def connect(self):
        with closing(sqlite3.connect(self.path, timeout=5)) as db, db:
            db.row_factory = sqlite3.Row
            yield db

    def close(self):
        self._lock.close()

    @staticmethod
    def receipt(row):
        return DeliveryReceipt(**{key: row[key] for key in ('producer', 'notification_id', 'state', 'attempts')})

    def read(self, producer, notification_id):
        with self.connect() as db:
            row = db.execute('SELECT * FROM deliveries WHERE producer=? AND notification_id=?',
                             (producer, notification_id)).fetchone()
        if row is None:
            raise DeliveryError(404, 'DELIVERY_NOT_FOUND')
        return self.receipt(row)

    def accept(self, request, profile, route_hash, now):
        body = json.dumps(request.model_dump(), sort_keys=True, separators=(',', ':'), allow_nan=False)
        with self.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            row = db.execute('SELECT * FROM deliveries WHERE producer=? AND notification_id=?',
                             (request.producer, request.notification_id)).fetchone()
            if row is not None:
                if row['body'] != body:
                    raise DeliveryError(409, 'NOTIFICATION_IDENTITY_CONFLICT')
                return self.receipt(row)
            if not request.observed_at <= now < request.expires_at <= request.observed_at + profile.ttl_s:
                raise DeliveryError(422, 'NOTIFICATION_TIME_INVALID')
            db.execute("UPDATE deliveries SET state='EXPIRED' WHERE state IN ('PENDING','RETRY') AND expires<=?", (now,))
            db.execute("DELETE FROM deliveries WHERE admitted<? AND state NOT IN ('PENDING','RETRY','SENDING')",
                       (now - 7 * 86400,))
            db.execute('DELETE FROM channel_attempts WHERE attempted<?', (now - 7 * 86400,))
            count = db.execute('SELECT COUNT(*), SUM(admitted>?) FROM deliveries WHERE producer=?',
                               (now - 60, request.producer)).fetchone()
            if count[0] >= profile.capacity or (count[1] or 0) >= profile.admissions_per_minute:
                raise DeliveryError(429, 'PRODUCER_BUDGET_EXHAUSTED')
            db.execute('INSERT INTO deliveries VALUES (?,?,?,?,?,?,?,?,?,0)',
                       (request.producer, request.notification_id, body, request.channel, route_hash,
                        'PENDING', now, request.expires_at, now))
        return self.read(request.producer, request.notification_id)

    def claim(self, producer, now):
        with self.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            db.execute("UPDATE deliveries SET state='EXPIRED' WHERE state IN ('PENDING','RETRY') AND expires<=?", (now,))
            row = db.execute("""SELECT * FROM deliveries WHERE producer=? AND state IN ('PENDING','RETRY')
                AND due<=? ORDER BY due, admitted, notification_id LIMIT 1""", (producer, now)).fetchone()
            if row is not None:
                db.execute("UPDATE deliveries SET state='SENDING' WHERE producer=? AND notification_id=?",
                           (producer, row['notification_id']))
                return dict(row)

    def start_attempt(self, row, profile, now):
        with self.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            recent = db.execute('SELECT attempted FROM channel_attempts WHERE route_hash=?',
                                (row['route_hash'],)).fetchone()
            if recent and now - recent[0] < profile.interval_s:
                return False
            db.execute('INSERT OR REPLACE INTO channel_attempts VALUES (?,?)', (row['route_hash'], now))
            db.execute('UPDATE deliveries SET attempts=attempts+1 WHERE producer=? AND notification_id=?',
                       (row['producer'], row['notification_id']))
        row['attempts'] += 1
        return True

    def finish(self, row, state, now, delay=60):
        with self.connect() as db:
            db.execute("UPDATE deliveries SET state=?, due=? WHERE producer=? AND notification_id=? AND state='SENDING'",
                       (state, now + delay, row['producer'], row['notification_id']))
