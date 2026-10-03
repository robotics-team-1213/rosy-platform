"""D-379 decision 3: intake scores a lane_seg model on a fixed eval set."""
import json
import sys
from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pytest

cv2 = pytest.importorskip("cv2")

ROOT = Path(__file__).resolve().parents[4]
_MODEL = str(ROOT / "learning" / "training" / "perception" / "model")
if _MODEL not in sys.path:
    sys.path.insert(0, _MODEL)

import intake  # noqa: E402

SHA = "c" * 64
H, W = 4, 8  # model input; eval frames are 8x16, so the masks are resized (nearest)
SPEC = SimpleNamespace(height=H, width=W, color="rgb", scale=1 / 255, mean=(0, 0, 0), std=(1, 1, 1))
MODEL_CLASSES = (SimpleNamespace(index=0, name="floor", role="background"),
                 SimpleNamespace(index=1, name="lane", role="lane_marking"),
                 SimpleNamespace(index=2, name="extra", role="drivable"))
GOOD = {"frames": 10, "latency_ms": {"p50": 5.0, "p95": 6.0}, "nan_frames": 0, "error_frames": 0,
        "visible_fraction": 1.0}


def _truth():
    """Eval label at 8x16: left half floor (0), right half lane (1), top row ignored."""
    m = np.zeros((8, 16), np.uint8)
    m[:, 8:] = 1
    m[0] = 255
    return m


def _eval_set(root, classes=(("floor", "background"), ("lane", "lane_marking"), ("wall", "ignore")),
              n=3):
    d = root / "store" / "evalsets" / "ev" / SHA
    frames = []
    for i in range(n):
        img, mask = f"images/s/s__{i:06d}.jpg", f"masks/s/s__{i:06d}.png"
        for rel in (img, mask):
            (d / rel).parent.mkdir(parents=True, exist_ok=True)
        cv2.imwrite(str(d / img), np.full((8, 16, 3), 50, np.uint8))
        cv2.imwrite(str(d / mask), _truth())
        frames.append({"image": img, "mask": mask, "session": "s", "split": "eval"})
    manifest = {"schema": "rosy.perception.dataset/1", "purpose": "eval", "ignore_index": 255,
                "classes": [{"index": i, "name": n_, "role": r} for i, (n_, r) in enumerate(classes)],
                "frames": frames}
    (d / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
    return d


class _Session:
    def __init__(self, pred):
        self.pred = pred

    def run(self, x):
        assert x.shape == (1, 3, H, W)
        return np.eye(len(MODEL_CLASSES), dtype=np.float32)[self.pred].transpose(2, 0, 1)[None] * 5


def _pred(lane_cols=4):
    """Prediction at 4x8: floor, lane on the right lane_cols columns."""
    p = np.zeros((H, W), np.int64)
    p[:, W - lane_cols:] = 1
    return p


def _model(pred, revision="lane-seg-20261003-aaaa1111", val_iou=None, dataset_revision="a" * 40):
    manifest = SimpleNamespace(input=SPEC, classes=MODEL_CLASSES, model_revision=revision,
                               files=(), raw={"metrics": {"val_iou": val_iou or {}}},
                               dataset_revision=dataset_revision)
    return SimpleNamespace(manifest=manifest, _session=_Session(pred))


def test_evaluate_matches_classes_by_name_and_ignores_255(tmp_path):
    ev = intake.evaluate(_model(_pred()), _eval_set(tmp_path), 400)
    assert ev["frames"] == 3 and ev["set"]["content_sha"] == SHA
    assert ev["matched_classes"] == ["floor", "lane"]
    assert ev["unmatched"] == {"model_only": ["extra"], "eval_only": ["wall"]}
    assert ev["iou"] == {"floor": 1.0, "lane": 1.0} and ev["miou"] == ev["miou_all"] == 1.0
    assert ev["miou_classes"] == ["lane"]  # floor has role background in the eval set
    assert ev["lane_marking_iou"] == {"lane": 1.0}
    # lane too wide by two columns: lane 4/6 per row, floor 2/4 per row
    ev = intake.evaluate(_model(_pred(6)), _eval_set(tmp_path / "b"), 400)
    assert ev["iou"] == {"floor": pytest.approx(0.5), "lane": pytest.approx(4 / 6)}
    assert ev["miou_all"] == pytest.approx((0.5 + 4 / 6) / 2)
    assert ev["miou"] == pytest.approx(4 / 6)  # gated mean leaves background out


def test_evaluate_frame_cap(tmp_path):
    ev = intake.evaluate(_model(_pred()), _eval_set(tmp_path, n=5), 2)
    assert ev["frames"] == 2


def _run(tmp_path, monkeypatch, model, gate_extra, folder_name="m", store=None):
    folder = tmp_path / folder_name
    folder.mkdir(exist_ok=True)
    (folder / "model_manifest.json").write_text("{}", encoding="utf-8")
    monkeypatch.setattr(intake, "load_manifest", lambda f: model.manifest)
    monkeypatch.setattr(intake, "verify_files", lambda m: None)
    monkeypatch.setattr(intake, "check_precision", lambda m: None)
    monkeypatch.setattr(intake.LaneSegModel, "open", classmethod(lambda cls, f: model))
    monkeypatch.setattr(intake, "replay", lambda m, v, n: dict(GOOD))
    gate = {"max_host_latency_ms_p50": 400, "max_nan_frames": 0, "min_visible_fraction": 0.3,
            "replay_sources": ["*.mp4"], "max_frames_per_source": 10, "eval_set": None,
            "eval_max_frames": 400, "min_eval_miou": None, "max_eval_miou_drop": 0.01, **gate_extra}
    gate_path = tmp_path / "gate.yaml"
    gate_path.write_text(json.dumps(gate), encoding="utf-8")
    return intake.run(str(folder), out=tmp_path / "out", gate_path=gate_path, root=tmp_path,
                      store=store)


EVAL_REL = f"store/evalsets/ev/{SHA}"


def test_eval_set_null_keeps_the_old_report(tmp_path, monkeypatch):
    rc, report = _run(tmp_path, monkeypatch, _model(_pred()), {})
    assert rc == 0 and report["verdict"] == "pass" and report["eval"] is None
    assert "trainer_val_iou" not in report


def test_eval_pass_then_regression_against_the_champion_fails(tmp_path, monkeypatch):
    _eval_set(tmp_path)
    rc, first = _run(tmp_path, monkeypatch, _model(_pred(), val_iou={"lane": 0.9}),
                     {"eval_set": EVAL_REL, "min_eval_miou": 0.5})
    assert rc == 0, first["reasons"]
    assert first["eval"]["miou"] == 1.0 and first["eval"]["champion"] is None
    assert first["trainer_val_iou"] == {"lane": 0.9}
    saved = json.loads((tmp_path / "out" / "lane-seg-20261003-aaaa1111" / intake.REPORT_NAME)
                       .read_text(encoding="utf-8"))
    assert saved["eval"]["set"]["content_sha"] == SHA
    # a worse model (mIoU 0.58) on the same set: below the champion's 1.0 - 0.01
    rc, second = _run(tmp_path, monkeypatch, _model(_pred(6), revision="lane-seg-20261003-bbbb2222"),
                      {"eval_set": EVAL_REL, "min_eval_miou": 0.5}, folder_name="m2")
    assert rc == 1 and second["verdict"] == "fail" and second["transient"] is False
    assert second["eval"]["champion"] == {"model_revision": "lane-seg-20261003-aaaa1111", "miou": 1.0}
    assert any("champion" in r for r in second["reasons"])
    # the model under test is never its own champion
    assert intake.find_champion(tmp_path / "out", SHA, "lane-seg-20261003-aaaa1111") is None


def test_min_eval_miou_fails(tmp_path, monkeypatch):
    _eval_set(tmp_path)
    rc, report = _run(tmp_path, monkeypatch, _model(_pred(6)),
                      {"eval_set": EVAL_REL, "min_eval_miou": 0.9})
    assert rc == 1 and any("min_eval_miou" in r for r in report["reasons"])


def test_no_matched_class_fails(tmp_path, monkeypatch):
    _eval_set(tmp_path, classes=(("bg", "background"), ("paint", "lane_marking")))
    rc, report = _run(tmp_path, monkeypatch, _model(_pred()), {"eval_set": EVAL_REL})
    assert rc == 1 and report["transient"] is False
    assert report["eval"]["matched_classes"] == []
    assert any("no class name shared" in r for r in report["reasons"])


@pytest.mark.parametrize("broken", ["missing", "not_eval"])
def test_missing_or_wrong_eval_set_is_a_transient_setup_error(tmp_path, monkeypatch, broken):
    if broken == "not_eval":
        d = _eval_set(tmp_path)
        doc = json.loads((d / "manifest.json").read_text(encoding="utf-8"))
        doc.pop("purpose")
        (d / "manifest.json").write_text(json.dumps(doc), encoding="utf-8")
    rc, report = _run(tmp_path, monkeypatch, _model(_pred()), {"eval_set": EVAL_REL})
    assert rc == 1 and report["verdict"] == "fail" and report["transient"] is True
    assert "eval set" in report["reasons"][0]


def test_object_det_gate_drops_the_eval_keys():
    gate = intake.load_gate(intake.DEFAULT_GATE)
    assert gate["eval_set"] is None and gate["max_eval_miou_drop"] == 0.01
    assert not set(intake.EVAL_KEYS) & set(intake.task_gate(gate, "object_det"))
    assert set(intake.EVAL_KEYS) <= set(intake.task_gate(gate, "lane_seg"))


def _champion_report(out, rev, iou, miou, sha=SHA, verdict="pass"):
    d = out / rev
    d.mkdir(parents=True, exist_ok=True)
    (d / intake.REPORT_NAME).write_text(json.dumps({
        "model_revision": rev, "verdict": verdict,
        "eval": {"set": {"content_sha": sha}, "iou": iou, "miou": miou}}), encoding="utf-8")


def test_champion_is_compared_over_the_shared_classes_only(tmp_path, monkeypatch):
    _eval_set(tmp_path)
    # the champion scored lane 0.9 and a class this model does not have; its mIoU 0.5 alone
    # would let a candidate with lane 0.667 through
    _champion_report(tmp_path / "out", "lane-seg-20261001-cccc3333", {"lane": 0.9, "wall": 0.1}, 0.5)
    rc, report = _run(tmp_path, monkeypatch, _model(_pred(6)), {"eval_set": EVAL_REL})
    cmp = report["eval"]["champion_comparison"]
    assert cmp == {"classes": ["lane"], "miou": pytest.approx(4 / 6), "champion_miou": 0.9}
    assert rc == 1 and any("champion" in r and "['lane']" in r for r in report["reasons"])


def test_no_shared_classes_skips_the_champion_check(tmp_path, monkeypatch):
    _eval_set(tmp_path)
    _champion_report(tmp_path / "out", "lane-seg-20261001-cccc3333", {"zebra": 1.0}, 1.0)
    rc, report = _run(tmp_path, monkeypatch, _model(_pred(6)), {"eval_set": EVAL_REL})
    assert report["eval"]["champion_comparison"] == "no shared classes"
    assert rc == 0, report["reasons"]


def test_find_champion_skips_malformed_reports(tmp_path):
    out = tmp_path / "out"
    for rev, body in (("a", "[1, 2]"), ("b", '"text"'), ("c", "{not json")):
        (out / rev).mkdir(parents=True)
        (out / rev / intake.REPORT_NAME).write_text(body, encoding="utf-8")
    _champion_report(out, "d", {"lane": 1.0}, "high")
    _champion_report(out, "e", {"lane": 1.0}, True)
    _champion_report(out, "f", {"lane": 1.0}, 0.9, verdict="fail")
    _champion_report(out, "g", {"lane": 1.0}, 0.9, sha="d" * 64)
    (out / "h").mkdir()
    (out / "h" / intake.REPORT_NAME).write_text(json.dumps(
        {"verdict": "pass", "eval": {"set": "x", "miou": 0.9}}), encoding="utf-8")
    assert intake.find_champion(out, SHA, None) is None
    _champion_report(out, "ok", {"lane": 0.7, "bad": "x"}, 0.7)
    assert intake.find_champion(out, SHA, None) == {"model_revision": "ok", "miou": 0.7,
                                                    "iou": {"lane": 0.7}}


def test_min_lane_marking_iou(tmp_path, monkeypatch):
    _eval_set(tmp_path)
    rc, report = _run(tmp_path, monkeypatch, _model(_pred(6)),
                      {"eval_set": EVAL_REL, "min_lane_marking_iou": 0.8})
    assert rc == 1 and any("min_lane_marking_iou" in r and "lane" in r for r in report["reasons"])
    rc, report = _run(tmp_path, monkeypatch, _model(_pred()),
                      {"eval_set": EVAL_REL, "min_lane_marking_iou": 0.8})
    assert rc == 0, report["reasons"]


def test_eval_set_without_frames_is_a_setup_error(tmp_path, monkeypatch):
    d = _eval_set(tmp_path)
    doc = json.loads((d / "manifest.json").read_text(encoding="utf-8"))
    doc["frames"] = []
    (d / "manifest.json").write_text(json.dumps(doc), encoding="utf-8")
    rc, report = _run(tmp_path, monkeypatch, _model(_pred()), {"eval_set": EVAL_REL})
    assert rc == 1 and report["transient"] is True and "no frames" in report["reasons"][0]


def test_background_only_match_is_a_model_fail(tmp_path, monkeypatch):
    _eval_set(tmp_path, classes=(("floor", "background"), ("paint", "lane_marking")))
    rc, report = _run(tmp_path, monkeypatch, _model(_pred()), {"eval_set": EVAL_REL})
    assert rc == 1 and report["transient"] is False
    assert report["eval"]["miou"] is None and report["eval"]["miou_all"] == 1.0
    assert any("non-background" in r for r in report["reasons"])


DS_SHA = "e" * 64


def _store_dataset(tmp_path, sessions):
    d = tmp_path / "store" / "datasets" / "lanes" / DS_SHA
    d.mkdir(parents=True)
    (d / "manifest.json").write_text(json.dumps({"frames": [
        {"image": "x", "mask": "y", "session": s, "split": "train"} for s in sessions]}), encoding="utf-8")


def test_training_dataset_sharing_an_eval_session_fails(tmp_path, monkeypatch):
    _eval_set(tmp_path)  # its frames are session "s"
    _store_dataset(tmp_path, ["s", "t"])
    rc, report = _run(tmp_path, monkeypatch, _model(_pred(), dataset_revision=DS_SHA),
                      {"eval_set": EVAL_REL}, store=tmp_path / "store")
    ev = report["eval"]
    assert rc == 1 and report["transient"] is False
    assert ev["disjoint"] is False and ev["shared_sessions"] == ["s"]
    assert ev["training_dataset"] == f"lanes@{DS_SHA}"
    assert any("must be disjoint" in r for r in report["reasons"])


def test_disjoint_training_dataset_is_recorded(tmp_path, monkeypatch):
    _eval_set(tmp_path)
    _store_dataset(tmp_path, ["t", "u"])
    rc, report = _run(tmp_path, monkeypatch, _model(_pred(), dataset_revision=DS_SHA),
                      {"eval_set": EVAL_REL}, store=tmp_path / "store")
    assert rc == 0, report["reasons"]
    assert report["eval"]["disjoint"] is True and "warnings" not in report


@pytest.mark.parametrize("store_given, revision", [(False, DS_SHA), (True, "a" * 40), (True, "f" * 64)])
def test_unresolved_training_dataset_is_unverified_not_a_fail(tmp_path, monkeypatch, store_given, revision):
    _eval_set(tmp_path)
    _store_dataset(tmp_path, ["s"])
    rc, report = _run(tmp_path, monkeypatch, _model(_pred(), dataset_revision=revision),
                      {"eval_set": EVAL_REL}, store=(tmp_path / "store") if store_given else None)
    assert rc == 0, report["reasons"]
    assert report["eval"]["disjoint"] == "unverified"
    assert any(w.startswith("disjoint: unverified") for w in report["warnings"])
