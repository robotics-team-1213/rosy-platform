"""Owned SQLite observations, replay anchors and bounded public state-change history."""

from contextlib import contextmanager
from datetime import datetime, timedelta
import json
from pathlib import Path
import sqlite3

from .models import MonitoringLink, MonitoringNode


APPLICATION_ID = 0x52534D31


class StoreUnavailable(ValueError):
    def __init__(self):
        super().__init__('monitoring storage unavailable')


def state(item):
    fields = ('freshness', 'reported_health', 'reachable', 'failure_stage', 'reason_code')
    return {key: getattr(item, key) for key in fields if hasattr(item, key)}


class MonitoringStore:
    def __init__(self, path: Path, collector_id: str):
        self.path = Path(path)
        exists = self.path.exists()
        try:
            with self._connection() as db:
                if exists:
                    if (db.execute('pragma application_id').fetchone()[0] != APPLICATION_ID
                            or db.execute('pragma user_version').fetchone()[0] != 1
                            or db.execute('select collector from owner').fetchone() != (collector_id,)):
                        raise StoreUnavailable()
                else:
                    db.execute(f'pragma application_id={APPLICATION_ID}')
                    db.execute('pragma user_version=1')
                    db.execute('create table owner (collector text not null)')
                    db.execute('insert into owner values (?)', (collector_id,))
                    for table in ('visible', 'anchors'):
                        db.execute(f'''create table {table} (
                            kind text, source text, id text, captured text, payload text,
                            primary key(kind, source, id))''')
                    db.execute('create table peers (source text primary key, payload text)')
                    db.execute('create table counters (site text primary key, seq integer)')
                    db.execute('''create table events (site text, seq integer, time text, payload text,
                                primary key(site, seq))''')
        except (sqlite3.Error, OSError, TypeError, IndexError):
            raise StoreUnavailable() from None

    @contextmanager
    def _connection(self):
        db = None
        try:
            db = sqlite3.connect(self.path, timeout=0.1)
            db.execute('pragma synchronous=FULL')
            with db:
                yield db
        except (sqlite3.Error, OSError):
            raise StoreUnavailable() from None
        finally:
            if db is not None:
                db.close()

    def load(self):
        result = {}
        try:
            with self._connection() as db:
                for table in ('visible', 'anchors'):
                    rows = db.execute(f'select kind,source,id,captured,payload from {table} limit 8193').fetchall()
                    if len(rows) > 8192:
                        raise StoreUnavailable()
                    parsed = []
                    for kind, source, item_id, captured, payload in rows:
                        if len(payload) > 16384:
                            raise StoreUnavailable()
                        raw = json.loads(payload)
                        model = MonitoringLink if 'source_id' in raw else MonitoringNode
                        item = model.model_validate(raw)
                        wall = datetime.fromisoformat(captured)
                        if item.id != item_id or kind not in {'local', 'peer'} or wall.utcoffset() is None:
                            raise StoreUnavailable()
                        parsed.append(((kind, source), item, wall))
                    result[table] = parsed
                peers = db.execute('select source,payload from peers limit 129').fetchall()
                if len(peers) > 128:
                    raise StoreUnavailable()
                result['peers'] = {source: json.loads(payload) for source, payload in peers}
            return result
        except (ValueError, TypeError, KeyError):
            raise StoreUnavailable() from None

    def save(self, key, items, *, wall, peer_cursor=None):
        """One transaction precedes the in-memory publication and peer cursor advance."""
        with self._connection() as db:
            old = {item_id: json.loads(payload) for item_id, payload in db.execute(
                'select id,payload from visible where kind=? and source=?', key)}
            db.execute('delete from visible where kind=? and source=?', key)
            for item in items:
                row = (*key, item.id, wall.isoformat(), item.model_dump_json())
                db.execute('insert into visible values (?,?,?,?,?)', row)
                if item.sample_id is not None:
                    db.execute('insert or replace into anchors values (?,?,?,?,?)', row)
                public = state(item)
                previous = old.pop(item.id, None)
                if previous is None or public != {k: previous.get(k) for k in public}:
                    self._event(db, item.site_id, item.id, public, wall)
            for item_id, previous in old.items():
                self._event(db, previous['site_id'], item_id, {'freshness': 'unknown', 'present': False}, wall)
            if peer_cursor is not None:
                db.execute('insert or replace into peers values (?,?)', (key[1], json.dumps(peer_cursor)))
            cutoff = (wall - timedelta(days=7)).isoformat()
            db.execute('delete from events where time < ?', (cutoff,))

    @staticmethod
    def _event(db, site, item_id, public, wall):
        db.execute('insert into counters values (?,1) on conflict(site) do update set seq=seq+1', (site,))
        seq = db.execute('select seq from counters where site=?', (site,)).fetchone()[0]
        payload = json.dumps({'item_id': item_id, 'state': public}, separators=(',', ':'))
        db.execute('insert into events values (?,?,?,?)', (site, seq, wall.isoformat(), payload))
        db.execute('delete from events where site=? and seq<=?', (site, seq - 4096))

    def events(self, site, *, after, limit):
        if type(after) is not int or after < 0 or type(limit) is not int or not 1 <= limit <= 200:
            raise ValueError('invalid event cursor')
        with self._connection() as db:
            rows = db.execute('select seq,time,payload from events where site=? and seq>? order by seq limit ?',
                              (site, after, limit)).fetchall()
        try:
            return [{'sequence': seq, 'time': wall, **json.loads(payload)} for seq, wall, payload in rows]
        except (ValueError, TypeError):
            raise StoreUnavailable() from None
