"""Native Task navigation binds a CORE run, rather than caller CID alone."""

from uuid import uuid4

from fakes import run
from fleet.server.task_service import FleetTaskService
from fleet.server.task_store import FleetTaskStore


def _accepted_native_task(tmp_path):
    store = FleetTaskStore(tmp_path / "fleet.sqlite3")
    service = FleetTaskService(store, robot_ids={"rosy_01"})
    control = store.dispatch_control()
    store.rearm_dispatch(expected_generation=control["generation"], actor_id="operator")
    queued = run(service.submit_navigation(
        robot_id="rosy_01", x=1.0, y=2.0, source="operator",
        actor_id="site-console", request_key="one-native-goal"))
    run_id, boot_id = uuid4(), uuid4()

    async def dispatch(attempt):
        return {"accepted": True, "operation": {
            "run_id": str(run_id), "boot_id": str(boot_id), "kind": "navigate",
            "correlation_id": attempt["attempt_id"], "phase": "SUBMITTED",
            "result": None, "reason": None,
        }}

    accepted = run(service.dispatch_next({"rosy_01"}, dispatch=dispatch))
    assert accepted["task_id"] == queued["task_id"]
    assert accepted["status"] == "ACCEPTED"
    return service, accepted, run_id, boot_id


def test_task_keeps_first_core_native_receipt_with_its_attempt(tmp_path):
    _, accepted, run_id, boot_id = _accepted_native_task(tmp_path)
    assert accepted["receipt"]["operation"]["run_id"] == str(run_id)
    assert accepted["receipt"]["operation"]["boot_id"] == str(boot_id)
    assert accepted["receipt"]["operation"]["correlation_id"] == accepted["attempt_id"]


def test_same_caller_cid_cannot_complete_another_native_run(tmp_path):
    service, accepted, run_id, boot_id = _accepted_native_task(tmp_path)
    wrong = service.project_core_event({
        "robot_id": "rosy_01", "event_id": "wrong-run", "seq": 1,
        "type": "nav.completed", "data": {
            "correlation_id": accepted["attempt_id"],
            "run_id": str(uuid4()), "boot_id": str(boot_id),
        },
    })
    assert wrong is not None
    assert service.store.get_task(accepted["task_id"])["status"] == "ACCEPTED"

    right = service.project_core_event({
        "robot_id": "rosy_01", "event_id": "right-run", "seq": 2,
        "type": "nav.completed", "data": {
            "correlation_id": accepted["attempt_id"],
            "run_id": str(run_id), "boot_id": str(boot_id),
        },
    })
    assert right is not None and right["status"] == "COMPLETED"
