"""D-407/D-608 durable stuck answers, episodes and incident reviews."""

from __future__ import annotations

import json
import sqlite3
from contextlib import closing
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from fleet.server.sqlite_policy import configure_connection


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

    def append(self, row: dict) -> None:
        accepted = None if row["accepted"] is None else int(bool(row["accepted"]))
        with closing(self._connect()) as connection, connection:
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

    def reports(self, limit: int = 100) -> list[dict]:
        """Read-only, source-separated incident records for operator review and offline learning."""
        with closing(self._connect()) as connection:
            episodes = connection.execute(
                "SELECT * FROM fleet_line_stuck_episodes ORDER BY rowid DESC LIMIT ?", (limit,)).fetchall()
            tables = {row[0] for row in connection.execute("SELECT name FROM sqlite_master WHERE type='table'")}
            reports = []
            for episode in episodes:
                row = dict(episode)
                robot_id, stuck_id = row["robot_id"], row["stuck_id"]
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
                reports.append({"schema": "rosy.incident.v1", "id": f"line_stuck:{robot_id}:{stuck_id}",
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
