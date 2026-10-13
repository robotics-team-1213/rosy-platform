"""D-407/D-608 durable stuck answers, episodes and incident reviews."""

from __future__ import annotations

import json
import sqlite3
from contextlib import closing
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from fleet.server.sqlite_policy import configure_connection
from core_common.protocol.schemas import FleetJudgmentReceipt, FleetObservedClosure
from fleet.incidents.handoff import IncidentHandoff, judgment_revision
from fleet.incidents.notifications import NotificationOutbox


def _resolution(answers) -> tuple:
    """(resolved_by, resolved_principal, last_answer_tier, escalation_code) from one stuck's
    answers, oldest first. The last non-ESCALATE answer decides, as in ``view()``: accepted is
    its tier, unknown outcome is ``<tier>_unconfirmed`` (never "solved by itself"), refused
    falls back to the last accepted one. NULL = closed without an accepted answer."""
    answered = [a for a in answers if a["decision"] != "ESCALATE"]
    escalated = [a for a in answers if a["decision"] == "ESCALATE"]
    code = escalated[-1]["escalated"] if escalated else None
    if not answered:
        return None, None, None, code
    last = answered[-1]
    if last["accepted"] is None:
        return f"{last['tier'] or 'human'}_unconfirmed", last["principal_id"], last["tier"], code
    accepted = [a for a in answered if a["accepted"] == 1]
    if not accepted:
        return None, None, last["tier"], code
    return accepted[-1]["tier"], accepted[-1]["principal_id"], last["tier"], code


class LineStuckAnswerLog:
    """Durable answer record and stuck episodes in the Fleet journal database (beside
    ``fleet_api_audit``). Episodes are written only on open and close transitions."""

    def __init__(self, path: Path | str) -> None:
        self.path = Path(path)
        with closing(self._connect()) as connection, connection:
            connection.execute(
                """CREATE TABLE IF NOT EXISTS fleet_line_stuck_answers (
                       answer_id INTEGER PRIMARY KEY AUTOINCREMENT,
                       at TEXT NOT NULL, audit_id TEXT, robot_id TEXT NOT NULL,
                       stuck_id TEXT NOT NULL, decision TEXT NOT NULL,
                       principal_id TEXT NOT NULL, accepted INTEGER, outcome TEXT,
                       code TEXT, message TEXT)""")
            # D-438: a database made before the resolver lacks these; CREATE IF NOT EXISTS
            # does not add columns, so add each one missing (idempotent).
            have = {row["name"] for row in connection.execute(
                "PRAGMA table_info(fleet_line_stuck_answers)")}
            for column in ("tier", "rule", "escalated"):
                if column not in have:
                    connection.execute(
                        f"ALTER TABLE fleet_line_stuck_answers ADD COLUMN {column} TEXT")
            connection.execute(
                """CREATE TABLE IF NOT EXISTS fleet_line_stuck_episodes (
                       robot_id TEXT NOT NULL, stuck_id TEXT NOT NULL,
                       source TEXT NOT NULL DEFAULT 'fleet_poll',
                       cause TEXT, phase_at_open TEXT, local_enabled_at_open INTEGER,
                       trip_busy_at_open INTEGER, peer_ahead_at_open INTEGER,
                       opened_at TEXT NOT NULL, closed_at TEXT,
                       held_s_max REAL, attempts_max INTEGER, close_reason TEXT,
                       resolved_by TEXT, resolved_principal TEXT, last_answer_tier TEXT,
                       escalation_code TEXT,
                       pose_x REAL, pose_y REAL, pose_yaw REAL, pose_state TEXT, pose_age_s REAL,
                       UNIQUE (robot_id, stuck_id))""")
            connection.execute(
                """CREATE TABLE IF NOT EXISTS fleet_incident_reviews (
                       review_id INTEGER PRIMARY KEY AUTOINCREMENT,
                       robot_id TEXT NOT NULL, stuck_id TEXT NOT NULL,
                       at TEXT NOT NULL, principal_id TEXT NOT NULL,
                       root_cause TEXT NOT NULL, note TEXT NOT NULL)""")
            connection.execute(
                "CREATE INDEX IF NOT EXISTS fleet_incident_reviews_stuck "
                "ON fleet_incident_reviews(robot_id, stuck_id)")
            connection.execute(
                """CREATE TABLE IF NOT EXISTS fleet_ai_fact_reviews (
                       review_id INTEGER PRIMARY KEY AUTOINCREMENT,
                       fact_row INTEGER NOT NULL, at TEXT NOT NULL,
                       principal_id TEXT NOT NULL, root_cause TEXT NOT NULL, note TEXT NOT NULL)""")
            connection.execute(
                "CREATE INDEX IF NOT EXISTS fleet_ai_fact_reviews_fact ON fleet_ai_fact_reviews(fact_row)")
            connection.execute("""CREATE TABLE IF NOT EXISTS fleet_judgment_records (
                judgment_id INTEGER PRIMARY KEY AUTOINCREMENT, robot_id TEXT NOT NULL,
                recorded_at REAL NOT NULL, assessment TEXT NOT NULL)""")
            connection.execute("CREATE INDEX IF NOT EXISTS fleet_judgment_robot ON fleet_judgment_records(robot_id, judgment_id)")
            connection.execute("""CREATE TABLE IF NOT EXISTS fleet_judgment_current (
                robot_id TEXT PRIMARY KEY, recorded_at REAL NOT NULL, assessment TEXT NOT NULL)""")
        self.handoff = IncidentHandoff(self)
        self.notifications = NotificationOutbox(self)

    def record_judgment(self, receipt: dict) -> None:
        receipt = FleetJudgmentReceipt.model_validate(receipt).model_dump(mode="json")
        robot_id, now = receipt['request']['subject_id'], receipt['evaluated_at']
        body = json.dumps(receipt, allow_nan=False, sort_keys=True)
        def signature(value):
            return (value['necessity'], value['reason'], value['policy_revision'],
                    value['request'].get('case_id'), value['request'].get('owner'))
        with closing(self._connect()) as connection, connection:
            previous = connection.execute("SELECT recorded_at, assessment FROM fleet_judgment_records WHERE robot_id=? ORDER BY judgment_id DESC LIMIT 1", (robot_id,)).fetchone()
            if previous is None or signature(json.loads(previous['assessment'])) != signature(receipt) or now - previous['recorded_at'] >= 60:
                connection.execute("INSERT INTO fleet_judgment_records(robot_id, recorded_at, assessment) VALUES (?, ?, ?)", (robot_id, now, body))
            connection.execute("INSERT INTO fleet_judgment_current VALUES (?, ?, ?) ON CONFLICT(robot_id) DO UPDATE SET recorded_at=excluded.recorded_at, assessment=excluded.assessment", (robot_id, now, body))
            self.notifications.enqueue(connection, receipt)
            connection.execute("DELETE FROM fleet_judgment_records WHERE recorded_at < ?", (now - 7 * 86400,))
            connection.execute("DELETE FROM fleet_judgment_current WHERE recorded_at < ?", (now - 7 * 86400,))

    def judgments(self, limit: int = 100) -> list[dict]:
        if type(limit) is not int or not 1 <= limit <= 1000:
            raise ValueError('judgment limit must be between 1 and 1000')
        with closing(self._connect()) as connection:
            rows = connection.execute("SELECT * FROM fleet_judgment_records ORDER BY judgment_id DESC LIMIT ?", (limit,)).fetchall()
        return [{**dict(row), 'assessment': json.loads(row['assessment'])} for row in rows]

    def append(self, row: dict, *, connection=None) -> None:
        if connection is not None:
            if (type(connection) is not sqlite3.Connection or not connection.in_transaction
                    or not any(item[1] == 'main' and Path(item[2]).resolve() == self.path.resolve()
                               for item in connection.execute('PRAGMA database_list'))):
                raise ValueError('EXISTING_STUCK_TRANSACTION_REQUIRED')
            return self._append(connection, row)
        with closing(self._connect()) as connection, connection: self._append(connection, row)

    @staticmethod
    def _append(connection, row):
        accepted = None if row["accepted"] is None else int(bool(row["accepted"]))
        connection.execute(
                """INSERT INTO fleet_line_stuck_answers (at, audit_id, robot_id, stuck_id,
                   decision, principal_id, accepted, outcome, code, message, tier, rule,
                   escalated) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (row["at"], row["audit_id"], row["robot_id"], row["stuck_id"], row["decision"],
                 row["principal_id"], accepted, row["outcome"], row["code"],
                 (row["message"] or "")[:512] or None, row.get("tier"), row.get("rule"),
                 row.get("escalated")))

    def rows(self, limit: int = 100) -> list[dict]:
        with closing(self._connect()) as connection:
            found = connection.execute(
                "SELECT * FROM fleet_line_stuck_answers ORDER BY answer_id DESC LIMIT ?",
                (limit,)).fetchall()
        return [dict(row) for row in found]

    def uncertain_motion(self) -> set[tuple[str, str]]:
        with closing(self._connect()) as connection:
            rows = connection.execute("""SELECT DISTINCT a.robot_id, a.stuck_id
                FROM fleet_line_stuck_answers a WHERE a.principal_id='fleet-resolver'
                AND a.code IN ('STUCK_DECISION_OUTCOME_UNKNOWN', 'FLEET_STUCK_DISPATCH_PENDING')
                AND a.decision != 'WAIT'
                AND NOT EXISTS (SELECT 1 FROM fleet_line_stuck_answers r
                    WHERE r.robot_id=a.robot_id AND r.stuck_id=a.stuck_id
                    AND r.code='STUCK_DECISION_RECONCILED' AND r.answer_id>a.answer_id)""").fetchall()
        return {(row["robot_id"], row["stuck_id"]) for row in rows}

    def open_episode(self, row: dict) -> None:
        """Open (or, after a Fleet restart, reopen) one episode. The first ``opened_at`` stays."""
        columns = ", ".join(row)
        with closing(self._connect()) as connection, connection:
            connection.execute(
                f"""INSERT INTO fleet_line_stuck_episodes ({columns})
                    VALUES ({", ".join("?" * len(row))})
                    ON CONFLICT(robot_id, stuck_id) DO UPDATE SET
                        closed_at = NULL, close_reason = NULL""", tuple(row.values()))

    def close_episode(self, robot_id: str, stuck_id: str, *, closed_at: str, close_reason: str,
                      held_s_max: Optional[float], attempts_max: Optional[int]) -> None:
        with closing(self._connect()) as connection, connection:
            answers = connection.execute(
                """SELECT decision, accepted, tier, principal_id, escalated
                   FROM fleet_line_stuck_answers WHERE robot_id = ? AND stuck_id = ?
                   ORDER BY answer_id""", (robot_id, stuck_id)).fetchall()
            connection.execute(
                """UPDATE fleet_line_stuck_episodes SET closed_at = ?, close_reason = ?,
                       held_s_max = ?, attempts_max = ?, resolved_by = ?, resolved_principal = ?,
                       last_answer_tier = ?, escalation_code = ?
                   WHERE robot_id = ? AND stuck_id = ?""",
                (closed_at, close_reason, held_s_max, attempts_max, *_resolution(answers),
                 robot_id, stuck_id))
            self.notifications.closed(connection, robot_id, stuck_id,
                                      now=datetime.fromisoformat(closed_at).timestamp(), reason=close_reason)

    def close_orphans(self, closed_at: str) -> None:
        """Start-up: an episode still open was left by the previous Fleet process."""
        with closing(self._connect()) as connection, connection:
            connection.execute(
                """UPDATE fleet_line_stuck_episodes SET closed_at = ?, close_reason = 'fleet_restart'
                   WHERE closed_at IS NULL""", (closed_at,))

    def episodes(self, limit: int = 100) -> list[dict]:
        with closing(self._connect()) as connection:
            found = connection.execute(
                "SELECT * FROM fleet_line_stuck_episodes ORDER BY rowid DESC LIMIT ?",
                (limit,)).fetchall()
        return [dict(row) for row in found]

    def reports(self, limit: int = 100, *, robot_id=None, stuck_id=None) -> list[dict]:
        """Read-only, source-separated incident records for operator review and offline learning."""
        with closing(self._connect()) as connection:
            where, params = ('', []) if robot_id is None else (' WHERE robot_id=? AND stuck_id=?', [robot_id, stuck_id])
            episodes = connection.execute(
                'SELECT * FROM fleet_line_stuck_episodes' + where + ' ORDER BY rowid DESC LIMIT ?',
                (*params, limit)).fetchall()
            tables = {row[0] for row in connection.execute("SELECT name FROM sqlite_master WHERE type='table'")}
            reports = []
            for episode in episodes:
                row = dict(episode)
                robot_id, stuck_id = row["robot_id"], row["stuck_id"]
                current = connection.execute('SELECT assessment FROM fleet_judgment_current WHERE robot_id=?',
                                             (robot_id,)).fetchone()
                receipt = json.loads(current['assessment']) if current else None
                revision = (judgment_revision(receipt) if row['closed_at'] is None and receipt is not None
                            and receipt['request'].get('case_id') == stuck_id else None)
                answers = [dict(item) for item in connection.execute(
                    """SELECT at, decision, principal_id, accepted, outcome, code, tier, escalated
                       FROM fleet_line_stuck_answers WHERE robot_id=? AND stuck_id=? ORDER BY answer_id""",
                    (robot_id, stuck_id))]
                reviews = [dict(item) for item in connection.execute(
                    """SELECT at, principal_id, root_cause, note FROM fleet_incident_reviews
                       WHERE robot_id=? AND stuck_id=? ORDER BY review_id""", (robot_id, stuck_id))]
                opened = datetime.fromisoformat(row["opened_at"]).timestamp()
                camera = None
                if "sighting_audit" in tables:
                    # shortcut: only a nearby accepted sighting is joined; use a recording index for image review.
                    seen = connection.execute(
                        """SELECT source_id, seq, captured_at, received_at FROM sighting_audit
                           WHERE robot_id=? AND captured_at BETWEEN ? AND ?
                           ORDER BY ABS(captured_at - ?) LIMIT 1""",
                        (robot_id, opened - 5, opened + 5, opened)).fetchone()
                    if seen is not None:
                        camera = dict(seen)
                ai = []
                if "fleet_ai_facts" in tables:
                    draft = connection.execute(
                        """SELECT kind, robot_ids, value, confidence, evidence, source, observed_at, stage
                           FROM fleet_ai_facts WHERE kind='incident_context'
                             AND json_extract(evidence, '$.stuck_id')=?
                             AND observed_at BETWEEN ? AND ?
                           ORDER BY observed_at DESC LIMIT 20""",
                        (stuck_id, opened - 5, opened + 120)).fetchall()
                    for fact in draft:
                        item = dict(fact)
                        item["robot_ids"] = json.loads(item["robot_ids"])
                        if robot_id in item["robot_ids"]:
                            item["value"] = json.loads(item["value"])
                            item["evidence"] = json.loads(item["evidence"])
                            ai.append(item)
                            break
                    candidates = connection.execute(
                        """SELECT kind, robot_ids, value, confidence, evidence, source, observed_at, stage
                           FROM fleet_ai_facts WHERE kind!='incident_context' AND observed_at BETWEEN ? AND ?
                           ORDER BY observed_at DESC LIMIT 50""", (opened - 5, opened + 5)).fetchall()
                    for fact in candidates:
                        item = dict(fact)
                        item["robot_ids"] = json.loads(item["robot_ids"])
                        if robot_id in item["robot_ids"]:
                            item["value"] = json.loads(item["value"])
                            item["evidence"] = json.loads(item["evidence"])
                            ai.append(item)
                            if len(ai) == 3:
                                break
                has_answer = any(a['decision'] != 'ESCALATE' and a['accepted'] != 0 for a in answers)
                status = 'OPEN'
                if row['closed_at'] is not None:
                    status = 'OBSERVATION_ENDED'
                    if row['close_reason'] == 'cleared':
                        status = 'CLEARANCE_OBSERVED' if has_answer else 'NATURAL_CLEARANCE'
                closure = FleetObservedClosure(
                    status=status, action_credit='UNVERIFIED' if has_answer else 'NONE',
                    reason=row['close_reason'], observed_at=row['closed_at'],
                ).model_dump(mode='json')
                reports.append({"schema": "rosy.incident.v1", "id": f"line_stuck:{robot_id}:{stuck_id}",
                                "closure": closure,
                                "handoff": self.handoff.get(robot_id, stuck_id),
                                "judgment_revision": revision,
                                "notifications": self.notifications.rows(20, robot_id=robot_id, stuck_id=stuck_id),
                                "stuck_id": stuck_id,
                                "classification": "line_stuck", "robot_ids": [robot_id],
                                "opened_at": row["opened_at"], "closed_at": row["closed_at"],
                                "evidence": {
                                    "core": {key: row[key] for key in ("cause", "phase_at_open", "held_s_max",
                                                                           "attempts_max", "local_enabled_at_open")},
                                    "fleet": {key: row[key] for key in ("source", "trip_busy_at_open",
                                                                            "peer_ahead_at_open", "pose_x", "pose_y",
                                                                            "pose_yaw", "pose_state", "pose_age_s",
                                                                            "close_reason", "resolved_by", "escalation_code")},
                                    "rosy_cam": camera, "ai_facts": ai,
                                    "front_image": {"status": "requestable_while_open" if row["closed_at"] is None
                                                    else "not_retained"}},
                                "actions": answers, "reviews": reviews})
        return reports

    def review(self, robot_id: str, stuck_id: str, *, principal_id: str,
               root_cause: str, note: str) -> bool:
        with closing(self._connect()) as connection, connection:
            found = connection.execute(
                "SELECT 1 FROM fleet_line_stuck_episodes WHERE robot_id=? AND stuck_id=?",
                (robot_id, stuck_id)).fetchone()
            if found is None:
                return False
            connection.execute(
                """INSERT INTO fleet_incident_reviews (robot_id, stuck_id, at, principal_id, root_cause, note)
                   VALUES (?, ?, ?, ?, ?, ?)""",
                (robot_id, stuck_id, datetime.now(timezone.utc).isoformat(timespec="milliseconds"),
                 principal_id, root_cause, note))
        return True

    def traffic_reports(self, limit: int = 100) -> list[dict]:
        """Durable AI situation facts, kept distinct from CORE line-stuck episodes."""
        with closing(self._connect()) as connection:
            if not connection.execute(
                    "SELECT 1 FROM sqlite_master WHERE type='table' AND name='fleet_ai_facts'").fetchone():
                return []
            facts = connection.execute(
                """SELECT fact_row, kind, robot_ids, value, confidence, evidence, source,
                          observed_at, ttl_s, stage, rule_input FROM fleet_ai_facts
                   WHERE kind IN ('wait_cycle_confirmed', 'wait_cycle_stale_input',
                                  'waiting_but_moving', 'livelock', 'stalled', 'unknown_occupancy_long')
                   ORDER BY fact_row DESC LIMIT ?""", (limit,)).fetchall()
            reports = []
            for fact in facts:
                row = dict(fact)
                row["robot_ids"] = json.loads(row["robot_ids"])
                row["value"] = json.loads(row["value"])
                row["evidence"] = json.loads(row["evidence"])
                reviews = [dict(item) for item in connection.execute(
                    """SELECT at, principal_id, root_cause, note FROM fleet_ai_fact_reviews
                       WHERE fact_row=? ORDER BY review_id""", (row["fact_row"],))]
                reports.append({"schema": "rosy.incident.v1", "id": f"ai_fact:{row['fact_row']}",
                                "classification": row["kind"], "robot_ids": row["robot_ids"],
                                "opened_at": datetime.fromtimestamp(row["observed_at"], timezone.utc).isoformat(),
                                "evidence": {"ai_fact": row, "fleet": None, "core": None,
                                             "rosy_cam": None, "front_image": {"status": "not_retained"}},
                                "actions": [], "reviews": reviews})
        return reports

    def review_traffic_fact(self, fact_row: int, *, principal_id: str,
                            root_cause: str, note: str) -> bool:
        with closing(self._connect()) as connection, connection:
            if not connection.execute(
                    "SELECT 1 FROM sqlite_master WHERE type='table' AND name='fleet_ai_facts'").fetchone():
                return False
            if not connection.execute(
                    "SELECT 1 FROM fleet_ai_facts WHERE fact_row=?", (fact_row,)).fetchone():
                return False
            connection.execute(
                """INSERT INTO fleet_ai_fact_reviews (fact_row, at, principal_id, root_cause, note)
                   VALUES (?, ?, ?, ?, ?)""",
                (fact_row, datetime.now(timezone.utc).isoformat(timespec="milliseconds"),
                 principal_id, root_cause, note))
        return True

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.path, timeout=5.0)
        connection.row_factory = sqlite3.Row
        return configure_connection(connection)
