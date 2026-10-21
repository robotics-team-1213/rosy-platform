"""Native observation handoff preserves capture age without blocking ROS callbacks."""
from hashlib import sha256
import importlib.util
import json
from pathlib import Path
import ssl
import sys
import threading
from types import SimpleNamespace
from urllib.request import HTTPRedirectHandler, HTTPSHandler

import pytest

from core_common.protocol.workcell_observations import ArmObservation, WorkcellObservationManifest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "operations" / "overhead"))
from rosy_vision import protocol

_spec = importlib.util.spec_from_file_location("workcell_observation_bridge", ROOT / "deploy" / "robot" / "omx" / "workcell_observation_bridge.py")
bridge = importlib.util.module_from_spec(_spec)
sys.modules[_spec.name] = bridge
_spec.loader.exec_module(bridge)


@pytest.fixture
def manifest():
    return WorkcellObservationManifest.model_validate({"schema": "rosy.workcell-observations/1", "workcells": [{
        "workcell_id": "example", "label": "Example", "arms": [{
            "source_id": "arm_feedback", "arm_id": "arm_a", "label": "Arm A", "board_id": "EXAMPLE-BOARD",
            "joint_topic": "/omx_commissioning/arm_a/joint_states", "joint_names": ["joint1"],
            "token_env": "EXAMPLE_ARM", "credential_sha256": sha256(b"arm-secret").hexdigest()}],
        "cameras": [{"source_id": "top", "label": "Top", "role": "overhead", "arm_id": None,
            "image_topic": "/top/image_raw", "device_path": "/dev/v4l/by-path/example-top",
            "token_env": "EXAMPLE_TOP", "credential_sha256": sha256(b"top-secret").hexdigest()}]}]})


def test_selected_source_credentials_are_required_and_bound_to_manifest_hashes(manifest):
    env = {"EXAMPLE_ARM": "arm-secret", "EXAMPLE_TOP": "top-secret"}
    cell, tokens = bridge.select_sources(manifest, "example", env)
    assert cell.workcell_id == "example" and tokens == {"arm_feedback": "arm-secret", "top": "top-secret"}
    for changed in ({"EXAMPLE_ARM": "arm-secret"}, {**env, "EXAMPLE_TOP": "another-secret"}):
        with pytest.raises(ValueError, match="credential"):
            bridge.select_sources(manifest, "example", changed)
    with pytest.raises(ValueError, match="workcell"):
        bridge.select_sources(manifest, "unknown", env)


@pytest.mark.parametrize("url,scheme", [("http://fleet.example", "https"), ("ws://vision.example", "wss"),
    ("https://user:secret@fleet.example", "https"), ("https://fleet.example/?secret=value", "https")])
def test_transports_refuse_plaintext_and_credentials_in_urls(url, scheme):
    with pytest.raises(ValueError):
        bridge.secure_url(url, scheme)


def test_latest_source_rejects_replay_and_bad_clocks_without_refreshing_receipt():
    clock = SimpleNamespace(wall=100.0, monotonic=10.0)
    source = bridge.LatestSource(wall=lambda: clock.wall, monotonic=lambda: clock.monotonic)
    assert source.put(100, {"joint1": 0.25})
    assert not source.put(100, {"joint1": 9})
    for stamp in (0, True, "100", float("nan"), float("inf"), 97.9, 100.251):
        with pytest.raises(ValueError):
            source.put(stamp, {})
    assert source.latest().value == {"joint1": 0.25}
    clock.wall, clock.monotonic = 100.1, 12.1
    assert source.latest() is None


def test_arm_sender_starts_wire_sequence_at_one_after_queue_drops_and_failed_delivery(monkeypatch):
    source = bridge.LatestSource(wall=lambda: 100, monotonic=lambda: 10)
    source.put(99.5, {"joint1": 0.1})
    source.put(100, {"joint1": 0.25})
    sent = []

    def post(url, source_id, token, observation, **kwargs):
        sent.append((source_id, token, observation))
        if len(sent) == 1:
            raise OSError("not delivered")

    monkeypatch.setattr(bridge, "post_arm", post)
    sender = bridge.ArmSender("https://fleet.example", "arm_feedback", "arm-secret", context=ssl.create_default_context())
    with pytest.raises(OSError):
        sender.send(source.latest())
    sender.send(source.latest())
    assert all(item[2].sequence == 1 for item in sent)
    assert len(sent[1][2].epoch) == 32
    assert sent[1][2].captured_at == 100 and sent[1][2].positions == {"joint1": 0.25}


def test_http_arm_request_uses_real_api_auth_tls_and_refuses_redirects(monkeypatch):
    captured = {}

    class Response:
        status = 202
        def __enter__(self): return self
        def __exit__(self, *args): pass
        def read(self, *args): return b'{"accepted":true}'

    def build(*handlers):
        captured["handlers"] = handlers
        def send(request, timeout):
            captured.update(request=request, timeout=timeout)
            return Response()
        return SimpleNamespace(open=send)

    monkeypatch.setattr(bridge, "build_opener", build)
    context = ssl.create_default_context()
    observation = ArmObservation(epoch="a" * 32, sequence=1, captured_at=100, positions={"joint1": 0.25})
    bridge.post_arm("https://fleet.example", "arm_feedback", "arm-secret", observation, context=context)
    request = captured["request"]
    assert request.full_url == "https://fleet.example/api/fleet/workcell-observations/arms/arm_feedback"
    assert {key.lower(): value for key, value in request.header_items()}["x-workcell-observation-token"] == "arm-secret"
    assert json.loads(request.data) == observation.model_dump()
    assert 0 < captured["timeout"] <= 2
    assert context.check_hostname and context.verify_mode == ssl.CERT_REQUIRED
    assert any(isinstance(handler, HTTPSHandler) for handler in captured["handlers"])
    redirect = next(handler for handler in captured["handlers"] if isinstance(handler, HTTPRedirectHandler))
    assert redirect.redirect_request(request, None, 302, "redirect", {}, "https://other.example") is None


def test_camera_packet_uses_canonical_wire_header_and_includes_source_and_queue_age():
    source = bridge.LatestSource(wall=lambda: 100, monotonic=lambda: 10)
    source.put(99.8, (b"jpeg", 640, 480))
    sample = source.latest()
    packet = bridge.camera_packet(sample, wall=100.4, monotonic=10.4)
    header = protocol.parse_header(packet)
    assert header.seq == sample.sequence and 599 <= header.age_ms <= 601
    assert (header.width, header.height, header.rotation_deg) == (640, 480, 0)
    assert packet[protocol.HEADER_SIZE:] == b"jpeg"
    protocol.validate_hello(bridge.camera_hello("top", 640, 480))
    with pytest.raises(ValueError):
        bridge.camera_packet(sample, wall=102, monotonic=12)


def test_blocked_failed_source_keeps_only_latest_and_does_not_block_other_sources():
    sources = [bridge.LatestSource(wall=lambda: 100, monotonic=lambda: 10) for _ in range(2)]
    stop, blocked, release, written, recovered, other = [threading.Event() for _ in range(6)]
    attempts = []

    def send_a(sample):
        attempts.append(sample.value)
        if len(attempts) == 1:
            blocked.set()
            assert release.wait(3)
            raise OSError("source A unavailable")
        recovered.set()

    workers = [bridge.SourceWorker(sources[0], send_a), bridge.SourceWorker(sources[1], lambda sample: other.set())]
    threads = [threading.Thread(target=worker.run, args=(stop,), daemon=True) for worker in workers]
    for thread in threads: thread.start()
    try:
        sources[0].put(99.5, 1)
        assert blocked.wait(2)
        def overwrite():
            sources[0].put(99.6, 2); sources[0].put(99.7, 3); written.set()
        writer = threading.Thread(target=overwrite, daemon=True)
        writer.start()
        assert written.wait(1), "ROS callback blocked behind network I/O"
        sources[1].put(100, "independent")
        assert other.wait(1)
        release.set()
        assert recovered.wait(2)
        assert attempts == [1, 3]
        writer.join(timeout=1)
    finally:
        stop.set(); release.set()
        for thread in threads: thread.join(timeout=3)
    assert not any(thread.is_alive() for thread in threads)
