"""Real journal/latch transactions; no mocked latch helper or device execution."""

from contextlib import closing
import json
import sqlite3

import pytest

from core_common.protocol.integrated_control import ControlStopIngress, ControlStopReconcile
from fleet.server.cell_job_store import CellJobStore
from fleet.server.charge_store import ChargeStore
from fleet.server.control_stop_store import ControlStopStore, has_local_uncertainty
from fleet.server.task_scheduler import FleetTaskScheduler
from fleet.server.task_store import FleetTaskStore, InvalidTaskTransition
from test_cell_job_store import _create, _stores
from test_charge_store import session
from test_task_scheduler import _queue


def owners(tmp_path):
    path, tasks, _, enabled = _stores(tmp_path)
    cell = CellJobStore(path)
    _create(cell)
    cell.admit("cell-mission-1", actor_id="operator-1", expected_generation=enabled["generation"])
    charge = ChargeStore(tasks)
    charge.reserve(session())
    _queue(tasks, task_id="leased-work", robot_id="robot-work")
    assert FleetTaskScheduler(tasks, worker_id="worker").claim_next({"robot-work"}) is not None
    return tasks, cell, charge


def capture(tasks):
    with closing(tasks._connect()) as connection:
        return {table: [dict(row) for row in connection.execute("SELECT * FROM " + table + " ORDER BY 1")]
                for table in ("fleet_dispatch_control", "fleet_tasks", "fleet_robot_reservations",
                              "fleet_action_claims", "fleet_cell_jobs", "fleet_cell_steps", "fleet_cell_events",
                              "fleet_charge_sessions", "fleet_charge_history")}


def ingress(tasks, *, unit="R", revision="v1"):
    current = tasks.dispatch_control()
    return ControlStopIngress(origin_id=unit, stop_id="stop-1", target_unit=unit, config_revision=revision,
                              expected_controls={unit: {key: current[key]
                                                        for key in ("authority_epoch", "generation")}})


def test_standalone_task_store_initializes_stop_schema_before_existing_dispatch_queries(tmp_path):
    tasks = FleetTaskStore(tmp_path / "standalone.sqlite3")
    control = tasks.dispatch_control()
    assert set(control) == {"authority_epoch", "generation", "dispatch_enabled", "reason", "queued_tasks",
                            "unresolved_actions", "rearm_available"}
    assert control["unresolved_actions"] == 0 and control["rearm_available"]
    with closing(tasks._connect()) as connection:
        assert not has_local_uncertainty(connection)
        assert connection.execute("SELECT COUNT(*) FROM fleet_control_stops").fetchone()[0] == 0
        assert connection.execute("SELECT COUNT(*) FROM fleet_control_stop_deliveries").fetchone()[0] == 0
    enabled = tasks.rearm_dispatch(expected_generation=control["generation"], actor_id="operator")
    stopped = tasks.trip_stop_latch(actor_id="operator")
    assert stopped["generation"] == enabled["generation"] + 1 and stopped["rearm_available"]
    assert tasks.rearm_dispatch(expected_generation=stopped["generation"], actor_id="operator")["dispatch_enabled"]


def test_connection_scoped_helper_preserves_caller_transaction_and_all_cleanup_rollback(tmp_path):
    tasks, _, _ = owners(tmp_path)
    before = capture(tasks)
    with closing(tasks._connect()) as connection:
        connection.execute("BEGIN IMMEDIATE")
        tasks._advance_dispatch_control_in(connection, enabled=False, actor_id="operator",
                                           reason="CONTROL_UNIT_STOP", release_pre_dispatch=True)
        assert connection.in_transaction
        assert connection.execute("SELECT generation FROM fleet_dispatch_control").fetchone()[0] == (
            before["fleet_dispatch_control"][0]["generation"] + 1)
        assert connection.execute("SELECT phase FROM fleet_action_claims WHERE owner_kind='charge_session'"
                                  ).fetchone()[0] == "UNKNOWN"
        connection.rollback()
    assert capture(tasks) == before


def test_journal_failure_after_real_latch_rolls_back_cell_charge_and_pre_dispatch_claims(tmp_path, monkeypatch):
    tasks, _, _ = owners(tmp_path)
    journal = ControlStopStore(tasks, unit_id="R", config_revision="v1")
    request = ingress(tasks)
    before = capture(tasks)

    def unavailable(*args, **kwargs):
        raise sqlite3.OperationalError("synthetic journal insertion failure after latch")

    monkeypatch.setattr(journal, "_insert", unavailable)
    with pytest.raises(sqlite3.OperationalError):
        journal.claim(request, scope=("R",), assignments={}, actor_id="operator")
    assert capture(tasks) == before
    assert journal.history().stops == []
    with closing(tasks._connect()) as connection:
        assert connection.execute("SELECT COUNT(*) FROM fleet_control_stop_deliveries").fetchone()[0] == 0


@pytest.mark.parametrize("operation", ["typed", "site_stop", "restart"])
def test_existing_cell_charge_and_pre_dispatch_cleanup_survives_latch_binding(tmp_path, operation):
    tasks, cell, _ = owners(tmp_path)
    before = tasks.dispatch_control()
    if operation == "typed":
        journal = ControlStopStore(tasks, unit_id="R", config_revision="v1")
        claimed = journal.claim(ingress(tasks), scope=("R",), assignments={}, actor_id="operator")
        assert len(claimed.tickets) == 1
        assert claimed.snapshot.results[0].dispatch.generation == before["generation"] + 1
        control = tasks.dispatch_control()
    else:
        control = tasks.trip_stop_latch(actor_id="operator") if operation == "site_stop" else (
            tasks.close_dispatch_for_startup())
    assert control["generation"] == before["generation"] + 1
    assert control["authority_epoch"] == before["authority_epoch"] + (operation == "restart")
    assert not control["dispatch_enabled"] and control["unresolved_actions"] == 2
    assert not control["rearm_available"]
    job = cell.get("cell-mission-1")
    if operation != "restart":
        assert (job["status"], job["reason"]) == ("HOLD", "site_stop")
    else:
        assert job["status"] == "READY"
    with closing(tasks._connect()) as connection:
        claims = [dict(row) for row in connection.execute("SELECT owner_kind,phase FROM fleet_action_claims")]
        assert all(row["phase"] == "HELD" for row in claims if row["owner_kind"] == "mission")
        assert [row["phase"] for row in claims if row["owner_kind"] == "charge_session"] == ["UNKNOWN", "UNKNOWN"]
        assert not any(row["owner_kind"] == "task" for row in claims)
        assert connection.execute("SELECT COUNT(*) FROM fleet_robot_reservations").fetchone()[0] == 0
    task = tasks.get_task("leased-work")
    assert task["status"] == "QUEUED" and task["lease_owner"] is task["lease_until"] is None
    with pytest.raises(InvalidTaskTransition, match="unresolved"):
        tasks.rearm_dispatch(expected_generation=control["generation"], actor_id="operator")


def test_unknown_stop_blocks_actual_rearm_across_configuration_identity_changes(tmp_path):
    tasks = FleetTaskStore(tmp_path / "site.sqlite3")
    old = ControlStopStore(tasks, unit_id="old-unit", config_revision="v1")
    claimed = old.claim(ingress(tasks, unit="old-unit"), scope=("old-unit",), assignments={}, actor_id="operator")
    assert old.fail("old-unit", "stop-1", "old-unit", claimed.tickets[0].ticket)
    ControlStopStore(tasks, unit_id="new-unit", config_revision="v2")
    current = tasks.close_dispatch_for_startup()
    assert current["unresolved_actions"] == 0 and not current["rearm_available"]
    with pytest.raises(InvalidTaskTransition, match="control stop"):
        tasks.rearm_dispatch(expected_generation=current["generation"], actor_id="operator")
    confirmation = ControlStopReconcile(expected_generation=current["generation"],
                                        receiver_channels_terminated=True, receivers_recommissioned=True,
                                        affected_units=["old-unit"],
                                        evidence="Synthetic named recommissioning attestation")
    view = old.reconcile("old-unit", "stop-1", confirmation, actor_id="named-local", live_work=lambda *_: False)
    assert view.results[0].state == "SUPERSEDED_BY_OPERATOR_RECOMMISSIONING"
    assert tasks.dispatch_control()["rearm_available"] and tasks.dispatch_control()["unresolved_actions"] == 0
    enabled = tasks.rearm_dispatch(expected_generation=current["generation"], actor_id="operator")
    assert enabled["dispatch_enabled"] and enabled["generation"] == current["generation"] + 1
    with closing(tasks._connect()) as connection:
        row = connection.execute("SELECT original_json FROM fleet_control_stop_deliveries").fetchone()
        assert json.loads(row["original_json"])[0]["state"] == "UNKNOWN"
    assert old.snapshot("old-unit", "stop-1").results[0].state == "SUPERSEDED_BY_OPERATOR_RECOMMISSIONING"
