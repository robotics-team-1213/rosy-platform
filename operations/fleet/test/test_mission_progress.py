from __future__ import annotations

import sqlite3
import time
from pathlib import Path

import pytest

from test_mission_api import _client, _create, _resolve
from fleet.server.mission_progress import MissionProgressService
from fleet.server.mission_store import MissionStore


_OPERATOR = {"Authorization": "Bearer operator-secret"}
_VIEWER = {"Authorization": "Bearer viewer-secret"}


def _resolved_mission(client):
    proposal_id = _create(client).json()["proposal"]["proposal_id"]
    return _resolve(client, proposal_id).json()["mission"]["mission_id"]


def _admit_mission(client, tasks, mission_id):
    control = tasks.store.dispatch_control()
    generation = tasks.store.rearm_dispatch(
        expected_generation=control["generation"], actor_id="operator-1",
    )["generation"]
    response = client.post(
        f"/api/fleet/missions/{mission_id}/admit", headers=_OPERATOR,
        json={"expected_generation": generation},
    )
    assert response.status_code == 200, response.text
    return response.json()["mission"]


def test_mission_read_contains_four_truthful_progress_axes(tmp_path):
    client, tasks, _ = _client(tmp_path)
    mission_id = _resolved_mission(client)

    response = client.get(f"/api/fleet/missions/{mission_id}", headers=_OPERATOR)

    assert response.status_code == 200
    assert response.json()["history_truncated"] is False
    progress = response.json()["progress"]
    assert set(progress) == {
        "snapshot_event_id", "snapshot_at", "mission", "step", "action",
        "goal_evidence", "stop", "active_phase", "phases",
    }
    assert progress["active_phase"] is None
    assert progress["phases"] == []
    assert progress["mission"]["state"] == "PROPOSED"
    assert progress["step"]["state"] == "NOT_ADMITTED"
    assert progress["action"]["state"] == "UNKNOWN"
    assert progress["goal_evidence"]["state"] == "UNKNOWN"
    assert progress["stop"]["state"] == "DISPATCH_BLOCKED"
    assert progress["stop"]["observed_at"] is not None
    assert progress["stop"]["physical_state"] == "UNKNOWN"
    assert all("source" in progress[axis] for axis in (
        "mission", "step", "action", "goal_evidence", "stop",
    ))
    assert "percent_complete" not in progress
    assert tasks.store.dispatch_control()["dispatch_enabled"] is False


def test_mission_snapshot_bounds_history_but_keeps_current_attempt_projection(tmp_path):
    client, tasks, _ = _client(tmp_path)
    mission_id = _resolved_mission(client)
    mission = _admit_mission(client, tasks, mission_id)
    store = client.app.state.mission_service.store
    store.start_step(
        mission_id, action_id="action-current", attempt_id="attempt-current",
        expected_authority_epoch=mission["authority_epoch"],
        expected_generation=mission["dispatch_generation"],
    )
    with sqlite3.connect(store.path) as connection:
        row = connection.execute(
            "SELECT step_id, actor_id FROM fleet_mission_events "
            "WHERE mission_id=? ORDER BY event_id DESC LIMIT 1", (mission_id,),
        ).fetchone()
        connection.executemany(
            """INSERT INTO fleet_mission_events
               (event_source, source_event_id, mission_id, step_id, action_id,
                attempt_id, state, event_type, actor_id, detail_json, created_at)
               VALUES ('test', ?, ?, ?, NULL, NULL, 'NOTE', 'TEST_NOTE', ?, '{}', ?)""",
            [
                (f"note-{index}", mission_id, row[0], row[1], f"2026-09-29T00:00:{index:02d}+00:00")
                for index in range(60)
            ],
        )

    response = client.get(
        f"/api/fleet/missions/{mission_id}", headers=_OPERATOR,
    )
    body = response.json()

    assert response.status_code == 200
    assert len(body["history"]) == 50
    assert body["history_truncated"] is True
    assert [event["event_id"] for event in body["history"]] == sorted(
        event["event_id"] for event in body["history"]
    )
    assert body["progress"]["snapshot_event_id"] == body["history"][-1]["event_id"]
    assert body["progress"]["action"]["state"] == "RUNNING"
    assert body["progress"]["action"]["last_event_id"] is not None


def test_snapshot_history_and_attempt_projection_use_ordered_indexes(tmp_path):
    client, _, _ = _client(tmp_path)
    mission_id = _resolved_mission(client)
    store = client.app.state.mission_service.store
    with sqlite3.connect(store.path) as connection:
        history_plan = connection.execute(
            "EXPLAIN QUERY PLAN SELECT * FROM fleet_mission_events "
            "WHERE mission_id=? ORDER BY event_id DESC LIMIT 51", (mission_id,),
        ).fetchall()
        attempt_plan = connection.execute(
            "EXPLAIN QUERY PLAN SELECT * FROM fleet_mission_events "
            "WHERE mission_id=? AND action_id=? AND attempt_id=? "
            "AND event_type IN ('STEP_SUBMITTED', 'ACTION_TERMINAL_RESULT') "
            "ORDER BY event_id DESC LIMIT 1",
            (mission_id, "action", "attempt"),
        ).fetchall()

    history_details = " ".join(str(row[3]) for row in history_plan).upper()
    attempt_details = " ".join(str(row[3]) for row in attempt_plan).upper()
    assert "FLEET_MISSION_EVENTS_MISSION" in history_details
    assert "TEMP B-TREE" not in history_details
    assert "FLEET_MISSION_EVENTS_ATTEMPT" in attempt_details
    assert "TEMP B-TREE" not in attempt_details


def test_oversized_action_event_rolls_back_mission_transition(tmp_path):
    client, tasks, _ = _client(tmp_path)
    mission_id = _resolved_mission(client)
    mission = _admit_mission(client, tasks, mission_id)
    store = client.app.state.mission_service.store
    store.start_step(
        mission_id, action_id="action-current", attempt_id="attempt-current",
        expected_authority_epoch=mission["authority_epoch"],
        expected_generation=mission["dispatch_generation"],
    )

    with pytest.raises(ValueError, match="16 KiB"):
        store.record_action_result(
            mission_id, event_id="oversized-result", action_id="action-current",
            attempt_id="attempt-current", outcome="SUCCEEDED",
            result={"payload": "x" * 17_000},
        )

    assert store.get_mission(mission_id)["status"] == "RUNNING"
    assert all(
        event["source_event_id"] != "oversized-result"
        for event in store.history(mission_id)
    )


def test_action_event_size_limit_counts_utf8_json_bytes(tmp_path):
    client, tasks, _ = _client(tmp_path)
    mission_id = _resolved_mission(client)
    mission = _admit_mission(client, tasks, mission_id)
    store = client.app.state.mission_service.store
    store.start_step(
        mission_id, action_id="action-current", attempt_id="attempt-current",
        expected_authority_epoch=mission["authority_epoch"],
        expected_generation=mission["dispatch_generation"],
    )

    result = store.record_action_result(
        mission_id, event_id="unicode-result", action_id="action-current",
        attempt_id="attempt-current", outcome="SUCCEEDED",
        result={"message": "한" * 5_000},
    )

    assert result["status"] == "ACTION_SUCCEEDED"


def test_event_cursor_pages_in_journal_order_and_reconnects_after_snapshot(tmp_path):
    client, _, _ = _client(tmp_path)
    mission_id = _resolved_mission(client)
    snapshot = client.get(f"/api/fleet/missions/{mission_id}", headers=_OPERATOR).json()
    snapshot_cursor = snapshot["progress"]["snapshot_event_id"]

    first = client.get(
        f"/api/fleet/missions/{mission_id}/events?after_event_id=0&limit=1",
        headers=_OPERATOR,
    )
    assert first.status_code == 200
    first_page = first.json()
    assert len(first_page["events"]) == 1
    assert first_page["events"][0]["event_id"] <= snapshot_cursor

    reconnect = client.get(
        f"/api/fleet/missions/{mission_id}/events?"
        f"after_event_id={snapshot_cursor}&limit=10",
        headers=_OPERATOR,
    )
    assert reconnect.status_code == 200
    assert reconnect.json()["events"] == []
    assert reconnect.json()["snapshot_event_id"] == snapshot_cursor


def test_event_pages_are_monotonic_even_when_created_timestamps_are_out_of_order(tmp_path):
    client, tasks, _ = _client(tmp_path)
    mission_id = _resolved_mission(client)
    _admit_mission(client, tasks, mission_id)
    store = client.app.state.mission_service.store
    with sqlite3.connect(store.path) as connection:
        second_id = connection.execute(
            "SELECT MAX(event_id) FROM fleet_mission_events WHERE mission_id=?",
            (mission_id,),
        ).fetchone()[0]
        connection.execute(
            "UPDATE fleet_mission_events SET created_at=? WHERE event_id=?",
            ("2000-01-01T00:00:00+00:00", second_id),
        )

    first = client.get(
        f"/api/fleet/missions/{mission_id}/events?after_event_id=0&limit=1",
        headers=_OPERATOR,
    ).json()
    second = client.get(
        f"/api/fleet/missions/{mission_id}/events?"
        f"after_event_id={first['next_after_event_id']}&limit=1",
        headers=_OPERATOR,
    ).json()

    assert first["has_more"] is True
    assert second["events"][0]["event_id"] > first["events"][0]["event_id"]
    assert second["events"][0]["created_at"].startswith("2000-")
    assert second["has_more"] is False


def test_stale_action_and_goal_observations_are_shown_stale_without_state_rollback(tmp_path):
    client, tasks, _ = _client(tmp_path)
    mission_id = _resolved_mission(client)
    mission = _admit_mission(client, tasks, mission_id)
    service = client.app.state.mission_service
    store = service.store
    store.start_step(
        mission_id, action_id="action-current", attempt_id="attempt-current",
        expected_authority_epoch=mission["authority_epoch"],
        expected_generation=mission["dispatch_generation"],
    )
    observed_at = 946684801.0
    store.record_action_result(
        mission_id, event_id="result-current", action_id="action-current",
        attempt_id="attempt-current", outcome="SUCCEEDED",
        result={"observed_at": observed_at, "source": "local_action_receipt"},
    )
    with sqlite3.connect(store.path) as connection:
        connection.execute(
            "UPDATE fleet_mission_events SET created_at=? "
            "WHERE event_source='device_action' AND source_event_id='result-current'",
            ("2000-01-01T00:00:00+00:00",),
        )
    service.goal_evidence_verifier = lambda _mission, _evidence: True
    evidence = {
        "predicate_id": "block-in-tray", "object_id": "block-1",
        "destination_id": "tray-1", "evidence_source": "camera_observation",
        "evidence_id": "camera:post-action-stale", "evidence_revision": "cal-4/tf-9",
        "producer_id": "registered-camera-evaluator", "observation_id": "obs-post-action",
        "observation_digest": "b" * 64, "evaluator_revision": "placement-check-v3",
        "action_id": "action-current", "attempt_id": "attempt-current",
        "gripper_state": "OPEN", "gripper_evidence_id": "gripper-readback-1",
        "gripper_evidence_revision": "gripper-driver-v2",
        "gripper_observed_at": observed_at + 0.1,
        "observed_at": observed_at + 0.1, "satisfied": True,
    }
    service.confirm_goal(
        mission_id, event_id="goal-evidence-stale", evidence=evidence,
        now=observed_at + 0.2, max_age_s=2.0,
    )

    progress = client.get(
        f"/api/fleet/missions/{mission_id}", headers=_OPERATOR,
    ).json()["progress"]
    assert progress["mission"]["state"] == "GOAL_CONFIRMED"
    assert progress["action"]["state"] == "ACTION_SUCCEEDED"
    assert progress["action"]["freshness"] == "STALE"
    assert progress["goal_evidence"]["state"] == "CONFIRMED"
    assert progress["goal_evidence"]["freshness"] == "STALE"


def test_event_cursor_ahead_requests_snapshot_restart_and_ownership_is_enforced(tmp_path):
    client, _, _ = _client(tmp_path)
    mission_id = _resolved_mission(client)
    ahead = client.get(
        f"/api/fleet/missions/{mission_id}/events?after_event_id=999999",
        headers=_OPERATOR,
    )
    hidden = client.get(
        f"/api/fleet/missions/{mission_id}/events?after_event_id=0",
        headers=_VIEWER,
    )

    assert ahead.status_code == 409
    assert ahead.json()["detail"]["code"] == "MISSION_CURSOR_RESET_REQUIRED"
    assert ahead.json()["detail"]["snapshot_restart_required"] is True
    assert ahead.json()["detail"]["snapshot"]["progress"]["snapshot_event_id"] < 999999
    assert hidden.status_code == 404


def test_pruned_cursor_returns_snapshot_restart_instead_of_partial_history(tmp_path):
    client, _, _ = _client(tmp_path)
    mission_id = _resolved_mission(client)
    store = client.app.state.mission_service.store
    with sqlite3.connect(store.path) as connection:
        connection.execute(
            "INSERT INTO fleet_mission_event_retention "
            "(mission_id, cursor_floor) VALUES (?, 1)", (mission_id,),
        )

    response = client.get(
        f"/api/fleet/missions/{mission_id}/events?after_event_id=0",
        headers=_OPERATOR,
    )

    assert response.status_code == 410
    assert response.json()["detail"]["code"] == "MISSION_CURSOR_EXPIRED"
    assert response.json()["detail"]["snapshot_restart_required"] is True
    assert response.json()["detail"]["snapshot"]["progress"]["snapshot_event_id"] >= 1


def test_snapshot_watermark_survives_pruning_the_entire_event_history(tmp_path):
    client, _, _ = _client(tmp_path)
    mission_id = _resolved_mission(client)
    store = client.app.state.mission_service.store
    with sqlite3.connect(store.path) as connection:
        last_id = connection.execute(
            "SELECT MAX(event_id) FROM fleet_mission_events WHERE mission_id=?",
            (mission_id,),
        ).fetchone()[0]
        connection.execute(
            "INSERT INTO fleet_mission_event_retention "
            "(mission_id, cursor_floor) VALUES (?, ?)", (mission_id, last_id),
        )
        connection.execute(
            "DELETE FROM fleet_mission_events WHERE mission_id=?", (mission_id,),
        )

    snapshot = client.get(
        f"/api/fleet/missions/{mission_id}", headers=_OPERATOR,
    ).json()["progress"]
    page = client.get(
        f"/api/fleet/missions/{mission_id}/events?after_event_id={last_id}",
        headers=_OPERATOR,
    )

    assert snapshot["snapshot_event_id"] == last_id
    assert page.status_code == 200
    assert page.json()["snapshot_event_id"] == last_id
    assert page.json()["events"] == []


def test_running_action_and_stop_request_do_not_claim_physical_completion(tmp_path):
    client, tasks, _ = _client(tmp_path)
    mission_id = _resolved_mission(client)
    mission = _admit_mission(client, tasks, mission_id)
    store = client.app.state.mission_service.store
    store.start_step(
        mission_id, action_id="action-current", attempt_id="attempt-current",
        expected_authority_epoch=mission["authority_epoch"],
        expected_generation=mission["dispatch_generation"],
    )
    running = client.get(
        f"/api/fleet/missions/{mission_id}", headers=_OPERATOR,
    ).json()["progress"]
    assert running["action"]["state"] == "RUNNING"
    assert running["action"]["freshness"] == "UNKNOWN"
    assert running["goal_evidence"]["state"] == "UNKNOWN"
    assert running["stop"]["state"] == "DISPATCH_ENABLED"
    assert running["stop"]["physical_state"] == "UNKNOWN"

    tasks.store.trip_stop_latch(actor_id="operator-1", reason="ESTOP_REQUESTED")
    latched = client.get(
        f"/api/fleet/missions/{mission_id}", headers=_OPERATOR,
    ).json()["progress"]
    assert latched["mission"]["state"] == "RUNNING"
    assert latched["action"]["state"] == "RUNNING"
    assert latched["goal_evidence"]["state"] == "UNKNOWN"
    assert latched["stop"]["state"] == "DISPATCH_BLOCKED"
    assert latched["stop"]["physical_state"] == "UNKNOWN"

    phase_time = "2026-10-01T12:00:00+00:00"
    store.record_action_phase_summaries(
        mission_id, action_id="action-current", attempt_id="attempt-current",
        authority_epoch=mission["authority_epoch"],
        dispatch_generation=mission["dispatch_generation"], phases=[
            {"phase_id": phase_id, "ordinal": ordinal, "state": "SUCCEEDED",
             "journal_event_id": ordinal + 1, "observed_at": phase_time}
            for ordinal, phase_id in enumerate(("approach", "grasp", "transfer", "release"))
        ],
    )

    store.record_action_result(
        mission_id, event_id="result-current", action_id="action-current",
        attempt_id="attempt-current", outcome="SUCCEEDED",
        result={"observed_at": time.time(), "source": "local_action_receipt"},
    )
    after = client.get(
        f"/api/fleet/missions/{mission_id}", headers=_OPERATOR,
    ).json()["progress"]

    assert after["mission"]["state"] == "ACTION_SUCCEEDED"
    assert after["action"]["state"] == "ACTION_SUCCEEDED"
    assert after["action"]["freshness"] == "FRESH"
    assert after["goal_evidence"]["state"] == "PENDING"
    assert after["active_phase"] is None
    assert [phase["state"] for phase in after["phases"]] == ["SUCCEEDED"] * 4
    assert after["stop"]["state"] == "DISPATCH_BLOCKED"
    assert after["stop"]["reason"] == "ESTOP_REQUESTED"
    assert after["stop"]["physical_state"] == "UNKNOWN"

    reopened = MissionProgressService(MissionStore(store.path)).snapshot(mission_id)
    assert reopened["progress"]["goal_evidence"]["state"] == "PENDING"
    assert [phase["state"] for phase in reopened["progress"]["phases"]] == ["SUCCEEDED"] * 4


def test_late_previous_attempt_event_cannot_replace_current_action_projection(tmp_path):
    client, tasks, _ = _client(tmp_path)
    mission_id = _resolved_mission(client)
    mission = _admit_mission(client, tasks, mission_id)
    store = client.app.state.mission_service.store
    store.start_step(
        mission_id, action_id="action-current", attempt_id="attempt-current",
        expected_authority_epoch=mission["authority_epoch"],
        expected_generation=mission["dispatch_generation"],
    )
    starting_snapshot = client.get(
        f"/api/fleet/missions/{mission_id}", headers=_OPERATOR,
    ).json()["progress"]
    with sqlite3.connect(store.path) as connection:
        connection.execute(
            "INSERT INTO fleet_mission_events "
            "(event_source, source_event_id, mission_id, step_id, action_id, attempt_id, "
            "state, event_type, actor_id, detail_json, created_at) "
            "VALUES ('device_action', 'late-old-attempt', ?, ?, 'action-old', 'attempt-old', "
            "'HOLD', 'ACTION_TERMINAL_RESULT', 'operator-1', '{\"outcome\":\"FAILED\"}', ?)",
            (mission_id, mission["step_id"], "2000-01-01T00:00:00+00:00"),
        )

    progress = client.get(
        f"/api/fleet/missions/{mission_id}", headers=_OPERATOR,
    ).json()["progress"]
    late_event = client.get(
        f"/api/fleet/missions/{mission_id}/events?"
        f"after_event_id={starting_snapshot['snapshot_event_id']}",
        headers=_OPERATOR,
    ).json()["events"][0]
    assert progress["action"]["state"] == "RUNNING"
    assert progress["action"]["revision"] == "attempt-current"
    assert late_event["attempt_id"] == "attempt-old"
    assert late_event["event_id"] > starting_snapshot["snapshot_event_id"]


def test_model_context_is_allowlisted_and_scoped_to_owner_and_workcell(tmp_path):
    client, _, _ = _client(tmp_path)
    mission_id = _resolved_mission(client)
    progress = client.app.state.mission_progress

    context = progress.model_context(
        mission_id, principal_id="operator-1", workcell_id="omx_01",
    )
    wrong_owner = progress.model_context(
        mission_id, principal_id="viewer-1", workcell_id="omx_01",
    )
    wrong_workcell = progress.model_context(
        mission_id, principal_id="operator-1", workcell_id="other-cell",
    )

    assert context["mission_id"] == mission_id
    assert context["mission_state"] == "PROPOSED"
    control = client.app.state.task_service.store.dispatch_control()
    assert context["stop_generation"] == control["generation"]
    assert context["authority_epoch"] == control["authority_epoch"]
    assert "history" not in context and "candidate" not in context
    assert "object_id" not in context and "image_sha256" not in context
    assert wrong_owner is None
    assert wrong_workcell is None


def test_progress_and_cursor_routes_publish_typed_openapi_contract(tmp_path):
    client, _, _ = _client(tmp_path)
    spec = client.app.openapi()

    snapshot = spec["paths"]["/api/fleet/missions/{mission_id}"]["get"]
    events = spec["paths"]["/api/fleet/missions/{mission_id}/events"]["get"]

    assert snapshot["responses"]["200"]["content"]["application/json"]["schema"]["$ref"].endswith(
        "/MissionProgressReadResponse"
    )
    assert events["responses"]["200"]["content"]["application/json"]["schema"]["$ref"].endswith(
        "/MissionProgressEventPage"
    )
    assert events["responses"]["409"]["content"]["application/json"]["schema"]["$ref"].endswith(
        "/MissionCursorResetError"
    )
    assert events["responses"]["410"]["content"]["application/json"]["schema"]["$ref"].endswith(
        "/MissionCursorExpiredError"
    )
    assert {param["name"] for param in events["parameters"]} == {
        "authorization", "mission_id", "after_event_id", "limit",
    }


def test_api_reference_pins_snapshot_cursor_retention_and_unknown_physical_state():
    root = Path(__file__).resolve().parents[3]
    reference = (root / "docs/reference/ROSY API & Protocol Reference.md").read_text(
        encoding="utf-8",
    )

    assert "**Version:** v1.156" in reference
    assert "## 10.14 Mission progress snapshots and event cursor" in reference
    assert "`/api/fleet/missions/{mission_id}/events?after_event_id=" in reference
    assert "MISSION_CURSOR_EXPIRED" in reference
    assert "MISSION_CURSOR_RESET_REQUIRED" in reference
    assert "physical_state: UNKNOWN" in reference
    assert "No percentage is returned" in reference
    assert "history_truncated" in reference
    assert "## 10.15 ER 2 Mission feedback tools and outbox (D-357/D-358)" in reference
    assert "atomic stop/candidate transaction" in reference
    assert "not implemented because candidate creation is unavailable" in reference
