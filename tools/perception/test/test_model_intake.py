"""Task 9: model export and intake (D-356)."""
import json
import sys
from pathlib import Path

import numpy as np
import pytest

ROOT = Path(__file__).resolve().parents[3]
for _p in (ROOT / "tools" / "perception" / "model", ROOT / "tools" / "perception" / "training"):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

import intake  # noqa: E402

GATE = {"max_host_latency_ms_p50": 400, "max_nan_frames": 0, "min_visible_fraction": 0.30,
        "replay_sources": ["data/teleop/learning/*.mp4"], "max_frames_per_source": 200}
GOOD = {"frames": 100, "latency_ms": {"p50": 50.0, "p95": 80.0}, "nan_frames": 0,
        "visible_fraction": 0.8}


def test_judge_pass():
    assert intake.judge(GOOD, GATE) == ("pass", [])


@pytest.mark.parametrize("over, word", [
    ({"latency_ms": {"p50": 401.0, "p95": 500.0}}, "latency"),
    ({"nan_frames": 1}, "nan"),
    ({"visible_fraction": 0.29}, "visible"),
    ({"frames": 0}, "frames"),
])
def test_judge_fail_reasons(over, word):
    verdict, reasons = intake.judge(dict(GOOD, **over), GATE)
    assert verdict == "fail"
    assert len(reasons) == 1 and word in reasons[0].lower()


def test_judge_collects_every_reason():
    stats = dict(GOOD, nan_frames=3, visible_fraction=0.0, latency_ms={"p50": 999, "p95": 999})
    verdict, reasons = intake.judge(stats, GATE)
    assert verdict == "fail" and len(reasons) == 3


@pytest.mark.parametrize("src", ["hf:org/repo@main", "hf:org/repo@v1.0", "hf:org/repo",
                                 "hf:org/repo@" + "a" * 39, "hf:org/repo@" + "g" * 40])
def test_hf_source_refuses_non_commit(src):
    with pytest.raises(ValueError):
        intake.resolve_source(src, downloader=lambda **kw: pytest.fail("downloaded"))


def test_hf_source_pinned_commit_downloads():
    sha = "0123456789abcdef0123456789abcdef01234567"
    seen = {}

    def fake(**kw):
        seen.update(kw)
        return "/snap"

    assert intake.resolve_source(f"hf:org/repo@{sha}", downloader=fake) == Path("/snap")
    assert seen == {"repo_id": "org/repo", "revision": sha}


def test_local_source_is_a_path(tmp_path):
    assert intake.resolve_source(str(tmp_path)) == tmp_path


def test_even_indices():
    assert intake.even_stride(1000, 200) == 5
    assert intake.even_stride(50, 200) == 1
    assert intake.even_stride(0, 200) == 1


def test_gate_file_parses():
    gate = intake.load_gate(ROOT / "tools" / "perception" / "model" / "intake_gate.yaml")
    assert gate == GATE


def test_bad_folder_fails_with_report(tmp_path, capsys):
    folder = tmp_path / "m"
    folder.mkdir()
    (folder / "model_manifest.json").write_text("{}", encoding="utf-8")
    rc = intake.main([str(folder), "--out", str(tmp_path / "out")])
    assert rc == 1
    report = json.loads((tmp_path / "m.intake_report.json").read_text(encoding="utf-8"))
    assert report["verdict"] == "fail" and report["reasons"]
    assert not (tmp_path / "out").exists()


# ---- end to end: tiny ONNX model + synthetic video (venv only) ----

def _tiny_onnx(path: Path):
    onnx = pytest.importorskip("onnx")
    from onnx import TensorProto, helper, numpy_helper
    # 1x1 conv: class 1 (lane) = 10 * mean(rgb) - 5, others 0 -> bright pixels are lane
    w = np.zeros((4, 3, 1, 1), np.float32)
    w[1, :, 0, 0] = 10.0 / 3
    b = np.array([0.0, -5.0, 0.0, 0.0], np.float32)
    graph = helper.make_graph(
        [helper.make_node("Conv", ["x", "w", "b"], ["logits"])], "tiny",
        [helper.make_tensor_value_info("x", TensorProto.FLOAT, [1, 3, 240, 320])],
        [helper.make_tensor_value_info("logits", TensorProto.FLOAT, [1, 4, 240, 320])],
        [numpy_helper.from_array(w, "w"), numpy_helper.from_array(b, "b")])
    model = helper.make_model(graph, opset_imports=[helper.make_opsetid("", 17)])
    model.ir_version = 8
    onnx.save(model, str(path))


def _video(path: Path, n: int):
    import cv2
    vw = cv2.VideoWriter(str(path), cv2.VideoWriter_fourcc(*"MJPG"), 10, (320, 240))
    assert vw.isOpened()
    for i in range(n):
        f = np.zeros((240, 320, 3), np.uint8)
        f[:, 190 + (i % 5):210 + (i % 5)] = 255
        vw.write(f)
    vw.release()


def test_intake_end_to_end(tmp_path):
    pytest.importorskip("onnxruntime")
    import export_cell
    raw = tmp_path / "raw.onnx"
    _tiny_onnx(raw)
    folder = tmp_path / "m"
    doc = export_cell.write_manifest(
        folder, onnx_path=raw,
        classes=[("bg", "background"), ("lane", "lane_marking"), ("road", "drivable"),
                 ("stop", "stop_line")],
        color="rgb", scale=1 / 255, mean=[0, 0, 0], std=[1, 1, 1], dataset_repo="org/ds",
        dataset_revision="a" * 40, camera_profile_revision="cam-1", trainer="t",
        date="20260930")
    vids = tmp_path / "root" / "vids"
    vids.mkdir(parents=True)
    _video(vids / "a.avi", 30)
    gate = dict(GATE, replay_sources=["vids/*.avi"], max_frames_per_source=10)
    gate_path = tmp_path / "gate.yaml"
    gate_path.write_text(json.dumps(gate), encoding="utf-8")  # JSON is valid YAML
    out = tmp_path / "out"
    rc = intake.main([str(folder), "--out", str(out), "--gate", str(gate_path),
                      "--root", str(tmp_path / "root")])
    rev = doc["model_revision"]
    report = json.loads((out / rev / "intake_report.json").read_text(encoding="utf-8"))
    assert rc == 0, report
    assert report["verdict"] == "pass"
    assert report["frames"] == 10
    assert report["nan_frames"] == 0
    assert report["visible_fraction"] == 1.0
    assert report["error_delta"]["p95"] < 0.1
    assert set(report["class_fractions_mean"]) == {"bg", "lane", "road", "stop"}
    assert report["gate"] == gate
    assert "tool_commit" in report
    assert (out / rev / "model.onnx").is_file()
    assert (out / rev / "model_manifest.json").is_file()


def test_export_onnx_parity(tmp_path):
    torch = pytest.importorskip("torch")
    pytest.importorskip("onnxruntime")
    import export_onnx
    from control.sensing.perception.learned.manifest import load_manifest, verify_files
    ts = tmp_path / "m.torchscript.pt"
    torch.manual_seed(0)
    torch.jit.script(torch.nn.Conv2d(3, 4, 3, padding=1)).save(str(ts))
    classes = tmp_path / "classes.yaml"
    classes.write_text("classes:\n"
                       "  - {index: 0, name: bg, role: background, color: [0, 0, 0]}\n"
                       "  - {index: 1, name: lane, role: lane_marking}\n"
                       "  - {index: 2, name: road, role: drivable}\n"
                       "  - {index: 3, name: stop, role: stop_line}\n", encoding="utf-8")
    out = tmp_path / "out"
    rc = export_onnx.main([str(ts), "--out", str(out), "--classes", str(classes),
                           "--color", "rgb", "--scale", "0.00392156862745098",
                           "--mean", "0", "0", "0", "--std", "1", "1", "1",
                           "--dataset-repo", "org/ds", "--dataset-revision", "a" * 40,
                           "--camera-profile-revision", "cam-1", "--trainer", "t"])
    assert rc == 0
    m = load_manifest(out)
    verify_files(m)
    diff = m.raw["metrics"]["export_parity_max_abs_diff"]
    assert 0 <= diff <= 1e-3
    assert [c.role for c in m.classes] == ["background", "lane_marking", "drivable", "stop_line"]


def test_export_classes_index_must_match_position(tmp_path):
    import export_onnx
    classes = tmp_path / "classes.yaml"
    classes.write_text("classes:\n  - {index: 1, name: a, role: background}\n"
                       "  - {index: 0, name: b, role: lane_marking}\n", encoding="utf-8")
    with pytest.raises(ValueError):
        export_onnx.load_classes(classes)


def test_export_requires_classes(tmp_path):
    import export_onnx
    with pytest.raises(SystemExit):
        export_onnx.main([str(tmp_path / "m.pt"), "--out", str(tmp_path / "o")])
