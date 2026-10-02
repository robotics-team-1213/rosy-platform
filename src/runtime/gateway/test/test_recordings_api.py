"""D-411 A: CORE recording control, download gate and teleop intent evidence."""

import hashlib
import io
import json
import tarfile

import pytest

OPERATOR = {"Authorization": "Bearer rosy-dev-operator"}
VIEWER = {"Authorization": "Bearer rosy-dev-viewer"}
ADMIN = {"Authorization": "Bearer rosy-dev-admin"}


def test_teleop_rejected_before_the_manager_is_still_evidence(core_client):
    client, svc = core_client()
    seen = []
    svc.command.intent_sink = lambda **fields: seen.append(fields)
    svc.capability._data["teleop"] = False
    response = client.post("/api/v1/teleop", json={"linear": 0.1, "angular": 0.0}, headers=OPERATOR)
    assert response.status_code == 501
    assert seen and seen[0]["accepted"] is False and seen[0]["code"] == "CAPABILITY_NOT_SUPPORTED"

RID ="20261002T101500Z_rosy_01"


def _status(state="idle", rid=None, reason=""):
    return {"schema": "rosy.pilot.recording.status/1", "state": state, "id": rid, "elapsed_s": 0.0,
            "bytes": 0, "max_duration_s": 600, "quota_free_bytes": 1000, "last_stop_reason": reason}


def _wire(svc, *, ok=True, code="RECORDING_QUOTA_FULL"):
    calls = []

    def request(on, wait):
        calls.append((on, wait))
        state = ("recording", RID) if on else ("stopping", RID)
        return ok, json.dumps({"code": "" if ok else code, "status": _status(*state)})

    svc.pilot_recording.request_active = request
    sent = []
    svc.pilot_recording.publish_fetched = sent.append
    svc.pilot_recording.on_status(_status())
    return calls, sent


def _recording(root):
    folder = root / RID
    (folder / "bag").mkdir(parents=True)
    (folder / "bag" / "bag_0.mcap").write_bytes(b"m" * 600)
    (folder / "session.json").write_text(json.dumps({"mode": "pilot", "started_at": "2026-10-02T10:15:00Z",
                                                    "ended_at": "2026-10-02T10:16:00Z", "topics": []}))
    files = [{"path": p, "bytes": (folder / p).stat().st_size,
              "sha256": hashlib.sha256((folder / p).read_bytes()).hexdigest()}
             for p in ("bag/bag_0.mcap", "session.json")]
    (folder / "manifest.json").write_text(json.dumps({
        "schema": "rosy.pilot.recording.manifest/1", "id": RID, "started_at": "2026-10-02T10:15:00Z",
        "ended_at": "2026-10-02T10:16:00Z", "duration_s": 60.0, "topics": [], "stop_reason": "requested",
        "files": files}))


@pytest.fixture
def rec_client(core_client, tmp_path):
    client, svc = core_client(config_overrides={"recording": {"pilot_root": str(tmp_path / "rec")}})
    (tmp_path / "rec").mkdir()
    # Frozen evidence clock: a velocity set by the test stays fresh however slow the host is.
    svc.state._clock = lambda: 1_790_000_000.0
    return client, svc, tmp_path / "rec"


def test_a_download_aborts_when_manual_input_starts_mid_stream(rec_client, monkeypatch):
    from core_api_web.api.v1 import recordings
    client, svc, root = rec_client
    _, sent = _wire(svc)
    _recording(root)
    svc.state.set_velocity(0.0, 0.0)
    assert client.post("/api/v1/mode", json={"mode": "MANUAL"}, headers=OPERATOR).status_code == 200
    real = recordings.iter_archive

    def driven(members, *args, **kwargs):
        for index, block in enumerate(real(members, *args, **kwargs)):
            if index == 1:
                assert svc.command.teleop(0.1, 0.0) == (True, "")   # the stick moves mid-download
            yield block

    monkeypatch.setattr(recordings, "iter_archive", driven)
    response = client.get(f"/api/v1/recordings/{RID}/archive", headers=OPERATOR)
    assert len(response.content) < int(response.headers["content-length"])
    assert sent == []                            # an aborted download is never "fetched"
    # The aborted stream gave its slot back: the retry from zero is served in full.
    monkeypatch.undo()
    svc.command.clear_manual()
    again = client.get(f"/api/v1/recordings/{RID}/archive", headers=OPERATOR)
    assert again.status_code == 200 and len(again.content) == int(again.headers["content-length"])
    assert sent == [RID]


def test_the_download_slot_is_released_by_the_response_itself():
    # Version-independent: the slot is freed around the response's own __call__, even
    # when sending fails before the stream generator ever runs (client already gone).
    import asyncio
    from core_api_web.api.v1 import recordings
    released, started = [], []

    def body():
        started.append(1)
        yield b"x"

    async def receive():
        return {"type": "http.disconnect"}

    async def send(_message):
        raise OSError("client gone")

    response = recordings._SlotResponse(body(), release=lambda: released.append(1),
                                        media_type="application/x-tar")
    with pytest.raises(OSError):
        asyncio.run(response({"type": "http", "asgi": {"spec_version": "2.3"}}, receive, send))
    assert released == [1] and started == []


def test_a_download_that_fails_mid_stream_is_not_fetched(rec_client, monkeypatch):
    from core_api_web.api.v1 import recordings
    client, svc, root = rec_client
    _, sent = _wire(svc)
    _recording(root)
    svc.state.set_velocity(0.0, 0.0)
    real = recordings.iter_archive

    def failing(members, *args, **kwargs):
        stream = real(members, *args, **kwargs)
        yield next(stream)
        raise OSError("bag_0.mcap was replaced while streaming")

    monkeypatch.setattr(recordings, "iter_archive", failing)
    response = client.get(f"/api/v1/recordings/{RID}/archive", headers=OPERATOR)
    assert len(response.content) < int(response.headers["content-length"])
    assert sent == []
    monkeypatch.undo()
    assert client.get(f"/api/v1/recordings/{RID}/archive", headers=OPERATOR).status_code == 200


def test_only_one_download_at_a_time(rec_client):
    from core_api_web.api.v1 import recordings
    client, svc, root = rec_client
    _wire(svc)
    _recording(root)
    svc.state.set_velocity(0.0, 0.0)
    assert recordings._DOWNLOADS.acquire(blocking=False)
    try:
        response = client.get(f"/api/v1/recordings/{RID}/archive", headers=OPERATOR)
        assert response.status_code == 409 and response.json()["error"]["code"] == "RECORDING_BUSY"
    finally:
        recordings._DOWNLOADS.release()
    assert client.get(f"/api/v1/recordings/{RID}/archive", headers=OPERATOR).status_code == 200
    # Released after each download, finished or not.
    assert client.get(f"/api/v1/recordings/{RID}/archive", headers=OPERATOR).status_code == 200


def test_download_refused_while_docking_or_line_following(rec_client, monkeypatch):
    client, svc, root = rec_client
    _wire(svc)
    _recording(root)
    svc.state.set_velocity(0.0, 0.0)
    from core_api_web.api.deps import Mode
    assert svc.modes.transition(Mode.DOCKING)[0]
    response = client.get(f"/api/v1/recordings/{RID}/archive", headers=OPERATOR)
    assert response.json()["error"]["code"] == "ROBOT_MOVING"
    assert svc.modes.transition(Mode.IDLE)[0]
    assert client.get(f"/api/v1/recordings/{RID}/archive", headers=OPERATOR).status_code == 200
    monkeypatch.setattr(type(svc.line_follow), "active", property(lambda self: True))
    response = client.get(f"/api/v1/recordings/{RID}/archive", headers=OPERATOR)
    assert response.json()["error"]["code"] == "ROBOT_MOVING"


def test_a_failing_recording_hook_never_refuses_an_accepted_teleop(rec_client):
    client, svc, _ = rec_client

    def boom(_token):
        raise RuntimeError("guard broke")

    svc.pilot_recording.on_teleop = boom
    svc.state.set_velocity(0.0, 0.0)     # odometry evidence keeps teleop available
    assert client.post("/api/v1/mode", json={"mode": "MANUAL"}, headers=OPERATOR).status_code == 200
    assert client.post("/api/v1/teleop", json={"linear": 0.05}, headers=OPERATOR).status_code == 200
    assert svc.pilot_recording.hook_errors == 1


def test_start_and_stop_go_through_the_recorder(rec_client):
    client, svc, _ = rec_client
    calls, _ = _wire(svc)
    assert client.post("/api/v1/recordings", headers=VIEWER).status_code == 403
    started = client.post("/api/v1/recordings", headers=OPERATOR)
    assert started.status_code == 201 and started.json()["state"] == "recording"
    assert client.post("/api/v1/recordings", headers=OPERATOR).json()["error"]["code"] == "RECORDING_BUSY"
    active = client.get("/api/v1/recordings/active", headers=OPERATOR).json()
    assert active["owned"] is True and active["active"]["id"] == RID
    stopped = client.post("/api/v1/recordings/active/stop", headers=OPERATOR)
    assert stopped.status_code == 200 and calls == [(True, True), (False, True)]


def test_only_the_starting_token_or_an_admin_stops(rec_client):
    client, svc, _ = rec_client
    _wire(svc)
    client.post("/api/v1/recordings", headers=ADMIN)
    response = client.post("/api/v1/recordings/active/stop", headers=OPERATOR)
    assert response.status_code == 403 and response.json()["error"]["code"] == "FORBIDDEN"


@pytest.mark.parametrize("code", ["RECORDING_QUOTA_FULL", "RECORDING_DISK_FULL"])
def test_storage_refusal_is_507(rec_client, code):
    client, svc, _ = rec_client
    _wire(svc, ok=False, code=code)
    response = client.post("/api/v1/recordings", headers=OPERATOR)
    assert response.status_code == 507 and response.json()["error"]["code"] == code


def test_unwired_recorder_is_503(rec_client):
    client, _, _ = rec_client
    response = client.post("/api/v1/recordings", headers=OPERATOR)
    assert response.status_code == 503 and response.json()["error"]["code"] == "RECORDER_UNAVAILABLE"


def test_list_and_download_when_stopped(rec_client):
    client, svc, root = rec_client
    _, sent = _wire(svc)
    _recording(root)
    svc.state.set_velocity(0.0, 0.0)
    listing = client.get("/api/v1/recordings", headers=VIEWER).json()
    assert listing["download_allowed"] is True and listing["items"][0]["id"] == RID
    assert client.get(f"/api/v1/recordings/{RID}/archive", headers=VIEWER).status_code == 403
    response = client.get(f"/api/v1/recordings/{RID}/archive", headers=OPERATOR)
    assert response.status_code == 200 and response.headers["content-type"] == "application/x-tar"
    assert int(response.headers["content-length"]) == len(response.content)
    with tarfile.open(fileobj=io.BytesIO(response.content), mode="r:") as archive:
        assert f"{RID}/bag/bag_0.mcap" in archive.getnames()
    assert sent == [RID]


def test_download_refused_while_recording(rec_client):
    client, svc, root = rec_client
    _wire(svc)
    _recording(root)
    svc.state.set_velocity(0.0, 0.0)
    client.post("/api/v1/recordings", headers=OPERATOR)
    response = client.get(f"/api/v1/recordings/{RID}/archive", headers=OPERATOR)
    assert response.status_code == 409 and response.json()["error"]["code"] == "RECORDING_BUSY"


def test_download_refused_while_the_manifest_is_hashing(rec_client):
    client, svc, root = rec_client
    _wire(svc)
    _recording(root)
    svc.state.set_velocity(0.0, 0.0)
    svc.pilot_recording.on_status(_status("stopping", "20261002T111500Z_rosy_01"))
    response = client.get(f"/api/v1/recordings/{RID}/archive", headers=OPERATOR)
    assert response.json()["error"]["code"] == "RECORDING_BUSY"


def test_download_refused_while_moving(rec_client):
    client, svc, root = rec_client
    _wire(svc)
    _recording(root)
    svc.state.set_velocity(0.2, 0.0)
    response = client.get(f"/api/v1/recordings/{RID}/archive", headers=OPERATOR)
    assert response.status_code == 409 and response.json()["error"]["code"] == "ROBOT_MOVING"
    svc.state.set_velocity(0.0, 0.0)
    assert client.post("/api/v1/mode", json={"mode": "MANUAL"}, headers=OPERATOR).status_code == 200
    assert client.post("/api/v1/teleop", json={"linear": 0.1}, headers=OPERATOR).status_code == 200
    response = client.get(f"/api/v1/recordings/{RID}/archive", headers=OPERATOR)
    assert response.json()["error"]["code"] == "ROBOT_MOVING"
    svc.command.clear_manual()
    # MANUAL mode itself is fine: a Pilot that let go of the stick downloads in place.
    assert client.get(f"/api/v1/recordings/{RID}/archive", headers=OPERATOR).status_code == 200


def test_download_refused_in_navigation(rec_client):
    client, svc, root = rec_client
    _wire(svc)
    _recording(root)
    svc.state.set_velocity(0.0, 0.0)
    from core_api_web.api.deps import Mode
    svc.modes.transition(Mode.NAVIGATION)
    response = client.get(f"/api/v1/recordings/{RID}/archive", headers=OPERATOR)
    assert response.json()["error"]["code"] == "ROBOT_MOVING"


def test_unknown_or_traversal_ids_are_not_found(rec_client):
    client, svc, _ = rec_client
    _wire(svc)
    svc.state.set_velocity(0.0, 0.0)
    for rid in ("20261002T101500Z_missing", "..%2F..%2Fetc"):
        response = client.get(f"/api/v1/recordings/{rid}/archive", headers=OPERATOR)
        assert response.status_code == 404
        assert response.json()["error"]["code"] == "RECORDING_NOT_FOUND"


def test_ws_state_link_feeds_the_guard(rec_client):
    client, svc, _ = rec_client
    with client.websocket_connect("/ws/state?token=rosy-dev-operator") as socket:
        socket.receive_json()
        assert sum(svc.pilot_recording._links.values()) == 1
    assert sum(svc.pilot_recording._links.values()) == 0


def test_another_tokens_teleop_stops_the_recording(rec_client):
    client, svc, _ = rec_client
    calls, _ = _wire(svc)
    svc.state.set_velocity(0.0, 0.0)
    client.post("/api/v1/mode", json={"mode": "MANUAL"}, headers=OPERATOR)
    client.post("/api/v1/recordings", headers=OPERATOR)
    client.post("/api/v1/teleop", json={"linear": 0.05}, headers=OPERATOR)
    assert calls[-1] == (True, True)
    client.post("/api/v1/teleop", json={"linear": 0.05}, headers=ADMIN)
    assert calls[-1] == (False, False)
