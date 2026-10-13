"""Named incident claims in the existing Fleet journal; no device admission."""

import hashlib
import json
from contextlib import closing

from rosy_situation.snapshot_assessment import POLICY


def judgment_revision(receipt: dict) -> str:
    # Frame sequence and evaluation time change on every poll; ownership binds the case and decision.
    request = receipt['request']
    fields = [request.get(key) for key in ('subject_id', 'case_id', 'owner')]
    fields += [receipt[key] for key in ('necessity', 'reason', 'policy_revision')]
    return hashlib.sha256(json.dumps(fields, allow_nan=False).encode()).hexdigest()


class IncidentHandoff:
    def __init__(self, log):
        self._log = log
        with closing(log._connect()) as connection, connection:
            connection.execute('''CREATE TABLE IF NOT EXISTS fleet_incident_claims (
                robot_id TEXT NOT NULL, stuck_id TEXT NOT NULL,
                principal_id TEXT NOT NULL, judgment_revision TEXT NOT NULL,
                claimed_at REAL NOT NULL, PRIMARY KEY(robot_id, stuck_id))''')

    def claim(self, robot_id: str, stuck_id: str, receipt: dict,
              principal_id: str, *, now: float, admission=None) -> dict:
        if not principal_id or principal_id == 'site-console':
            raise ValueError('OPERATOR_IDENTITY_REQUIRED')
        revision = judgment_revision(receipt)
        with closing(self._log._connect()) as connection, connection:
            connection.execute('BEGIN IMMEDIATE')
            current = connection.execute(
                'SELECT assessment FROM fleet_judgment_current WHERE robot_id=?',
                (robot_id,)).fetchone()
            latest = json.loads(current['assessment']) if current else None
            if (latest is None or latest['request'].get('subject_id') != robot_id
                    or latest['request'].get('case_id') != stuck_id
                    or judgment_revision(latest) != revision):
                raise ValueError('INCIDENT_JUDGMENT_CHANGED')
            if not 0 <= now - latest['evaluated_at'] <= POLICY.max_age_s:
                raise ValueError('INCIDENT_JUDGMENT_STALE')
            episode = connection.execute(
                'SELECT closed_at FROM fleet_line_stuck_episodes WHERE robot_id=? AND stuck_id=?',
                (robot_id, stuck_id)).fetchone()
            if episode is None or episode['closed_at'] is not None:
                raise ValueError('INCIDENT_NOT_OPEN')
            previous = connection.execute(
                'SELECT * FROM fleet_incident_claims WHERE robot_id=? AND stuck_id=?',
                (robot_id, stuck_id)).fetchone()
            if previous is not None:
                if previous['principal_id'] != principal_id:
                    raise ValueError('INCIDENT_ALREADY_CLAIMED')
            if admission is not None:
                admission(connection)
            if previous is not None:
                return dict(previous)
            connection.execute('INSERT INTO fleet_incident_claims VALUES (?, ?, ?, ?, ?)',
                               (robot_id, stuck_id, principal_id, revision, now))
            return dict(connection.execute(
                'SELECT * FROM fleet_incident_claims WHERE robot_id=? AND stuck_id=?',
                (robot_id, stuck_id)).fetchone())

    def get(self, robot_id: str, stuck_id: str):
        with closing(self._log._connect()) as connection:
            row = connection.execute(
                'SELECT * FROM fleet_incident_claims WHERE robot_id=? AND stuck_id=?',
                (robot_id, stuck_id)).fetchone()
        return dict(row) if row else None

    def active(self) -> list[dict]:
        with closing(self._log._connect()) as connection:
            rows = connection.execute('''SELECT c.* FROM fleet_incident_claims c
                JOIN fleet_line_stuck_episodes e USING(robot_id, stuck_id)
                WHERE e.closed_at IS NULL''').fetchall()
        return [dict(row) for row in rows]
