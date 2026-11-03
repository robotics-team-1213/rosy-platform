"""Delegated ARM approval checks real parent evidence before the shared physical transaction."""
import asyncio
import sqlite3
import threading
import time
from types import SimpleNamespace

import pytest

from core_common.protocol.control_units import ControlArmIngressRequest, ControlArmWorkRequest
from fleet.server.console import FleetConsole
from fleet.server.control_unit_config import ControlUnitTopology
from fleet.server.control_unit_service import ControlUnitService
from fleet.server.control_unit_store import ControlUnitStore
from fleet.server.task_service import FleetTaskService
from fleet.server.task_store import FleetTaskStore
from fleet.server.site_auth import SitePrincipal
from fleet.server.mission_store import MissionConflict
import fleet.server.physical_transfer_store as physical_module
import fleet.server.arm_transfer_policy_admission as policy_module
import test_arm_transfer_job_api as api
from test_arm_transfer_job_api import rig as http_rig  # noqa: F401
from test_arm_transfer_policy_admission import arm_core, FakeDispatcher
from test_physical_transfer_evidence import geometry, policy  # noqa: F401
from test_physical_transfer_store import installation  # noqa: F401
from fleet.server.missions.policy_admission_audit import PolicyAdmissionAuditLog


@pytest.fixture
def world(request, monkeypatch, tmp_path, installation):
    core = arm_core(robots=frozenset(p.instance_id for p in installation.policy.participants),
                    proposers=frozenset({"control-unit:R"}))
    core.audit_log = PolicyAdmissionAuditLog(str(tmp_path / "policy-audit.sqlite3"))
    create_app, worker_type = api.create_app, policy_module.ArmTransferPolicyWorker
    workers, services, dispatcher = [], [], FakeDispatcher()

    def app_factory(*args, **kwargs):
        services.append(kwargs["task_service"])
        return create_app(*args, **{**kwargs, "policy_admission_core": core})

    def worker_factory(**kwargs):
        worker = worker_type(**kwargs)
        worker._dispatcher = dispatcher
        workers.append(worker)
        return worker

    monkeypatch.setattr(api, "create_app", app_factory)
    monkeypatch.setattr(policy_module, "ArmTransferPolicyWorker", worker_factory)
    rig = request.getfixturevalue("http_rig")
    assert len(workers) == 1
    return SimpleNamespace(rig=rig, core=core, worker=workers[0], dispatcher=dispatcher,
                           task_service=services[0])


def delegated(world, tmp_path, *, fault="healthy"):
    client, tasks, _, installed = world.rig
    rows = client.app.state.arm_transfer_job_store
    ancestor = fault == "ancestor_canceled"
    units = ([{"id": "ROOT"}, {"id": "R", "parent": "ROOT"}] if ancestor else [{"id": "R"}])
    units.append({"id": "CELL-A", "parent": "R", "resources": ["workcell:" + installed.policy.primary[0]]})
    topology = ControlUnitTopology.from_mapping({"revision": "v1", "units": units})
    nodes, reads, faults = {}, [], {"disconnected": False, "blocked": False, "canceled": threading.Event()}
    for unit in units:
        unit_id = unit["id"]
        journal = tasks if unit_id == "CELL-A" else FleetTaskStore(tmp_path / (unit_id + ".sqlite3"))

        async def peer(target, method, path, body=None, caller=unit_id):
            if method == "GET":
                reads.append((caller, target, path))
                with sqlite3.connect(tasks.path, timeout=.05) as connection:
                    connection.execute("BEGIN IMMEDIATE")
                    connection.rollback()
                if caller == "CELL-A" and faults["disconnected"]:
                    raise ConnectionError("parent unavailable")
                if caller == "CELL-A" and faults["blocked"]:
                    try:
                        await asyncio.Event().wait()
                    finally:
                        faults["canceled"].set()
                origin, identity = path.split("/")
                return await nodes[target].read(origin, identity, for_child=caller)
            if path == "inbox":
                principal = SitePrincipal("control-unit:" + caller, "service")
                return await nodes[target].receive(ControlArmIngressRequest.model_validate(body),
                                                   parent_id=caller, principal=principal)
            origin, identity = path.split("/")
            return await nodes[target].cancel(origin, identity)

        nodes[unit_id] = ControlUnitService(
            topology, ControlUnitStore(journal.path, unit_id=unit_id),
            world.task_service if unit_id == "CELL-A" else FleetTaskService(journal, robot_ids=()),
            FleetConsole([], []), peer=peer,
            arm_jobs=lambda unit_id=unit_id: client.app.state.arm_transfer_delegate if unit_id == "CELL-A" else None)
    client.app.state.control_unit = nodes["CELL-A"]
    origin = "ROOT" if ancestor else "R"
    request = ControlArmWorkRequest.model_validate({
        "delegation_id": "arm-1", "target_unit": "CELL-A", "transfer": api.body(installed)})
    asyncio.run(nodes[origin].submit(request))
    if fault in {"canceled", "ancestor_canceled"}:
        nodes[origin].store.request_cancel(origin, "arm-1")
    faults["disconnected"] = fault == "disconnected"
    faults["blocked"] = fault == "blocked"
    reads.clear()
    binding = nodes["CELL-A"].store.get(origin, "arm-1")
    proposal = rows.peek(binding["local_task_id"]) if binding["local_task_id"] else None
    return SimpleNamespace(nodes=nodes, origin=origin, request=request, proposal=proposal, reads=reads,
                           parent_canceled=faults["canceled"])


def assert_unadmitted(world, mission_id):
    client, tasks, _, _ = world.rig
    proposal = client.app.state.arm_transfer_job_store.peek(mission_id)
    assert proposal["status"] == "PROPOSED"
    assert proposal["approved_by"] is None
    assert api.claims(world.rig) == []
    with sqlite3.connect(tasks.path) as connection:
        assert connection.execute("SELECT COUNT(*) FROM fleet_physical_transfer_approvals").fetchone()[0] == 0
    assert client.app.state.cell_job_store.get(mission_id) is None


@pytest.mark.parametrize("fault", ["healthy", "disconnected", "canceled", "ancestor_canceled"])
def test_named_arm_admission_requires_current_parent_chain(world, tmp_path, fault):
    context = delegated(world, tmp_path, fault=fault)
    client, tasks, _, _ = world.rig
    proposal = context.proposal
    assert proposal is not None
    assert not context.nodes["CELL-A"].store.get(context.origin, "arm-1")["cancel_requested"]
    response = client.post(api.PATH + "/" + proposal["mission_id"] + "/admit",
        headers=api.headers("operator"), json={"expected_proposal_digest": proposal["proposal_digest"],
            "expected_generation": tasks.dispatch_control()["generation"]})
    if fault == "healthy":
        assert response.status_code == 200, response.text
        assert response.json()["job"]["status"] == "READY"
    else:
        assert response.status_code != 200
        assert_unadmitted(world, proposal["mission_id"])
    assert context.reads


@pytest.mark.parametrize("fault", ["healthy", "disconnected", "canceled", "ancestor_canceled", "blocked"])
def test_policy_arm_admission_requires_current_parent_chain(world, tmp_path, fault):
    context = delegated(world, tmp_path, fault=fault)
    proposal = context.proposal
    assert proposal is not None
    world.core.toggle(enabled=True, actor="operator-2")
    done, original = threading.Event(), world.worker.tick

    def tick(*args, **kwargs):
        try:
            return original(*args, **kwargs)
        finally:
            done.set()

    world.worker.tick = tick
    client = world.rig[0]
    start = next(f for f in client.app.router.on_startup if f.__name__ == "arm_transfer_policy_start")
    stop = next(f for f in client.app.router.on_shutdown if f.__name__ == "arm_transfer_policy_stop")
    # The custom app lifespan does not start this legacy hook; exercise its installed component explicitly.
    with client:
        client.portal.call(start)
        try:
            assert done.wait(10), "the real policy loop did not finish its first tick"
            if fault == "healthy":
                assert client.app.state.arm_transfer_job_store.peek(proposal["mission_id"])["status"] == "READY"
                assert world.dispatcher.prepared == [proposal["mission_id"]]
            else:
                assert_unadmitted(world, proposal["mission_id"])
                assert world.dispatcher.prepared == []
            assert context.reads
            if fault == "blocked":
                assert context.parent_canceled.wait(2), "timed-out parent coroutine was not canceled"
        finally:
            client.portal.call(stop)


def test_policy_never_sees_an_unbound_delegated_proposal(world, tmp_path, monkeypatch):
    rows = world.rig[0].app.state.arm_transfer_job_store
    original = rows.create
    world.core.toggle(enabled=True, actor="operator-2")
    observed = []

    def create(**kwargs):
        proposal = original(**kwargs)
        observed.append(proposal["mission_id"])
        world.worker.tick()
        assert_unadmitted(world, proposal["mission_id"])
        assert world.dispatcher.prepared == []
        return proposal

    monkeypatch.setattr(rows, "create", create)
    context = delegated(world, tmp_path)
    assert observed == [context.proposal["mission_id"]]
    assert context.nodes["CELL-A"].store.owns_task(context.proposal["mission_id"])


def test_failed_delegation_binding_rolls_back_the_physical_proposal(world, tmp_path, monkeypatch):
    original = ControlUnitStore.bind_local

    def refused(self, *args, **kwargs):
        raise ValueError("binding refused")

    monkeypatch.setattr(ControlUnitStore, "bind_local", refused)
    context = delegated(world, tmp_path)
    rows = world.rig[0].app.state.arm_transfer_job_store
    assert rows.proposed_ids() == []
    assert context.proposal is None
    monkeypatch.setattr(ControlUnitStore, "bind_local", original)
    asyncio.run(context.nodes[context.origin].submit(context.request))
    binding = context.nodes["CELL-A"].store.get(context.origin, "arm-1")
    assert rows.proposed_ids() == [(binding["local_task_id"], "control-unit:R")]


def direct_admit(world, proposal, checked_at):
    _, tasks, port, _ = world.rig
    rows = world.rig[0].app.state.arm_transfer_job_store
    return rows.admit(proposal["mission_id"], principal=SitePrincipal("operator", "operator"),
        expected_proposal_digest=proposal["proposal_digest"],
        expected_generation=tasks.dispatch_control()["generation"],
        capabilities=tuple(port.capabilities), capabilities_observed_at_ns=time.time_ns(),
        delegation_checked_at=checked_at)


@pytest.mark.parametrize("kind", ["missing", "boolean", "nan", "infinite", "future", "expired"])
def test_bound_arm_admission_refuses_invalid_parent_proof(world, tmp_path, kind):
    context = delegated(world, tmp_path)
    value = {"missing": None, "boolean": True, "nan": float("nan"), "infinite": float("inf"),
             "future": time.monotonic() + 30, "expired": time.monotonic() - 30}[kind]
    with pytest.raises(MissionConflict, match="current parent evidence"):
        direct_admit(world, context.proposal, value)
    assert_unadmitted(world, context.proposal["mission_id"])


def test_parent_proof_expiring_during_reservation_rolls_back_claims(world, tmp_path, monkeypatch):
    context = delegated(world, tmp_path)
    checked_at = time.monotonic()
    readings = iter((checked_at, checked_at + 6.0))
    monkeypatch.setattr(physical_module, "time", SimpleNamespace(
        time_ns=time.time_ns, monotonic=lambda: next(readings)))
    with pytest.raises(MissionConflict, match="current parent evidence"):
        direct_admit(world, context.proposal, checked_at)
    assert_unadmitted(world, context.proposal["mission_id"])


def test_legacy_unbound_parent_proposal_cannot_be_admitted(world):
    client, tasks, _, installed = world.rig
    request = api.body(installed)
    key = request.pop("request_key")
    rows = client.app.state.arm_transfer_job_store
    proposal = rows.create(principal=SitePrincipal("control-unit:R", "service"),
                           request_key=key, request=request)
    response = client.post(api.PATH + "/" + proposal["mission_id"] + "/admit",
        headers=api.headers("operator"), json={"expected_proposal_digest": proposal["proposal_digest"],
            "expected_generation": tasks.dispatch_control()["generation"]})
    assert response.status_code == 409
    assert_unadmitted(world, proposal["mission_id"])


def test_legacy_ambiguous_parent_bindings_cannot_be_admitted(world, tmp_path):
    context = delegated(world, tmp_path)
    child = context.nodes["CELL-A"].store
    child.create(context.origin, "arm-2", context.request.model_dump(mode="json", include={"target_unit", "transfer"}),
                 owner_unit="CELL-A", config_revision="v1")
    child.bind_local(context.origin, "arm-2", context.proposal["mission_id"])
    client, tasks, _, _ = world.rig
    response = client.post(api.PATH + "/" + context.proposal["mission_id"] + "/admit",
        headers=api.headers("operator"), json={"expected_proposal_digest": context.proposal["proposal_digest"],
            "expected_generation": tasks.dispatch_control()["generation"]})
    assert response.status_code == 503
    assert_unadmitted(world, context.proposal["mission_id"])
