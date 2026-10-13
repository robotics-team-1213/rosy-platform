from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from threading import Event

from core_common.protocol.schemas import FleetActionGrant, StopRequestSource
from omx_adapter.action_api import ActionApi, LocalStopApi
from omx_adapter.action_runner import DriverSubmission
from omx_adapter.action_store import ActionStore
from omx_adapter.local_stop import LocalStopBlocked, LocalStopController
from test_omx_action_api import FakeDriver, _grant, _runner


def _stop_request(*, generation=8):
    return {
        "version": 1, "operation": "StopLocal", "workcell_id": "omx-1",
        "instance_id": "omx-1-control", "authority_epoch": 2,
        "dispatch_generation": generation,
        "requested_at": datetime.now(timezone.utc).isoformat(),
        "reason": "operator_estop",
    }


def test_stop_latches_even_when_stale_and_final_submit_fence_blocks_motion(tmp_path):
    store, driver, runner = _runner(tmp_path)
    first = FleetActionGrant.model_validate(_grant())
    accepted = runner.submit(first, peer_uid=1001)
    stop_api = LocalStopApi(
        runner.local_stop, source_by_peer_uid={1001: StopRequestSource.FLEET},
        cancel_active=lambda uid: runner.cancel_unresolved(peer_uid=uid),
    )
    api = ActionApi(runner, stop_api=stop_api)

    stopped = api.dispatch(_stop_request(generation=7), peer_uid=1001)
    second = FleetActionGrant.model_validate(_grant(
        action_id="action-2", attempt_id="attempt-2",
    ))
    rejected = runner.submit(second, peer_uid=1001)

    assert accepted["state"] == "ACCEPTED"
    assert stopped["snapshot"]["state"] == "LOCAL_LATCHED"
    assert stopped["snapshot"]["dispatch_generation"] == 8
    assert stopped["snapshot"]["source"] == "fleet"
    assert stopped["cancellations"][0]["state"] == "CANCEL_REQUESTED"
    assert rejected["state"] == "HOLD"
    assert rejected["reason"] == "STOP_GENERATION_FENCED"
    assert driver.submissions == [first.action_id]
    assert store.get_action(second.action_id)["state"] == "HOLD"


def test_rearm_requires_fresh_generation_operator_and_reconciled_actions(tmp_path):
    _, driver, runner = _runner(tmp_path)
    grant = FleetActionGrant.model_validate(_grant())
    runner.submit(grant, peer_uid=1001)
    stop_api = LocalStopApi(
        runner.local_stop, source_by_peer_uid={1001: StopRequestSource.OPERATOR_LOCAL},
        cancel_active=lambda uid: runner.cancel_unresolved(peer_uid=uid),
    )
    api = ActionApi(runner, stop_api=stop_api)
    api.dispatch(_stop_request(), peer_uid=1001)

    try:
        runner.local_stop.rearm(
            authority_epoch=2, dispatch_generation=9, operator_confirmed=True,
            fleet_fence_current=lambda epoch, generation: True,
        )
        raise AssertionError("unresolved Action claims must block rearm")
    except LocalStopBlocked:
        pass
    assert driver.cancellations == [grant.attempt_id]
    assert runner.local_stop.snapshot(
        workcell_id="omx-1", instance_id="omx-1-control",
    ).state == "LOCAL_LATCHED"

    runner.record_terminal(
        grant.action_id, grant.attempt_id, driver_goal_id="driver-goal-1",
        outcome="FAILED", result_source="driver-readback",
        result_observed_at=datetime.now(timezone.utc).isoformat(),
        result={"stopped": True}, peer_uid=1001,
    )
    reopened = runner.local_stop.rearm(
        authority_epoch=2, dispatch_generation=9, operator_confirmed=True,
        fleet_fence_current=lambda epoch, generation: (epoch, generation) == (2, 9),
    )
    assert reopened.state == "OPEN"
    try:
        runner.local_stop.rearm(
            authority_epoch=2, dispatch_generation=9, operator_confirmed=True,
            fleet_fence_current=lambda epoch, generation: True,
        )
        raise AssertionError("replayed generation must not clear stop latch")
    except LocalStopBlocked:
        pass


def test_stop_and_final_submit_are_serialized_through_the_driver_call(tmp_path):
    entered = Event()
    release = Event()

    class BlockingDriver(FakeDriver):
        def submit(self, grant):
            self.submissions.append(grant.action_id)
            entered.set()
            if not release.wait(5):
                raise TimeoutError("test driver was not released")
            return DriverSubmission(accepted=True, driver_goal_id="driver-goal-1")

    store, driver, runner = _runner(tmp_path, BlockingDriver())
    grant = FleetActionGrant.model_validate(_grant())
    stop_api = LocalStopApi(
        runner.local_stop, source_by_peer_uid={1001: StopRequestSource.FLEET},
        cancel_active=lambda uid: runner.cancel_unresolved(peer_uid=uid),
    )
    api = ActionApi(runner, stop_api=stop_api)

    with ThreadPoolExecutor(max_workers=2) as pool:
        submitted = pool.submit(runner.submit, grant, peer_uid=1001)
        assert entered.wait(2)
        stopped = pool.submit(api.dispatch, _stop_request(), peer_uid=1001)
        release.set()
        submit_result = submitted.result(timeout=3)
        stop_result = stopped.result(timeout=3)

    assert submit_result["state"] == "ACCEPTED"
    assert stop_result["snapshot"]["state"] == "LOCAL_LATCHED"
    assert driver.submissions == [grant.action_id]
    assert driver.cancellations == [grant.attempt_id]
    assert store.get_action(grant.action_id)["state"] == "CANCEL_REQUESTED"


def test_startup_state_is_unknown_and_closed_until_rearm(tmp_path):
    db = tmp_path / "stop.sqlite3"
    ActionStore(db)
    controller = LocalStopController(db, workcell_id="omx-1", instance_id="omx-1-control")
    snapshot = controller.snapshot(workcell_id="omx-1", instance_id="omx-1-control")

    assert snapshot.state == "UNKNOWN"
    try:
        controller.run_if_open(authority_epoch=2, dispatch_generation=8,
                               fleet_fence_current=lambda: True,
                               operation=lambda: "submitted")
        raise AssertionError("startup unknown state must prevent submission")
    except LocalStopBlocked:
        pass

    controller.rearm(authority_epoch=2, dispatch_generation=8,
                     operator_confirmed=True,
                     fleet_fence_current=lambda epoch, generation: True)
    restarted = LocalStopController(
        db, workcell_id="omx-1", instance_id="omx-1-control",
    )
    assert restarted.snapshot(
        workcell_id="omx-1", instance_id="omx-1-control",
    ).state == "UNKNOWN"
    try:
        restarted.run_if_open(authority_epoch=2, dispatch_generation=8,
                              fleet_fence_current=lambda: True,
                              operation=lambda: "submitted")
        raise AssertionError("process restart must close the prior generation")
    except LocalStopBlocked:
        pass


def test_uds_rearm_is_fleet_only_and_must_match_a_new_current_generation(tmp_path):
    _, _, runner = _runner(tmp_path)
    stop_api = LocalStopApi(
        runner.local_stop,
        source_by_peer_uid={
            1001: StopRequestSource.FLEET,
            1002: StopRequestSource.OPERATOR_LOCAL,
        },
        fleet_fence_current=lambda epoch, generation: (epoch, generation) == (2, 9),
    )
    api = ActionApi(runner, stop_api=stop_api)
    api.dispatch(_stop_request(), peer_uid=1001)
    body = {"version": 1, "operation": "RearmLocal", "workcell_id": "omx-1",
            "instance_id": "omx-1-control", "authority_epoch": 2,
            "dispatch_generation": 9}

    denied = api.dispatch(body, peer_uid=1002)
    wrong_instance = api.dispatch(
        {**body, "instance_id": "other-instance"}, peer_uid=1001,
    )
    stale = api.dispatch({**body, "dispatch_generation": 8}, peer_uid=1001)
    reopened = api.dispatch(body, peer_uid=1001)

    assert denied["error"]["code"] == "FLEET_PEER_REQUIRED"
    assert wrong_instance["error"]["code"] == "WORKCELL_NOT_FOUND"
    assert stale["error"]["code"] == "LOCAL_REARM_REFUSED"
    assert reopened["snapshot"]["state"] == "OPEN"
    assert reopened["snapshot"]["dispatch_generation"] == 9
