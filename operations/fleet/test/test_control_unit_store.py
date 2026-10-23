"""A lost reply, restart or relationship update must not create another execution."""

from concurrent.futures import ThreadPoolExecutor

import pytest


def open_store(path, unit_id="A"):
    from fleet.server.control_unit_store import ControlUnitStore
    return ControlUnitStore(path, unit_id=unit_id)


def create(store, *, revision="v1", request=None, owner="A"):
    return store.create("R", "job-1", request or {"target_unit": "A", "robot_id": "a",
                        "goal": {"x": 1.0, "y": 2.0, "yaw": 0.0}},
                        owner_unit=owner, config_revision=revision)


def test_identity_survives_restarts_and_relation_revisions(tmp_path):
    path = tmp_path / "fleet.db"
    first = create(open_store(path))
    again = create(open_store(path), revision="v2")
    assert again == first
    assert again["config_revision"] == "v1"
    assert again["status"] == "PENDING"
    assert len(open_store(path).list()) == 1


def test_same_identity_cannot_change_body_or_owner(tmp_path):
    store = open_store(tmp_path / "fleet.db")
    create(store)
    for kwargs in [{"request": {"target_unit": "B"}}, {"owner": "B"}]:
        with pytest.raises(ValueError, match="CONFLICT"):
            create(store, **kwargs)


def test_concurrent_delivery_creates_one_durable_row(tmp_path):
    path = tmp_path / "fleet.db"
    open_store(path)
    with ThreadPoolExecutor(max_workers=6) as pool:
        rows = list(pool.map(lambda _: create(open_store(path)), range(12)))
    assert all(row == rows[0] for row in rows)
    assert len(open_store(path).list()) == 1


def test_operator_approval_is_durable_and_cannot_be_reassigned(tmp_path):
    path = tmp_path / "fleet.db"
    store = open_store(path)
    create(store)
    approved = store.approve("R", "job-1", actor_id="operator-a")
    assert approved["status"] == "APPROVING"
    assert approved["local_actor"] == "operator-a"
    with pytest.raises(ValueError, match="APPROVAL"):
        open_store(path).approve("R", "job-1", actor_id="operator-b")
    assert open_store(path).approve("R", "job-1", actor_id="operator-a") == approved


def test_parent_cannot_approve_for_child_or_reopen_cancelled_candidate(tmp_path):
    store = open_store(tmp_path / "fleet.db")
    create(store, owner="A1")
    with pytest.raises(ValueError):
        store.approve("R", "job-1", actor_id="operator-a")
    store.request_cancel("R", "job-1")
    assert store.get("R", "job-1")["cancel_requested"] is True


def test_owner_revision_and_terminal_result_are_fenced(tmp_path):
    store = open_store(tmp_path / "fleet.db")
    create(store, owner="A1")
    done = store.project("R", "job-1", owner_unit="A1", owner_revision=5,
                         status="COMPLETED", result={"task_id": "task-1"})
    assert store.project("R", "job-1", owner_unit="A1", owner_revision=4,
                         status="RUNNING", result={}) == done
    with pytest.raises(ValueError):
        store.project("R", "job-1", owner_unit="B", owner_revision=6,
                      status="FAILED", result={})
    with pytest.raises(ValueError):
        store.project("R", "job-1", owner_unit="A1", owner_revision=6,
                      status="FAILED", result={})
    assert store.get("R", "job-1") == done


def test_cancel_request_does_not_claim_physical_stop(tmp_path):
    store = open_store(tmp_path / "fleet.db")
    create(store, owner="A1")
    store.project("R", "job-1", owner_unit="A1", owner_revision=1,
                  status="RUNNING", result={"task_id": "task-1"})
    row = store.request_cancel("R", "job-1")
    assert row["status"] == "RUNNING"
    assert row["cancel_requested"] is True


def test_database_cannot_change_its_control_unit_identity(tmp_path):
    path = tmp_path / "fleet.db"
    open_store(path)
    with pytest.raises(ValueError, match="IDENTITY"):
        open_store(path, unit_id="other")


def test_task_binding_uses_the_existing_task_transaction(tmp_path):
    from fleet.server.task_store import FleetTaskStore
    path = tmp_path / "fleet.db"
    tasks, store = FleetTaskStore(path), open_store(path)
    create(store)
    def submit(task_id, key="control:R:job-1"):
        return tasks.create_task(task_id=task_id, robot_id="a", task_type="navigate",
                                 source="operator", actor_id="operator-a", request_key=key,
                                 request={"goal": {"x": 1.0, "y": 2.0, "yaw": 0.0}}, evidence=None,
                                 admission=store.task_admission("R", "job-1", actor_id="operator-a"))
    with pytest.raises(ValueError, match="APPROVAL"):
        submit("task-1")
    store.approve("R", "job-1", actor_id="operator-a")
    assert submit("task-1")["created"] is True
    assert submit("task-2")["task"]["task_id"] == "task-1"
    reopened = open_store(path)
    assert reopened.get("R", "job-1")["local_task_id"] == "task-1"
    with pytest.raises(ValueError, match="CONFLICT"):
        submit("task-2", key="different-intent")
    assert tasks.get_task("task-2") is None


def test_binding_rolls_back_with_a_failed_task_creation(tmp_path):
    from fleet.server.task_store import FleetTaskStore
    path = tmp_path / "fleet.db"
    tasks, store = FleetTaskStore(path), open_store(path)
    create(store)
    store.approve("R", "job-1", actor_id="operator-a")
    bind = store.task_admission("R", "job-1", actor_id="operator-a")
    def fail_after_binding(connection, task_id):
        bind(connection, task_id)
        raise RuntimeError("injected insert failure")
    with pytest.raises(RuntimeError):
        tasks.create_task(task_id="task-1", robot_id="a", task_type="navigate",
                          source="operator", actor_id="operator-a", request_key="stable-key",
                          request={"goal": {}}, evidence=None, admission=fail_after_binding)
    assert tasks.get_task("task-1") is None
    assert open_store(path).get("R", "job-1")["local_task_id"] is None


@pytest.mark.parametrize("actor_id", [None, "", True])
def test_missing_approval_identity_cannot_match_an_unapproved_row(tmp_path, actor_id):
    from fleet.server.task_store import FleetTaskStore
    path = tmp_path / "fleet.db"
    tasks, store = FleetTaskStore(path), open_store(path)
    create(store)
    with pytest.raises(ValueError, match="APPROVAL"):
        tasks.create_task(task_id="unapproved-task", robot_id="a", task_type="navigate",
                          source="operator", actor_id="operator-a", request_key="unapproved",
                          request={"goal": {}}, evidence=None,
                          admission=store.task_admission("R", "job-1", actor_id=actor_id))
    assert tasks.get_task("unapproved-task") is None
    assert store.get("R", "job-1")["local_task_id"] is None
