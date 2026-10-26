"""Atomic parent-journal provenance migration; legacy execution values stay unchanged."""
from contextlib import contextmanager
import re

from .cell_arm_ledger import _run

_PARENT_SQL = """CREATE TABLE fleet_cell_jobs (
mission_id TEXT PRIMARY KEY,
proposal_principal_id TEXT NOT NULL,
request_key TEXT NOT NULL,
request_digest TEXT NOT NULL,
job_id TEXT,
workcell_id TEXT NOT NULL,
instance_id TEXT NOT NULL,
recipe_digest TEXT,
cell_digest TEXT,
process_artifact_digest TEXT,
job_json TEXT NOT NULL,
resources_json TEXT NOT NULL,
ledger_markers_json TEXT NOT NULL,
status TEXT NOT NULL CHECK(status IN (
'PROPOSED', 'READY', 'RUNNING', 'ACTION_SUCCEEDED',
'GOAL_CONFIRMED', 'HOLD'
)),
current_step_index INTEGER NOT NULL DEFAULT 0 CHECK(current_step_index >= 0),
authority_epoch INTEGER,
dispatch_generation INTEGER,
reason TEXT,
created_at TEXT NOT NULL,
updated_at TEXT NOT NULL,
provenance_kind TEXT NOT NULL DEFAULT 'legacy' CHECK(provenance_kind IN ('legacy','physical')),
CHECK((provenance_kind='legacy' AND job_id IS NOT NULL AND recipe_digest IS NOT NULL
AND cell_digest IS NOT NULL AND process_artifact_digest IS NOT NULL)
OR (provenance_kind='physical' AND job_id IS NULL AND recipe_digest IS NULL
AND cell_digest IS NULL AND process_artifact_digest IS NULL))
);"""
_BASE_SQL = """CREATE TABLE IF NOT EXISTS fleet_component_migrations (
component TEXT NOT NULL,
version INTEGER NOT NULL,
applied_at TEXT NOT NULL,
PRIMARY KEY(component, version)
);
CREATE TABLE IF NOT EXISTS fleet_cell_events (
event_id INTEGER PRIMARY KEY AUTOINCREMENT,
event_key TEXT NOT NULL UNIQUE,
mission_id TEXT NOT NULL REFERENCES fleet_cell_jobs(mission_id),
step_index INTEGER,
event_type TEXT NOT NULL,
actor_id TEXT NOT NULL,
detail_json TEXT NOT NULL,
created_at TEXT NOT NULL
);"""
_LEGACY_COLUMNS = (
    "mission_id", "proposal_principal_id", "request_key", "request_digest", "job_id",
    "workcell_id", "instance_id", "recipe_digest", "cell_digest", "process_artifact_digest",
    "job_json", "resources_json", "ledger_markers_json", "status", "current_step_index",
    "authority_epoch", "dispatch_generation", "reason", "created_at", "updated_at",
)


def _canonical_sql(sql):
    sql = sql.replace('CREATE TABLE "fleet_cell_jobs"', 'CREATE TABLE fleet_cell_jobs')
    return re.sub(r"\s+", " ", sql).strip().rstrip(";")


def _quoted(identifier):
    return '"' + identifier.replace('"', '""') + '"'


def _rebuild(connection):
    expected = _PARENT_SQL.split(",\nprovenance_kind ", 1)[0] + "\n)"
    for name in ("job_id", "recipe_digest", "cell_digest", "process_artifact_digest"):
        expected = expected.replace(f"\n{name} TEXT,", f"\n{name} TEXT NOT NULL,")
    sql = connection.execute("SELECT sql FROM sqlite_master WHERE name='fleet_cell_jobs'").fetchone()[0]
    if _canonical_sql(sql) != _canonical_sql(expected):
        raise RuntimeError("unsupported legacy job provenance schema")
    objects = connection.execute(
        "SELECT type,name,sql FROM sqlite_master WHERE sql IS NOT NULL "
        "AND (type IN ('trigger','view') OR (type='index' AND tbl_name='fleet_cell_jobs'))"
    ).fetchall()
    for kind, name, _ in objects:
        if kind in {"trigger", "view"}:
            connection.execute(f"DROP {kind.upper()} {_quoted(name)}")
    connection.execute(_PARENT_SQL.replace("fleet_cell_jobs (", "fleet_cell_jobs_next (", 1))
    columns = ",".join(_LEGACY_COLUMNS)
    connection.execute(f"INSERT INTO fleet_cell_jobs_next ({columns}) SELECT {columns} FROM fleet_cell_jobs")
    connection.execute("DROP TABLE fleet_cell_jobs")
    connection.execute("ALTER TABLE fleet_cell_jobs_next RENAME TO fleet_cell_jobs")
    for kind in ("index", "view", "trigger"):
        for object_kind, _, sql in objects:
            if object_kind == kind:
                connection.execute(sql)


@contextmanager
def initialize(connection, *, version, now):
    """Own one startup transaction, including the caller's step/sheet initialization."""
    if connection.in_transaction:
        raise RuntimeError("job provenance initialization requires no active transaction")
    foreign_keys = connection.execute("PRAGMA foreign_keys").fetchone()[0]
    if foreign_keys != 1:
        raise RuntimeError("job provenance initialization requires foreign keys enabled")
    connection.execute("PRAGMA foreign_keys=OFF")
    try:
        connection.execute("BEGIN IMMEDIATE")
        _run(connection, _BASE_SQL)
        applied = connection.execute(
            "SELECT MAX(version) FROM fleet_component_migrations WHERE component='cell_jobs'"
        ).fetchone()[0] or 0
        if applied > version:
            raise RuntimeError(f"unsupported Cell Job journal migration version {applied}")
        columns = {row[1]: row for row in connection.execute("PRAGMA table_info(fleet_cell_jobs)")}
        if not columns:
            connection.execute(_PARENT_SQL)
        elif set(columns) == set(_LEGACY_COLUMNS):
            _rebuild(connection)
        else:
            sql = connection.execute("SELECT sql FROM sqlite_master WHERE name='fleet_cell_jobs'").fetchone()[0]
            if _canonical_sql(sql) != _canonical_sql(_PARENT_SQL):
                raise RuntimeError("unsupported job provenance schema")
        yield
        if connection.execute("PRAGMA foreign_key_check").fetchone() is not None:
            raise RuntimeError("job provenance migration violates foreign keys")
        connection.execute(
            "INSERT OR IGNORE INTO fleet_component_migrations(component,version,applied_at) "
            "VALUES('cell_jobs',?,?)", (version, now))
        connection.commit()
    except BaseException:
        connection.rollback()
        raise
    finally:
        connection.execute("PRAGMA foreign_keys=ON")
