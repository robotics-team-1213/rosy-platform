"""The bench serves only fresh previews from its current recording session."""

import io
import json
import os
from pathlib import Path
import sys
from threading import Event, Lock, current_thread

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "deploy/robot/omx"))
import bench_live_frames as frames
from bench_live_preview import SessionPreview, camera_labels


def test_latest_observation_is_encoded_on_daemon(tmp_path, monkeypatch):
    np = pytest.importorskip("numpy")
    image = pytest.importorskip("PIL.Image")
    monkeypatch.setenv(frames.LIVE_DIR, str(tmp_path))
    encode = frames.LiveFrames._encode
    run = frames.LiveFrames._run
    ready = Event()
    published = Event()
    seen = []

    def observe(self, observation):
        seen.append((current_thread().daemon, observation))
        encode(self, observation)
        published.set()

    monkeypatch.setattr(frames.LiveFrames, "_encode", observe)
    monkeypatch.setattr(frames.LiveFrames, "_run", lambda self: ready.wait(5) and run(self))
    preview = frames.start_live_frames()
    try:
        old = {"front": np.zeros((400, 800, 3), dtype=np.uint8)}
        latest = {"front": np.full((400, 800, 3), (255, 0, 0), dtype=np.uint8)}
        frames.offer_preview(preview, old)
        frames.offer_preview(preview, latest)
        assert preview.latest is latest
        ready.set()
        assert published.wait(5)
        assert len(seen) == 1 and seen[0][0] and seen[0][1] is latest
        with image.open(io.BytesIO((tmp_path / "front.jpg").read_bytes())) as jpeg:
            assert jpeg.size == (640, 320)
            r, g, b = jpeg.getpixel((0, 0))
            assert r > 240 and g < 10 and b < 10
        assert json.loads((tmp_path / "meta.json").read_text())["front"] > 0
        assert not list(tmp_path.glob("*.tmp"))
    finally:
        preview.close()


def test_disabled_preview_never_creates_files(tmp_path, monkeypatch):
    monkeypatch.delenv(frames.LIVE_DIR, raising=False)
    monkeypatch.chdir(tmp_path)
    preview = frames.start_live_frames()
    assert preview is None
    frames.offer_preview(preview, {"top": object()})
    assert not list(tmp_path.iterdir())


def test_frame_builder_returns_original_result_when_preview_fails(monkeypatch):
    import guarded_native_cli as cli
    from types import SimpleNamespace

    class BrokenPreview:
        def offer(self, values):
            raise RuntimeError("preview failure")

        def close(self):
            pass

    monkeypatch.setattr(cli, "start_live_frames", BrokenPreview)
    observation, result = {"front": object()}, object()

    def build(features, values, *, prefix):
        assert values is observation and prefix == "observation"
        return result

    module = SimpleNamespace(ACTION="action", OBS_STR="observation", build_dataset_frame=build,
                             make_robot_from_config=None, make_teleoperator_from_config=None)
    module.main = lambda: module.build_dataset_frame({}, observation, prefix="observation")
    assert cli.run_native(module, object, object) is result
    assert module.build_dataset_frame is build

    kwargs = {"robot_observation_processor": lambda values: result}
    frames.preview_reset_loop(BrokenPreview(), kwargs)
    assert kwargs["robot_observation_processor"](observation) is result


def test_camera_labels_follow_device_binding_and_viewer_alias(tmp_path, monkeypatch):
    monkeypatch.setattr(Path, "home", lambda: tmp_path)
    env = tmp_path / ".config/rosy"
    env.mkdir(parents=True)
    for role, device in (("jieli", "arm_s_jieli"), ("arm_s_wrist", "arm_s_wrist"), ("side", "side")):
        (env / f"omx-camera-{role}.env").write_text(
            f"ROSY_CAMERA_DEVICE=/dev/v4l/by-id/rosy-{device}\nROSY_CAMERA_TOPIC=/cameras/{role}\n")
    (env / "omx-camera-view.env").write_text('ROSY_VIEW_ARGS="--camera-topic arm_s_top=/cameras/jieli"')
    robot = {"cameras": {
        "top": {"index_or_path": "/dev/v4l/by-id/rosy-arm_s_jieli"},
        "front": {"index_or_path": "/dev/v4l/by-id/rosy-arm_s_wrist"},
        "side": {"index_or_path": "/dev/v4l/by-id/rosy-side"},
        "unknown": {"index_or_path": "/dev/v4l/by-id/unknown"},
    }}
    assert camera_labels(robot) == {"arm_s_top": "top", "arm_s_wrist": "front", "side": "side"}
    assert camera_labels(dict(robot, type="bi_omx_follower", arm_a={"cameras": {}})) == camera_labels(robot)


def test_session_preview_removes_only_its_own_directory(tmp_path, monkeypatch):
    monkeypatch.setattr("bench_live_preview.SHM", tmp_path / "missing")
    other = tmp_path / "another-session"
    other.mkdir()
    preview = SessionPreview(tmp_path, {})
    assert preview.folder.parent == tmp_path
    assert preview.folder.is_dir()
    (preview.folder / "front.jpg").write_bytes(b"jpeg")
    preview.close()
    assert not preview.folder.exists()
    assert other.is_dir()


def test_bench_camera_routes_use_fresh_recording_frames_then_fall_back(tmp_path, monkeypatch):
    from types import SimpleNamespace
    from unittest.mock import Mock

    from bench_record_http import camera_frame, camera_state

    monkeypatch.setattr("bench_live_preview.SHM", tmp_path / "missing")
    preview = SessionPreview(tmp_path, {})
    try:
        preview.labels = {"arm_s_wrist": "front"}
        jpg = preview.folder / "front.jpg"
        jpg.write_bytes(b"live")
        requests = Mock(side_effect=lambda url, **_: io.BytesIO(
            b'{"arm_s_wrist":{"quality":{},"fresh":true}}' if url.endswith("state.json") else b"viewer"))
        monkeypatch.setattr("bench_record_http.urllib.request.urlopen", requests)
        bench = SimpleNamespace(live_preview=preview, state={"status": "recording"}, lock=Lock())
        assert camera_frame(bench, "arm_s_wrist") == b"live"
        requests.assert_not_called()
        with monkeypatch.context() as offline:
            offline.setattr("bench_record_http.urllib.request.urlopen", Mock(side_effect=OSError))
            assert camera_state(bench)["arm_s_wrist"]["fresh"] is True
        assert camera_state(bench)["arm_s_wrist"]["fresh"] is True
        os.utime(jpg, (1, 1))
        assert camera_frame(bench, "arm_s_wrist") == b"viewer"
        requests.assert_called_with("http://127.0.0.1:8767/frame/arm_s_wrist.jpg", timeout=1.5)
        bench.state["status"] = "restoring"
        jpg.touch()
        assert camera_frame(bench, "arm_s_wrist") == b"viewer"
    finally:
        preview.close()
