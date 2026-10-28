"""SQLite task-column and legacy reservation migrations for the existing task ledger."""
import sqlite3


class TaskSchemaMigrations:
    @staticmethod
    def _migrate_dispatch_claims(connection: sqlite3.Connection) -> None:
        connection.execute("BEGIN IMMEDIATE")
        connection.execute(
            """INSERT OR IGNORE INTO fleet_action_claims
               (resource_key, resource_kind, resource_id, owner_kind, owner_id,
                generation, phase, lease_until, created_at)
               SELECT 'robot:' || r.robot_id, 'robot', r.robot_id, 'task', r.task_id,
                      COALESCE(t.dispatch_generation, 0),
                      CASE WHEN t.status='UNKNOWN' THEN 'UNKNOWN'
                           WHEN t.dispatch_phase='DISPATCHING' THEN 'DISPATCHING'
                           ELSE 'CLAIMED' END,
                      CASE WHEN t.dispatch_phase='READY' THEN t.lease_until ELSE NULL END,
                      r.reserved_at
               FROM fleet_robot_reservations r
               LEFT JOIN fleet_tasks t ON t.task_id=r.task_id"""
        )
        connection.commit()

    @staticmethod
    def _migrate_task_columns(connection: sqlite3.Connection) -> None:
        columns = {row[1] for row in connection.execute("PRAGMA table_info(fleet_tasks)")}
        additions = {
            "priority_class": "INTEGER NOT NULL DEFAULT 0",
            "queued_at": "TEXT",
            "first_queued_at": "TEXT",
            "expires_at": "TEXT",
            "lease_owner": "TEXT",
            "lease_until": "TEXT",
            "dispatch_generation": "INTEGER NOT NULL DEFAULT 0",
            "dispatch_phase": "TEXT NOT NULL DEFAULT 'READY'",
            "attempt_id": "TEXT",
            "attempt_seq": "INTEGER NOT NULL DEFAULT 0",
            "blocked_by": "TEXT",
            "waiting_on_json": "TEXT NOT NULL DEFAULT '[]'",
        }
        connection.execute("BEGIN IMMEDIATE")
        for name, definition in additions.items():
            if name not in columns:
                connection.execute(f"ALTER TABLE fleet_tasks ADD COLUMN {name} {definition}")

    @staticmethod
    def _migrate_dispatch_control(connection: sqlite3.Connection) -> None:
        columns = {row[1] for row in connection.execute(
            "PRAGMA table_info(fleet_dispatch_control)"
        )}
        if "authority_epoch" not in columns:
            connection.execute(
                "ALTER TABLE fleet_dispatch_control ADD COLUMN authority_epoch "
                "INTEGER NOT NULL DEFAULT 0"
            )
        connection.execute(
            "CREATE INDEX IF NOT EXISTS fleet_tasks_queue_order "
            "ON fleet_tasks(status, priority_class, queued_at, task_id)"
        )
        connection.execute(
            "CREATE INDEX IF NOT EXISTS fleet_tasks_dispatch_queue_position "
            "ON fleet_tasks(priority_class, queued_at, task_id) "
            "WHERE status='QUEUED' AND lease_owner IS NULL "
            "AND dispatch_phase IN ('READY', 'WAITING_TRAFFIC')"
        )
        connection.commit()
