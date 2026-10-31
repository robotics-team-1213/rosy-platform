"""Raw training episodes: the runner appends a row per tick between `episode start` and `save`; a dropped episode
leaves nothing; conversion pairs each tick with the latest frame taken at or before it."""
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "deploy/robot/omx"))
import episode_recorder as er  # noqa: E402
import test_omx_chunk_runner as tr  # noqa: E402


class NoCameras:
    def __init__(self, urls, folder):
        self.stop_event = type("E", (), {"set": lambda self: None})()
        self.counts, self.errors = {}, {}

    def start(self):
        pass

    def join(self, timeout=None):
        pass


def episode(tmp_path, name="ep"):
    folder = tmp_path / name
    folder.mkdir()
    (folder / "task.json").write_text(json.dumps({"task": "t", "cameras": {}}))
    return folder


def test_the_runner_records_ticks_only_while_an_episode_is_open(tmp_path):
    kept, dropped = episode(tmp_path, "kept"), episode(tmp_path, "dropped")
    robot = tr.Robot()
    status, clock, queue = [], [0.0], [f"episode start {kept}", "run approach_pinky", "episode save",
                                       "run grasp_pinky", f"episode start {dropped}", "state", "episode drop", "stop"]
    r = tr.m.Runner(robot, tr.library(), fps=30, status=status.append, clock=lambda: clock[0],
                    sleep=lambda s: clock.__setitem__(0, clock[0] + 1 / 30))
    r.recorder = er.Recorder(NoCameras)
    r.run(lambda: [queue.pop(0)] if queue and not r.chunk else [])
    rows = [json.loads(line) for line in (kept / "ticks.jsonl").read_text().splitlines()]
    assert len(rows) >= 10 and (kept / "result.json").exists()
    assert rows[-1]["action"][0] == 18.0 and len(rows[0]["state"]) == 6  # the approach chunk, as sent
    assert not dropped.exists()
    assert all(s["ok"] for s in status if s["command"].startswith("episode"))


def test_frames_written_by_the_camera_thread_and_aligned_to_ticks(tmp_path):
    folder = episode(tmp_path)
    frames = iter([b"a", b"a", b"b", b"c"] + [b"c"] * 100)
    cams = er.Cameras({"top": "u"}, folder, period_s=0.001, fetch=lambda url: next(frames))
    cams.start()
    while cams.counts["top"] < 3:
        pass
    cams.stop_event.set()
    cams.join()
    assert sorted(p.name for p in (folder / "top").iterdir()) == ["000000.jpg", "000001.jpg", "000002.jpg"]
    ticks = [{"t": 0.5}, {"t": 1.5}, {"t": 2.5}]
    pairs = er.aligned(ticks, {"top": [{"seq": 0, "t": 1.0}, {"seq": 1, "t": 2.0}]})
    assert [(row["t"], seqs["top"]) for row, seqs in pairs] == [(1.5, 0), (2.5, 1)]  # 0.5 had no frame yet


def test_an_episode_whose_camera_gave_no_frame_is_not_kept(tmp_path):
    folder = tmp_path / "ep"
    folder.mkdir()
    (folder / "task.json").write_text(json.dumps({"task": "t", "cameras": {"top": "u"}}))

    def refused(url):
        raise OSError("HTTP Error 503: Service Unavailable")  # camera services stopped by another session

    rec = er.Recorder(lambda urls, f: er.Cameras(urls, f, period_s=0.001, fetch=refused))
    rec.command(["start", str(folder)])
    rec.tick([0] * 6, [0] * 6)
    out = rec.command(["save"])
    assert out["kept"] is False and "503" in out["why"]["top"]
    assert json.loads((folder / "result.json").read_text())["kept"] is False


def test_kept_episodes_convert_to_a_lerobot_dataset_with_the_teleop_feature_names(tmp_path):
    import pytest
    pytest.importorskip("lerobot")
    cv2 = pytest.importorskip("cv2")
    np = pytest.importorskip("numpy")
    eps = tmp_path / "episodes"
    for n, kept in ((0, True), (1, False)):
        folder = eps / f"ep{n}"
        for cam in ("top", "front"):
            (folder / cam).mkdir(parents=True)
            with (folder / f"{cam}.jsonl").open("w") as f:
                for seq in range(12):
                    img = np.full((480, 640, 3), 10 * seq, np.uint8)
                    (folder / cam / f"{seq:06d}.jpg").write_bytes(cv2.imencode(".jpg", img)[1].tobytes())
                    f.write(json.dumps({"seq": seq, "t": 100 + seq / 30}) + "\n")
        (folder / "task.json").write_text(json.dumps({"task": "Pick the green container from the floor.", "cameras": {}}))
        (folder / "ticks.jsonl").write_text("".join(json.dumps({"t": 100 + k / 30 + 0.001, "state": [k] * 6, "action": [k + 1] * 6}) + "\n"
                                                    for k in range(12)))
        (folder / "result.json").write_text(json.dumps({"kept": kept}))
    assert er.convert(eps, tmp_path / "ds", "local/test", 30, {"top": "top", "front": "front"}) == 1
    info = json.loads((tmp_path / "ds/meta/info.json").read_text())
    assert info["total_episodes"] == 1 and info["total_frames"] == 12 and info["robot_type"] == "omx_follower"
    assert {"action", "observation.state", "observation.images.top", "observation.images.front"} <= set(info["features"])


def test_a_failed_carry_is_kept_as_a_labelled_failure_not_deleted(tmp_path):
    folder = episode(tmp_path, "failed")
    rec = er.Recorder(NoCameras)
    rec.command(["start", str(folder)])
    rec.tick([0] * 6, [0] * 6)
    out = rec.command(["fail", "contact", "at", "run", "descend_place"])
    result = json.loads((folder / "result.json").read_text())
    assert out["outcome"] == "failed" and result["kept"] is False and result["why"] == "contact at run descend_place"
    assert (folder / "ticks.jsonl").exists()  # the data stays for learning from the miss


def test_the_runner_recorder_has_no_camera_thread_and_the_pipeline_session_counts_frames(tmp_path):
    folder = episode(tmp_path, "split")
    rec = er.Recorder()  # the runner: rows only (a camera thread there stalled the guard, 2026-10-29)
    rec.command(["start", str(folder)])
    assert rec.cameras is None
    frames = iter([b"a", b"b"] + [b"b"] * 50)
    session = er.CameraSession(folder, {"top": "u"}, factory=lambda urls, f: er.Cameras(urls, f, 0.001, lambda url: next(frames)))
    while session.cams.counts["top"] < 2:
        pass
    rec.tick([0] * 6, [0] * 6)
    rec.command(["save"])
    result = session.finish()
    assert result["frames"]["top"] == 2 and result["kept"] is True
