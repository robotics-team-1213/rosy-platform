"""Neutral proposals and two-person admission share Fleet's existing claim transaction."""
from concurrent.futures import ThreadPoolExecutor
from contextlib import closing
from importlib import import_module
import sqlite3

import pytest

from core_common.protocol.arm_transfer import ArmTransferCapability
from fleet.server.cell_job_store import CellJobStore
from fleet.server.mission_store import MissionConflict
from fleet.server.site_auth import SitePrincipal
from test_cell_job_store import _stores
from test_job_provenance_migration import connect, legacy_database, snapshot
from test_physical_transfer_evidence import geometry, policy

NOW = 2_000_000_000
PROPOSER = SitePrincipal("harbor", "service")
OPERATOR = SitePrincipal("operator-2", "operator")


def api():
    try:
        return import_module("fleet.server.physical_transfer_store")
    except ModuleNotFoundError:
        pytest.fail("neutral physical transfer store is missing")


@pytest.fixture
def installation(policy):
    capabilities = tuple(ArmTransferCapability(action_kind="ARM_TRANSFER", control_mode="fleet_managed",
        workcell_id=p.workcell_id, instance_id=p.instance_id, journal_id="journal-" + p.instance_id,
        owner_session_id="session-1", catalog_digest=policy.catalog_digest, bindings_digest=policy.bindings_digest,
        resource_policy_digest=policy.digest, capability_revision="cap-1", config_revision="config-1") for p in policy.participants)
    return api().TransferInstallation(policy=policy, source="source", target="target", capabilities=capabilities)


@pytest.fixture
def rig(tmp_path, installation):
    path, tasks, _, control = _stores(tmp_path)
    store = api().PhysicalTransferStore(path, installation=installation, deployment_profile="simulation", clock_ns=lambda: NOW)
    return path, tasks, control, store


def request(installation, **changes):
    return api().PhysicalTransferRequest(**{**dict(workcell_id=installation.policy.primary[0],
        instance_id=installation.policy.primary[1], object_ref=installation.policy.object_ref,
        source=installation.source, target=installation.target), **changes})


def create(store, *, principal=PROPOSER, key="move-1", **changes):
    return store.create(principal=principal, request_key=key, request=request(store.installation, **changes))


def admit(store, proposal, control, *, principal=OPERATOR, **changes):
    arguments = dict(principal=principal, expected_proposal_digest=proposal["proposal_digest"],
        expected_generation=control["generation"], capabilities=store.installation.capabilities,
        capabilities_observed_at_ns=NOW - 1)
    return store.admit(proposal["mission_id"], **{**arguments, **changes})


def claims(path):
    with closing(connect(path)) as connection:
        return [dict(row) for row in connection.execute("SELECT * FROM fleet_action_claims ORDER BY resource_key")]


def test_create_is_principal_scoped_idempotent_and_has_no_legacy_process_fields(rig):
    path, _, _, store = rig
    with ThreadPoolExecutor(max_workers=4) as pool:
        jobs = list(pool.map(lambda _: create(store), range(8)))
    assert len({job["mission_id"] for job in jobs}) == 1
    proposed = jobs[0]
    assert proposed["status"] == "PROPOSED" and not claims(path)
    assert set(map(tuple, proposed["resources"])) == set(store.installation.policy.resources)
    assert store.get_by_request_key("move-1", principal=PROPOSER) == proposed
    assert create(store, principal=SitePrincipal("other-app", "service"))["mission_id"] != proposed["mission_id"]
    with pytest.raises(MissionConflict):
        create(store, target="different")
    assert store.get(proposed["mission_id"], principal=PROPOSER) == proposed
    with closing(connect(path)) as connection:
        row = connection.execute("SELECT * FROM fleet_cell_jobs WHERE mission_id=?", (proposed["mission_id"],)).fetchone()
        assert row["provenance_kind"] == "physical"
        assert all(row[name] is None for name in ("job_id", "recipe_digest", "cell_digest", "process_artifact_digest"))
    assert not {"job_id", "recipe_digest", "cell_digest", "process_artifact_digest"} & set(proposed)
    assert CellJobStore(path).get(proposed["mission_id"]) is None


def test_creator_and_named_operator_read_permissions_are_distinct(rig):
    _, _, _, store = rig
    proposal = create(store)
    assert store.get(proposal["mission_id"], principal=OPERATOR) == proposal
    for principal in (SitePrincipal("viewer", "viewer"), SitePrincipal("other-service", "service"),
                      SitePrincipal("site-console", "operator"), SitePrincipal("operator-3", "operator", True)):
        with pytest.raises(PermissionError):
            store.get(proposal["mission_id"], principal=principal)
    assert store.get_by_request_key("move-1", principal=SitePrincipal("other-service", "service")) is None
    with pytest.raises(PermissionError):
        create(store, principal=SitePrincipal("viewer", "viewer"), key="viewer-create")


def test_two_person_admission_records_exact_approval_and_claims_atomically(rig):
    path, _, control, store = rig
    proposal = create(store)
    ready = admit(store, proposal, control)
    assert ready["status"] == "READY"
    assert ready["approved_by"] == OPERATOR.principal_id
    assert ready["claims_acquired_at_ns"] == NOW
    assert ready["dispatch_generation"] == control["generation"]
    assert ready["authority_epoch"] == control["authority_epoch"]
    occupied = claims(path)
    assert len(occupied) == len(store.installation.policy.resources)
    assert {(row["owner_id"], row["phase"]) for row in occupied} == {(ready["mission_id"], "CLAIMED")}
    assert admit(store, proposal, control) == ready
    assert claims(path) == occupied
    with closing(connect(path)) as connection:
        assert connection.execute("SELECT COUNT(*) FROM fleet_physical_transfer_approvals").fetchone()[0] == 1


@pytest.mark.parametrize("principal", [SitePrincipal("harbor", "operator"), SitePrincipal("service", "service"),
    SitePrincipal("viewer", "viewer"), SitePrincipal("site-console", "operator"),
    SitePrincipal("password-change", "operator", True)])
def test_self_service_unnamed_and_blocked_operators_cannot_approve(rig, principal):
    path, _, control, store = rig
    proposal = create(store)
    with pytest.raises(PermissionError):
        admit(store, proposal, control, principal=principal)
    assert not claims(path)
    assert store.get(proposal["mission_id"], principal=PROPOSER)["status"] == "PROPOSED"


@pytest.mark.parametrize("change", ["digest", "generation", "missing_owner", "session", "config", "stale", "future"])
def test_admission_rechecks_proposal_control_and_all_current_capabilities(rig, change):
    path, _, control, store = rig
    proposal = create(store)
    changes = {}
    if change == "digest":
        changes["expected_proposal_digest"] = "f" * 64
    elif change == "generation":
        changes["expected_generation"] = control["generation"] + 1
    elif change == "missing_owner":
        changes["capabilities"] = store.installation.capabilities[:1]
    elif change in {"session", "config"}:
        caps = store.installation.capabilities
        field = "owner_session_id" if change == "session" else "config_revision"
        changes["capabilities"] = (caps[0], caps[1].model_copy(update={field: "changed"}))
    else:
        changes["capabilities_observed_at_ns"] = NOW + 1 if change == "future" else NOW - store.installation.policy.max_age_ns - 1
    with pytest.raises(MissionConflict):
        admit(store, proposal, control, **changes)
    assert not claims(path)
    with closing(connect(path)) as connection:
        assert not connection.execute("SELECT * FROM fleet_physical_transfer_approvals").fetchall()


def test_stale_installation_keeps_original_idempotent_proposal_but_cannot_admit(rig):
    path, _, control, store = rig
    proposal = create(store)
    changed = store.installation.model_copy(update={"source": "different-source"})
    replacement = api().PhysicalTransferStore(path, installation=changed, deployment_profile="simulation", clock_ns=lambda: NOW)
    original = replacement.create(principal=PROPOSER, request_key="move-1", request=request(store.installation))
    assert original == proposal
    with pytest.raises(MissionConflict):
        admit(replacement, proposal, control)
    assert not claims(path)


def test_conflicting_jobs_cannot_both_be_admitted(rig):
    path, _, control, store = rig
    first, second = create(store), create(store, key="move-2")
    with ThreadPoolExecutor(max_workers=2) as pool:
        def attempt(proposal):
            try:
                return admit(store, proposal, control)["mission_id"]
            except MissionConflict:
                return None
        results = list(pool.map(attempt, (first, second)))
    assert len([item for item in results if item]) == 1
    assert len(claims(path)) == len(store.installation.policy.resources)


def test_a_legacy_owner_workcell_claim_blocks_neutral_admission(rig):
    path, tasks, control, store = rig
    proposal = create(store)
    assert tasks.reserve_resources(owner_kind="mission", owner_id="legacy-owner", generation=control["generation"],
                                   resources=[("workcell", store.installation.policy.primary[0])])
    with pytest.raises(MissionConflict):
        admit(store, proposal, control)
    assert {row["owner_id"] for row in claims(path)} == {"legacy-owner"}


def test_failure_after_claim_reservation_rolls_back_approval_status_and_every_claim(rig):
    path, _, control, store = rig
    proposal = create(store)
    with closing(connect(path)) as connection:
        connection.execute("CREATE TRIGGER fail_physical_approval BEFORE INSERT ON fleet_physical_transfer_approvals "
                           "BEGIN SELECT RAISE(ABORT,'injected approval failure'); END")
        connection.commit()
    with pytest.raises(sqlite3.IntegrityError, match="injected"):
        admit(store, proposal, control)
    assert not claims(path)
    assert store.get(proposal["mission_id"], principal=PROPOSER) == proposal


def test_site_stop_and_restart_preserve_admitted_occupancy_and_close_legacy_resume(rig):
    path, tasks, control, store = rig
    proposal = create(store)
    admit(store, proposal, control)
    tasks.trip_stop_latch(actor_id="stop-operator")
    held = store.get(proposal["mission_id"], principal=PROPOSER)
    assert held["status"] == "HOLD"
    assert {row["phase"] for row in claims(path)} == {"HELD"}
    assert len(claims(path)) == len(store.installation.policy.resources)
    with pytest.raises((KeyError, MissionConflict)):
        CellJobStore(path).resume(proposal["mission_id"], actor_id="operator", expected_generation=control["generation"])
    with pytest.raises(MissionConflict):
        admit(store, proposal, control)
    from fleet.server.task_store import FleetTaskStore
    FleetTaskStore(path)
    assert store.get(proposal["mission_id"], principal=PROPOSER)["status"] == "HOLD"
    assert len(claims(path)) == len(store.installation.policy.resources)


def test_migration_adds_physical_tables_preserves_legacy_and_old_host_refuses_new_version(tmp_path, installation, monkeypatch):
    path = legacy_database(tmp_path)
    before = snapshot(path)
    api().PhysicalTransferStore(path, installation=installation, deployment_profile="simulation")
    assert snapshot(path) == {**before, "fleet_physical_transfer_approvals": [], "fleet_physical_transfer_attempts": [],
                              "fleet_physical_transfer_observations": []}
    with closing(connect(path)) as connection:
        assert not connection.execute("PRAGMA foreign_key_check").fetchall()
        assert connection.execute("SELECT MAX(version) FROM fleet_component_migrations WHERE component='cell_jobs'").fetchone()[0] == 8
    module = import_module("fleet.server.cell_job_store")
    monkeypatch.setattr(module, "_MIGRATION_VERSION", 5)
    with pytest.raises(RuntimeError, match="unsupported.*8"):
        CellJobStore(path)


def test_physical_schema_failure_rolls_back_tables_indexes_and_legacy_migration(tmp_path, installation, monkeypatch):
    path = legacy_database(tmp_path)
    before = snapshot(path)
    api()
    schema = import_module("fleet.server.physical_transfer_schema")
    original = schema.ensure
    def fail(connection):
        original(connection)
        raise RuntimeError("injected schema failure")
    monkeypatch.setattr(schema, "ensure", fail)
    with pytest.raises(RuntimeError, match="injected"):
        CellJobStore(path)
    assert snapshot(path) == before
    with closing(connect(path)) as connection:
        assert connection.execute("PRAGMA foreign_keys").fetchone()[0] == 1
        assert connection.execute("SELECT MAX(version) FROM fleet_component_migrations WHERE component='cell_jobs'").fetchone()[0] == 4


def test_old_job_schema_allows_task_startup_before_the_atomic_job_upgrade(tmp_path):
    path = legacy_database(tmp_path)
    from fleet.server.task_store import FleetTaskStore
    FleetTaskStore(path).close_dispatch_for_startup()
    with closing(connect(path)) as connection:
        assert connection.execute("SELECT COUNT(*) FROM fleet_cell_jobs").fetchone()[0] == 3
        assert {row[0] for row in connection.execute("SELECT phase FROM fleet_action_claims")} == {"UNKNOWN", "HELD"}


@pytest.mark.parametrize("change", ["session", "stale"])
def test_ready_retry_requires_current_capability_facts_without_replacing_original_approval(rig, change):
    path, _, control, store = rig
    proposal = create(store)
    ready = admit(store, proposal, control)
    before = claims(path)
    changes = {"capabilities_observed_at_ns": NOW - store.installation.policy.max_age_ns - 1}
    if change == "session":
        caps = store.installation.capabilities
        changes = {"capabilities": (caps[0], caps[1].model_copy(update={"owner_session_id": "changed"}))}
    with pytest.raises(MissionConflict):
        admit(store, proposal, control, **changes)
    assert store.get(proposal["mission_id"], principal=PROPOSER) == ready
    assert claims(path) == before


def test_constructor_rejects_unrelated_sqlite_without_creating_or_migrating_tables(tmp_path, installation):
    path = tmp_path / "unrelated.sqlite3"
    with sqlite3.connect(path) as connection:
        connection.execute("CREATE TABLE unrelated(value TEXT)")
        connection.execute("INSERT INTO unrelated VALUES('preserve')")
    before = path.read_bytes()
    with pytest.raises(ValueError, match="Fleet journal"):
        api().PhysicalTransferStore(path, installation=installation, deployment_profile="simulation")
    assert path.read_bytes() == before


def test_projection_rejects_unrecognized_snapshot_keys_instead_of_overwriting_authority(rig):
    import json
    path, _, _, store = rig
    proposal = create(store)
    with closing(connect(path)) as connection:
        value = json.loads(connection.execute("SELECT job_json FROM fleet_cell_jobs WHERE mission_id=?", (proposal["mission_id"],)).fetchone()[0])
        value.update(status="READY", approved_by="fabricated", proposal_principal_id="other-service")
        connection.execute("UPDATE fleet_cell_jobs SET job_json=? WHERE mission_id=?", (json.dumps(value), proposal["mission_id"]))
        connection.commit()
    with pytest.raises(ValueError, match="snapshot"):
        store.get(proposal["mission_id"], principal=SitePrincipal("other-service", "service"))


def test_backwards_server_time_during_reservation_rolls_back_all_approval_effects(rig):
    path, _, control, store = rig
    proposal = create(store)
    times = iter((NOW, NOW - 10))
    store._clock_ns = lambda: next(times)
    with pytest.raises(MissionConflict, match="clock"):
        admit(store, proposal, control, capabilities_observed_at_ns=NOW - 100)
    assert not claims(path)
    assert store.get(proposal["mission_id"], principal=PROPOSER) == proposal


def test_restart_with_an_inflight_physical_action_retains_unknown_claims(rig):
    path, tasks, control, store = rig
    proposal = create(store)
    admit(store, proposal, control)
    with closing(connect(path)) as connection:
        connection.execute("UPDATE fleet_cell_jobs SET status='RUNNING' WHERE mission_id=?", (proposal["mission_id"],))
        connection.execute("UPDATE fleet_action_claims SET phase='DISPATCHING' WHERE owner_id=?", (proposal["mission_id"],))
        connection.commit()
    tasks.close_dispatch_for_startup()
    assert store.get(proposal["mission_id"], principal=PROPOSER)["status"] == "HOLD"
    assert {row["phase"] for row in claims(path)} == {"UNKNOWN"}
    assert not tasks.dispatch_control()["rearm_available"]
