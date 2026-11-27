"""2026-11-27: a process restart alone no longer needs a human rearm; every other close still does."""
import asyncio
from contextlib import closing
from hashlib import sha256
from types import SimpleNamespace

import pytest
from fastapi import FastAPI
from rosy_account.principal import SitePrincipal
from core_common.protocol.arm_incident.arm_incidents import ArmIncidentReport
from fleet.server.arm_incidents import ArmIncidentStore
from fleet.server import dispatch_auto_rearm
from fleet.server.dispatch_auto_rearm import install_auto_rearm
from fleet.server.ledger.task_dispatch_routes import install_task_dispatch_routes
from test_arm_incidents import report as incident_report

from fakes import FakeRobot
from fleet.server.app import create_app
from fleet.server.console import FleetConsole
from fleet.server.task_service import FleetTaskService
from fleet.server.task_store import FleetTaskStore
from fleet.swarm.robots import RobotEndpoint

@pytest.fixture(autouse=True)
def _no_wait(monkeypatch):
    monkeypatch.setattr(dispatch_auto_rearm, "AUTO_REARM_READY_INTERVAL_S", 0)


USERS = {sha256(b"operator-console").hexdigest(): {"principal_id": "operator", "role": "operator"}}


def _boot(path, incidents=None):
    store = FleetTaskStore(path)
    service = FleetTaskService(store, robot_ids={"rosy_01"})
    app = create_app(FleetConsole([RobotEndpoint("rosy_01", "http://robot.local", "t")], [FakeRobot("rosy_01")]),
                     site_users=USERS, task_service=service, start_task_dispatcher=False)
    if incidents is not None:
        app.state.arm_incidents = incidents
    return store, app


def _auto(app):
    return asyncio.run(app.state.auto_rearm_after_restart())


def test_clean_restart_rearms_once_with_audit(tmp_path):
    store, app = _boot(tmp_path / "f.sqlite3")
    assert store.dispatch_control()["reason"] == "PROCESS_RESTARTED"
    control = _auto(app)
    assert control["dispatch_enabled"] is True and control["reason"] == "AUTO_REARM_AFTER_RESTART"
    rows = [r for r in store.api_audit() if r["path"] == "/api/fleet/dispatch/rearm"]
    assert {r["principal_id"] for r in rows} == {"system:auto-rearm-after-restart"}
    assert sorted(r["event_type"] for r in rows) == ["INTENT", "RESULT"]
    assert _auto(app) is None  # once per start
    _, again = _boot(tmp_path / "f.sqlite3")  # the next restart closes and reopens again
    assert _auto(again)["dispatch_enabled"] is True


def test_unresolved_action_blocks_auto_rearm(tmp_path):
    path = tmp_path / "f.sqlite3"
    FleetTaskService(FleetTaskStore(path), robot_ids={"rosy_01"})
    store, app = _boot(path)
    assert store.restore_unresolved_action_claim(
        owner_kind="mission", owner_id="m1", generation=0, resources=[("robot", "rosy_01")], phase="UNKNOWN")
    assert _auto(app) is None
    assert store.dispatch_control()["dispatch_enabled"] is False


def test_open_arm_incident_blocks_auto_rearm(tmp_path):
    store, app = _boot(tmp_path / "f.sqlite3", incidents=SimpleNamespace(any_hold=lambda: True))
    assert _auto(app) is None
    assert store.dispatch_control()["dispatch_enabled"] is False
    assert not [r for r in store.api_audit() if r["path"] == "/api/fleet/dispatch/rearm"]


def test_operator_stop_survives_restart(tmp_path):
    path = tmp_path / "f.sqlite3"
    first = FleetTaskStore(path)
    FleetTaskService(first, robot_ids={"rosy_01"})
    first.trip_stop_latch(actor_id="operator", reason="SITE_STOP")
    store, app = _boot(path)
    assert store.dispatch_control()["reason"] == "SITE_STOP"
    assert _auto(app) is None
    assert store.dispatch_control()["dispatch_enabled"] is False


class _Transport:
    def __init__(self, status=200):
        self.status, self.rearms = status, 0

    def owner_state(self, **_k):
        return {"status": self.status}

    def rearm(self, **_k):
        self.rearms += 1
        return {"state": "OPEN"}

    def stop(self, **_k):
        return {"state": "LOCAL_LATCHED"}


def _omx(path, transport, incidents="missing"):
    """Routes installed directly with one configured OMX owner."""
    store = FleetTaskStore(path)
    service = FleetTaskService(store, robot_ids={"rosy_01"})
    app, who = FastAPI(), SitePrincipal(principal_id="op1", role="operator")
    console = SimpleNamespace(estop_all=lambda: asyncio.sleep(0, result={"robots": []}),
                              discard_task_queue_entries=lambda _s: None)
    install_task_dispatch_routes(
        app, console=console, task_service=service, configured_omx={"cell_s": "omx1"},
        stop_transport=transport, stop_targets=(("cell_s", "omx1"),),
        require_viewer=lambda: who, require_operator=lambda: who, require_named_operator=lambda: who,
        read_guard=(), operator_guard=(), authorize=lambda: who)
    install_auto_rearm(app, store=store, configured_omx={"cell_s": "omx1"}, stop_targets=(("cell_s", "omx1"),),
                       stop_transport=transport)
    if incidents != "missing":
        app.state.arm_incidents = incidents
    return store, app


def test_missing_incident_store_with_omx_stays_closed(tmp_path):
    transport = _Transport()
    store, app = _omx(tmp_path / "f.sqlite3", transport)
    assert _auto(app) is None and transport.rearms == 0
    assert store.dispatch_control()["dispatch_enabled"] is False


def test_incident_check_error_stays_closed(tmp_path):
    def boom():
        raise RuntimeError("db locked")
    transport = _Transport()
    store, app = _omx(tmp_path / "f.sqlite3", transport, SimpleNamespace(any_hold=boom))
    assert _auto(app) is None and transport.rearms == 0
    assert store.dispatch_control()["dispatch_enabled"] is False


def test_real_incident_store_with_held_incident_stays_closed(tmp_path):
    incidents = ArmIncidentStore()
    incidents.report(ArmIncidentReport.model_validate(incident_report()))
    assert incidents.any_hold()
    transport = _Transport()
    store, app = _omx(tmp_path / "f.sqlite3", transport, incidents)
    assert _auto(app) is None and transport.rearms == 0
    assert store.dispatch_control()["dispatch_enabled"] is False
    clean_store, clean_app = _omx(tmp_path / "g.sqlite3", _Transport(), ArmIncidentStore())
    assert _auto(clean_app)["dispatch_enabled"] is True  # same wiring, no incident: reopens and fences rearm


def test_stop_delivery_uncertainty_stays_closed(tmp_path, monkeypatch):
    # patch the globals the live store methods actually use (the module is also loaded under an alias path)
    monkeypatch.setitem(FleetTaskStore.dispatch_control.__globals__, "has_local_uncertainty", lambda *_a, **_k: True)
    transport = _Transport()
    store, app = _omx(tmp_path / "f.sqlite3", transport, ArmIncidentStore())
    assert _auto(app) is None and transport.rearms == 0
    assert store.dispatch_control()["dispatch_enabled"] is False


def test_stop_between_check_and_rearm_blocks_rearm(tmp_path, monkeypatch):
    transport = _Transport()
    store, app = _omx(tmp_path / "f.sqlite3", transport, ArmIncidentStore())
    real = dispatch_auto_rearm.auto_rearm_pending

    def stop_after_check(s):
        control = real(s)
        s.trip_stop_latch(actor_id="estop-op", reason="SITE_STOP")
        return control
    monkeypatch.setattr(dispatch_auto_rearm, "auto_rearm_pending", stop_after_check)
    assert _auto(app) is None and transport.rearms == 0
    control = store.dispatch_control()
    assert control["dispatch_enabled"] is False and control["reason"] == "SITE_STOP"


def test_owners_never_ready_stays_closed_without_rollback(tmp_path):
    transport = _Transport(status=503)
    store, app = _omx(tmp_path / "f.sqlite3", transport, ArmIncidentStore())
    assert _auto(app) is None and transport.rearms == 0
    control = store.dispatch_control()
    assert control["dispatch_enabled"] is False and control["reason"] == "PROCESS_RESTARTED"
    assert not [r for r in store.api_audit() if r["path"] == "/api/fleet/dispatch/rearm"]


def test_manual_close_keeps_prior_actor_across_restart(tmp_path):
    path = tmp_path / "f.sqlite3"
    first = FleetTaskStore(path)
    FleetTaskService(first, robot_ids={"rosy_01"})
    first.trip_stop_latch(actor_id="operator-7", reason="SITE_STOP")
    second = FleetTaskStore(path)
    FleetTaskService(second, robot_ids={"rosy_01"})
    with closing(second._connect()) as c:
        row = c.execute("SELECT reason, actor_id FROM fleet_dispatch_control").fetchone()
    assert (row["reason"], row["actor_id"]) == ("SITE_STOP", "operator-7")


def test_incident_arriving_during_readiness_wait_stays_closed(tmp_path):
    calls = []

    def any_hold():
        calls.append(1)
        return len(calls) > 1  # clear at the first check, held at the re-check
    transport = _Transport()
    store, app = _omx(tmp_path / "f.sqlite3", transport, SimpleNamespace(any_hold=any_hold))
    assert _auto(app) is None and len(calls) == 2 and transport.rearms == 0
    assert store.dispatch_control()["dispatch_enabled"] is False
    assert not [r for r in store.api_audit() if r["path"] == "/api/fleet/dispatch/rearm"]
