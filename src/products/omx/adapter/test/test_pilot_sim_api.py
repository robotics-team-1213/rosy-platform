"""The Pilot HTTP boundary cannot bypass one simulated workcell owner."""

from pathlib import Path
import time

from fastapi.testclient import TestClient

from omx_adapter.pilot_sim_api import create_pilot_sim_app


ROOT = Path(__file__).resolve().parents[5]
PILOT = ROOT / "src" / "hmi" / "pilot"
COMMON = ROOT / "src" / "hmi" / "web_common"
PREFIX = "/api/v1/sim/omx"


class FakeRuntime:
    instance_id = "omx_01"
    joint_names = ("joint1", "joint2", "gripper_joint_1")
    gripper = "gripper_joint_1"
    calls = None

    def __init__(self):
        self.calls = []

    def snapshot(self):
        return {"sequence": 8, "positions": {name: 0.0 for name in self.joint_names},
                "owner_state": "ready", "camera": {"available": False}}

    def submit(self, jog):
        self.calls.append(jog)
        return {"command_id": jog.request_id, "state": "LOCAL_ACCEPTED"}

    def submit_gripper(self, goal):
        self.calls.append(goal)
        if goal.position > 1.1:
            return {"command_id": goal.request_id, "state": "REJECTED", "reason": "gripper_limit"}
        return {"command_id": goal.request_id, "state": "LOCAL_ACCEPTED"}

    def goal(self, command_id):
        return {"command_id": command_id, "state": "LOCAL_ACCEPTED"}

    def cancel(self, command_id):
        return {"command_id": command_id, "state": "CANCEL_REQUESTED"}

    def cancel_active(self):
        self.calls.append("cancel_active")

    def on_watchdog(self):
        pass

    def controls(self):
        return {"schema": "rosy.controls/1", "items": []}


class FakeCapture:
    def __init__(self):
        self.value = {"status": "idle", "frame_count": 0, "issues": []}

    def status(self):
        return self.value

    def start(self, task):
        self.value = {"episode_id": "11111111-1111-4111-8111-111111111111", "task": task,
                      "status": "recording", "frame_count": 0, "issues": []}
        return self.value

    def stop(self, episode_id, outcome):
        assert episode_id == self.value["episode_id"]
        self.value.update(status="incomplete", task_outcome=outcome, issues=["insufficient_frames"])
        return self.value

    def camera_status(self):
        return {"available": True, "fresh": False}

    def camera_jpeg(self):
        raise ValueError("camera stale")


def _client():
    runtime = FakeRuntime()
    app = create_pilot_sim_app(runtime=runtime, pilot_root=PILOT,
                               common_root=COMMON, pairing_code="ABCD-EFGH")
    return TestClient(app), runtime


def _paired(client):
    response = client.post(f"{PREFIX}/pair", json={"code": "ABCD-EFGH"})
    assert response.status_code == 201
    return {"Authorization": f"Bearer {response.json()['token']}"}


def _jog(seat_id, **changes):
    return {"instance_id": "omx_01", "seat_id": seat_id, "request_id": "req-1",
            "joint": "joint1", "delta_rad": 0.02, "duration_s": 0.4,
            "state_sequence": 8, "expires_at_ms": int(time.time() * 1000) + 1000, **changes}


def test_serves_pilot_and_only_allowlisted_assets():
    client, _ = _client()
    assert client.get("/pilot").status_code == 200
    assert client.get("/pilot/assets/app.js").status_code == 200
    assert client.get("/pilot/assets/screens/arm.js").status_code == 200
    for asset in ("controls.js", "arm-stick.js", "screens/compose.js", "widgets/joint_jog.js"):  # D-411 B
        assert client.get(f"/pilot/assets/{asset}").status_code == 200, asset
    assert client.get("/pilot/assets/secret.env").status_code == 404
    assert client.get("/common/tokens.css").status_code == 200
    assert client.get(f"{PREFIX}/target").json()["kind"] == "omx_sim"


def test_pairing_is_one_time_and_command_needs_active_seat():
    client, runtime = _client()
    assert client.post(f"{PREFIX}/goals", json=_jog("no-seat")).status_code == 401
    assert client.post(f"{PREFIX}/goals", json=_jog("no-seat")).json()["error"]["code"] == "UNAUTHORIZED"
    headers = _paired(client)
    assert client.post(f"{PREFIX}/pair", json={"code": "ABCD-EFGH"}).status_code == 403
    assert client.post(f"{PREFIX}/goals", headers=headers,
                       json=_jog("no-seat")).status_code == 409
    seat = client.post(f"{PREFIX}/seat", headers=headers).json()["seat_id"]
    jog = _jog(seat)
    accepted = client.post(f"{PREFIX}/goals", headers=headers, json=jog)
    assert accepted.status_code == 202
    assert accepted.json()["state"] == "LOCAL_ACCEPTED"
    assert len(runtime.calls) == 1
    assert client.post(f"{PREFIX}/goals", headers=headers, json=jog).status_code == 202
    assert len(runtime.calls) == 1
    conflict = client.post(f"{PREFIX}/goals", headers=headers,
                           json={**jog, "delta_rad": 0.03})
    assert conflict.status_code == 409


def test_seat_release_and_validation_fail_closed():
    client, runtime = _client()
    headers = _paired(client)
    seat = client.post(f"{PREFIX}/seat", headers=headers).json()["seat_id"]
    assert client.post(f"{PREFIX}/goals", headers=headers,
                       json={**_jog(seat), "instance_id": "wrong"}).status_code == 409
    assert client.post(f"{PREFIX}/goals", headers=headers,
                       json={**_jog(seat), "delta_rad": 2.0}).status_code == 400
    assert client.post(f"{PREFIX}/goals", headers=headers,
                       json={**_jog(seat), "expires_at_ms": int(time.time() * 1000) + 100000}).status_code == 409
    assert client.delete(f"{PREFIX}/seat/{seat}", headers=headers).status_code == 204
    assert client.post(f"{PREFIX}/goals", headers=headers, json=_jog(seat)).status_code == 409
    assert runtime.calls == ["cancel_active"]


def test_recording_needs_own_seat_and_cannot_select_server_output_path():
    client, runtime = _client()
    runtime.capture = FakeCapture()
    assert client.post(f"{PREFIX}/recordings", json={"seat_id": "bad", "task": "move"}).status_code == 401
    headers = _paired(client)
    assert client.get(f"{PREFIX}/camera", headers=headers).json()["fresh"] is False
    assert client.get(f"{PREFIX}/camera/frame", headers=headers).status_code == 409
    assert client.post(f"{PREFIX}/recordings", headers=headers,
                       json={"seat_id": "bad", "task": "move"}).status_code == 409
    seat = client.post(f"{PREFIX}/seat", headers=headers).json()["seat_id"]
    assert client.post(f"{PREFIX}/recordings", headers=headers,
                       json={"seat_id": seat, "task": "move", "root": "F:/source"}).status_code == 400
    started = client.post(f"{PREFIX}/recordings", headers=headers, json={"seat_id": seat, "task": "move"})
    assert started.status_code == 201
    episode_id = started.json()["episode_id"]
    assert client.get(f"{PREFIX}/recordings", headers=headers).json()["status"] == "recording"
    stopped = client.post(f"{PREFIX}/recordings/{episode_id}/stop", headers=headers,
                          json={"seat_id": seat, "outcome": "success"})
    assert stopped.json()["status"] == "incomplete"
    assert stopped.json()["task_outcome"] == "success"


def test_target_carries_the_runtime_controls():
    client, _ = _client()
    body = client.get(f"{PREFIX}/target").json()
    assert body["controls"] == {"schema": "rosy.controls/1", "items": []}
    assert body["joints"] == ["joint1", "joint2"] and body["gripper"] == "gripper_joint_1"


def test_target_serializes_every_control_kind_with_the_schema_alias():
    class Runtime(FakeRuntime):
        def controls(self):
            return {"schema": "rosy.controls/1", "items": [
                {"id": "arm", "kind": "joint_jog", "label": "팔", "max_step_rad": 0.05, "duration_s": 0.4,
                 "joints": [{"name": "joint1", "lower": -1.0, "upper": 1.0}]},
                {"id": "gripper", "kind": "gripper", "label": "그리퍼", "joint": "gripper_joint_1",
                 "closed": 0.0, "open": 1.0, "presets": {"open": 1.0, "half": 0.5, "close": 0.0}},
                {"id": "base", "kind": "base_velocity", "label": "주행", "max_linear": 0.1,
                 "max_angular": 0.5, "pivot": False, "fine": False}]}

    app = create_pilot_sim_app(runtime=Runtime(), pilot_root=PILOT, common_root=COMMON,
                               pairing_code="ABCD-EFGH")
    controls = TestClient(app).get(f"{PREFIX}/target").json()["controls"]
    assert controls["schema"] == "rosy.controls/1" and "schema_id" not in controls
    assert [item["kind"] for item in controls["items"]] == ["joint_jog", "gripper", "base_velocity"]
    assert controls["items"][0]["command"] == "bounded_goal"
    assert controls["items"][1]["readback"] == ["position", "grasp"]


def _grip(seat_id, **changes):
    return {"instance_id": "omx_01", "seat_id": seat_id, "request_id": "grip-1", "position": 0.5,
            "duration_s": 0.8, "state_sequence": 8, "expires_at_ms": int(time.time() * 1000) + 1000, **changes}


def _seated():
    client, runtime = _client()
    token = client.post(f"{PREFIX}/pair", json={"code": "ABCD-EFGH"}).json()["token"]
    headers = {"Authorization": f"Bearer {token}"}
    seat = client.post(f"{PREFIX}/seat", headers=headers).json()["seat_id"]
    return client, runtime, headers, seat


def test_gripper_goal_needs_the_seat_and_is_idempotent():
    client, runtime, headers, seat = _seated()
    assert client.post(f"{PREFIX}/gripper", json=_grip(seat)).status_code == 401
    assert client.post(f"{PREFIX}/gripper", json=_grip("other"), headers=headers).status_code == 409
    body = _grip(seat)
    first = client.post(f"{PREFIX}/gripper", json=body, headers=headers)
    again = client.post(f"{PREFIX}/gripper", json=body, headers=headers)
    assert first.status_code == again.status_code == 202 and first.json() == again.json()
    assert len(runtime.calls) == 1 and runtime.calls[0].position == 0.5
    assert client.post(f"{PREFIX}/gripper", json=_grip(seat, position=0.1), headers=headers).status_code == 409
    assert client.get(f"{PREFIX}/goals/grip-1", headers=headers).json()["state"] == "LOCAL_ACCEPTED"


def test_gripper_and_jog_share_request_ids():
    client, _, headers, seat = _seated()
    assert client.post(f"{PREFIX}/goals", json=_jog(seat, request_id="same"), headers=headers).status_code == 202
    reused = client.post(f"{PREFIX}/gripper", json=_grip(seat, request_id="same"), headers=headers)
    assert reused.status_code == 409 and reused.json()["error"]["message"] == "request id reused"


def test_gripper_limit_rejection_is_a_conflict():
    client, _, headers, seat = _seated()
    response = client.post(f"{PREFIX}/gripper", json=_grip(seat, position=2.0), headers=headers)
    assert response.status_code == 409 and response.json()["error"]["message"] == "gripper_limit"


def test_gripper_duration_out_of_range_is_validation_error():
    client, _, headers, seat = _seated()
    for duration in (0.1, 3.0):
        response = client.post(f"{PREFIX}/gripper", json=_grip(seat, duration_s=duration), headers=headers)
        assert response.status_code == 400 and response.json()["error"]["code"] == "VALIDATION_ERROR"
