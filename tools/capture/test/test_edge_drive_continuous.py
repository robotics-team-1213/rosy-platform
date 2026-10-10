"""A continuous test observes CORE stops; lease loss/OFF ends it without re-arming."""
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import edge_drive


@pytest.mark.parametrize("ending", ["off", "lease", "connection", "interrupt", "recording"])
def test_continuous_test_keeps_core_holds_then_stops_and_cleans_up(monkeypatch, ending):
    calls, samples = [], []
    holds = edge_drive.argparse.Namespace(status=200)
    clock = iter(range(0, 10000, 10))
    monkeypatch.setattr(edge_drive.time, "time", lambda: next(clock))
    monkeypatch.setattr(edge_drive.time, "sleep", lambda _: None)
    monkeypatch.setattr(edge_drive, "rec_start", lambda _: calls.append("record-start") or "rec-1")
    monkeypatch.setattr(edge_drive, "_recording_state", lambda _: {
        "state": "idle" if ending == "recording" and len(samples) == 3 else "recording", "id": "rec-1"})
    monkeypatch.setattr(edge_drive, "rec_stop", lambda _: calls.append("record-stop"))
    monkeypatch.setattr(edge_drive, "_arm", lambda _: calls.append("arm") or holds)
    monkeypatch.setattr(edge_drive, "_disarm", lambda _: calls.append("disarm"))

    class Core:
        def call(self, method, path, body=None, **kwargs):
            calls.append((method, path, body))
            if method == "PUT":
                return 200, {"mode": "OFF"}
            if len(samples) == 3:
                if ending == "interrupt":
                    raise KeyboardInterrupt
                if ending == "connection":
                    return 0, None
                if ending == "lease":
                    holds.status = 409
                return 200, {"mode": "OFF" if ending == "off" else "CAMERA_LINE"}
            reason = ["crosswalk_person_present", "lane_departure", "obstacle"][len(samples)]
            samples.append(reason)
            return 200, {"mode": "CAMERA_LINE", "state": "HOLD", "reason": reason,
                         "linear": 0.0, "angular": 0.0, "stuck": {"cause": reason}}

    args = edge_drive.argparse.Namespace(max_s=1, rearm=10, continuous_test=True)
    if ending == "interrupt":
        with pytest.raises(KeyboardInterrupt):
            edge_drive.cmd_drive(Core(), args)
    else:
        edge_drive.cmd_drive(Core(), args)
    assert samples == ["crosswalk_person_present", "lane_departure", "obstacle"]
    assert calls.count("arm") == 1
    assert calls[-3:] == ["disarm", ("PUT", "/line-follow/mode", {"mode": "OFF"}), "record-stop"]
    assert not any(isinstance(c, tuple) and c[1] in ("/teleop", "/line-follow/stuck/decision") for c in calls)


def test_hold_connection_preserves_certificate_hostname():
    context = edge_drive.ssl.create_default_context()
    core = edge_drive.Core("127.0.0.1", "test-token", 8080, context, "robot.example")
    clone = core.clone()
    assert clone.tls_host == "robot.example" and clone.context is context
    assert clone.conn is None


def test_refused_recording_does_not_arm_or_stop_another_recording(monkeypatch):
    calls = []
    def refused(_):
        raise SystemExit("recording refused")
    monkeypatch.setattr(edge_drive, "rec_start", refused)
    monkeypatch.setattr(edge_drive, "_arm", lambda _: calls.append("arm"))
    monkeypatch.setattr(edge_drive, "rec_stop", lambda _: calls.append("record-stop"))
    with pytest.raises(SystemExit, match="recording refused"):
        edge_drive.cmd_drive(None, edge_drive.argparse.Namespace(continuous_test=True))
    assert calls == []
