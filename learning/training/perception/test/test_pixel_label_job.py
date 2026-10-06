"""A draft job cannot start from unverified pixels or source identity."""
import hashlib
import importlib.util
import json
from contextlib import nullcontext
from pathlib import Path
from types import SimpleNamespace

import pytest


SCRIPT = Path(__file__).resolve().parents[1] / "dataset" / "pixel_label_job.py"


def job_module():
    assert SCRIPT.is_file(), "pixel label input doctor is missing"
    spec = importlib.util.spec_from_file_location("pixel_label_job", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


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
                           scale=1.0 / 255, mean=(0, 0, 0), std=(1, 1, 1))

    class Session:
        def run(self, image):
            calls.append(image.shape)
            logits = np.zeros((1, 2, 8, 8), np.float32)
            logits[:, 1, :4, :] = 8
            return logits

    manifest_file = tmp_path / "model_manifest.json"
    manifest_file.write_text("{}")
    model = SimpleNamespace(manifest=SimpleNamespace(classes=classes, input=spec,
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
