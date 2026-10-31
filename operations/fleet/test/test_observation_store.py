import asyncio
import json
import sqlite3

import pytest
from fastapi.testclient import TestClient

from fleet.server.core_event_store import EventRejected
from fleet.server.observation_store import ObservationStore
from fleet.server.app import create_app
from fleet.server.task_service import FleetTaskService
from fleet.server.task_store import FleetTaskStore
from test_stuck_resolver_loop import _setup


def sample():
    return {"robot_id": "rosy_01", "online": True, "gather_source": "hub", "_state_mono": 8.0,
            "state": {"ts": "2026-10-12T00:00:00Z", "battery": {"voltage": 7.4}, "pose": None}}


def test_observations_preserve_values_time_quality_and_bound_retention(tmp_path):
    store = ObservationStore(tmp_path / "fleet.sqlite3", max_rows=2, retention_s=5)
    for received in (10, 11, 12):
        store.append_snapshot([sample()], received_at=received, monotonic_now=10)
    rows = store.read_observations(limit=1)
    assert len(rows) == 2
    body = rows[0]["observation"]
    assert body["state"]["battery"]["voltage"] == 7.4
    assert body["observed_at"] == 9 and body["state_age_s"] == 2
    assert body["verification"] == "observed_not_labeled"
    store.append_snapshot([{**sample(), "online": False, "state": None}], received_at=20, monotonic_now=20)
    rows = store.read_observations()
    assert len(rows) == 1 and rows[0]["observation"]["online"] is False
    assert rows[0]["observation"]["state"] is None


def test_row_cap_keeps_the_newest_rows_across_multi_robot_snapshots(tmp_path):
    store = ObservationStore(tmp_path / "fleet.sqlite3", max_rows=3)
    for received in (10, 11, 12):
        store.append_snapshot([sample(), {**sample(), "robot_id": "rosy_02"}],
                              received_at=received, monotonic_now=10)
    rows = store.read_observations()
    assert [(r["observation_id"], r["robot_id"]) for r in rows] == [
        (4, "rosy_02"), (5, "rosy_01"), (6, "rosy_02")]


def test_secret_nonfinite_and_large_payloads_cannot_enter_training_source(tmp_path):
    store = ObservationStore(tmp_path / "fleet.sqlite3")
    for bad in ({"access_" + "token": "secret"}, {"value": float("nan")}, {"image": "x" * 70000}):
        with pytest.raises(EventRejected):
            store.append_snapshot([{**sample(), "state": bad}], received_at=10, monotonic_now=10)
    assert store.read_observations() == []


def test_shared_gather_captures_once_per_real_read_and_surfaces_storage_failure(tmp_path):
    loop, _board, _robot = _setup()
    gather = loop._snapshot
    gather.max_age_s = 10
    gather.observations = ObservationStore(tmp_path / "fleet.sqlite3")
    asyncio.run(gather())
    asyncio.run(gather())
    assert len(gather.observations.read_observations()) == 1
    gather.max_age_s = 0
    gather.observations.append_snapshot = lambda *_args, **_kw: (_ for _ in ()).throw(OSError("disk full"))
    assert asyncio.run(gather())["robots"]
    assert gather.recording_status["state"] == "error"


def test_observation_route_uses_existing_read_guard_and_robot_cursor(tmp_path):
    loop, _board, _robot = _setup()
    tasks = FleetTaskService(FleetTaskStore(tmp_path / "fleet.sqlite3"), robot_ids={"rosy_01"})
    app = create_app(loop._snapshot._console, console_token="test-operator", task_service=tasks)
    client = TestClient(app)
    assert client.get("/api/fleet/observations").status_code == 401
    asyncio.run(app.state.fleet_gather())
    reply = client.get("/api/fleet/observations?robot_id=rosy_01&limit=1",
                       headers={"Authorization": "Bearer test-operator"})
    assert reply.status_code == 200 and len(reply.json()["observations"]) == 1


def test_offline_learning_export_preserves_hashes_and_has_no_automatic_labels(tmp_path):
    from pathlib import Path
    import importlib.util
    source = Path(__file__).resolve().parents[3] / "learning/curation/pinky/fleet_observations.py"
    spec = importlib.util.spec_from_file_location("fleet_observations", source)
    exporter = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(exporter)
    store = ObservationStore(tmp_path / "fleet.sqlite3")
    store.append_snapshot([sample()], received_at=10, monotonic_now=10)
    manifest = exporter.export(store.path, tmp_path / "training-source")
    assert manifest["train_eligible"] is False and manifest["labels"] is None
    raw = (tmp_path / "training-source/observations.jsonl").read_bytes()
    import hashlib
    assert manifest["sha256"] == hashlib.sha256(raw).hexdigest()
    assert json.loads(raw)["observation"]["state"]["battery"]["voltage"] == 7.4
    with pytest.raises(FileExistsError):
        exporter.export(store.path, tmp_path / "training-source")
    (tmp_path / "training-source/observations.jsonl").write_bytes(raw.replace(b"7.4", b"8.4"))
    with pytest.raises(ValueError, match="changed"):
        exporter.verify(tmp_path / "training-source")
    for index, bad in enumerate(({"nested": [{"api_key": "hidden"}]},
                                 {"private": "-----BEGIN " + "PRIVATE KEY-----"})):
        body = store.read_observations()[0]["observation"]
        body["state"] = bad
        with sqlite3.connect(store.path) as connection:
            connection.execute("UPDATE fleet_observations SET payload_json=?",
                               (json.dumps(body, ensure_ascii=False, separators=(",", ":")),))
        with pytest.raises(ValueError, match="validation"):
            exporter.export(store.path, tmp_path / f"unsafe-{index}")
        assert not (tmp_path / f"unsafe-{index}/manifest.json").exists()
