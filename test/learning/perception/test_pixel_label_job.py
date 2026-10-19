"""A draft job cannot start from unverified pixels or source identity."""
import ast
import hashlib
import importlib.util
import json
import subprocess
import sys
from contextlib import nullcontext
from pathlib import Path
from types import SimpleNamespace

import pytest


SCRIPT = Path(__file__).resolve().parents[3] / 'learning/curation/perception/pixel_label_job.py'


def job_module():
    assert SCRIPT.is_file(), "pixel label input doctor is missing"
    spec = importlib.util.spec_from_file_location("pixel_label_job", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


@pytest.mark.parametrize("declared", [None, "20261006T010000Z_robot"])
def test_prepare_sources_binds_png_to_exact_decoded_video_frame(tmp_path, declared):
    import cv2
    import numpy as np
    video = tmp_path / "teleop_robot_20261006T010000Z.mp4"
    writer = cv2.VideoWriter(str(video), cv2.VideoWriter_fourcc(*"mp4v"), 5, (32, 24))
    assert writer.isOpened()
    for value in (30, 120, 210):
        writer.write(np.full((24, 32, 3), value, dtype=np.uint8))
    writer.release()
    spec = {"sources": [{"video": str(video), "sha256": digest(video),
                          "capture_group": "robot-day", "frames": [0, 2]}]}
    if declared is not None:
        spec["sources"][0]["source_session"] = declared
    out = tmp_path / "prepared"

    assert job_module().prepare_sources(spec, out) == 2
    rows = [json.loads(line) for line in (out / "verified-inputs.jsonl").read_text().splitlines()]
    assert [row["video_frame"] for row in rows] == [0, 2]
    assert {row["source_session"] for row in rows} == {"20261006T010000Z_robot"}
    assert {row["capture_group"] for row in rows} == {"robot-day"}
    assert [row["image"] for row in rows] == [
        "images/20261006T010000Z_robot__000000.png",
        "images/20261006T010000Z_robot__000002.png"]
    copied = out / rows[0]["source_video"]
    assert digest(copied) == digest(video) == rows[0]["source_video_sha256"]
    cap = cv2.VideoCapture(str(copied))
    decoded = []
    while True:
        ok, frame = cap.read()
        if not ok:
            break
        decoded.append(frame)
    cap.release()
    for row in rows:
        image = out / row["image"]
        assert digest(image) == row["image_sha256"]
        assert np.array_equal(cv2.imdecode(np.frombuffer(image.read_bytes(), np.uint8), cv2.IMREAD_COLOR),
                              decoded[row["video_frame"]])
    assert (out / "classes.yaml").is_file()
    assert not list(out.rglob("READY"))


LEGACY_SESSION = "legacy-teleop-20260919-151213"
# Independently recorded original inventory; never derived from producer output.
LEGACY_ORIGINALS = [
    (3027828, "939180124c12e8eedb200ba3a34901149557a1e4c110b2781ea345b4bda7d22d"),  # SHA256 original fixture integrity
    (3354324, "e88325e134af782121838ef77324cc5e186b8dfd3a7b6213f4a5ffe074140be5"),  # SHA256 original fixture integrity
    (3648053, "d5a0e6c84160e73925e469553a693c84bd7c373627a2146a58828a4bdb91533c"),  # SHA256 original fixture integrity
    (3795012, "ca6dab1ed6140f13372c0510d71dafcb54989b29cab601abf5fb0b3bebe1779f"),  # SHA256 original fixture integrity
    (3232286, "ed52707f3dda5a8104ef9df4b65a24c786e410161cb449f1ff4989a30453d151"),  # SHA256 original fixture integrity
    (4190305, "0916bb53747546823b4c945570e404d542bec6f92023f3a624cbe7e150b3e0d1"),  # SHA256 original fixture integrity
    (866985, "204d52d0a95819a2dfe788f814268ab1d67952838304093c3f95420fdf72e131"),  # SHA256 original fixture integrity
]


def prepare_legacy(tmp_path):
    # Codec/dependency absence is a failure: these are actual seven-part decode tests.
    import cv2
    import numpy as np

    root = SCRIPT.parents[3]
    sources = []
    for part, (size, expected) in enumerate(LEGACY_ORIGINALS, 1):
        video = root / "data/teleop/learning" / f"teleop_20260919_151213_part{part:02}.mp4"
        assert video.stat().st_size == size
        assert digest(video) == expected
        sources.append(dict(video=str(video), sha256=expected, frames=[0],
                            capture_group=LEGACY_SESSION, source_session=LEGACY_SESSION))
    out = tmp_path / "prepared"
    assert job_module().prepare_sources({"sources": sources}, out) == 7
    rows = [json.loads(line) for line in (out / "verified-inputs.jsonl").read_text().splitlines()]
    assert len(rows) == 7
    assert len({row["image"] for row in rows}) == 7
    assert len(list((out / "images").glob("*.png"))) == 7
    assert len({(row["source_video_sha256"], row["video_frame"]) for row in rows}) == 7
    for source, row in zip(sources, rows):
        expected = source["sha256"]
        original = Path(source["video"])
        assert row["source_video"] == f"videos/{original.name}"
        copied = out / row["source_video"]
        assert copied.read_bytes() == original.read_bytes()
        assert digest(copied) == digest(original) == row["source_video_sha256"] == expected
        assert row["source_session"] == row["capture_group"] == LEGACY_SESSION
        assert row["video_frame"] == 0
        assert expected in Path(row["image"]).name  # Full original SHA separates same-session parts.
        assert LEGACY_SESSION in Path(row["image"]).name
        assert not Path(row["image"]).is_absolute()
        assert not Path(row["source_video"]).is_absolute()
        assert not {"device_id", "capture_time_utc", "timestamp_basis", "video_time_s",
                    "mask", "approval", "reader_verified", "training_admission"} & row.keys()
        cap = cv2.VideoCapture(str(copied))
        try:
            assert cap.isOpened()
            ok, decoded = cap.read()
            assert ok
        finally:
            cap.release()
        image = out / row["image"]
        raw = image.read_bytes()
        assert digest(image) == row["image_sha256"]
        assert raw == cv2.imencode(".png", decoded)[1].tobytes()
        assert np.array_equal(cv2.imdecode(np.frombuffer(raw, np.uint8), cv2.IMREAD_COLOR), decoded)
        assert (row["height"], row["width"]) == decoded.shape[:2]
    assert not list(out.rglob("READY"))
    return out, rows


def test_prepare_legacy_seven_original_parts_have_exact_distinct_pngs(tmp_path):
    out, rows = prepare_legacy(tmp_path)
    assert {row["capture_group"] for row in rows} == {LEGACY_SESSION}
    assert (out / "classes.yaml").is_file()


def test_prepare_legacy_roundtrip_cli_keeps_pending_and_preserves_human_review(tmp_path):
    import numpy as np
    import review_masks
    from review_app import ReviewStore

    out, rows = prepare_legacy(tmp_path)
    # Relocation demonstrates that the published catalog remains portable.
    moved = tmp_path / "portable-prepared"
    out.rename(moved)
    state = (tmp_path / "review").resolve()
    store = ReviewStore(state, empty_training=True)
    assert store.list_frames() == []
    assert review_masks.classes(store) is None
    command = [sys.executable, str(SCRIPT.parent / "edge_capture.py"), "import",
               str((moved / "verified-inputs.jsonl").resolve()), "--state", str(state)]

    def import_cli():
        completed = subprocess.run(command, cwd=moved, capture_output=True, text=True,
                                   timeout=120, check=False)
        assert completed.returncode == 0, completed.stderr
        return ast.literal_eval(completed.stdout.strip())

    assert import_cli() == {"added": 7, "pixel_reviews_pending": 7, "indices": list(range(7))}
    assert review_masks.classes(store)["sha256"] == digest(moved / "classes.yaml")
    sources = []
    for index, row in enumerate(rows):
        frame = store.get(index)
        assert frame["status"] == "pending"
        assert frame["review"]["review_status"] == "pending_human"
        assert frame["review"]["complete_frame_review"] is False
        source = frame["source"]
        assert source["source_session"] == source["source_session_declared"] == LEGACY_SESSION
        assert source["capture_group"] == LEGACY_SESSION
        assert source["source_video_sha256"] == row["source_video_sha256"]
        assert source["video_frame"] == 0
        assert source["original_video_verified"] is False
        assert source["timestamp_basis"] is source["video_time_s"] is None
        assert source.get("device_id") is source.get("capture_time_utc") is None
        mask = review_masks.get(store, index)
        assert mask["status"] == "pending" and mask["approval"] is None
        assert mask["complete"] == mask["background"] == 0
        assert np.all(review_masks.pixels(store, mask) == 255)
        assert digest(store.image(index)) == row["image_sha256"]
        sources.append(dict(source, frame=index))
    assert {source['source_session'] for source in sources} == {LEGACY_SESSION}
    assert {source['capture_group'] for source in sources} == {LEGACY_SESSION}
    with store.connect() as db:
        assert [row[0] for row in db.execute("SELECT identity FROM frame_keys ORDER BY frame")] == [
            f"video:{expected}:0" for _, expected in LEGACY_ORIGINALS]
        assert db.execute("SELECT COUNT(*) FROM pixel_events").fetchone()[0] == 0
    # Explicit test human action through the real review API, after proving zero approvals.
    current = review_masks.get(store, 0)
    filled = review_masks.update(store, 0, {"version": current["version"], "action": "fill",
                                          "label": 0}, ValueError, actor="test-human")
    approved = review_masks.update(store, 0, {"version": filled["version"], "action": "approve",
        "complete_frame_review": True, "background_reviewed": True}, ValueError, actor="test-human")
    before_frame, before_history = store.get(0), store.history(0)
    before_pixels = review_masks.pixels(store, approved).copy()
    assert approved["status"] == "approved"
    assert import_cli() == {"added": 0, "pixel_reviews_pending": 0, "indices": []}
    assert store.get(0) == before_frame and store.history(0) == before_history
    assert review_masks.get(store, 0) == approved
    assert np.array_equal(review_masks.pixels(store, approved), before_pixels)
    assert not list(tmp_path.rglob("READY"))


def forbid_preparation_io(module, monkeypatch):
    def forbidden(*args, **kwargs):
        pytest.fail("validation must refuse before video copy/decoder")
    monkeypatch.setattr(module.shutil, "copyfile", forbidden)
    monkeypatch.setattr(module.cv2, "VideoCapture", forbidden)


@pytest.mark.parametrize("declared", ["__absent__", None, "", "../escape", "/absolute", "a/b", "a\\b",
                                      ".", "..", "with space", "x" * 129, 4, [], {}])
def test_prepare_legacy_refuses_missing_or_unsafe_session_before_io(tmp_path, monkeypatch, declared):
    video = tmp_path / "teleop_20260919_151213_part01.mp4"
    video.write_bytes(b"unchanged-source")
    source = dict(video=str(video), sha256=digest(video), capture_group=LEGACY_SESSION, frames=[0])
    if declared != "__absent__":
        source["source_session"] = declared
    module = job_module()
    forbid_preparation_io(module, monkeypatch)
    out = tmp_path / "prepared"
    with pytest.raises(ValueError, match="source session"):
        module.prepare_sources({"sources": [source]}, out)
    assert not out.exists()


@pytest.mark.parametrize("declared", ["other-session", None, ""])
def test_prepare_canonical_refuses_contradictory_session_before_io(tmp_path, monkeypatch, declared):
    video = tmp_path / "teleop_robot_20261006T010000Z.mp4"
    video.write_bytes(b"unchanged-source")
    module = job_module()
    forbid_preparation_io(module, monkeypatch)
    out = tmp_path / "prepared"
    with pytest.raises(ValueError, match="source session"):
        module.prepare_sources({"sources": [dict(video=str(video), sha256=digest(video),
            capture_group="robot-day", frames=[0], source_session=declared)]}, out)
    assert not out.exists()


@pytest.mark.parametrize("broken, message", [("hash", "video hash"), ("budget", "2000"),
                                             ("relative", "absolute regular video")])
def test_prepare_declared_legacy_reaches_existing_refusals(tmp_path, monkeypatch, broken, message):
    video = tmp_path / "teleop_20260919_151213_part01.mp4"
    video.write_bytes(b"unchanged-source")
    source = dict(video=str(video), sha256=digest(video), capture_group=LEGACY_SESSION,
                  frames=[0], source_session=LEGACY_SESSION)
    if broken == "hash":
        source["sha256"] = "0" * 64
    elif broken == "budget":
        source["frames"] = list(range(2001))
    else:
        source["video"] = video.name
    module = job_module()
    forbid_preparation_io(module, monkeypatch)
    out = tmp_path / "prepared"
    with pytest.raises(ValueError, match=message):
        module.prepare_sources({"sources": [source]}, out)
    assert not out.exists()


def test_prepare_declared_legacy_refuses_ordinal_past_real_video(tmp_path):
    import cv2
    import numpy as np

    video = tmp_path / "teleop_20260919_151213_part01.mp4"
    writer = cv2.VideoWriter(str(video), cv2.VideoWriter_fourcc(*"mp4v"), 5, (32, 24))
    assert writer.isOpened()
    writer.write(np.full((24, 32, 3), 75, dtype=np.uint8))
    writer.release()
    out = tmp_path / "prepared"
    with pytest.raises(ValueError, match="frame index exceeds"):
        job_module().prepare_sources({"sources": [dict(video=str(video), sha256=digest(video),
            capture_group=LEGACY_SESSION, frames=[1], source_session=LEGACY_SESSION)]}, out)
    assert not out.exists()


def test_prepare_declared_legacy_refuses_source_change_during_snapshot(tmp_path, monkeypatch):
    video = tmp_path / "teleop_20260919_151213_part01.mp4"
    video.write_bytes(b"unchanged-source")
    expected = digest(video)
    module = job_module()
    copy = module.shutil.copyfile

    def copy_then_change(source, destination):
        copy(source, destination)
        video.write_bytes(b"changed-during-copy")

    def forbidden(*args, **kwargs):
        pytest.fail("source mutation must refuse before decoder")

    monkeypatch.setattr(module.shutil, "copyfile", copy_then_change)
    monkeypatch.setattr(module.cv2, "VideoCapture", forbidden)
    out = tmp_path / "prepared"
    with pytest.raises(ValueError, match="hash changed during snapshot"):
        module.prepare_sources({"sources": [dict(video=str(video), sha256=expected,
            capture_group=LEGACY_SESSION, frames=[0], source_session=LEGACY_SESSION)]}, out)
    assert not out.exists()


@pytest.mark.parametrize("legacy_first", [True, False], ids=["legacy-first", "canonical-first"])
def test_prepare_refuses_mixed_session_image_collision_before_overwrite(tmp_path, monkeypatch, legacy_first):
    import cv2
    import numpy as np

    def record(path, value):
        writer = cv2.VideoWriter(str(path), cv2.VideoWriter_fourcc(*"mp4v"), 5, (32, 24))
        assert writer.isOpened()
        writer.write(np.full((24, 32, 3), value, dtype=np.uint8))
        writer.release()
        cap = cv2.VideoCapture(str(path))
        try:
            assert cap.isOpened()
            ok, pixels = cap.read()
            assert ok
            return pixels
        finally:
            cap.release()

    legacy = tmp_path / "teleop_20260919_151213_part01.mp4"
    legacy_pixels = record(legacy, 35)
    legacy_sha = digest(legacy)
    declared = "20261006T010000Z_robot"
    canonical = tmp_path / f"teleop_robot__{legacy_sha}_20261006T010000Z.mp4"
    canonical_pixels = record(canonical, 205)
    assert not np.array_equal(legacy_pixels, canonical_pixels)
    assert legacy.name != canonical.name and legacy_sha != digest(canonical)
    module = job_module()
    # Both admitted naming rules resolve to this same destination before the guard.
    assert module.edge_review.session(canonical.name) == f"{declared}__{legacy_sha}"
    sources = [dict(video=str(legacy), sha256=legacy_sha, capture_group="mixed", frames=[0],
                    source_session=declared),
               dict(video=str(canonical), sha256=digest(canonical), capture_group="mixed", frames=[0])]
    if not legacy_first:
        sources.reverse()
    originals = {path: path.read_bytes() for path in (legacy, canonical)}
    writes, write_bytes = [], Path.write_bytes

    def observe_write(path, raw):
        if path.suffix == ".png":
            writes.append(path.name)
        return write_bytes(path, raw)

    monkeypatch.setattr(Path, "write_bytes", observe_write)
    out = tmp_path / "prepared"
    with pytest.raises(ValueError, match="duplicate image"):
        module.prepare_sources({"sources": sources}, out)
    assert writes == [f"{declared}__{legacy_sha}__000000.png"]
    assert not out.exists()
    assert {path: path.read_bytes() for path in originals} == originals


def test_prepare_sources_rejects_changed_video_before_publishing(tmp_path):
    video = tmp_path / "teleop_robot_20261006T010000Z.mp4"
    video.write_bytes(b"changed")
    out = tmp_path / "prepared"
    with pytest.raises(ValueError, match="video hash"):
        job_module().prepare_sources({"sources": [{"video": str(video), "sha256": "0" * 64,
                                       "capture_group": "robot-day", "frames": [0]}]}, out)
    assert not out.exists()


def inputs(tmp_path):
    cv2, np = pytest.importorskip("cv2"), pytest.importorskip("numpy")
    frame = tmp_path / "frame.png"
    frame.write_bytes(cv2.imencode(".png", np.zeros((24, 32, 3), dtype=np.uint8))[1].tobytes())
    video = tmp_path / "teleop_robot_20261006T010000Z.mp4"
    video.write_bytes(b"original-video")
    classes = tmp_path / "classes.yaml"
    classes.write_text("classes:\n  - {index: 0, name: floor, role: background, color: [0, 0, 0]}\n"
                       "  - {index: 1, name: lane_line, role: lane_marking, color: [255, 255, 255]}\n")
    checkpoint = tmp_path / "model.onnx"
    checkpoint.write_bytes(b"fixed-checkpoint")
    evaluation = tmp_path / "eval.json"
    evaluation.write_text(json.dumps({"frames": [{"session": "different-session", "split": "eval"}]}))
    catalog = tmp_path / "verified-inputs.jsonl"
    row = {"image": frame.name, "image_sha256": digest(frame), "width": 32, "height": 24,
           "source_video": video.name, "source_video_sha256": digest(video), "video_frame": 7,
           "source_session": "20261006T010000Z_robot", "capture_group": "session-a"}
    catalog.write_text(json.dumps(row) + "\n")
    config = {"catalog": str(catalog), "classes": str(classes), "classes_sha256": digest(classes),
              "checkpoint": {"path": str(checkpoint), "sha256": digest(checkpoint)},
              "eval_sets": [{"path": str(evaluation), "sha256": digest(evaluation)}],
              "source_commit": "a" * 40, "environment_fingerprint": "b" * 64}
    return config, row, catalog


def test_doctor_verifies_originals_without_inventing_geometry(tmp_path):
    config, _, _ = inputs(tmp_path)
    result = job_module().verify_inputs(config)
    assert result["frames"] == 1
    assert result["geometry"] is None
    assert result["source_commit"] == "a" * 40


def test_doctor_records_gpu_and_refuses_wrong_active_code(tmp_path, monkeypatch):
    config, _, _ = inputs(tmp_path)
    active = tmp_path / "model-code-state.json"
    active.write_text(json.dumps({"source_commit": "a" * 40,
                                  "environment_sha256": "b" * 64}))
    config["model_code_state"] = str(active)
    config["api_token"] = "never-in-a-receipt"
    cfg = tmp_path / "config.json"
    cfg.write_text(json.dumps(config))
    module = job_module()
    monkeypatch.setattr(module, "probe_gpu", lambda: {"verdict": "pass", "name": "test GPU",
                                                 "memory_total_mib": 16000,
                                                 "memory_free_mib": 12000,
                                                 "driver": "test", "torch_cuda": True}, raising=False)
    monkeypatch.setattr(module, "probe_onnx_cuda", lambda _path: {"verdict": "pass"})
    out = tmp_path / "private-receipt"
    assert module.main(["doctor", "--config", str(cfg), "--out", str(out)]) == 0
    receipt = json.loads((out / "doctor.json").read_text())
    assert receipt["gpu"]["verdict"] == "pass"
    assert receipt["input_verdict"] == "pass"
    assert "never-in-a-receipt" not in (out / "doctor.json").read_text()
    active.write_text(json.dumps({"source_commit": "c" * 40,
                                  "environment_sha256": "b" * 64}))
    assert module.main(["doctor", "--config", str(cfg), "--out", str(tmp_path / "denied")]) == 1
    assert not (tmp_path / "denied").exists()


def test_doctor_holds_when_onnx_cuda_cannot_open(tmp_path, monkeypatch):
    config, _, _ = inputs(tmp_path)
    active = tmp_path / "model-code-state.json"
    active.write_text(json.dumps({"source_commit": "a" * 40,
                                  "environment_sha256": "b" * 64}))
    config["model_code_state"] = str(active)
    cfg = tmp_path / "config.json"
    cfg.write_text(json.dumps(config))
    module = job_module()
    monkeypatch.setattr(module, "probe_gpu", lambda: {"verdict": "pass"})
    monkeypatch.setattr(module.prelabel, "_open_model", lambda *_args, **_kwargs:
                        (_ for _ in ()).throw(RuntimeError("required ONNX provider unavailable")))
    out = tmp_path / "doctor"
    assert module.main(["doctor", "--config", str(cfg), "--out", str(out)]) == 1
    assert json.loads((out / "doctor.json").read_text())["gpu"]["verdict"] == "hold"


@pytest.mark.parametrize("changed", ["image", "video", "classes", "invalid_classes",
                                     "checkpoint", "identity", "missing_catalog"])
def test_doctor_rejects_changed_or_unbound_inputs(tmp_path, changed):
    config, row, catalog = inputs(tmp_path)
    if changed == "identity":
        row.pop("capture_group")
        catalog.write_text(json.dumps(row) + "\n")
    elif changed == "classes":
        Path(config["classes"]).write_text("classes: []\n")
    elif changed == "invalid_classes":
        Path(config["classes"]).write_text("classes:\n  - {index: 255, name: bad, role: background, color: [0, 0, 0]}\n")
        config["classes_sha256"] = digest(Path(config["classes"]))
    elif changed == "checkpoint":
        Path(config["checkpoint"]["path"]).write_bytes(b"other-model")
    elif changed == "video":
        (catalog.parent / row["source_video"]).write_bytes(b"other-video")
    elif changed == "missing_catalog":
        config.pop("catalog")
    else:
        (catalog.parent / row["image"]).write_bytes(b"other-frame")
    with pytest.raises(ValueError):
        job_module().verify_inputs(config)


def test_draft_preserves_original_size_ignore_and_verified_resume(tmp_path, monkeypatch):
    cv2, np = pytest.importorskip("cv2"), pytest.importorskip("numpy")
    config, row, catalog = inputs(tmp_path)
    active = tmp_path / "model-code-state.json"
    active.write_text(json.dumps({"source_commit": "a" * 40,
                                  "environment_sha256": "b" * 64}))
    config["model_code_state"] = str(active)
    cfg = tmp_path / "config.json"
    cfg.write_text(json.dumps(config))
    mod = job_module()
    monkeypatch.setattr(mod, "probe_gpu", lambda: {"verdict": "pass"})
    monkeypatch.setattr(mod.train_job, "gpu_lease", nullcontext)
    calls = []
    classes = (SimpleNamespace(index=0, name="floor", role="background"),
               SimpleNamespace(index=1, name="lane_line", role="lane_marking"))
    spec = SimpleNamespace(height=8, width=8, shape=(1, 3, 8, 8), color="bgr",
                           scale=1.0 / 255, mean=(0, 0, 0), std=(1, 1, 1), crop=None)

    class Session:
        def run(self, image):
            calls.append(image.shape)
            logits = np.zeros((1, 2, 8, 8), np.float32)
            logits[:, 1, :4, :] = 8
            return logits

    manifest_file = tmp_path / "model_manifest.json"
    manifest_file.write_text("{}")
    model = SimpleNamespace(manifest=SimpleNamespace(classes=classes, input=spec,
                                                      raw={'output': {'classes': [vars(c) for c in classes]}},
                                                      folder=tmp_path,
                                                      onnx_file=lambda: tmp_path / "model.onnx"),
                            model_revision="lane-test")
    monkeypatch.setattr(mod.prelabel, "_open_model", lambda path, providers=None: (model, Session()))
    out = tmp_path / "job"
    assert mod.main(["draft", "--config", str(cfg), "--out", str(out)]) == 0
    mask_path = out / "drafts" / "000000.png"
    mask = cv2.imread(str(mask_path), cv2.IMREAD_UNCHANGED)
    assert mask.dtype == np.uint8 and mask.shape == (24, 32)
    assert set(np.unique(mask)) == {1, 255}
    receipt = json.loads((out / "draft-receipt.json").read_text())
    assert receipt["frames"][0]["source_video_sha256"] == row["source_video_sha256"]
    assert receipt["frames"][0]["mask_sha256"] == digest(mask_path)
    assert receipt["frames"][0]["transform"] == "nearest_original_size"
    indexed = json.loads((out / "verified-inputs.jsonl").read_text().splitlines()[0])
    assert indexed['annotation_source'] == 'model_pixel_draft'
    assert 'lane-test' in indexed['annotation_note']
    assert indexed["mask"] == {"indexed_png": "drafts/000000.png", "sha256": digest(mask_path),
                               "classes_sha256": digest(Path(config["classes"]))}
    assert (out / "classes.yaml").read_bytes() == Path(config["classes"]).read_bytes()
    assert len(calls) == 1
    assert mod.main(["draft", "--config", str(cfg), "--out", str(out)]) == 0
    assert len(calls) == 1
    mask_path.write_bytes(b"changed")
    assert mod.main(["draft", "--config", str(cfg), "--out", str(out)]) == 1
    assert len(calls) == 1
    assert not (out / "READY").exists()


def test_draft_refuses_model_road_retagging_before_inference_and_output(tmp_path, monkeypatch):
    config, _, _ = inputs(tmp_path)
    classes_path = Path(config['classes'])
    classes_path.write_text(classes_path.read_text() +
        '  - {index: 2, name: road, role: drivable, semantic: road_surface/1, color: [0, 255, 0]}\n')
    config['classes_sha256'] = digest(classes_path)
    mod = job_module()
    monkeypatch.setattr(mod, '_active_code', lambda config: None)
    monkeypatch.setattr(mod, 'probe_gpu', lambda: {'verdict': 'pass'})
    monkeypatch.setattr(mod.train_job, 'gpu_lease', nullcontext)
    raw = mod.build.load_classes(classes_path)
    raw[-1]['semantic'] = 'current_road_region/1'
    model = SimpleNamespace(manifest=SimpleNamespace(
        classes=[SimpleNamespace(index=c['index'], name=c['name'], role=c['role']) for c in raw],
        raw={'output': {'classes': raw}}, onnx_file=lambda: Path(config['checkpoint']['path'])))
    monkeypatch.setattr(mod.prelabel, '_open_model', lambda *args, **kwargs: (model, None))
    out = tmp_path / 'job'
    with pytest.raises(mod.build.BuildError, match='semantic'):
        mod.run_draft(config, out)
    assert not out.exists()


def test_model_only_drivable_is_unlabelled_and_bad_logits_fail():
    np = pytest.importorskip("numpy")
    mod = job_module()
    classes = (SimpleNamespace(index=0, role="background"),
               SimpleNamespace(index=1, role="lane_marking"),
               SimpleNamespace(index=2, role="drivable"))
    logits = np.zeros((1, 3, 2, 2), np.float32)
    logits[0, 2, 0, 0] = 10
    logits[0, 1, 0, 1] = 10
    mask = mod.draft_mask(logits, classes, (4, 6), 0.6)
    assert mask.shape == (4, 6)
    assert mask[0, 0] == 255 and mask[0, -1] == 1
    assert mask[-1, 0] == 255
    logits[0, 1, 0, 1] = np.nan
    with pytest.raises(ValueError, match="logits"):
        mod.draft_mask(logits, classes, (4, 6), 0.6)
