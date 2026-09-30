"""D-379: session catalog and the auto-label dataset build into the store layout."""
import hashlib
import json

import numpy as np
import pytest

cv2 = pytest.importorskip("cv2")

import build  # noqa: E402
import catalog  # noqa: E402
import labels as L  # noqa: E402


def _labels_dir(root, session, frames):
    """frames: list of (mask value fill, conflict flag)."""
    d = root / "labels" / session
    for sub in ("frames", "masks", "conf"):
        (d / sub).mkdir(parents=True)
    rows = []
    for i, (fill, conflict) in enumerate(frames):
        cv2.imwrite(str(d / "frames" / f"{i:06d}.jpg"), np.full((24, 32, 3), 100 + i, np.uint8))
        mask = np.full((24, 32), fill, np.uint8)
        mask[:4] = L.WALL
        cv2.imwrite(str(d / "masks" / f"{i:06d}.png"), mask)
        cv2.imwrite(str(d / "conf" / f"{i:06d}.png"), np.full((24, 32), 200, np.uint8))
        rows.append({"index": i, "session": session, "version": L.LABEL_VERSION, "conflict": conflict,
                     "sources": ["lidar"], "disagreement": {}})
    (d / "labels.jsonl").write_text("".join(json.dumps(r) + "\n" for r in rows), encoding="utf-8")
    (d / "meta.json").write_text(json.dumps({
        "version": L.LABEL_VERSION, "session": session, "classes": L.CLASSES,
        "ignore_index": L.IGNORE_INDEX, "camera": {"pitch_deg": 11.7},
        "session_json": {"schema": "rosy.recording.session/1", "device": "d", "reason": session}}),
        encoding="utf-8")
    return d


def test_content_sha_is_the_sorted_path_hash_listing(tmp_path):
    (tmp_path / "b").mkdir()
    (tmp_path / "b" / "x.bin").write_bytes(b"xx")
    (tmp_path / "a.txt").write_bytes(b"a")
    lines = sorted([f"a.txt\0{hashlib.sha256(b'a').hexdigest()}\n",
                    f"b/x.bin\0{hashlib.sha256(b'xx').hexdigest()}\n"])
    assert build.content_sha(tmp_path) == hashlib.sha256("".join(lines).encode()).hexdigest()
    before = build.content_sha(tmp_path)
    (tmp_path / "a.txt").write_bytes(b"A")
    assert build.content_sha(tmp_path) != before


def test_auto_build_lands_in_the_store_by_content_sha(tmp_path):
    a = _labels_dir(tmp_path, "20260930T124745Z_d", [(L.DRIVABLE, False), (L.FLOOR, True)])
    b = _labels_dir(tmp_path, "20260930T133221Z_d", [(L.FLOOR, False), (L.UNKNOWN, False)])
    store = tmp_path / "store"
    manifest, final = build.build_auto_dataset([a, b], store, "lanes", min_labelled=0.2)
    assert final.parent == store / "datasets" / "lanes"
    assert final.name == build.content_sha(final)
    on_disk = json.loads((final / "manifest.json").read_text(encoding="utf-8"))
    assert on_disk == manifest
    assert manifest["schema"] == build.SCHEMA
    assert manifest["classes"] == L.CLASSES and manifest["ignore_index"] == L.IGNORE_INDEX
    kept = [(f["session"], f["image"]) for f in manifest["frames"]]
    assert kept == [("20260930T124745Z_d", "images/20260930T124745Z_d/20260930T124745Z_d__000000.jpg"),
                    ("20260930T133221Z_d", "images/20260930T133221Z_d/20260930T133221Z_d__000000.jpg")]
    # every 5th sorted session is val, and a session never spans splits
    assert {f["session"]: f["split"] for f in manifest["frames"]} == {
        "20260930T124745Z_d": "val", "20260930T133221Z_d": "train"}
    assert manifest["deleted_indexes"] == ["20260930T124745Z_d__000001"]
    reasons = {e["frame"]: e["reason"] for e in manifest["excluded"]}
    assert reasons["20260930T133221Z_d__000001"] == "labelled 0.167 < 0.2"
    mask = cv2.imread(str(final / manifest["frames"][0]["mask"]), cv2.IMREAD_UNCHANGED)
    assert mask.ndim == 2 and mask.dtype == np.uint8 and set(np.unique(mask)) == {L.WALL, L.DRIVABLE}
    assert {s["reason"] for s in manifest["sources"]} == {"20260930T124745Z_d", "20260930T133221Z_d"}
    assert all(v["version"] == L.LABEL_VERSION for v in manifest["labels"])
    # same inputs -> same version, and the staging folder is gone
    again, final2 = build.build_auto_dataset([a, b], store, "lanes", min_labelled=0.2)
    assert final2 == final
    assert [p.name for p in (store / "datasets" / "lanes").iterdir()] == [final.name]


def test_auto_build_cli_needs_store_and_name(tmp_path, capsys):
    a = _labels_dir(tmp_path, "s1", [(L.FLOOR, False)])
    with pytest.raises(SystemExit):
        build.main(["--auto-labels", str(a)])
    b = _labels_dir(tmp_path, "s2", [(L.FLOOR, False)])
    assert build.main(["--auto-labels", str(a), str(b), "--store", str(tmp_path / "st"),
                       "--name", "n"]) == 0
    assert "2 frames" in capsys.readouterr().out


def _raw_session(root, name, reason, topics=("camera/front", "odom", "scan")):
    s = root / "raw" / name
    (s / "bag").mkdir(parents=True)
    (s / "bag" / "bag_0.mcap").write_bytes(b"mcap-bytes")
    (s / "session.json").write_text(json.dumps({
        "schema": "rosy.recording.session/1", "device": "rosy-pinky-8kcn", "reason": reason,
        "started_at": "2026-09-30T13:32:22+00:00", "ended_at": "2026-09-30T13:46:51+00:00",
        "topics": list(topics)}), encoding="utf-8")
    (s / "bag" / "metadata.yaml").write_text(
        "rosbag2_bagfile_information:\n  duration:\n    nanoseconds: 869000000000\n"
        "  topics_with_message_count:\n" + "".join(
            f"    - topic_metadata:\n        name: /rosy_60/{t}\n      message_count: 7\n" for t in topics),
        encoding="utf-8")
    return s


def test_catalog_scan_finds_artefacts_and_keeps_hand_fields(tmp_path):
    pytest.importorskip("yaml")
    root = tmp_path / "perception"
    name = "20260930T133221Z_rosy-pinky-8kcn"
    _raw_session(root, name, "intersection-claude-scripted")
    videos = tmp_path / "teleop"
    videos.mkdir()
    for ext in (".mp4", ".jsonl", ".json", ".scan.npz"):
        (videos / f"teleop_rosy-pinky-8kcn_20260930T133221Z{ext}").write_bytes(b"v" + ext.encode())
    lab = _labels_dir(root, name, [(L.FLOOR, False)])
    other = _labels_dir(tmp_path, "20260930T124745Z_rosy-pinky-8kcn", [(L.FLOOR, False)])
    store = tmp_path / "store"
    _, final = build.build_auto_dataset([other, lab], store, "lanes")
    args = ["--root", str(root), "scan", "--video-dir", str(videos), "--store", str(store)]
    assert catalog.main(args) == 0
    (row,) = catalog.load(root / "catalog.jsonl")
    assert row["session"] == name and row["schema"] == catalog.SCHEMA
    assert row["driver"] == "claude-scripted" and row["driver_inferred"] is True
    assert row["duration_s"] == 869.0 and row["has_scan"] is True
    assert row["topics"] == {"camera/front": 7, "odom": 7, "scan": 7}
    mcap = next(f for f in row["files"] if f["path"].endswith("bag_0.mcap"))
    assert mcap["sha256"] == hashlib.sha256(b"mcap-bytes").hexdigest()
    (video,) = row["derived"]["video"]
    assert set(video) == {"video", "sidecar", "meta", "scan", "sha256"}
    assert row["derived"]["labels"][0]["version"] == L.LABEL_VERSION
    assert row["derived"]["datasets"] == [{"name": "lanes", "version": final.name, "split": "train"}]
    assert catalog.main(["--root", str(root), "update-tags", name, "--add", "intersection,wall",
                         "--driver", "human", "--error", "D-378/E2"]) == 0
    assert catalog.main(args) == 0  # rescan keeps what a person set
    (row,) = catalog.load(root / "catalog.jsonl")
    assert row["scene_tags"] == ["intersection", "wall"]
    assert row["driver"] == "human" and row["driver_inferred"] is False
    assert row["errors"] == ["D-378/E2"]


def test_catalog_reuses_hashes_while_files_are_unchanged(tmp_path, monkeypatch):
    pytest.importorskip("yaml")
    root = tmp_path / "p"
    _raw_session(root, "20260930T124745Z_x", "real-lane-drive")
    assert catalog.main(["--root", str(root), "scan", "--video-dir", str(tmp_path)]) == 0
    calls = []
    real = catalog.sha256
    monkeypatch.setattr(catalog, "sha256", lambda p: calls.append(p) or real(p))
    assert catalog.main(["--root", str(root), "scan", "--video-dir", str(tmp_path)]) == 0
    assert calls == []
    (row,) = catalog.load(root / "catalog.jsonl")
    assert row["driver"] == "human" and row["has_scan"] is True


def test_catalog_add_and_list(tmp_path, capsys):
    pytest.importorskip("yaml")
    root = tmp_path / "p"
    s = _raw_session(root, "20260930T124745Z_x", "real-lane-drive", topics=("camera/front", "odom"))
    assert catalog.main(["--root", str(root), "add", str(s), "--driver", "human",
                         "--tags", "straight,curve", "--video-dir", str(tmp_path)]) == 0
    assert catalog.main(["--root", str(root), "list", "--tag", "curve"]) == 0
    out = capsys.readouterr().out
    assert "20260930T124745Z_x" in out and "scan=n" in out
