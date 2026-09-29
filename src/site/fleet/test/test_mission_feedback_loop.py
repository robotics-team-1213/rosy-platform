import asyncio
import sqlite3
import pytest

from core_common.protocol.schemas import MissionFeedbackContext, MissionFeedbackTurnScope
from fleet.ai.er2_standard import ER2FeedbackEgressPolicy, ER2RequestError
from fleet.server.mission_model_turn_worker import MissionModelTurnWorker
from fleet.server.mission_model_turn_scheduler import MissionModelTurnScheduler
from fleet.server.mission_model_turn_store import MissionModelTurnStore


def _scope():
    return {
        "principal_id": "operator-1", "workcell_id": "omx_01",
        "mission_id": "mission-1", "action_id": "action-1",
        "attempt_id": "attempt-1", "dispatch_generation": 4,
        "event_watermark": 19, "model_policy_revision": "policy-v1",
        "outcome_policy": "STATUS_ONLY",
    }


def _context(stop_state="DISPATCH_ENABLED"):
    return MissionFeedbackContext.model_validate({
        "mission_id": "mission-1", "workcell_id": "omx_01",
        "action_id": "action-1", "attempt_id": "attempt-1",
        "dispatch_generation": 4, "stop_generation": 4, "authority_epoch": 2,
        "snapshot_event_id": 19, "snapshot_at": "2026-09-30T12:00:00Z",
        "policy_revision": "policy-v1", "outcome_policy": "STATUS_ONLY",
        "task_summary": "Place the red block in the green tray.",
        "mission_source": "fleet_missions", "step_source": "fleet_missions",
        "action_source": "fleet_mission_events", "action_freshness": "FRESH",
        "action_observed_at": "2026-09-30T12:00:00Z",
        "goal_evidence_source": "none", "goal_evidence_freshness": "UNKNOWN",
        "goal_evidence_observed_at": None,
        "stop_source": "fleet_dispatch_control", "stop_freshness": "CURRENT",
        "stop_observed_at": "2026-09-30T12:00:00Z",
        "mission_state": "ACTION_SUCCEEDED", "step_state": "AWAITING_GOAL_EVIDENCE",
        "action_state": "SUCCEEDED", "action_reason": None,
        "goal_evidence_state": "PENDING", "goal_evidence_reason": None,
        "stop_state": stop_state, "stop_reason": None,
    })


def _policy():
    return ER2FeedbackEgressPolicy(
        approved=True, project_id="approved-project", service_tier="standard",
        approved_data_classes=frozenset({"mission_progress", "mission_instruction"}),
        approved_workcell_ids=frozenset({"omx_01"}),
        approved_task_classes=frozenset({"PICK_PLACE"}),
        estimated_cost_usd=0.05,
    )


def test_egress_policy_requires_approval_for_mission_instruction_payload():
    policy = ER2FeedbackEgressPolicy(
        approved=True, project_id="approved-project", service_tier="standard",
        approved_data_classes=frozenset({"mission_progress"}),
        approved_workcell_ids=frozenset({"omx_01"}),
        approved_task_classes=frozenset({"PICK_PLACE"}),
        estimated_cost_usd=0.05,
    )

    with pytest.raises(ER2RequestError):
        policy.validate_for(
            scope=MissionFeedbackTurnScope.model_validate(_scope()),
            task_class="PICK_PLACE",
        )


def _seed_submission_fence(store, *, dispatch_enabled=1, generation=4,
                           event_watermark=19):
    with sqlite3.connect(store.path) as db:
        db.executescript("""
            CREATE TABLE fleet_dispatch_control (
                control_id INTEGER PRIMARY KEY, generation INTEGER, dispatch_enabled INTEGER
            );
            CREATE TABLE fleet_missions (
                mission_id TEXT PRIMARY KEY, principal_id TEXT, workcell_id TEXT,
                action_kind TEXT, action_id TEXT, attempt_id TEXT,
                dispatch_generation INTEGER, status TEXT
            );
            CREATE TABLE fleet_mission_events (
                event_id INTEGER PRIMARY KEY, mission_id TEXT
            );
        """)
        db.execute("INSERT INTO fleet_dispatch_control VALUES (1, ?, ?)",
                   (generation, dispatch_enabled))
        db.execute("INSERT INTO fleet_missions VALUES (?, ?, ?, 'PICK_PLACE', ?, ?, ?, 'ACTION_SUCCEEDED')",
                   ("mission-1", "operator-1", "omx_01", "action-1", "attempt-1", generation))
        db.execute("INSERT INTO fleet_mission_events VALUES (?, ?)",
                   (event_watermark, "mission-1"))


class Adapter:
    def __init__(self, *, error=None):
        self.calls = 0
        self.error = error

    async def reason_about_mission(self, **_kwargs):
        self.calls += 1
        if self.error:
            raise self.error
        return "status reviewed"


class Dispatcher:
    def dispatch(self, **_kwargs):
        raise AssertionError("status-only final response should not call a tool")


class MissionService:
    def __init__(self, journal=None):
        self.store = journal

    def get(self, _mission_id):
        return {
            "principal_id": "operator-1", "workcell_id": "omx_01",
            "action_id": "action-1", "attempt_id": "attempt-1",
            "dispatch_generation": 4,
        }


class ProgressService:
    def __init__(self, *, action_state="SUCCEEDED", action_freshness="FRESH",
                 stop_state="DISPATCH_ENABLED", event_type="ACTION_TERMINAL_RESULT",
                 snapshot_event_id=23):
        self.action_state = action_state
        self.action_freshness = action_freshness
        self.stop_state = stop_state
        self.event_type = event_type
        self.snapshot_event_id = snapshot_event_id

    def events(self, _mission_id, *, after_event_id, limit):
        assert after_event_id == 18 and limit == 1
        return {"events": [{
            "event_id": 19, "event_type": self.event_type,
            "action_id": "action-1", "attempt_id": "attempt-1",
        }]}

    def snapshot(self, _mission_id):
        return {"progress": {
            "snapshot_event_id": self.snapshot_event_id,
            "action": {"state": self.action_state, "freshness": self.action_freshness},
            "stop": {"state": self.stop_state,
                     "revision": "epoch:2/generation:4"},
        }}


def _scheduler(store, progress=None):
    return MissionModelTurnScheduler(
        mission_service=MissionService(), progress_service=progress or ProgressService(),
        turn_store=store, policy_revision="policy-v1",
    )


def test_scheduler_uses_trigger_event_and_later_current_watermark_idempotently(tmp_path):
    store = MissionModelTurnStore(tmp_path / "fleet.sqlite3")
    _seed_submission_fence(store)
    scheduler = _scheduler(store)

    first = scheduler.consider("mission-1", trigger_event_id=19)
    duplicate = scheduler.consider("mission-1", trigger_event_id=19)

    assert first["created"] is True
    assert first["turn"]["trigger_event_id"] == 19
    assert first["turn"]["event_watermark"] == 23
    assert first["turn"]["outcome_policy"] == "STATUS_ONLY"
    assert duplicate["created"] is False
    assert duplicate["turn"]["turn_id"] == first["turn"]["turn_id"]


def test_scheduler_suppresses_stop_or_stale_action_evidence(tmp_path):
    store = MissionModelTurnStore(tmp_path / "fleet.sqlite3")
    stopped = _scheduler(store, ProgressService(stop_state="DISPATCH_BLOCKED")).consider(
        "mission-1", trigger_event_id=19,
    )
    stale_store = MissionModelTurnStore(tmp_path / "stale.sqlite3")
    stale = _scheduler(
        stale_store, ProgressService(action_state="UNKNOWN", action_freshness="UNKNOWN"),
    ).consider("mission-1", trigger_event_id=19)

    assert stopped["turn"]["state"] == "SUPPRESSED"
    assert stopped["turn"]["reason_code"] == "STOP_FENCE_CLOSED"
    assert stale["turn"]["state"] == "SUPPRESSED"
    assert stale["turn"]["reason_code"] == "ACTION_READBACK_UNSAFE"


def test_scheduler_treats_trusted_negative_goal_as_status_only(tmp_path):
    store = MissionModelTurnStore(tmp_path / "fleet.sqlite3")
    progress = ProgressService(event_type="GOAL_PREDICATE_UNSATISFIED")

    result = _scheduler(store, progress).consider("mission-1", trigger_event_id=19)

    assert result["turn"]["state"] == "PENDING"
    assert result["turn"]["outcome_policy"] == "STATUS_ONLY"


def test_scheduler_poll_persists_cursor_and_enqueues_only_durable_trigger_events(tmp_path):
    class Journal:
        events = [
            {"event_id": 19, "mission_id": "mission-1", "event_type": "ACTION_TERMINAL_RESULT"},
            {"event_id": 20, "mission_id": "mission-1", "event_type": "MODEL_NOTE"},
        ]

        def feedback_events_after(self, *, after_event_id, limit):
            return [event for event in self.events if event["event_id"] > after_event_id][:limit]

    store = MissionModelTurnStore(tmp_path / "fleet.sqlite3")
    scheduler = MissionModelTurnScheduler(
        mission_service=MissionService(Journal()), progress_service=ProgressService(),
        turn_store=store, policy_revision="policy-v1",
    )

    assert scheduler.poll_once(limit=10) == 2
    assert scheduler.poll_once(limit=10) == 0
    assert store.get_event_cursor() == 20
    assert store.get_event_cursor() == MissionModelTurnStore(
        tmp_path / "fleet.sqlite3",
    ).get_event_cursor()


def test_capacity_drop_is_terminal_for_scanned_event_and_does_not_stall_cursor(tmp_path):
    class Journal:
        events = [
            {"event_id": 19, "mission_id": "mission-1", "event_type": "ACTION_TERMINAL_RESULT"},
            {"event_id": 20, "mission_id": "mission-1", "event_type": "MODEL_NOTE"},
        ]

        def feedback_events_after(self, *, after_event_id, limit):
            return [event for event in self.events if event["event_id"] > after_event_id][:limit]

    store = MissionModelTurnStore(tmp_path / "fleet.sqlite3", max_rows=1)
    store.enqueue(scope=_scope(), trigger_event_id=18)
    scheduler = MissionModelTurnScheduler(
        mission_service=MissionService(Journal()), progress_service=ProgressService(),
        turn_store=store, policy_revision="policy-v1",
    )

    assert scheduler.poll_once(limit=10) == 2
    assert scheduler.poll_once(limit=10) == 0
    assert store.get_event_cursor() == 20
    assert store.capacity_dropped_count() == 1


def test_event_to_outbox_to_atomic_provider_submission_fence(tmp_path):
    class Journal:
        def feedback_events_after(self, *, after_event_id, limit):
            events = [{
                "event_id": 19, "mission_id": "mission-1",
                "event_type": "ACTION_TERMINAL_RESULT",
            }]
            return [event for event in events if event["event_id"] > after_event_id][:limit]

    store = MissionModelTurnStore(tmp_path / "fleet.sqlite3")
    _seed_submission_fence(store)
    scheduler = MissionModelTurnScheduler(
        mission_service=MissionService(Journal()),
        progress_service=ProgressService(snapshot_event_id=19),
        turn_store=store, policy_revision="policy-v1",
    )
    adapter = Adapter()

    assert scheduler.poll_once(limit=10) == 1
    assert store.get_event_cursor() == 19
    worker = MissionModelTurnWorker(
        store=store, adapter=adapter, dispatcher=Dispatcher(),
        context_loader=lambda _turn: _context(), egress_policy=_policy(),
        authorization_check=lambda scope: scope.principal_id == "operator-1",
    )

    result = asyncio.run(worker.consume_next(worker_id="worker-1"))

    assert result["trigger_event_id"] == 19
    assert result["state"] == "RESPONDED"
    assert store.get(result["turn_id"])["attempt_count"] == 1
    assert adapter.calls == 1


def test_worker_claims_once_and_releases_only_a_confirmed_stateless_turn(tmp_path):
    store = MissionModelTurnStore(tmp_path / "fleet.sqlite3")
    _seed_submission_fence(store)
    turn_id = store.enqueue(scope=_scope(), trigger_event_id=19)["turn"]["turn_id"]
    adapter = Adapter()
    worker = MissionModelTurnWorker(
        store=store, adapter=adapter, dispatcher=Dispatcher(),
        context_loader=lambda _turn: _context(), egress_policy=_policy(),
        authorization_check=lambda scope: scope.principal_id == "operator-1",
    )

    result = asyncio.run(worker.consume(turn_id, worker_id="worker-1"))

    assert result["state"] == "RESPONDED"
    assert store.get(turn_id)["attempt_count"] == 1
    assert adapter.calls == 1
    assert asyncio.run(worker.consume(turn_id, worker_id="worker-2")) is None
    assert adapter.calls == 1


def test_worker_consumes_oldest_pending_turn_without_a_turn_id(tmp_path):
    store = MissionModelTurnStore(tmp_path / "fleet.sqlite3")
    _seed_submission_fence(store)
    enqueued = store.enqueue(scope=_scope(), trigger_event_id=19)["turn"]
    adapter = Adapter()
    worker = MissionModelTurnWorker(
        store=store, adapter=adapter, dispatcher=Dispatcher(),
        context_loader=lambda _turn: _context(), egress_policy=_policy(),
        authorization_check=lambda scope: scope.principal_id == "operator-1",
    )

    result = asyncio.run(worker.consume_next(worker_id="worker-1"))

    assert result["turn_id"] == enqueued["turn_id"]
    assert result["state"] == "RESPONDED"
    assert store.get(enqueued["turn_id"])["attempt_count"] == 1
    assert adapter.calls == 1
    assert asyncio.run(worker.consume_next(worker_id="worker-2")) is None


def test_worker_suppresses_stopped_scope_before_provider_call(tmp_path):
    store = MissionModelTurnStore(tmp_path / "fleet.sqlite3")
    _seed_submission_fence(store)
    turn_id = store.enqueue(scope=_scope(), trigger_event_id=19)["turn"]["turn_id"]
    adapter = Adapter()
    worker = MissionModelTurnWorker(
        store=store, adapter=adapter, dispatcher=Dispatcher(),
        context_loader=lambda _turn: _context("DISPATCH_BLOCKED"),
        egress_policy=_policy(),
        authorization_check=lambda _scope: True,
    )

    result = asyncio.run(worker.consume(turn_id, worker_id="worker-1"))

    assert result["state"] == "SUPPRESSED"
    assert result["reason_code"] == "STOP_FENCE_CLOSED"
    assert adapter.calls == 0


def test_worker_releases_preflight_denial_without_spending_provider_attempt(tmp_path):
    store = MissionModelTurnStore(tmp_path / "fleet.sqlite3")
    _seed_submission_fence(store)
    turn_id = store.enqueue(scope=_scope(), trigger_event_id=19)["turn"]["turn_id"]
    adapter = Adapter()
    policy = ER2FeedbackEgressPolicy(
        approved=False, project_id="", service_tier="",
        approved_data_classes=frozenset(), approved_workcell_ids=frozenset(),
        approved_task_classes=frozenset(), estimated_cost_usd=0.05,
    )
    worker = MissionModelTurnWorker(
        store=store, adapter=adapter, dispatcher=Dispatcher(),
        context_loader=lambda _turn: _context(), egress_policy=policy,
        authorization_check=lambda _scope: True,
    )

    result = asyncio.run(worker.consume(turn_id, worker_id="worker-1"))

    assert result["state"] == "PENDING"
    assert result["reason_code"] == "EGRESS_POLICY_REJECTED"
    assert result["attempt_count"] == 0
    assert adapter.calls == 0


def test_worker_records_ambiguous_provider_outcome_and_never_retries(tmp_path):
    store = MissionModelTurnStore(tmp_path / "fleet.sqlite3")
    _seed_submission_fence(store)
    turn_id = store.enqueue(scope=_scope(), trigger_event_id=19)["turn"]["turn_id"]
    adapter = Adapter(error=TimeoutError("private provider details"))
    worker = MissionModelTurnWorker(
        store=store, adapter=adapter, dispatcher=Dispatcher(),
        context_loader=lambda _turn: _context(), egress_policy=_policy(),
        authorization_check=lambda _scope: True,
    )

    result = asyncio.run(worker.consume(turn_id, worker_id="worker-1"))

    assert result["state"] == "UNKNOWN"
    assert result["reason_code"] == "PROVIDER_OUTCOME_UNKNOWN"
    assert "private provider details" not in str(result)
    assert asyncio.run(worker.consume(turn_id, worker_id="worker-2")) is None
    assert adapter.calls == 1


def test_worker_rechecks_authorization_and_allowlist_before_provider_call(tmp_path):
    store = MissionModelTurnStore(tmp_path / "fleet.sqlite3")
    _seed_submission_fence(store)
    turn_id = store.enqueue(scope=_scope(), trigger_event_id=19)["turn"]["turn_id"]
    adapter = Adapter()
    worker = MissionModelTurnWorker(
        store=store, adapter=adapter, dispatcher=Dispatcher(),
        context_loader=lambda _turn: _context(), egress_policy=_policy(),
        authorization_check=lambda _scope: False,
    )

    result = asyncio.run(worker.consume(turn_id, worker_id="worker-1"))

    assert result["state"] == "PENDING"
    assert result["reason_code"] == "EGRESS_POLICY_REJECTED"
    assert adapter.calls == 0


def test_atomic_submission_fence_suppresses_changed_stop_or_event(tmp_path):
    store = MissionModelTurnStore(tmp_path / "fleet.sqlite3")
    _seed_submission_fence(store, dispatch_enabled=0, generation=5, event_watermark=20)
    turn_id = store.enqueue(scope=_scope(), trigger_event_id=19)["turn"]["turn_id"]
    adapter = Adapter()
    worker = MissionModelTurnWorker(
        store=store, adapter=adapter, dispatcher=Dispatcher(),
        context_loader=lambda _turn: _context(), egress_policy=_policy(),
        authorization_check=lambda _scope: True,
    )

    asyncio.run(worker.consume(turn_id, worker_id="worker-1"))

    row = store.get(turn_id)
    assert row["state"] == "SUPPRESSED"
    assert row["reason_code"] == "STOP_FENCE_CLOSED"
    assert row["attempt_count"] == 0
    assert adapter.calls == 0
