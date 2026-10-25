"""Fleet viewer reads and source-scoped bounded observation ingestion."""
from fastapi import FastAPI, Header, HTTPException
from fastapi.testclient import TestClient
from hashlib import sha256
import pytest

from core_common.protocol.workcell_observations import WorkcellObservationManifest
from fleet.server.workcell_observations import WorkcellObservations
from fleet.server.workcell_observation_routes import install_workcell_observation_routes


def viewer(authorization: str | None = Header(None)):
    if authorization != "Bearer viewer-secret":
        raise HTTPException(401, "viewer credential required")


def client_for(service):
    app = FastAPI()
    install_workcell_observation_routes(app, service=service, require_viewer=viewer)
    return TestClient(app)


@pytest.fixture
def client():
    manifest = WorkcellObservationManifest.model_validate({"schema": "rosy.workcell-observations/1", "workcells": [{
        "workcell_id": "example", "label": "Example", "arms": [
            {"source_id": f"feedback_{side}", "arm_id": f"arm_{side}", "label": f"Arm {side}",
             "board_id": f"EXAMPLE-BOARD-{side}", "joint_topic": f"/omx_commissioning/arm_{side}/joint_states",
             "joint_names": ["joint1"], "token_env": f"EXAMPLE_{side.upper()}",
             "credential_sha256": sha256(f"{side}-secret".encode()).hexdigest()} for side in ("a", "b")],
        "cameras": [{"source_id": "top", "label": "Top", "role": "overhead", "arm_id": None,
                     "image_topic": "/top_camera/image_raw", "device_path": "/dev/v4l/by-path/example-top",
                     "token_env": "EXAMPLE_TOP", "credential_sha256": sha256(b"top-secret").hexdigest()}]}]})
    return client_for(WorkcellObservations(manifest, {"feedback_a": "a-secret", "feedback_b": "b-secret"},
                                         wall=lambda: 100.0, monotonic=lambda: 10.0))


PATH = "/api/fleet/workcell-observations"
VIEWER = {"Authorization": "Bearer viewer-secret"}
PRODUCER = {"X-Workcell-Observation-Token": "a-secret"}
PAYLOAD = {"epoch": "a" * 32, "sequence": 1, "captured_at": 100, "positions": {"joint1": 0.25}}


def test_read_requires_viewer_and_disables_caching(client):
    assert client.get(PATH).status_code == 401
    assert client.get(PATH, headers=PRODUCER).status_code == 401
    response = client.get(PATH, headers=VIEWER)
    assert response.status_code == 200
    assert response.headers["Cache-Control"] == "no-store"
    assert response.json()["read_only"] is True
    assert response.json()["workcells"][0]["arms"][0]["positions"] is None
    assert "EXAMPLE-BOARD" not in response.text and "a-secret" not in response.text
    assert "credential_sha256" not in response.text and sha256(b"top-secret").hexdigest() not in response.text


def test_source_token_cannot_write_another_arm_and_payload_is_strict(client):
    path = PATH + "/arms/feedback_a"
    assert client.post(path, headers=VIEWER, json=PAYLOAD).status_code == 401
    assert client.post(PATH + "/arms/feedback_b", headers=PRODUCER, json=PAYLOAD).status_code == 401
    assert client.post(PATH + "/arms/unknown", headers=PRODUCER, json=PAYLOAD).status_code == 401
    for changed in ({**PAYLOAD, "captured_at": True}, {**PAYLOAD, "workcell_id": "another"}):
        assert client.post(path, headers=PRODUCER, json=changed).status_code == 422
    assert client.get(PATH, headers=VIEWER).json()["workcells"][0]["arms"][0]["sequence"] == 0


def test_unauthorized_stream_is_rejected_without_consuming_body(client):
    consumed = []

    def body():
        consumed.append(True)
        yield b" " * 20000

    response = client.post(PATH + "/arms/feedback_a", headers=VIEWER, content=body())
    assert response.status_code == 401
    assert consumed == []


@pytest.mark.parametrize("declared_length", [None, "1"])
def test_actual_stream_limit_applies_without_or_despite_content_length(client, declared_length):
    headers = {**PRODUCER, "Content-Type": "application/json"}
    if declared_length is not None:
        headers["Content-Length"] = declared_length

    def body():
        yield b"{" + b" " * 8191
        yield b" " * 8193 + b"}"

    response = client.post(PATH + "/arms/feedback_a", headers=headers, content=body())
    assert response.status_code == 413
    assert client.get(PATH, headers=VIEWER).json()["workcells"][0]["arms"][0]["sequence"] == 0


def test_replay_conflict_preserves_the_accepted_snapshot(client):
    path = PATH + "/arms/feedback_a"
    response = client.post(path, headers=PRODUCER, json=PAYLOAD)
    assert response.status_code == 202 and response.json() == {"accepted": True}
    before = client.get(PATH, headers=VIEWER).json()
    assert before["workcells"][0]["arms"][0]["positions"] == {"joint1": 0.25}
    assert client.post(path, headers=PRODUCER, json={**PAYLOAD, "positions": {"joint1": 9}}).status_code == 409
    assert client.get(PATH, headers=VIEWER).json() == before


def test_unconfigured_observations_report_unavailable():
    client = client_for(None)
    assert client.get(PATH, headers=VIEWER).status_code == 503
    assert client.post(PATH + "/arms/feedback_a", headers=VIEWER, json=PAYLOAD).status_code == 401
    assert client.post(PATH + "/arms/feedback_a", json=PAYLOAD).status_code == 401
    assert client.post(PATH + "/arms/feedback_a", headers=PRODUCER, json=PAYLOAD).status_code == 503
