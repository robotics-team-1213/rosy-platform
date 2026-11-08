"""cell_evidence: every stop keeps the seconds around it from every camera as one hashed bundle, a dead camera is a gap,
and a finished pick descent is kept once per carry as the control."""
import hashlib
import json
import sys
import time
from pathlib import Path

import pytest

np = pytest.importorskip("numpy")
pytest.importorskip("cv2")
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "deploy/robot/omx"))
import cell_evidence as ev  # noqa: E402
import cell_hooks  # noqa: E402
import omx_incident  # noqa: E402


class Cell:
    def __init__(self):
        self.calls = 0

    def frame(self, camera):
        self.calls += 1
        if camera == "side":
            raise OSError("the hub dropped it")
        return np.full((48, 64, 3), 90, np.uint8)


def test_the_ring_keeps_every_camera_and_names_a_dead_one_as_a_gap(monkeypatch):
    monkeypatch.setattr(ev, "AFTER_S", 0.0)
    ring = ev.Ring(Cell().frame, ["top", "side"], period_s=0.01, keep_s=0.05)
    time.sleep(0.3)
    ring.close()
    frames, gaps = ring.window(0)
    assert frames and all(camera == "top" for _, camera, _ in frames)
    assert gaps and all(camera == "side" and "dropped" in why for _, camera, why in gaps)
    assert frames[-1][0] - frames[0][0] <= 0.1  # 0.3 s ran, only the last 0.05 s (and a tick) stay


def test_a_bundle_lists_every_file_with_its_hash_and_only_the_newest_stay(tmp_path, monkeypatch):
    monkeypatch.setattr(ev, "MAX_BUNDLES", 2)
    for i in range(3):
        out = ev.write(tmp_path, "stop", "arm_b", 100.0, [(98.0 + i, "top", b"jpeg%d" % i)], [(99.5, "side", "dropped")],
                       {"stop": {"error": "contact"}}, {"trace-tail.jsonl": b"{}"})
        time.sleep(0.002)  # the stamp orders the bundles
    kept = sorted(tmp_path.iterdir())
    assert len(kept) == 2 and kept[-1] == out
    twins = [ev.write(tmp_path / "twins", "stop", "arm_b", 100.0, [], [], {}) for _ in range(2)]  # one instant, two stops
    assert twins[0] != twins[1] and all(t.is_dir() for t in twins)
    manifest = json.loads((out / "manifest.json").read_text())
    assert manifest["schema"] == ev.SCHEMA and manifest["gaps"] == [{"camera": "side", "t_rel_s": -0.5, "why": "dropped"}]
    for listed in manifest["files"]:
        assert hashlib.sha256((out / listed["file"]).read_bytes()).hexdigest() == listed["sha256"]
    assert manifest["files"][0]["file"] == "top-+0.0-0.jpg"  # numbered: one tenth of a second may hold two frames


def test_a_stop_and_one_control_per_carry_are_bundled_and_close_waits_for_them(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(omx_incident, "INCIDENTS", tmp_path / "incidents")
    monkeypatch.setattr(omx_incident, "STILLS", tmp_path / "incidents" / "stills")
    monkeypatch.setattr(ev, "AFTER_S", 0.05)
    (tmp_path / "trace-arm_b-1.jsonl").write_text('{"t": 1, "load": {"current_ma": [0, 0, 0, 80, 0, 0]}}\n')
    config = {"arm_id": "arm_b", "cameras": {"top": {}, "side": {}}, "evidence": {"period_s": 0.01, "keep_s": 0.5}}
    stills = cell_hooks.stills(Cell(), config)
    time.sleep(0.1)
    stills.control({"command": "run descend_pick", "ok": True, "state": [0] * 6})
    stills.control({"command": "run descend_pick", "ok": True, "state": [0] * 6})  # once per carry
    stills([0] * 6, {"command": "run descend_pick", "ok": False, "contact": True, "error": "contact in descend_pick"})
    stills.close()
    bundles = sorted((tmp_path / "incidents" / "evidence").iterdir())
    assert [b.name.rsplit("-", 1)[-1] for b in bundles] == ["control", "stop"]
    stop = json.loads((bundles[-1] / "manifest.json").read_text())
    assert stop["stop"]["error"] == "contact in descend_pick" and stop["gaps"]
    assert any(f["camera"] == "top" for f in stop["files"] if "camera" in f)
    assert b'"current_ma"' in (bundles[-1] / "trace-tail.jsonl").read_bytes()
    assert sorted(p.name for p in (tmp_path / "incidents" / "stills").iterdir()) == ["arm_b-top.jpg"]  # D-971 stills as before
    assert not stills.ring.thread.is_alive() or stills.ring.stopped.is_set()


def test_without_evidence_config_a_stop_keeps_only_the_stills(tmp_path, monkeypatch):
    monkeypatch.setattr(omx_incident, "INCIDENTS", tmp_path / "incidents")
    monkeypatch.setattr(omx_incident, "STILLS", tmp_path / "incidents" / "stills")
    stills = cell_hooks.stills(Cell(), {"arm_id": "arm_b", "cameras": {"top": {}}})
    stills([0] * 6, {"contact": True})
    stills.close()
    assert stills.ring is None and not (tmp_path / "incidents" / "evidence").exists()
