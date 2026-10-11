"""Console review links existing work without another device writer."""
import hashlib

import pytest
from fastapi import HTTPException

from core_common.protocol.channel_requests import DiscordRequestEnvelope
from fleet.server.channel_requests import ChannelConfig, ChannelRequests
from fleet.server.channel_workflow import ChannelWorkflow
from fleet.server.task_store import FleetTaskStore


GUILD, CHANNEL, USER, BOT, MESSAGE = (str(100000000000000000 + i) for i in range(5))
GOAL = {"robot_id": "pinky", "x": 1.0, "y": 2.0, "yaw": 0.0}


def fixture(tmp_path):
    tasks = FleetTaskStore(tmp_path / "tasks.sqlite")
    accounts = {"op": "operator", "other": "operator"}
    config = ChannelConfig(guild_id=GUILD, channel_id=CHANNEL, bot_id=BOT,
                           transport_key="test-key-" * 5, users={USER: "op"})
    journal = ChannelRequests(tasks.path, config, accounts)
    receipt = journal.receive(DiscordRequestEnvelope(
        guild_id=GUILD, channel_id=CHANNEL, author_id=USER, message_id=MESSAGE,
        mentions=[BOT], author_bot=False, webhook_id=None, content=f"<@{BOT}> request"))
    return ChannelWorkflow(journal, task_store=tasks), journal, tasks, accounts, receipt


def review(workflow, receipt, **changes):
    body = {"expected_hash": receipt["content_hash"], "expected_revision": 0,
            "state": "READY", "candidate": GOAL, "reason": "operator reviewed original request"}
    body.update(changes)
    return workflow.review(receipt["request_id"], "op", **body)


def task(tasks, receipt, **changes):
    body = {"task_id": "task-one", "robot_id": "pinky", "task_type": "navigate",
            "source": "operator", "actor_id": "op", "request_key": "discord-" + receipt["request_id"],
            "request": {"goal": {key: GOAL[key] for key in ("x", "y", "yaw")}}}
    body.update(changes)
    return tasks.create_task(**body)["task"]


def test_review_is_durable_owner_scoped_revision_checked_and_not_execution(tmp_path):
    workflow, journal, tasks, _, receipt = fixture(tmp_path)
    assert workflow.read(receipt["request_id"], "op")["revision"] == 0
    first = review(workflow, receipt)
    assert first["state"] == "READY" and first["revision"] == 1
    assert tasks.get_task("task-one") is None
    restarted = ChannelWorkflow(journal, task_store=tasks)
    assert restarted.read(receipt["request_id"], "op") == first
    with pytest.raises(HTTPException) as denied:
        restarted.read(receipt["request_id"], "other")
    assert denied.value.status_code == 404
    with pytest.raises(HTTPException) as stale:
        review(workflow, receipt, state="HOLD", candidate=None, reason="clarify")
    assert stale.value.status_code == 409


def test_review_rejects_changed_original_revoked_account_and_invalid_goal(tmp_path):
    workflow, _, _, accounts, receipt = fixture(tmp_path)
    with pytest.raises(HTTPException) as changed:
        review(workflow, receipt, expected_hash=hashlib.sha256(b"different").hexdigest())
    assert changed.value.status_code == 409
    accounts["op"] = "viewer"
    with pytest.raises(HTTPException) as denied:
        review(workflow, receipt)
    assert denied.value.status_code == 403
    accounts["op"] = "operator"
    for goal in ({**GOAL, "x": float("nan")}, {**GOAL, "principal_id": "other"}):
        with pytest.raises(ValueError):
            review(workflow, receipt, candidate=goal)


def test_link_checks_current_task_owner_request_key_and_approved_goal(tmp_path):
    workflow, _, tasks, _, receipt = fixture(tmp_path)
    review(workflow, receipt)
    created = task(tasks, receipt)
    result = workflow.link_task(receipt["request_id"], "op", task_id=created["task_id"],
                                expected_hash=receipt["content_hash"], expected_revision=1)
    assert result["state"] == "LINKED" and result["work_id"] == created["task_id"]
    assert result["work_status"] == "REQUESTED"
    assert workflow.link_task(receipt["request_id"], "op", task_id=created["task_id"],
                              expected_hash=receipt["content_hash"], expected_revision=1) == result
    tasks.transition(created["task_id"], "UNKNOWN", actor_id="system", source="system", reason="unproven")
    assert workflow.read(receipt["request_id"], "op")["work_status"] == "UNKNOWN"


@pytest.mark.parametrize("changes", [
    {"actor_id": "other"}, {"source": "policy"}, {"request_key": "unrelated"},
    {"request": {"goal": {"x": 8.0, "y": 2.0, "yaw": 0.0}}},
])
def test_unrelated_task_cannot_be_linked(tmp_path, changes):
    workflow, _, tasks, _, receipt = fixture(tmp_path)
    review(workflow, receipt)
    created = task(tasks, receipt, **changes)
    with pytest.raises(HTTPException) as denied:
        workflow.link_task(receipt["request_id"], "op", task_id=created["task_id"],
                           expected_hash=receipt["content_hash"], expected_revision=1)
    assert denied.value.status_code in (403, 409)
    assert workflow.read(receipt["request_id"], "op")["state"] == "READY"
