"""Bounded actual resolver selections in the existing Fleet journal."""
from contextlib import closing
import hashlib
import json
import math
from itertools import islice

from rosy.contracts.learning.incident_rule import validate_rule
from .events import CoreEventStore, _contains_sensitive_field


class RuleSelectionStore(CoreEventStore):
    def __init__(self, path, *, max_rows=100_000, retention_s=30 * 86400,
                 debounce_s=0.0, prune_interval_s=0.0):
        if (type(max_rows) is not int or not 1 <= max_rows <= 100_000
                or type(retention_s) not in (int, float) or not math.isfinite(retention_s)
                or not 0 < retention_s <= 30 * 86400):
            raise ValueError('INVALID_RULE_RETENTION')
        super().__init__(path)
        self.max_rows, self.retention_s = max_rows, retention_s
        self.debounce_s, self.prune_interval_s = debounce_s, prune_interval_s
        self._last_signature = None
        self._last_written_at = None
        self._last_pruned_at = None
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
        parsed = [json.loads(item[2]) for item in values]
        signature = tuple(
            (r['assessment']['request']['subject_id'], r['assessment']['request']['case_id'],
             r['assessment']['request']['owner'], r['assessment']['request']['condition'],
             r['assessment']['request']['conflicted'], r['assessment']['necessity'],
             r['assessment']['reason'], r['assessment']['policy_revision'],
             r['selection'], r['config_sha256'], r['strategy'])
            for r in parsed
        )
        if (self.debounce_s > 0 and self._last_signature == signature
                and self._last_written_at is not None
                and 0 <= now - self._last_written_at < self.debounce_s):
            return parsed
        prune_due = (self.prune_interval_s <= 0 or self._last_pruned_at is None
                     or now - self._last_pruned_at >= self.prune_interval_s or now < self._last_pruned_at)
        with closing(self._connect()) as db, db:
            db.executemany('INSERT INTO fleet_rule_selections(robot_id,received_at,payload_json) VALUES(?,?,?)', values)
            if prune_due:
                db.execute('DELETE FROM fleet_rule_selections WHERE received_at < ?', (now - self.retention_s,))
                # AUTOINCREMENT ids never repeat, so MAX(id) bounds the cap without walking 100k payload rows.
                db.execute('''DELETE FROM fleet_rule_selections WHERE selection_id <=
                    (SELECT COALESCE(MAX(selection_id), 0) FROM fleet_rule_selections) - ?''',
                           (self.max_rows,))
                self._last_pruned_at = now
        self._last_signature = signature
        self._last_written_at = now
        return parsed

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
