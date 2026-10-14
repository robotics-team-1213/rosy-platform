"""Recording smoke must reject false motion success and lost control leases."""

import importlib.util
import sys
from pathlib import Path

import pytest

DEPLOY = Path(__file__).resolve().parents[1] / "deploy/robot/omx"
sys.path.insert(0, str(DEPLOY))
SPEC = importlib.util.spec_from_file_location("omx_recording_probe", DEPLOY / "probe_pilot_recording.py")
recording = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(recording)


class Event:
    def __init__(self):
        self.stopped = False
        self.waits = 0

    def set(self):
        self.stopped = True

    def is_set(self):
        return self.stopped

    def wait(self, _duration):
        self.waits += 1
        return self.stopped or self.waits > 1


@pytest.fixture
def harness(monkeypatch):
    class HTTP:
        position = 0.0
        movement = 0.02
        refusals = 0
        renewal_fails = False
        episode = 0

        def __init__(self):
            self.calls = []

        def request(self, path, *, method="GET", token="", body=None, **_kwargs):
            self.calls.append((path, method, body))
            if path == "/pair":
                return {"token": "test-private-token"}
            if path == "/seat" and method == "POST":
                return {"seat_id": "seat"}
            if path == "/seat/seat":
                if method == "PUT" and self.renewal_fails:
                    raise RuntimeError("HTTP 409: lease expired")
                return None
            if path == "/target":
                return {"controls": {"items": []}}
            if path == "/state":
                return {"ready": True, "instance_id": "sim", "state_sequence": len(self.calls),
                        "positions": {"joint1": self.position}, "owner_state": "ready"}
            if path == "/camera":
                return {"fresh": True}
            if path == "/recordings" and method == "POST":
                self.episode += 1
                return {"episode_id": f"episode-{self.episode}"}
            if path == "/recordings":
                if self.episode == 2:
                    return {"status": "incomplete", "issues": ["control_released"]}
                return {"status": "recording", "frame_count": 10}
            if path.endswith("/stop"):
                return {"status": "complete", "issues": []}
            if path == "/goals":
                if self.refusals:
                    self.refusals -= 1
                    raise RuntimeError("HTTP 409: joint_state_sequence_mismatch")
                self.position += self.movement
                return {"state": "LOCAL_ACCEPTED"}
            if path.startswith("/goals/"):
                return {"state": "SUCCEEDED", "ros_goal_id": "sim-goal"}
            raise AssertionError((path, method))

    http = HTTP()

    class Thread:
        def __init__(self, *, target, daemon):
            self.target = target

        def start(self):
            # Reproduce a worker exception being separate from the caller.
            try:
                self.target()
            except RuntimeError:
                pass

        def join(self, timeout):
            pass

    monkeypatch.setattr(recording.threading, "Event", Event)
    monkeypatch.setattr(recording.threading, "Thread", Thread)
    monkeypatch.setattr(recording.time, "sleep", lambda _delay: None)
    monkeypatch.setattr(recording.subprocess, "run",
                        lambda *args, **kwargs: type("Result", (), {"stdout": "test-code"})())
    monkeypatch.setattr(recording, "request", http.request)
    import probe_pilot_sim_http
    monkeypatch.setattr(probe_pilot_sim_http, "request", http.request)
    return http


def test_successful_recording_and_expiry_do_not_print_credentials(harness, capsys):
    recording.main("container")
    output = capsys.readouterr().out
    assert '"complete"' in output and '"control_released"' in output
    assert "test-code" not in output and "test-private-token" not in output


def test_ros_success_without_motion_cannot_finalize_success(harness):
    harness.movement = 0.0
    with pytest.raises(RuntimeError, match="readback"):
        recording.main("container")
    assert not any(path.endswith("/stop") for path, _, _ in harness.calls)


def test_recording_retries_one_stale_state_with_a_fresh_request_id(harness):
    harness.refusals = 1
    recording.main("container")
    goals = [body for path, method, body in harness.calls if path == "/goals" and method == "POST"]
    assert len(goals) == 2
    assert goals[0]["request_id"] != goals[1]["request_id"]
    assert goals[1]["state_sequence"] > goals[0]["state_sequence"]


def test_renewal_worker_failure_stops_before_recording_success(harness):
    harness.renewal_fails = True
    with pytest.raises(RuntimeError, match="renewal"):
        recording.main("container")
    assert not any(path.endswith("/stop") for path, _, _ in harness.calls)
