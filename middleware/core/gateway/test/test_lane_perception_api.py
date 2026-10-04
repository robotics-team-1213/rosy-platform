"""Authentication, closed input schema and truthful Host Agent failure relay."""
from core_api_web.api.host_agent_client import AgentReply
from core_features.command.arbitration import Mode
from threading import Event, Thread
import json
import time

VIEWER = {"Authorization": "Bearer rosy-dev-viewer"}
OPERATOR = {"Authorization": "Bearer rosy-dev-operator"}
ADMIN = {"Authorization": "Bearer rosy-dev-admin"}


class Agent:
    def __init__(self, reply):
        self.reply, self.calls = reply, []

    def request(self, command, **kwargs):
        self.calls.append((command, kwargs))
        return self.reply


def test_selection_admin_only_and_no_arbitrary_inputs(core_client, monkeypatch):
    client, svc = core_client()
    agent = Agent(AgentReply(True, "OK", data={"paint_source": "learned", "applied": True}))
    monkeypatch.setattr("core_api_web.api.v1.host._agent", lambda _: agent)
    assert client.get("/api/v1/line-follow/perception", headers=VIEWER).status_code == 200
    for auth in (VIEWER, OPERATOR):
        assert client.put("/api/v1/line-follow/perception", headers=auth,
                          json={"paint_source": "learned"}).status_code == 403
    assert client.put("/api/v1/line-follow/perception", headers=ADMIN,
                      json={"paint_source": "learned", "path": "/tmp/model"}).status_code == 400
    assert client.put("/api/v1/line-follow/perception", headers=ADMIN,
                      json={"paint_source": "unknown"}).status_code == 400
    assert client.put("/api/v1/line-follow/perception", headers=ADMIN,
                      json={"paint_source": "learned"}).status_code == 200
    assert agent.calls[-1][1]["params"] == {"paint_source": "learned"}


def test_running_robot_never_sends_host_mutation(core_client, monkeypatch):
    client, svc = core_client()
    agent = Agent(AgentReply(True, "OK", data={}))
    monkeypatch.setattr("core_api_web.api.v1.host._agent", lambda _: agent)
    svc.modes.transition(Mode.MANUAL)
    assert client.put("/api/v1/line-follow/perception", headers=ADMIN,
                      json={"paint_source": "denoise"}).status_code == 409
    assert not agent.calls


def test_host_refusal_does_not_return_selection_success(core_client, monkeypatch):
    client, svc = core_client()
    agent = Agent(AgentReply(False, "HOST_AGENT_COMMAND_FAILED", detail="moving"))
    monkeypatch.setattr("core_api_web.api.v1.host._agent", lambda _: agent)
    result = client.put("/api/v1/line-follow/perception", headers=ADMIN,
                        json={"paint_source": "learned"})
    assert result.status_code == 409
    assert result.json()["error"]["code"] == "HOST_AGENT_COMMAND_FAILED"
    assert not svc.modes.motion_reserved


def test_motion_starts_refused_until_host_apply_finishes(core_client, monkeypatch):
    client, svc = core_client()
    entered, finish = Event(), Event()

    class WaitingAgent(Agent):
        def request(self, command, **kwargs):
            entered.set()
            assert finish.wait(5)
            return self.reply

    agent = WaitingAgent(AgentReply(True, "OK", data={"paint_source": "learned", "applied": True}))
    monkeypatch.setattr("core_api_web.api.v1.host._agent", lambda _: agent)
    replies = []
    worker = Thread(target=lambda: replies.append(client.put(
        "/api/v1/line-follow/perception", headers=ADMIN, json={"paint_source": "learned"})))
    worker.start()
    assert entered.wait(5)
    try:
        for path, body in (("/api/v1/mode", {"mode": "MANUAL"}),
                           ("/api/v1/teleop", {"linear": 0.1}),
                           ("/api/v1/line-follow/mode", {"mode": "CAMERA_LINE"}),
                           ("/api/v1/calibration/session", {"kind": "camera"}),
                           ("/api/v1/navigation/goal", {"x": 1.0, "y": 0.0})):
            result = client.post(path, headers=ADMIN, json=body) if path != "/api/v1/line-follow/mode" else client.put(path, headers=ADMIN, json=body)
            assert result.status_code in (409, 503), (path, result.text)
        assert svc.modes.transition(Mode.NAVIGATION)[0] is False  # also fences callers past API guard
        assert svc.modes.mode is Mode.IDLE
        assert client.post("/api/v1/mode", headers=ADMIN, json={"mode": "IDLE"}).status_code == 200
        assert svc.calibration.current() is None
    finally:
        finish.set()
        worker.join(5)
    assert replies[0].status_code == 200
    assert not svc.modes.motion_reserved
    assert client.post("/api/v1/mode", headers=ADMIN, json={"mode": "MANUAL"}).status_code == 200


def test_calibration_admission_cannot_race_perception_reservation(core_client, monkeypatch):
    from core_api_web.api.v1.line_follow import set_lane_perception
    from core_api_web.api.deps import AuthContext
    from core_common.protocol.schemas import LanePerceptionRequest
    from core_api_web.api.errors import ApiError

    client, svc = core_client()
    checked, finish_calibration, config_done = Event(), Event(), Event()
    start = svc.calibration.start

    def paused_start(**kwargs):
        checked.set()  # API already found idle, but has not created its session
        assert finish_calibration.wait(5)
        return start(**kwargs)

    monkeypatch.setattr(svc.calibration, "start", paused_start)
    agent = Agent(AgentReply(True, "OK", data={"paint_source": "learned"}))
    monkeypatch.setattr("core_api_web.api.v1.host._agent", lambda _: agent)
    calibration_results, config_results = [], []
    calibration_thread = Thread(target=lambda: calibration_results.append(client.post(
        "/api/v1/calibration/session", headers=ADMIN, json={"kind": "camera"})))
    calibration_thread.start()
    assert checked.wait(5)

    def configure():
        try:
            set_lane_perception(LanePerceptionRequest(paint_source="learned"),
                                AuthContext(role="administrator", token_id="other-admin"), svc)
            config_results.append("accepted")
        except ApiError as exc:
            config_results.append(exc.code)
        finally:
            config_done.set()

    config_thread = Thread(target=configure)
    config_thread.start()
    try:
        assert not config_done.wait(0.5), "configuration passed a pending calibration admission"
        assert not agent.calls
    finally:
        finish_calibration.set()
        calibration_thread.join(5)
        config_thread.join(5)
    assert calibration_results[0].status_code == 201
    assert config_results == ["CALIBRATION_ACTIVE"]
    assert not agent.calls
    assert not svc.modes.motion_reserved


def test_api_merges_actual_fallback_and_clears_evidence_after_restart(core_client, monkeypatch):
    client, svc = core_client()
    agent = Agent(AgentReply(True, "OK", data={"paint_source": "learned", "model_revision": "lane-r1"}))
    monkeypatch.setattr("core_api_web.api.v1.host._agent", lambda _: agent)
    svc.vision.lane_perception.accept(json.dumps({"paint_source_used": "denoise_fallback",
        "paint_source_requested": "learned", "stamp": 10.0}), now=time.monotonic(), source_now=10.1)
    result = client.get("/api/v1/line-follow/perception", headers=VIEWER).json()
    assert result["paint_source"] == "learned"
    assert result["applied_paint_source"] == "denoise_fallback"
    assert result["applied_model_revision"] is None
    changed = client.put("/api/v1/line-follow/perception", headers=ADMIN,
                         json={"paint_source": "learned"}).json()
    assert changed["applied_paint_source"] is None
    svc.vision.lane_perception.accept(json.dumps({"paint_source_used": "learned",
        "paint_source_requested": "learned", "paint_model_revision": "lane-r1", "stamp": 11.0}),
        now=time.monotonic(), source_now=11.1)
    result = client.get("/api/v1/line-follow/perception", headers=VIEWER).json()
    assert result["applied_paint_source"] == "learned"
    assert result["applied_model_revision"] == "lane-r1"
