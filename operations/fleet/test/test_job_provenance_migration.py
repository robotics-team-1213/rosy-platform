"""D-856: preserve populated legacy journals while separating physical provenance."""
from concurrent.futures import ThreadPoolExecutor
from contextlib import closing
import importlib
import json
from pathlib import Path
import sqlite3

import pytest

from fleet.server.cell_job_store import CellJobStore
from fleet.server import cell_sheet_checkpoints, step_ledger_schema
from fleet.server.dispatch_admission import reserve
from fleet.server.sqlite_policy import configure_connection
from test_cell_job_store import _stores, _submission, _step


def initialize():
    try:
        return importlib.import_module("fleet.server.job_provenance_schema").initialize
    except ModuleNotFoundError:
        pytest.fail("atomic job provenance migration is missing")


def connect(path):
    connection = sqlite3.connect(path)
    connection.row_factory = sqlite3.Row
    return configure_connection(connection)


def legacy_database(tmp_path):
    path, _, _, control = _stores(tmp_path)
    with closing(connect(path)) as connection:
        connection.executescript((Path(__file__).parent / "fixtures/cell_jobs_v4.sql").read_text())
        connection.execute("INSERT INTO fleet_component_migrations VALUES('cell_jobs',4,'before')")
        step_ledger_schema.ensure(connection)
        cell_sheet_checkpoints.migrate(connection)
        submission = _submission(1)
        for index, (kind, status, phase) in enumerate([
            ("CELL_TRANSFER", "RUNNING", "UNKNOWN"), ("CELL_TRANSFER", "HOLD", "HELD"),
            ("TRIP", "READY", "CLAIMED"),
        ]):
            mission = f"legacy-{index}"
            row = dict(mission_id=mission, proposal_principal_id="operator-1", request_key=mission,
                       request_digest="0" * 64, job_id=mission, workcell_id="workcell-1", instance_id="arm-1",
                       recipe_digest="a" * 64, cell_digest="b" * 64, process_artifact_digest="c" * 64,
                       job_json=json.dumps(submission["job"]), resources_json='[["workcell","'+mission+'"]]',
                       ledger_markers_json="[]", status=status, current_step_index=0,
                       authority_epoch=control["authority_epoch"], dispatch_generation=control["generation"],
                       reason=None, created_at="before", updated_at="before")
            connection.execute(f"INSERT INTO fleet_cell_jobs ({','.join(row)}) VALUES "
                               f"({','.join(':'+key for key in row)})", row)
            connection.execute("INSERT INTO fleet_cell_steps(mission_id,step_index,step_id,action_kind,"
                               "step_json,status,action_id,attempt_id,updated_at) VALUES(?,0,?,?,?,?,?,?,?)",
                               (mission, f"step-{index}", kind, json.dumps(_step()), status,
                                f"action-{index}", f"attempt-{index}", "before"))
            connection.execute("INSERT INTO fleet_cell_events(event_key,mission_id,event_type,actor_id,"
                               "detail_json,created_at) VALUES(?,?,'legacy','operator-1','{}','before')",
                               (mission, mission))
            reserve(connection, owner_kind="mission", owner_id=mission, generation=control["generation"],
                    resources=[("workcell", mission)], phase="CLAIMED")
            connection.execute("UPDATE fleet_action_claims SET phase=? WHERE owner_id=?", (phase, mission))
        connection.execute("CREATE INDEX provenance_test_status ON fleet_cell_jobs(status)")
        connection.execute("CREATE VIEW provenance_test_view AS SELECT mission_id,reason FROM fleet_cell_jobs")
        connection.execute("CREATE TRIGGER provenance_test_child AFTER UPDATE ON fleet_cell_events BEGIN "
                           "UPDATE fleet_cell_jobs SET reason='child-updated' WHERE mission_id=NEW.mission_id; END")
        connection.commit()
    return path


def snapshot(path):
    with closing(connect(path)) as connection:
        tables = [r[0] for r in connection.execute("SELECT name FROM sqlite_master WHERE type='table'")
                  if not r[0].startswith("sqlite_") and r[0] != "fleet_component_migrations"]
        return {name: sorted((repr({k: row[k] for k in row.keys() if k != "provenance_kind"})
                              for row in connection.execute(f'SELECT * FROM "{name}"')))
                for name in tables}


def test_populated_v4_migrates_without_changing_rows_claims_or_mirror_behavior(tmp_path):
    path = legacy_database(tmp_path)
    before = snapshot(path)
    initialize()
    store = CellJobStore(path)
    assert snapshot(path) == before
    assert "provenance_kind" not in store.get("legacy-0")
    with closing(connect(path)) as connection:
        assert not connection.execute("PRAGMA foreign_key_check").fetchall()
        assert {r[0] for r in connection.execute("SELECT provenance_kind FROM fleet_cell_jobs")} == {"legacy"}
        assert connection.execute("SELECT reason FROM provenance_test_view WHERE mission_id='legacy-0'").fetchone()[0] is None
        connection.execute("UPDATE fleet_cell_events SET actor_id='other' WHERE mission_id='legacy-0'")
        assert connection.execute("SELECT reason FROM fleet_cell_jobs WHERE mission_id='legacy-0'").fetchone()[0] == "child-updated"
        assert connection.execute("SELECT name FROM sqlite_master WHERE name='provenance_test_status'").fetchone()
    assert snapshot(path) == before
    CellJobStore(path)
    assert snapshot(path) == before


def test_later_initialization_failure_rolls_back_schema_version_and_rows_and_restores_fk(tmp_path):
    path = legacy_database(tmp_path)
    before = snapshot(path)
    with closing(connect(path)) as connection:
        old_sql = connection.execute("SELECT sql FROM sqlite_master WHERE name='fleet_cell_jobs'").fetchone()[0]
        with pytest.raises(RuntimeError, match="injected"):
            with initialize()(connection, version=5, now="after"):
                raise RuntimeError("injected after parent rebuild")
        assert connection.execute("PRAGMA foreign_keys").fetchone()[0] == 1
        assert connection.execute("SELECT sql FROM sqlite_master WHERE name='fleet_cell_jobs'").fetchone()[0] == old_sql
        assert connection.execute("SELECT MAX(version) FROM fleet_component_migrations WHERE component='cell_jobs'").fetchone()[0] == 4
    assert snapshot(path) == before
    CellJobStore(path)
    assert snapshot(path) == before


def test_open_transaction_and_future_version_are_rejected_without_implicit_commit(tmp_path):
    path = legacy_database(tmp_path)
    with closing(connect(path)) as connection:
        connection.execute("UPDATE fleet_cell_jobs SET reason='pending' WHERE mission_id='legacy-0'")
        with pytest.raises(RuntimeError, match="transaction"):
            with initialize()(connection, version=5, now="after"):
                pass
        assert connection.in_transaction
        connection.rollback()
        connection.execute("INSERT INTO fleet_component_migrations VALUES('cell_jobs',6,'future')")
        connection.commit()
    before = snapshot(path)
    with pytest.raises(RuntimeError, match="unsupported.*6"):
        CellJobStore(path)
    assert snapshot(path) == before


def test_concurrent_startups_apply_once_and_preserve_legacy_data(tmp_path):
    path = legacy_database(tmp_path)
    before = snapshot(path)
    initialize()
    with ThreadPoolExecutor(max_workers=2) as pool:
        list(pool.map(CellJobStore, [path, path]))
    assert snapshot(path) == before
    with closing(connect(path)) as connection:
        assert connection.execute("SELECT COUNT(*) FROM fleet_component_migrations WHERE component='cell_jobs' AND version=5").fetchone()[0] == 1


@pytest.mark.parametrize("kind,legacy", [(None, False), ("other", False), ("physical", True), ("legacy", False)])
def test_parent_union_constraints_reject_null_unknown_and_mixed_provenance(tmp_path, kind, legacy):
    path = legacy_database(tmp_path)
    initialize()
    CellJobStore(path)
    with closing(connect(path)) as connection:
        with pytest.raises(sqlite3.IntegrityError):
            connection.execute("UPDATE fleet_cell_jobs SET provenance_kind=?,job_id=?,recipe_digest=?,"
                               "cell_digest=?,process_artifact_digest=? WHERE mission_id='legacy-0'",
                               (kind, *(('x',) * 4 if legacy else (None,) * 4)))


def test_physical_row_is_not_read_or_dispatched_as_a_cell_process(tmp_path):
    path = legacy_database(tmp_path)
    initialize()
    store = CellJobStore(path)
    with closing(connect(path)) as connection:
        connection.execute("UPDATE fleet_cell_jobs SET provenance_kind='physical',job_id=NULL,"
                           "recipe_digest=NULL,cell_digest=NULL,process_artifact_digest=NULL WHERE mission_id='legacy-2'")
        connection.commit()
    assert store.get("legacy-2") is None
    assert "legacy-2" not in {row["mission_id"] for row in store.jobs("READY")}
    with pytest.raises(KeyError):
        store.cancel("legacy-2", actor_id="operator-1")


@pytest.mark.parametrize("constraint", ["", " DEFAULT 'legacy'"])
def test_matching_columns_without_provenance_constraints_are_not_accepted(tmp_path, constraint):
    path = tmp_path / "weak-schema.sqlite3"
    sql = (Path(__file__).parent / "fixtures/cell_jobs_v4.sql").read_text()
    for name in ("job_id", "recipe_digest", "cell_digest", "process_artifact_digest"):
        sql = sql.replace(name + " TEXT NOT NULL", name + " TEXT")
    with closing(connect(path)) as connection:
        connection.executescript(sql)
        connection.execute("ALTER TABLE fleet_cell_jobs ADD COLUMN provenance_kind TEXT NOT NULL" + constraint)
        connection.execute("INSERT INTO fleet_component_migrations VALUES('cell_jobs',4,'weak')")
        connection.commit()
        before = connection.execute("SELECT sql FROM sqlite_master WHERE name='fleet_cell_jobs'").fetchone()[0]
        with pytest.raises(RuntimeError, match="unsupported.*schema"):
            with initialize()(connection, version=5, now="after"):
                pass
        assert connection.execute("SELECT sql FROM sqlite_master WHERE name='fleet_cell_jobs'").fetchone()[0] == before
        assert connection.execute("SELECT MAX(version) FROM fleet_component_migrations WHERE component='cell_jobs'").fetchone()[0] == 4
