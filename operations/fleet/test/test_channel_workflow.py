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
            "evidence": None,
            "request": {"goal": {key: GOAL[key] for key in ("x", "y", "yaw")}}}
    body.update(changes)
    return tasks.create_task(**body)["task"]


def test_review_and_existing_task_outcome_reply_once_without_execution_claim(tmp_path):
    from fleet.server.channel_replies import ChannelReplyOutbox
    workflow, journal, tasks, _, receipt = fixture(tmp_path)
    outbox = ChannelReplyOutbox(journal, clock=lambda: 1000)
    journal.reply_outbox = outbox
    held = review(workflow, receipt, state="HOLD", candidate=None, reason="clarify location")
    row = outbox.claim(now=1000)
    assert row["kind"] == "REVIEW:1" and "HOLD" in row["content"]
    assert "clarify location" not in row["content"]
    outbox.finish(row, state="SENT", provider_id=USER, now=1000)
    ready = review(workflow, receipt, expected_revision=held["revision"])
    created = task(tasks, receipt)
    workflow.link_task(receipt["request_id"], "op", task_id=created["task_id"],
                       expected_hash=receipt["content_hash"], expected_revision=ready["revision"])
    tasks.transition(created["task_id"], "UNKNOWN", actor_id="system", source="system", reason="unproven")
    outbox.observe_results()
    outbox.observe_results()
    rows = outbox.rows("op")
    assert len([row for row in rows if row["kind"] == "TASK:UNKNOWN"]) == 1
    tasks.transition(created["task_id"], "FAILED", actor_id="system", source="system", reason="expired")
    outbox.observe_results()
    rows = outbox.rows("op")
    assert len([row for row in rows if row["kind"] == "TASK:FAILED"]) == 1
    assert tasks.get_task(created["task_id"])["status"] == "FAILED"


def test_review_reply_intent_failure_rolls_back_review(tmp_path, monkeypatch):
    from fleet.server.channel_replies import ChannelReplyOutbox
    workflow, journal, _, _, receipt = fixture(tmp_path)
    outbox = ChannelReplyOutbox(journal)
    journal.reply_outbox = outbox

    def fail(*args, **kwargs):
        raise OSError("reply journal unavailable")
    monkeypatch.setattr(outbox, "enqueue", fail)
    with pytest.raises(OSError):
        review(workflow, receipt, state="HOLD", candidate=None, reason="clarify")
    assert workflow.read(receipt["request_id"], "op")["state"] == "REQUESTED"


@pytest.mark.parametrize("change", ["owner", "removed", "channel"])
def test_restarted_result_observation_does_not_reply_to_revoked_receipt(tmp_path, change):
    import asyncio
    from fleet.server.channel_replies import ChannelReplyOutbox, ChannelReplyWorker
    workflow, journal, tasks, _, receipt = fixture(tmp_path)
    ready = review(workflow, receipt)
    created = task(tasks, receipt)
    workflow.link_task(receipt["request_id"], "op", task_id=created["task_id"],
                       expected_hash=receipt["content_hash"], expected_revision=ready["revision"])
    tasks.transition(created["task_id"], "FAILED", actor_id="system", source="system", reason="expired")
    updated = dict(users={USER: "other"}) if change == "owner" else (
        dict(users={str(int(USER) + 10): "op"}) if change == "removed" else dict(channel_id=str(int(CHANNEL) + 10)))
    journal.config = journal.config.model_copy(update=updated)
    outbox = ChannelReplyOutbox(journal, clock=lambda: 1000)

    class Sender:
        async def send(self, **kwargs):
            raise AssertionError("revoked original request caused external reply")
    asyncio.run(ChannelReplyWorker(outbox, Sender(), clock=lambda: 1000).run_once())
    assert len(outbox.rows("op")) == 1 and outbox.rows("op")[0]["state"] == "SUPERSEDED"


def test_revoked_first_batch_does_not_starve_later_valid_result(tmp_path):
    import asyncio
    from contextlib import closing
    from fleet.server.channel_replies import ChannelReplyOutbox, ChannelReplyWorker
    workflow, journal, tasks, _, _ = fixture(tmp_path)
    second = str(int(USER) + 100)
    journal.config = journal.config.model_copy(update={"users": {USER: "op", second: "op"}})
    for index in range(51):
        receipt = journal.receive(DiscordRequestEnvelope(
            guild_id=GUILD, channel_id=CHANNEL, author_id=USER if index < 50 else second,
            message_id=str(int(MESSAGE) + index + 100), mentions=[BOT], author_bot=False,
            webhook_id=None, content=f"<@{BOT}> request {index}"))
        ready = review(workflow, receipt)
        created = task(tasks, receipt, task_id=f"result-{index}")
        workflow.link_task(receipt["request_id"], "op", task_id=created["task_id"],
                           expected_hash=receipt["content_hash"], expected_revision=ready["revision"])
        tasks.transition(created["task_id"], "FAILED", actor_id="system", source="system", reason="expired")
        with closing(tasks._connect()) as conn, conn:
            conn.execute("UPDATE fleet_tasks SET updated_at=? WHERE task_id=?",
                         (f"2026-10-12T00:00:{index:02d}+00:00", created["task_id"]))
    journal.config = journal.config.model_copy(update={"users": {USER: "other", second: "op"}})
    outbox = ChannelReplyOutbox(journal, clock=lambda: 1000)
    sent = []

    class Sender:
        async def send(self, **kwargs):
            sent.append(kwargs)
            return {"state": "SENT", "provider_id": MESSAGE}
    worker = ChannelReplyWorker(outbox, Sender(), clock=lambda: 1000)
    asyncio.run(worker.run_once())
    asyncio.run(worker.run_once())
    assert len(sent) == 1 and sent[0]["message_id"] == receipt["message_id"]
    with closing(journal._connect()) as conn:
        count = conn.execute("SELECT count(*) FROM fleet_channel_reply_outbox WHERE state='SUPERSEDED'").fetchone()[0]
        assert count == 50


@pytest.mark.parametrize("next_state", ["HOLD", "READY"])
def test_review_changed_between_read_and_task_creation_prevents_creation(tmp_path, monkeypatch, next_state):
    import asyncio
    from contextlib import closing
    from fleet.server.task_service import FleetTaskService
    workflow, journal, tasks, _, receipt = fixture(tmp_path)
    service = FleetTaskService(tasks, robot_ids={"pinky"})
    ready = review(workflow, receipt)
    create = tasks.create_task

    def race(**kwargs):
        workflow.review(receipt["request_id"], "op", expected_hash=receipt["content_hash"],
                        expected_revision=ready["revision"], state=next_state,
                        candidate={**GOAL, "x": 9.0} if next_state == "READY" else None, reason="changed in other tab")
        return create(**kwargs)
    monkeypatch.setattr(tasks, "create_task", race)
    with pytest.raises(HTTPException) as stale:
        asyncio.run(workflow.submit(receipt["request_id"], "op", task_service=service,
                                    expected_hash=receipt["content_hash"], expected_revision=ready["revision"]))
    assert stale.value.status_code == 409
    with closing(journal._connect()) as conn:
        assert conn.execute("SELECT count(*) FROM fleet_tasks").fetchone()[0] == 0


def test_submit_creates_and_links_once_with_original_confirmation_revision(tmp_path):
    import asyncio
    from fleet.server.task_service import FleetTaskService
    workflow, _, tasks, _, receipt = fixture(tmp_path)
    service = FleetTaskService(tasks, robot_ids={"pinky"})
    ready = review(workflow, receipt)
    body = dict(task_service=service, expected_hash=receipt["content_hash"], expected_revision=ready["revision"])
    first = asyncio.run(workflow.submit(receipt["request_id"], "op", **body))
    assert first["state"] == "LINKED" and first["work_status"] == "QUEUED"
    assert asyncio.run(workflow.submit(receipt["request_id"], "op", **body))["work_id"] == first["work_id"]
    assert tasks.get_task(first["work_id"])["actor_id"] == "op"


def test_task_history_insert_failure_rolls_back_task_relation_and_reply(tmp_path):
    import asyncio
    import sqlite3
    from contextlib import closing
    from fleet.server.channel_replies import ChannelReplyOutbox
    from fleet.server.task_service import FleetTaskService
    workflow, journal, tasks, _, receipt = fixture(tmp_path)
    service = FleetTaskService(tasks, robot_ids={"pinky"})
    outbox = ChannelReplyOutbox(journal)
    journal.reply_outbox = outbox
    ready = review(workflow, receipt)
    with closing(tasks._connect()) as conn, conn:
        conn.execute("CREATE TRIGGER reject_task_history BEFORE INSERT ON fleet_task_history "
                     "BEGIN SELECT RAISE(ABORT, 'synthetic history failure'); END")
    with pytest.raises(sqlite3.IntegrityError):
        asyncio.run(workflow.submit(receipt["request_id"], "op", task_service=service,
                                    expected_hash=receipt["content_hash"], expected_revision=ready["revision"]))
    assert workflow.read(receipt["request_id"], "op")["state"] == "READY"
    assert [row["kind"] for row in outbox.rows("op")] == ["REVIEW:1"]
    with closing(tasks._connect()) as conn:
        assert conn.execute("SELECT count(*) FROM fleet_tasks").fetchone()[0] == 0


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
