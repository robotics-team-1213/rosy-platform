"""D-862 journal tables in the existing Task database; no execution on migration."""


def ensure_schema(connection):
    statements = """
        CREATE TABLE IF NOT EXISTS fleet_control_stops (
            origin_id TEXT NOT NULL, stop_id TEXT NOT NULL, unit_id TEXT NOT NULL,
            config_revision TEXT NOT NULL, target_unit TEXT NOT NULL,
            body_json TEXT NOT NULL, actor_id TEXT NOT NULL,
            revision INTEGER NOT NULL, updated_at TEXT NOT NULL,
            PRIMARY KEY(origin_id, stop_id));
        CREATE TABLE IF NOT EXISTS fleet_control_stop_deliveries (
            origin_id TEXT NOT NULL, stop_id TEXT NOT NULL, delivery_unit TEXT NOT NULL,
            kind TEXT NOT NULL CHECK(kind IN ('LOCAL','CHILD')),
            assigned_json TEXT NOT NULL, state TEXT NOT NULL, ticket TEXT,
            results_json TEXT NOT NULL, peer_revision INTEGER NOT NULL DEFAULT 0,
            original_json TEXT, reconcile_json TEXT, reconciled_by TEXT,
            PRIMARY KEY(origin_id, stop_id, delivery_unit),
            FOREIGN KEY(origin_id, stop_id) REFERENCES fleet_control_stops(origin_id, stop_id));
        CREATE INDEX IF NOT EXISTS fleet_control_stop_pending
            ON fleet_control_stop_deliveries(state, kind);
    """
    for statement in statements.split(";"):
        if statement.strip():
            connection.execute(statement)
