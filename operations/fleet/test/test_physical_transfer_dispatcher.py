"""SDK execution is simulation-only, once per persisted intent; later requests only look up."""
from concurrent.futures import ThreadPoolExecutor
from contextlib import closing
from datetime import datetime, timezone
from importlib import import_module
import sqlite3
from types import SimpleNamespace
from threading import Event

import pytest

from fleet.server.local_action_transport import LocalActionUnavailable
from fleet.server.task_service import FleetTaskService
from fleet.server.task_store import FleetTaskStore
from test_physical_transfer_evidence import geometry, policy
from test_physical_transfer_store import NOW, PROPOSER, installation, rig, create, admit, claims
from test_physical_transfer_preparation import execution
from test_physical_transfer_submission import observations
from test_step_dispatcher import _receipt


def api():
    try:
        return import_module("fleet.server.physical_transfer_dispatcher")
    except ModuleNotFoundError:
        pytest.fail("installed physical SDK dispatcher is missing")


class Port:
    def __init__(self, store, clock):
        self.store, self.clock = store, clock
        self.capabilities = list(store.installation.capabilities)
        self.identities = {c.instance_id: dict(simulation=True, workcell_id=c.workcell_id,
            instance_id=c.instance_id, journal_id=c.journal_id) for c in self.capabilities}
        self.reads, self.submitted, self.lookups, self.cancels = [], [], [], []
        self.drop_submit = self.missing = False

    def probe(self):
        with closing(sqlite3.connect(self.store._journal.path, timeout=.05)) as connection:
            connection.execute("BEGIN IMMEDIATE")
            connection.rollback()

    def owner_identity(self, instance_id):
        self.probe()
        self.reads.append(("identity", instance_id))
        return self.identities[instance_id]

    def transfer_capability(self, instance_id, *, workcell_id):
        self.probe()
        self.reads.append(("capability", instance_id))
        return next(c for c in self.capabilities if (c.workcell_id, c.instance_id) == (workcell_id, instance_id))

    def result(self, grant, state, event_id):
        self.clock[0] += 10_000_000
        at = datetime.fromtimestamp((self.clock[0] - 1_000_000) / 1e9, timezone.utc)
        value = _receipt(grant, state, event_id, phases=None if state == "SUCCEEDED" else ("approach",))
        return value.model_copy(update={"journal_id": grant.owner_journal_id, "observed_at": at,
            "phase_summaries": tuple(p.model_copy(update={"observed_at": at}) for p in value.phase_summaries)})

    def submit(self, grant):
        self.probe()
        self.submitted.append(grant)
        if self.drop_submit:
            raise LocalActionUnavailable("reply lost")
        return self.result(grant, "ACCEPTED", 2)

    def get(self, grant):
        self.probe()
        self.lookups.append(grant)
        return None if self.missing else self.result(grant, "SUCCEEDED", 6)

    def cancel(self, grant, *, reason):
        self.probe()
        self.cancels.append((grant, reason))
        return self.result(grant, "CANCEL_REQUESTED", 3)


@pytest.fixture
def driver(rig):
    path, tasks, control, store = rig
    job = admit(store, create(store), control)
    clock = [NOW]
    store._clock_ns = lambda: clock[0]
    executor = execution(store)
    port = Port(store, clock)
    dispatcher = api().PhysicalTransferDispatcher(executor, port, tasks, deployment_profile="simulation")
    return SimpleNamespace(path=path, tasks=tasks, store=store, execution=executor,
        port=port, dispatcher=dispatcher, job=job, clock=clock)


def ready(driver):
    prepared = driver.dispatcher.prepare(driver.job["mission_id"])
    driver.clock[0] = NOW + 350_000_000
    return observations(driver.store, prepared)


def submit(driver, measured):
    return driver.dispatcher.submit(driver.job["mission_id"], observations=measured,
                                    authenticated_producer_id=driver.store.installation.policy.producer_id)


def test_prepare_send_and_lookup_use_every_current_simulation_owner_outside_sqlite(driver):
    measured = ready(driver)
    assert len(driver.port.reads) == 4
    sent = submit(driver, measured)
    assert sent["status"] == "SUBMITTING" and len(driver.port.reads) == 8
    assert len(driver.port.submitted) == 1 and {c["phase"] for c in claims(driver.path)} == {"DISPATCHING"}
    done = driver.dispatcher.refresh(driver.job["mission_id"])
    assert done["status"] == "ACTION_SUCCEEDED" and len(driver.port.reads) == 12
    assert driver.port.lookups[0] == driver.port.submitted[0]
    assert len(claims(driver.path)) == len(driver.store.installation.policy.resources)
    assert {c["phase"] for c in claims(driver.path)} == {"HELD"}


@pytest.mark.parametrize("simulation", [False, 1, "true"])
def test_a_non_simulation_secondary_owner_closes_preparation_without_minting_an_action(driver, simulation):
    driver.port.identities["arm-2"]["simulation"] = simulation
    with pytest.raises((ValueError, LocalActionUnavailable)):
        driver.dispatcher.prepare(driver.job["mission_id"])
    assert driver.store.get(driver.job["mission_id"], principal=PROPOSER)["status"] == "HOLD"
    assert {c["phase"] for c in claims(driver.path)} == {"HELD"}
    assert driver.port.submitted == []


def test_owner_identity_is_not_cached_between_preparation_and_send(driver):
    measured = ready(driver)
    driver.port.identities["arm-2"]["simulation"] = False
    result = submit(driver, measured)
    assert result["status"] == "HOLD" and driver.port.submitted == []
    assert {c["phase"] for c in claims(driver.path)} == {"HELD"}


def test_stop_between_intent_and_submit_prevents_sdk_submission(driver, monkeypatch):
    measured = ready(driver)
    original = driver.execution.authorize_submission
    def stop_after_intent(*args, **kwargs):
        result = original(*args, **kwargs)
        driver.tasks.trip_stop_latch(actor_id="operator")
        return result
    monkeypatch.setattr(driver.execution, "authorize_submission", stop_after_intent)
    assert submit(driver, measured)["status"] == "UNKNOWN"
    assert driver.port.submitted == [] and {c["phase"] for c in claims(driver.path)} == {"UNKNOWN"}


def test_duplicate_calls_never_submit_the_persisted_action_twice(driver):
    measured = ready(driver)
    with ThreadPoolExecutor(max_workers=2) as pool:
        result = list(pool.map(lambda _: submit(driver, measured), range(2)))
    assert all(r["status"] == "SUBMITTING" for r in result)
    assert len(driver.port.submitted) == 1


def test_lost_submit_reply_keeps_original_identity_and_never_replays_after_lookup(driver):
    measured = ready(driver)
    driver.port.drop_submit = True
    assert submit(driver, measured)["status"] == "UNKNOWN"
    assert driver.dispatcher.refresh(driver.job["mission_id"])["status"] == "UNKNOWN"
    assert submit(driver, measured)["status"] == "UNKNOWN"
    assert len(driver.port.submitted) == 1 and driver.port.lookups == driver.port.submitted
    assert {c["phase"] for c in claims(driver.path)} == {"UNKNOWN"}


def test_missing_lookup_retains_unknown_occupancy_without_resubmit(driver):
    submit(driver, ready(driver))
    driver.port.missing = True
    assert driver.dispatcher.refresh(driver.job["mission_id"])["status"] == "UNKNOWN"
    assert len(driver.port.submitted) == 1 and {c["phase"] for c in claims(driver.path)} == {"UNKNOWN"}


def test_changed_owner_session_is_never_queried_as_the_old_action(driver):
    submit(driver, ready(driver))
    driver.port.capabilities[1] = driver.port.capabilities[1].model_copy(update={"owner_session_id": "changed"})
    assert driver.dispatcher.refresh(driver.job["mission_id"])["status"] == "UNKNOWN"
    assert driver.port.lookups == [] and len(driver.port.submitted) == 1


def test_restart_looks_up_the_old_attempt_without_reactivating_it(driver):
    submit(driver, ready(driver))
    restarted = FleetTaskService(FleetTaskStore(driver.path), robot_ids=())
    another = api().PhysicalTransferDispatcher(execution(driver.store), driver.port, restarted.store,
                                               deployment_profile="simulation")
    assert another.refresh(driver.job["mission_id"])["status"] == "UNKNOWN"
    assert driver.port.lookups == driver.port.submitted and len(driver.port.submitted) == 1
    assert driver.store.get(driver.job["mission_id"], principal=PROPOSER)["status"] == "HOLD"


@pytest.mark.parametrize("sent", [False, True])
def test_cancel_preserves_occupancy_and_only_targets_an_already_submitted_grant(driver, sent):
    measured = ready(driver)
    if sent:
        submit(driver, measured)
    result = driver.dispatcher.cancel(driver.job["mission_id"], reason="operator cancel")
    assert result["status"] == ("UNKNOWN" if sent else "HOLD")
    assert len(driver.port.cancels) == int(sent)
    if sent:
        assert driver.port.cancels[0][0] == driver.port.submitted[0]
    assert len(claims(driver.path)) == len(driver.store.installation.policy.resources)


def test_dispatcher_cannot_be_opened_in_a_production_profile(driver):
    with pytest.raises(ValueError, match="simulation"):
        api().PhysicalTransferDispatcher(driver.execution, driver.port, driver.tasks, deployment_profile="production")


@pytest.mark.parametrize("after_control", [NOW + 340_000_000, NOW + 2_350_000_000])
def test_delayed_control_read_cannot_send_with_regressed_or_stale_facts(driver, monkeypatch, after_control):
    measured = ready(driver)
    original = driver.tasks.dispatch_control
    def delayed_control():
        driver.clock[0] = after_control
        return original()
    monkeypatch.setattr(driver.tasks, "dispatch_control", delayed_control)
    assert submit(driver, measured)["status"] == "UNKNOWN"
    assert driver.port.submitted == []
    assert {c["phase"] for c in claims(driver.path)} == {"UNKNOWN"}


def test_a_second_dispatcher_hold_between_intent_and_send_prevents_submission(driver, monkeypatch):
    measured = ready(driver)
    another = api().PhysicalTransferDispatcher(execution(driver.store), driver.port, driver.tasks,
                                               deployment_profile="simulation")
    original = driver.execution.authorize_submission
    def cancel_after_intent(*args, **kwargs):
        result = original(*args, **kwargs)
        another.cancel(driver.job["mission_id"], reason="operator cancel")
        return result
    monkeypatch.setattr(driver.execution, "authorize_submission", cancel_after_intent)
    assert submit(driver, measured)["status"] == "UNKNOWN"
    assert driver.port.submitted == []


def test_overlapping_dispatchers_serialize_rpcs_for_the_same_journal(driver, monkeypatch):
    measured = ready(driver)
    another = api().PhysicalTransferDispatcher(execution(driver.store), driver.port, driver.tasks,
                                               deployment_profile="simulation")
    reached_intent, continue_send, cancel_started, cancel_done = Event(), Event(), Event(), Event()
    original = driver.execution.authorize_submission
    def pause_after_intent(*args, **kwargs):
        result = original(*args, **kwargs)
        reached_intent.set()
        assert continue_send.wait(3)
        return result
    monkeypatch.setattr(driver.execution, "authorize_submission", pause_after_intent)
    def cancel():
        cancel_started.set()
        result = another.cancel(driver.job["mission_id"], reason="operator cancel")
        cancel_done.set()
        return result
    with ThreadPoolExecutor(max_workers=2) as pool:
        sent = pool.submit(submit, driver, measured)
        assert reached_intent.wait(3)
        canceled = pool.submit(cancel)
        try:
            assert cancel_started.wait(3)
            assert not cancel_done.wait(.1)
        finally:
            continue_send.set()
        sent.result()
        canceled.result()
    assert len(driver.port.submitted) == 1 and len(driver.port.cancels) == 1
