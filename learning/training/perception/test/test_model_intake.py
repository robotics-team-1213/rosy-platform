"""Task 9: model export and intake (D-356)."""
import json
import os
import sys
from pathlib import Path

import numpy as np
import pytest

ROOT = Path(__file__).resolve().parents[4]
for _p in (ROOT / "learning" / "training" / "perception" / "model", ROOT / "learning" / "training" / "perception" / "training"):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

import intake  # noqa: E402
from control.sensing.perception.learned.lane_mask import NonFiniteLogits  # noqa: E402

GATE = {"max_host_latency_ms_p50": 400, "max_nan_frames": 0, "min_visible_fraction": 0.30,
        "replay_sources": ["data/teleop/learning/*.mp4"], "max_frames_per_source": 200,
        "require_eval": False, "eval_set": None, "eval_max_frames": 400,
        "min_eval_miou": None, "max_eval_miou_drop": 0.01,
        "min_lane_marking_iou": None}
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


PASSING_D566 = {"val_outside_band_fp": 0.1, "val_beyond_line_fp": 0.1,
                "val_near_centre_drivable": {"pred": 0.8, "label": 0.8}}


def test_v13_drivable_intake_holds_until_review_lineage_is_verified(tmp_path):
    import export_cell

    raw = tmp_path / "candidate.onnx"
    raw.write_bytes(b"candidate")
    folder = tmp_path / "v13-candidate"
    export_cell.write_manifest(
        folder, onnx_path=raw,
        classes=[("background", "background"), ("lane_left", "lane_marking"),
                 ("drivable", "drivable")],
        color="rgb", scale=1 / 255, mean=[0, 0, 0], std=[1, 1, 1],
        dataset_repo="unreviewed", dataset_revision="a" * 64,
        camera_profile_revision="cam-1", trainer="direct", date="20261009",
        revision_prefix="v13-drivable",
        parent_lane_model={"model_revision": "lane-seg-20261006-abcd1234", "onnx_sha256": "b" * 64,
                           "torchscript_sha256": "c" * 64},
    )
    rc, report = intake.run(str(folder), out=tmp_path / "accepted", root=tmp_path)
    assert rc != 0 and report["verdict"] == "fail" and report["transient"] is False
    assert "D-554" in " ".join(report["reasons"])
    assert not (tmp_path / "accepted" / report["model_revision"]).exists()

    # D-554 lineage passes the lineage step; the fake ONNX then fails on its own merits.
    derived = tmp_path / "v13-derived"
    export_cell.write_manifest(
        derived, onnx_path=raw,
        classes=[("background", "background"), ("lane_left", "lane_marking"),
                 ("drivable", "drivable")],
        color="rgb", scale=1 / 255, mean=[0, 0, 0], std=[1, 1, 1],
        dataset_repo="store:v13-lane-derived", dataset_revision="a" * 64,
        camera_profile_revision="cam-1", trainer="t", date="20261009",
        revision_prefix="v13-drivable",
        parent_lane_model={"model_revision": "lane-seg-20261006-abcd1234", "onnx_sha256": "b" * 64,
                           "torchscript_sha256": "c" * 64},
        dataset_annotation={"annotation_origin": "derived_from_reviewed_lanes", "adr": "D-554"},
        camera_provenance="provisional", model_version="v13.1.00", metrics=PASSING_D566)
    import drivable_versions
    empty = tmp_path / "ledger.yaml"  # the real ledger holds v13.1.00 since 2026-10-09
    drivable_versions.save([], empty)
    rc, report = intake.run(str(derived), out=tmp_path / "accepted", root=tmp_path, ledger=empty)
    assert rc != 0 and "D-55" not in " ".join(report["reasons"])
    assert report["model_version"] == "v13.1.00"


def test_v13_drivable_intake_checks_the_d558_version(tmp_path):
    import drivable_versions
    import export_cell

    raw = tmp_path / "candidate.onnx"
    raw.write_bytes(b"candidate")
    kw = dict(onnx_path=raw, classes=[("background", "background"), ("lane_left", "lane_marking"),
                                      ("drivable", "drivable")],
              color="rgb", scale=1 / 255, mean=[0, 0, 0], std=[1, 1, 1],
              dataset_repo="store:v13-lane-derived", dataset_revision="a" * 64,
              camera_profile_revision="cam-1", trainer="t", date="20261010",
              revision_prefix="v13-drivable",
              parent_lane_model={"model_revision": "lane-seg-20261006-abcd1234", "onnx_sha256": "b" * 64,
                                 "torchscript_sha256": "c" * 64},
              dataset_annotation={"annotation_origin": "derived_from_reviewed_lanes", "adr": "D-554"},
              camera_provenance="provisional", metrics=PASSING_D566)
    ledger = tmp_path / "ledger.yaml"
    drivable_versions.save([{"version": "v13.1.00", "revision": "v13-drivable-20261010-ffffffff",
                             "onnx_sha256": "f" * 64, "dataset": "d", "dataset_sha256": "e" * 64, "rules": ["D-554 1-9"],
                             "status": "candidate", "note": "taken"}], ledger)

    def reasons(folder, version):
        doc = export_cell.write_manifest(folder, **kw)
        if version is not None:
            doc["model_version"] = version
        (folder / "model_manifest.json").write_text(json.dumps(doc), encoding="utf-8")
        rc, report = intake.run(str(folder), out=tmp_path / "accepted", root=tmp_path, ledger=ledger)
        assert rc != 0
        return " ".join(report["reasons"])

    assert "needs model_version" in reasons(tmp_path / "none", None)
    assert "major 12" in reasons(tmp_path / "major", "v12.1.00")
    assert "one version, one revision" in reasons(tmp_path / "taken", "v13.1.00")
    assert "D-558" not in reasons(tmp_path / "free", "v13.2.00")  # fails later on the fake ONNX


def test_v13_quality_gate_d566():
    from intake_eval_gate import v13_quality_error

    def doc(fp, pred=0.7, label=0.8, beyond=0.1):
        return {"metrics": {"val_outside_band_fp": fp, "val_beyond_line_fp": beyond,
                            "val_near_centre_drivable": {"pred": pred, "label": label}}}
    assert v13_quality_error(doc(0.15)) is None
    assert "needs metrics" in v13_quality_error({"metrics": {"val_iou": {"drivable": 0.9}}})
    assert "0.496 > 0.15" in v13_quality_error(doc(0.496))
    assert "near-centre" in v13_quality_error(doc(0.1, pred=0.63))  # < 0.8 x 0.8
    assert "val_beyond_line_fp 0.200" in v13_quality_error(doc(0.1, beyond=0.2))
    assert "val_beyond_line_fp" in v13_quality_error({"metrics": {"val_outside_band_fp": 0.1,
                                                                 "val_near_centre_drivable": {"pred": 1, "label": 1}}})


@pytest.mark.parametrize("src", ["hf:org/repo@main", "hf:org/repo@v1.0", "hf:org/repo",
                                 "hf:org/repo@" + "a" * 39, "hf:org/repo@" + "g" * 40])
def test_hf_source_refuses_non_commit(src):
    with pytest.raises(ValueError):
        intake.resolve_source(src, downloader=lambda **kw: pytest.fail("downloaded"))


SHA = "ab" * 20  # placeholder-shaped, low-entropy: the secret scanner flags
# high-entropy 40-hex literals; this fixture only needs the sha1 shape.


def test_hf_source_downloads_real_files_into_workdir(tmp_path):
    seen = {}

    def fake(**kw):
        seen.update(kw)
        d = Path(kw["local_dir"])
        d.mkdir(parents=True)
        (d / "model_manifest.json").write_text("{}", encoding="utf-8")
        return str(d)

    got = intake.resolve_source(f"hf:org/repo@{SHA}", downloader=fake, workdir=tmp_path)
    assert seen["repo_id"] == "org/repo" and seen["revision"] == SHA
    assert Path(seen["local_dir"]).is_relative_to(tmp_path)
    assert got.is_relative_to(tmp_path)
    assert (got / "model_manifest.json").is_file()


def test_hf_source_symlinked_snapshot_is_dereferenced(tmp_path):
    blobs = tmp_path / "blobs"
    blobs.mkdir()
    (blobs / "abc").write_bytes(b"weights")
    try:
        os.symlink(blobs / "abc", tmp_path / "probe")
    except (OSError, NotImplementedError):
        pytest.skip("os.symlink unavailable on this host")

    def fake(**kw):  # an old hub that still links into the blob cache
        d = Path(kw["local_dir"])
        d.mkdir(parents=True)
        os.symlink(blobs / "abc", d / "model.onnx")
        return str(d)

    got = intake.resolve_source(f"hf:org/repo@{SHA}", downloader=fake,
                                workdir=tmp_path / "work")
    f = got / "model.onnx"
    assert not f.is_symlink() and f.read_bytes() == b"weights"


def test_local_source_is_a_path(tmp_path):
    assert intake.resolve_source(str(tmp_path), workdir=tmp_path / "w") == tmp_path


def _inbox(tmp_path, name="m1", ready=True):
    sys.path.insert(0, str(ROOT / "learning" / "training" / "perception"))
    import store
    folder = tmp_path / "store" / "models" / "inbox" / name
    folder.mkdir(parents=True)
    (folder / "model_manifest.json").write_text("{}", encoding="utf-8")
    if ready:
        (folder / "READY").write_text(store.content_sha(folder), encoding="utf-8")
    return folder


def test_store_inbox_source_is_the_ready_inbox_folder(tmp_path):
    folder = _inbox(tmp_path)
    assert intake.resolve_source("store-inbox:m1", store=tmp_path / "store") == folder


@pytest.mark.parametrize("src, ready, store_given", [
    ("store-inbox:m1", False, True),      # half-synced: no READY
    ("store-inbox:m1", True, False),      # no store configured
    ("store-inbox:../x", True, True),     # never outside the inbox
])
def test_store_inbox_source_refusals(tmp_path, src, ready, store_given):
    _inbox(tmp_path, ready=ready)
    with pytest.raises(ValueError):
        intake.resolve_source(src, store=(tmp_path / "store") if store_given else None)


def test_failed_store_inbox_report_goes_under_out_not_the_inbox(tmp_path):
    folder = _inbox(tmp_path)
    rc, report = intake.run("store-inbox:m1", out=tmp_path / "out", store=tmp_path / "store")
    assert rc == 1 and report["verdict"] == "fail" and not report["transient"]
    assert sorted(p.name for p in folder.parent.iterdir()) == ["m1"]
    assert list((tmp_path / "out" / "_failed").glob("*intake_report.json"))


class _Ev:
    visible, error, confidence, class_fractions = False, None, 0.0, {"a": 1.0}


class _Res:
    evidence, latency_ms = _Ev(), 1.0


class _FlakyModel:
    def __init__(self):
        self.n = 0

    def infer(self, bgr):
        self.n += 1
        if self.n == 1:
            raise NonFiniteLogits("logits contain NaN")
        if self.n == 2:
            raise ValueError("expected an HxWx3 BGR frame")
        return _Res()


def test_replay_separates_nan_from_other_errors(monkeypatch):
    frames = [np.zeros((240, 320, 3), np.uint8)] * 4
    monkeypatch.setattr(intake, "_video_frames", lambda path, n: iter(frames))
    stats = intake.replay(_FlakyModel(), [Path("v.mp4")], 10)
    assert stats["frames"] == 4 and stats["nan_frames"] == 1 and stats["error_frames"] == 1
    verdict, reasons = intake.judge(dict(GOOD, error_frames=1), GATE)
    assert verdict == "fail" and "error" in reasons[0].lower()


def test_infrastructure_errors_are_marked_transient(tmp_path, monkeypatch):
    """watch.py retries these later; only a real gate verdict is final."""
    folder = tmp_path / "m"
    folder.mkdir()
    monkeypatch.setattr(intake, "load_manifest", lambda f: (_ for _ in ()).throw(OSError("disk")))
    rc, report = intake.run(str(folder), out=tmp_path / "out")
    assert rc == 1 and report["transient"] is True

    def offline(**kw):
        raise OSError("HF unreachable")  # requests/HF HTTP errors are OSError subclasses

    rc, report = intake.run(f"hf:org/m@{'a' * 40}", out=tmp_path / "out", downloader=offline)
    assert rc == 1 and report["transient"] is True


def test_failed_hf_report_goes_under_out_never_cwd(tmp_path, monkeypatch):
    cwd = tmp_path / "cwd"
    cwd.mkdir()
    monkeypatch.chdir(cwd)

    def offline(**kw):
        raise OSError("HF unreachable")

    for source in (f"hf:org/m@{'a' * 40}", "hf:org/m@main"):  # download error, bad spec
        rc, _ = intake.run(source, out=tmp_path / "out", downloader=offline)
        assert rc == 1
    assert list(cwd.iterdir()) == []
    failed = sorted(p.name for p in (tmp_path / "out" / "_failed").iterdir())
    assert failed == [f"org__m@{'a' * 40}.intake_report.json", "org__m@main.intake_report.json"]


def test_no_replay_frames_is_a_transient_setup_error(tmp_path, monkeypatch):
    """An empty or wrong replay_root is the site's problem, not the model's."""
    folder = tmp_path / "m"
    folder.mkdir()
    fake = type("M", (), {"model_revision": "lane-seg-20260930-abcd1234", "files": (), "backend": "onnx"})()
    monkeypatch.setattr(intake, "load_manifest", lambda f: fake)
    monkeypatch.setattr(intake, "verify_files", lambda m: None)
    monkeypatch.setattr(intake.LaneSegModel, "open", classmethod(lambda cls, f: object()))
    rc, report = intake.run(str(folder), out=tmp_path / "out", root=tmp_path / "empty")
    assert rc == 1 and report["verdict"] == "fail"
    assert report["transient"] is True
    assert any("replay" in r for r in report["reasons"])


def test_count_replay_frames_sources(tmp_path):
    (tmp_path / "data" / "teleop" / "learning").mkdir(parents=True)
    assert intake.replay_videos({"replay_sources": ["data/teleop/learning/*.mp4"]}, tmp_path) == []
    clip = tmp_path / "data" / "teleop" / "learning" / "a.mp4"
    clip.write_bytes(b"")
    assert intake.replay_videos({"replay_sources": ["data/teleop/learning/*.mp4"]},
                                tmp_path) == [clip]


def test_gate_failures_are_final(tmp_path):
    folder = tmp_path / "m"
    folder.mkdir()
    (folder / "model_manifest.json").write_text("{}", encoding="utf-8")
    rc, report = intake.run(str(folder), out=tmp_path / "out")
    assert rc == 1 and report["transient"] is False


def test_io_failure_still_writes_fail_report(tmp_path, monkeypatch):
    import cv2
    folder = tmp_path / "m"
    folder.mkdir()
    monkeypatch.setattr(intake, "load_manifest", lambda f: (_ for _ in ()).throw(OSError("disk")))
    assert intake.main([str(folder), "--out", str(tmp_path / "out")]) == 1
    report = json.loads((tmp_path / "m.intake_report.json").read_text(encoding="utf-8"))
    assert report["verdict"] == "fail" and "disk" in report["reasons"][0]

    def boom(f):
        raise cv2.error("codec")

    monkeypatch.setattr(intake, "load_manifest", boom)
    assert intake.main([str(folder), "--out", str(tmp_path / "out")]) == 1


def test_even_indices():
    assert intake.even_stride(1000, 200) == 5
    assert intake.even_stride(50, 200) == 1
    assert intake.even_stride(0, 200) == 1


def test_gate_file_parses():
    gate = intake.load_gate(ROOT / "learning" / "training" / "perception" / "model" / "intake_gate.yaml")
    assert intake.task_gate(gate, "lane_seg") == GATE  # D-423: plus an object_det section


def test_bad_folder_fails_with_report(tmp_path, capsys):
    folder = tmp_path / "m"
    folder.mkdir()
    (folder / "model_manifest.json").write_text("{}", encoding="utf-8")
    rc = intake.main([str(folder), "--out", str(tmp_path / "out")])
    assert rc == 1
    report = json.loads((tmp_path / "m.intake_report.json").read_text(encoding="utf-8"))
    assert report["verdict"] == "fail" and report["reasons"]
    assert not (tmp_path / "out").exists()


def test_run_returns_report_and_uses_injected_downloader(tmp_path):
    """model/watch.py calls run() in-process with its own (token-carrying) downloader."""
    seen = {}

    def downloader(**kw):
        seen.update(kw)
        d = Path(kw["local_dir"])
        d.mkdir(parents=True)
        (d / "model_manifest.json").write_text("{}", encoding="utf-8")
        return str(d)

    rc, report = intake.run(f"hf:org/m@{'a' * 40}", out=tmp_path / "out",
                            downloader=downloader)
    assert rc == 1 and report["verdict"] == "fail" and report["reasons"]
    assert seen["repo_id"] == "org/m" and seen["revision"] == "a" * 40


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
    assert report["files"] == [{"name": f["name"], "sha256": f["sha256"]} for f in doc["files"]]
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


def test_export_validates_classes_before_export(tmp_path, monkeypatch):
    import export_onnx
    monkeypatch.setattr(export_onnx, "export_and_check",
                        lambda *a, **k: pytest.fail("exported before validation"))
    classes = tmp_path / "classes.yaml"
    classes.write_text("classes:\n  - {name: a, role: background}\n"
                       "  - {name: b, role: background}\n", encoding="utf-8")
    with pytest.raises(ValueError):
        export_onnx.main([str(tmp_path / "m.pt"), "--out", str(tmp_path / "o"),
                          "--classes", str(classes), "--dataset-repo", "r",
                          "--dataset-revision", "s", "--camera-profile-revision", "c",
                          "--trainer", "t"])


def _qdq_onnx(path: Path):
    """The tiny conv behind QuantizeLinear/DequantizeLinear, as quantize_static makes it."""
    onnx = pytest.importorskip("onnx")
    from onnx import TensorProto, helper, numpy_helper
    w = np.zeros((4, 3, 1, 1), np.float32)
    w[1, :, 0, 0] = 10.0 / 3
    b = np.array([0.0, -5.0, 0.0, 0.0], np.float32)
    inits = [numpy_helper.from_array(w, "w"), numpy_helper.from_array(b, "b"),
             numpy_helper.from_array(np.array(1 / 255, np.float32), "s"),
             numpy_helper.from_array(np.array(0, np.uint8), "z")]
    nodes = [helper.make_node("QuantizeLinear", ["x", "s", "z"], ["xq"]),
             helper.make_node("DequantizeLinear", ["xq", "s", "z"], ["xd"]),
             helper.make_node("Conv", ["xd", "w", "b"], ["logits"])]
    graph = helper.make_graph(
        nodes, "tiny_qdq",
        [helper.make_tensor_value_info("x", TensorProto.FLOAT, [1, 3, 240, 320])],
        [helper.make_tensor_value_info("logits", TensorProto.FLOAT, [1, 4, 240, 320])], inits)
    model = helper.make_model(graph, opset_imports=[helper.make_opsetid("", 17)])
    model.ir_version = 8
    onnx.save(model, str(path))


def test_graph_precision_reads_qdq_nodes(tmp_path):
    _tiny_onnx(tmp_path / "f.onnx")
    _qdq_onnx(tmp_path / "q.onnx")
    assert intake.graph_precision(tmp_path / "f.onnx") == "fp32"
    assert intake.graph_precision(tmp_path / "q.onnx") == "int8"


@pytest.mark.parametrize("graph, declared, word", [("qdq", "fp32", "int8"), ("fp32", "int8", "fp32")])
def test_intake_refuses_a_precision_label_that_contradicts_the_graph(tmp_path, graph, declared, word):
    import export_cell
    raw = tmp_path / "raw.onnx"
    (_qdq_onnx if graph == "qdq" else _tiny_onnx)(raw)
    folder = tmp_path / "m"
    export_cell.write_manifest(
        folder, onnx_path=raw, classes=[("bg", "background"), ("lane", "lane_marking")],
        color="rgb", scale=1 / 255, mean=[0, 0, 0], std=[1, 1, 1], dataset_repo="org/ds",
        dataset_revision="a" * 40, camera_profile_revision="cam-1", trainer="t",
        date="20261001", precision=declared)
    rc, report = intake.run(str(folder), out=tmp_path / "out", root=tmp_path)
    assert rc != 0 and report["verdict"] == "fail" and not report["transient"]
    assert any("precision" in r and word in r for r in report["reasons"]), report["reasons"]


def test_a_missing_package_is_a_config_error_not_transient(tmp_path, monkeypatch):
    """Review 2026-10-01: ImportError (onnx or onnxruntime missing) is the site's
    environment, not a network hiccup: exit CONFIG_EXIT, never retried as transient."""
    import export_cell
    raw = tmp_path / "raw.onnx"
    raw.write_bytes(b"not-really-onnx")
    folder = tmp_path / "m"
    export_cell.write_manifest(
        folder, onnx_path=raw, classes=[("bg", "background"), ("lane", "lane_marking")],
        color="rgb", scale=1 / 255, mean=[0, 0, 0], std=[1, 1, 1], dataset_repo="org/ds",
        dataset_revision="a" * 40, camera_profile_revision="cam-1", trainer="t", date="20261001")

    def no_onnx(path):
        raise ImportError("No module named 'onnx'")
    monkeypatch.setattr(intake, "graph_precision", no_onnx)
    rc, report = intake.run(str(folder), out=tmp_path / "out", root=tmp_path)
    assert rc == intake.CONFIG_EXIT == 4
    assert report["config_error"] is True and report["transient"] is False
    assert "onnx" in report["reasons"][0]


def test_v13_lineage_accepts_d554_and_d563_annotations_only():
    from intake_eval_gate import v13_lineage_error
    def doc(origin, adr):
        return {"task": "lane_seg", "camera_provenance": "provisional",
                "parent_lane_model": {"model_revision": "lane-seg-20261006-abcd1234", "onnx_sha256": "b" * 64},
                "dataset": {"revision": "a" * 64, "annotation_origin": origin, "adr": adr}}
    assert v13_lineage_error(doc("derived_from_reviewed_lanes", "D-554")) is None
    assert v13_lineage_error(doc("map_projected", "D-563")) is None
    assert v13_lineage_error(doc("map_projected", "D-554")) is not None
    assert v13_lineage_error(doc("human_reviewed", "D-563")) is not None
