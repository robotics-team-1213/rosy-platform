"""Native observation handoff preserves capture age without blocking ROS callbacks."""
from hashlib import sha256
import importlib.util
import json
import os
from pathlib import Path
import ssl
import sys
import threading
from types import SimpleNamespace
from urllib.request import HTTPRedirectHandler, HTTPSHandler
from urllib.error import HTTPError

import pytest
import yaml

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


def test_lost_acceptance_recovers_only_after_conflict_and_new_capture_without_acknowledging_409(monkeypatch):
    source = bridge.LatestSource(wall=lambda: 100, monotonic=lambda: 10)
    source.put(99.5, {"joint1": 0.25})
    sent = []

    def post(url, source_id, token, observation, **kwargs):
        sent.append(observation)
        if len(sent) == 1:
            raise OSError("accepted but response lost")
        if len(sent) == 2:
            raise HTTPError(url, 409, "conflict", {}, None)

    monkeypatch.setattr(bridge, "post_arm", post)
    sender = bridge.ArmSender("https://fleet.example", "arm_feedback", "arm-secret", context=ssl.create_default_context())
    with pytest.raises(OSError): sender.send(source.latest())
    with pytest.raises(HTTPError): sender.send(source.latest())
    with pytest.raises(ValueError): sender.send(source.latest())
    assert len(sent) == 2 and sender.sequence == 0
    source.put(100, {"joint1": 0.5})
    sender.send(source.latest())
    assert sent[-1].epoch != sent[0].epoch and sent[-1].sequence == 1
    assert sent[-1].captured_at > sent[0].captured_at


@pytest.mark.parametrize("status", [401, 403])
def test_rejected_credentials_do_not_rotate_producer_epoch(monkeypatch, status):
    source = bridge.LatestSource(wall=lambda: 100, monotonic=lambda: 10)
    source.put(99.5, {"joint1": 0.25})
    sent = []
    def post(url, source_id, token, observation, **kwargs):
        sent.append(observation)
        raise HTTPError(url, status, "unauthorized", {}, None)
    monkeypatch.setattr(bridge, "post_arm", post)
    sender = bridge.ArmSender("https://fleet.example", "arm_feedback", "arm-secret", context=ssl.create_default_context())
    with pytest.raises(HTTPError): sender.send(source.latest())
    source.put(100, {"joint1": 0.5})
    with pytest.raises(HTTPError): sender.send(source.latest())
    assert sent[0].epoch == sent[1].epoch and sent[0].sequence == sent[1].sequence == 1


def test_camera_sender_uses_verified_source_scoped_persistent_websocket(monkeypatch):
    sent, opened, timeouts = [], [], []
    class Connection:
        socket = SimpleNamespace(settimeout=lambda seconds: timeouts.append(seconds))
        def send(self, value): sent.append(value)
        def recv(self, timeout): raise TimeoutError()
        def close(self): pass
    def connect(url, **kwargs):
        opened.append((url, kwargs))
        return Connection()
    monkeypatch.setitem(sys.modules, "websockets.sync.client", SimpleNamespace(connect=connect))
    packet = bridge.camera_packet
    monkeypatch.setattr(bridge, "camera_packet", lambda sample: packet(sample, wall=100.1, monotonic=10.1))
    source = bridge.LatestSource(wall=lambda: 100, monotonic=lambda: 10)
    source.put(100, (b"jpeg", 640, 480))
    context = ssl.create_default_context()
    sender = bridge.CameraSender("wss://vision.example", "top", "top-secret", context=context)
    sender.send(source.latest()); sender.send(source.latest()); sender.close()
    assert len(opened) == 1 and opened[0][0] == "wss://vision.example" + protocol.WS_PATH
    assert opened[0][1]["ssl"] is context and opened[0][1]["max_queue"] == 1
    assert opened[0][1]["additional_headers"] == {"Authorization": "Bearer top-secret"}
    assert timeouts == [2]
    protocol.validate_hello(json.loads(sent[0]))
    assert protocol.parse_header(sent[1]).width == 640 and sent[1][protocol.HEADER_SIZE:] == b"jpeg"


def test_joint_callback_conversion_rejects_aliases_nonfinite_and_wrong_identity():
    message = SimpleNamespace(header=SimpleNamespace(stamp=SimpleNamespace(sec=100, nanosec=0)),
                              name=["joint1"], position=[0.25])
    assert bridge.joint_values(message, ["joint1"]) == {"joint1": 0.25}
    for names, positions in ((["other"], [0.25]), (["joint1", "joint1"], [0.25, 0.5]),
                              (["joint1"], [float("nan")]), (["joint1"], [True])):
        message.name, message.position = names, positions
        with pytest.raises(ValueError): bridge.joint_values(message, ["joint1"])


@pytest.mark.parametrize("changed", [{"encoding": "mono8"}, {"width": 1280}, {"step": 1919}, {"data": b"short"}])
def test_camera_callback_rejects_unexpected_layout_before_encoding(changed):
    message = SimpleNamespace(**{"encoding": "bgr8", "width": 640, "height": 480, "step": 1920,
                                  "data": b"\0" * (1920 * 480), **changed})
    with pytest.raises(ValueError): bridge.encode_image(message, None, None)


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


@pytest.mark.parametrize("external_shutdown", [False, True])
def test_native_main_subscribes_only_to_configured_sources_with_localhost_discovery(manifest, tmp_path, monkeypatch, external_shutdown):
    path = tmp_path / "manifest.yaml"
    path.write_text(yaml.safe_dump(manifest.model_dump(by_alias=True)), encoding="utf-8")
    for key in ("CYCLONEDDS_URI", "FASTDDS_DEFAULT_PROFILES_FILE", "FASTRTPS_DEFAULT_PROFILES_FILE", "ROS_DISCOVERY_SERVER"):
        monkeypatch.delenv(key, raising=False)
    for key, value in {"EXAMPLE_ARM": "arm-secret", "EXAMPLE_TOP": "top-secret", "RMW_IMPLEMENTATION": "rmw_fastrtps_cpp",
                       "ROS_STATIC_PEERS": "", "ROS_AUTOMATIC_DISCOVERY_RANGE": "LOCALHOST"}.items():
        monkeypatch.setenv(key, value)
    subscriptions, delivered, lifecycle = [], [], []
    done = threading.Event()
    class ExternalShutdown(Exception): pass

    class Sender:
        def __init__(self, url, source, token, **kwargs): self.source = source
        def send(self, sample):
            delivered.append((self.source, sample.value))
            if len(delivered) == 2: done.set()
        def close(self): pass

    class Node:
        def create_subscription(self, kind, topic, callback, qos): subscriptions.append((topic, callback))
        def destroy_node(self): lifecycle.append("destroyed")

    def spin(node):
        stamp = bridge.time.time()
        header = SimpleNamespace(stamp=SimpleNamespace(sec=int(stamp), nanosec=int((stamp % 1) * 1e9)))
        for topic, callback in subscriptions:
            message = SimpleNamespace(header=header, name=["joint1"], position=[0.25])
            callback(message)
        assert done.wait(3)
        if external_shutdown:
            raise ExternalShutdown()

    def shutdown():
        if external_shutdown:
            raise RuntimeError("context already shut down by SIGTERM")
        lifecycle.append("shutdown")

    monkeypatch.setattr(bridge, "ArmSender", Sender)
    monkeypatch.setattr(bridge, "CameraSender", Sender)
    monkeypatch.setattr(bridge, "encode_image", lambda msg, cv, np: (b"jpeg", 640, 480))
    monkeypatch.setitem(sys.modules, "cv2", SimpleNamespace(error=RuntimeError))
    monkeypatch.setitem(sys.modules, "numpy", SimpleNamespace())
    monkeypatch.setitem(sys.modules, "rclpy", SimpleNamespace(
        init=lambda **kwargs: lifecycle.append(kwargs), create_node=lambda name: Node(), spin=spin,
        shutdown=shutdown, try_shutdown=lambda: lifecycle.append("shutdown")))
    monkeypatch.setitem(sys.modules, "rclpy.executors", SimpleNamespace(ExternalShutdownException=ExternalShutdown))
    monkeypatch.setitem(sys.modules, "rclpy.qos", SimpleNamespace(qos_profile_sensor_data=object()))
    monkeypatch.setitem(sys.modules, "sensor_msgs.msg", SimpleNamespace(Image=object(), JointState=object()))
    bridge.main(["--manifest", str(path), "--workcell", "example", "--fleet-url", "https://fleet.example",
                 "--vision-url", "wss://vision.example", "--domain-id", "13"])
    assert {topic for topic, _ in subscriptions} == {"/omx_commissioning/arm_a/joint_states", "/top/image_raw"}
    assert {source for source, _ in delivered} == {"arm_feedback", "top"}
    assert lifecycle == [{"args": [], "domain_id": 13}, "destroyed", "shutdown"]
    assert os.environ["ROS_AUTOMATIC_DISCOVERY_RANGE"] == "LOCALHOST" and os.environ["ROS_STATIC_PEERS"] == ""
