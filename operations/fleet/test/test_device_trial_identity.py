"""D-797 2–3: the device_trial profile and the real owner identity on the single-arm path only."""

import pytest

from fleet.server.app import DEPLOYMENT_PROFILES
from fleet.server.cell_arm_dispatcher import CellJobDispatcher
from fleet.server.cell_job_store import CellJobStore
from fleet.server.step_action_kinds import dispatch_open
from fleet.server.step_dispatcher import DEVICE_TRIAL, StepJobDispatcher

from test_cell_job_store import _create, _stores
from test_step_dispatcher import REVISIONS, Transport

DEVICE_REVISIONS = {"omx_01_control": {**REVISIONS["omx_01_control"], "commissioning_revision": "omx-01-c7"}}


def _device_owner(instance_id, **changes):
    return {"workcell_id": instance_id.removesuffix("_control"), "instance_id": instance_id,
            "device": True, "commissioning_revision": "omx-01-c7", "journal_id": "journal-1", **changes}


def _setup(tmp_path, revisions=DEVICE_REVISIONS, cls=StepJobDispatcher):
    path, tasks, _, enabled = _stores(tmp_path)
    store = CellJobStore(path)
    _create(store)
    store.admit("cell-mission-1", actor_id="operator-1", expected_generation=enabled["generation"])
    transport = Transport()
    transport.owner_identity = _device_owner
    dispatcher = cls(store, tasks, transport, {"omx_01": "omx_01_control"}, revisions,
                     deployment_profile=DEVICE_TRIAL)
    return store, transport, dispatcher


def test_device_trial_opens_trips_and_the_single_arm_while_production_stays_closed():
    assert DEVICE_TRIAL in DEPLOYMENT_PROFILES
    assert dispatch_open(DEVICE_TRIAL, "TRIP") and dispatch_open(DEVICE_TRIAL, "CELL_TRANSFER")
    assert not dispatch_open("production", "CELL_TRANSFER") and not dispatch_open("production", "TRIP")
    with pytest.raises(ValueError, match="closed"):
        StepJobDispatcher(None, None, Transport(), {"omx_01": "omx_01_control"}, REVISIONS,
                          deployment_profile="production")


def test_a_simulation_owner_is_unchanged_by_the_device_profile(tmp_path):
    path, tasks, _, enabled = _stores(tmp_path)
    store = CellJobStore(path)
    _create(store)
    store.admit("cell-mission-1", actor_id="operator-1", expected_generation=enabled["generation"])
    dispatcher = StepJobDispatcher(store, tasks, Transport(), {"omx_01": "omx_01_control"}, REVISIONS,
                                   deployment_profile="simulation")
    assert dispatcher.dispatch_next()["state"] == "ACCEPTED"


def test_a_device_trial_dispatcher_needs_the_commissioning_revision(tmp_path):
    with pytest.raises(ValueError, match="commissioning_revision"):
        _setup(tmp_path, revisions=REVISIONS)


def test_a_real_owner_with_the_configured_commissioning_revision_gets_the_grant(tmp_path):
    store, transport, dispatcher = _setup(tmp_path)
    assert dispatcher.dispatch_next()["state"] == "ACCEPTED"
    grant = transport.submissions[0]
    assert (grant.capability_revision, grant.config_revision) == ("cell-transfer-v1", "cell-config-v1")
    assert "commissioning_revision" not in grant.model_dump()  # the grant shape does not change


@pytest.mark.parametrize("changes", [
    {"device": False},
    {"device": None},
    {"simulation": True},                      # a simulation owner never passes as a device
    {"commissioning_revision": "omx-01-c6"},   # an owner re-commissioned since the configuration
    {"commissioning_revision": None},
    {"instance_id": "omx_02_control"},
    {"workcell_id": "omx_02"},
])
def test_anything_but_the_configured_real_owner_is_not_dispatched(tmp_path, changes):
    store, transport, dispatcher = _setup(tmp_path)
    transport.owner_identity = lambda instance_id: _device_owner(instance_id, **changes)
    assert dispatcher.dispatch_next()["state"] == "NOT_DEVICE_IDENTITY"
    assert transport.submissions == [] and store.get("cell-mission-1")["status"] == "READY"


def test_an_empty_configured_revision_never_matches(tmp_path):
    empty = {"omx_01_control": {**DEVICE_REVISIONS["omx_01_control"], "commissioning_revision": ""}}
    store, transport, dispatcher = _setup(tmp_path, revisions=empty)
    transport.owner_identity = lambda instance_id: _device_owner(instance_id, commissioning_revision="")
    assert dispatcher.dispatch_next()["state"] == "NOT_DEVICE_IDENTITY" and transport.submissions == []


def test_the_multi_arm_pass_stays_simulation_only_after_a_device_answer(tmp_path):
    # D-797 3: the single-arm device answer lives in its own cache; the multi-arm pass shares only
    # the simulation cache, so a real owner is still NOT_SIMULATION there (D-778/D-779 decide that).
    store, transport, dispatcher = _setup(tmp_path, cls=CellJobDispatcher)
    assert dispatcher.dispatch_next()["state"] == "ACCEPTED"
    assert dispatcher._device_identity["omx_01_control"][0] is True
    assert dispatcher.arms._identity is dispatcher._identity
    assert dispatcher.arms._simulation_identity("omx_01", "omx_01_control") is False
