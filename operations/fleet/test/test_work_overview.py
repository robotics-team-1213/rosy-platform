"""Mixed-ledger read API: owner scope, bounded data and no execution side effects."""

import pytest

from test_mission_api import _client, _create, _resolve


def _headers(token="operator-secret"):
    return {"Authorization": f"Bearer {token}"}


def _task(tasks, identity):
    return tasks.store.create_task(task_id=identity, robot_id="rosy_01", task_type="navigate",
                                   source="console", actor_id="operator-1", request_key=identity,
                                   request={"x": 1, "y": 2}, evidence=None)


def test_work_list_preserves_colliding_ids_and_owner_scope_without_dispatch(tmp_path):
    client, tasks, _ = _client(tmp_path)
    created = _create(client)
    assert created.status_code == 200
    identity = created.json()["proposal"]["proposal_id"]
    resolved = _resolve(client, identity)
    assert resolved.status_code == 200
    _task(tasks, identity)
    original = client.get(f"/api/fleet/missions/{identity}", headers=_headers()).json()
    result = client.get("/api/fleet/work", headers=_headers())
    assert result.status_code == 200
    rows = result.json()["rows"]
    assert {(r["source"], r["source_id"]) for r in rows} == {("task", identity), ("mission", identity)}
    assert next(r for r in rows if r["source"] == "mission")["status"] == original["mission"]["status"]
    assert next(r for r in rows if r["source"] == "mission")["workcell_id"] == "omx_01"
    assert "candidate" not in result.text and "plan" not in result.text and "operator-secret" not in result.text
    viewer = client.get("/api/fleet/work", headers=_headers("viewer-secret"))
    assert viewer.status_code == 200
    assert [r["source"] for r in viewer.json()["rows"]] == ["task"]
    after = client.get(f"/api/fleet/missions/{identity}", headers=_headers()).json()
    assert after["mission"] == original["mission"] and after["history"] == original["history"]


def test_work_limit_and_authentication(tmp_path):
    client, tasks, _ = _client(tmp_path)
    for index in range(4):
        _task(tasks, str(index))
    assert client.get("/api/fleet/work").status_code == 401
    response = client.get("/api/fleet/work?limit=2", headers=_headers("viewer-secret")).json()
    assert len(response["rows"]) == 2
    assert response["truncated_sources"] == ["task"]
    for invalid in (0, 101, "x"):
        assert client.get(f"/api/fleet/work?limit={invalid}", headers=_headers()).status_code == 422


@pytest.mark.parametrize("limit", [0, 102])
def test_store_summary_limits_are_bounded(tmp_path, limit):
    client, tasks, _ = _client(tmp_path)
    with pytest.raises(ValueError):
        tasks.store.work_summaries(limit=limit)
    with pytest.raises(ValueError):
        client.app.state.mission_service.store.work_summaries(principal_id="operator-1", limit=limit)
