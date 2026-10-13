"""Bounded actual resolver selections in the existing Fleet journal."""
from contextlib import closing
import hashlib
import json
import math
from itertools import islice

from rosy.contracts.learning.incident_rule import validate_rule
from .events import CoreEventStore, _contains_sensitive_field


class RuleSelectionStore(CoreEventStore):
    def __init__(self, path, *, max_rows=100_000, retention_s=30 * 86400):
        if (type(max_rows) is not int or not 1 <= max_rows <= 100_000
                or type(retention_s) not in (int, float) or not math.isfinite(retention_s)
                or not 0 < retention_s <= 30 * 86400):
            raise ValueError('INVALID_RULE_RETENTION')
        super().__init__(path)
        self.max_rows, self.retention_s = max_rows, retention_s
        with closing(self._connect()) as db, db:
            db.execute('''CREATE TABLE IF NOT EXISTS fleet_rule_selections (
                selection_id INTEGER PRIMARY KEY AUTOINCREMENT, robot_id TEXT NOT NULL,
                received_at REAL NOT NULL, payload_json TEXT NOT NULL)''')
            db.execute('CREATE INDEX IF NOT EXISTS fleet_rule_selection_robot ON fleet_rule_selections(robot_id,selection_id)')
            db.execute('CREATE INDEX IF NOT EXISTS fleet_rule_selection_time ON fleet_rule_selections(received_at)')

    def append_batch(self, receipts, *, now):
        if type(now) not in (int, float) or not math.isfinite(now):
            raise ValueError('INVALID_RULE_RECEIPT_CLOCK')
        receipts = list(islice(receipts, 1025))
        if len(receipts) > 1024: raise ValueError('RULE_ROSTER_LIMIT')
        values, ids = [], set()
        for receipt in receipts:
            checked = validate_rule(receipt)
            if _contains_sensitive_field(checked): raise ValueError('RULE_RECEIPT_CREDENTIAL')
            rid = checked['assessment']['request']['subject_id']
            if rid in ids: raise ValueError('DUPLICATE_RULE_SUBJECT')
            ids.add(rid)
            values.append((rid, now, json.dumps(checked, sort_keys=True, ensure_ascii=False,
                                              separators=(',', ':'), allow_nan=False)))
        with closing(self._connect()) as db, db:
            db.executemany('INSERT INTO fleet_rule_selections(robot_id,received_at,payload_json) VALUES(?,?,?)', values)
            db.execute('DELETE FROM fleet_rule_selections WHERE received_at < ?', (now - self.retention_s,))
            db.execute('''DELETE FROM fleet_rule_selections WHERE selection_id <= COALESCE(
                (SELECT selection_id FROM fleet_rule_selections ORDER BY selection_id DESC LIMIT 1 OFFSET ?),0)''',
                       (self.max_rows,))
        return [json.loads(item[2]) for item in values]

    def read(self, *, after_id=0, limit=100, robot_id=None):
        if type(after_id) is not int or after_id < 0 or type(limit) is not int or not 1 <= limit <= 200:
            raise ValueError('INVALID_RULE_CURSOR')
        where, params = 'selection_id>?', [after_id]
        if robot_id is not None:
            where += ' AND robot_id=?'
            params.append(robot_id)
        with closing(self._connect()) as db:
            rows = db.execute(f'SELECT * FROM fleet_rule_selections WHERE {where} ORDER BY selection_id LIMIT ?',
                              (*params, limit + 1)).fetchall()
        return [dict(selection_id=r['selection_id'], received_at=r['received_at'],
                     receipt=validate_rule(json.loads(r['payload_json'])),
                     sha256=hashlib.sha256(r['payload_json'].encode()).hexdigest()) for r in rows]
