"""D-356 runner: sha-verified open, shape check, keep-previous hot swap."""

import hashlib
import json

import numpy as np
import pytest

from control.sensing.perception.learned.manifest import ManifestError
from control.sensing.perception.learned.runner import LaneSegModel, ModelSlot


class FakeSession:
    def __init__(self, n_classes=2, lane_col=160, nan=False):
        self.n, self.col, self.nan = n_classes, lane_col, nan

    def run(self, x):
        out = np.full((1, self.n, x.shape[2], x.shape[3]), -5.0, np.float32)
        out[0, 0] = 5.0
        out[0, 0, :, self.col - 5:self.col + 5] = -5.0
        out[0, 1, :, self.col - 5:self.col + 5] = 5.0
        if self.nan:
            out[0, 0, 0, 0] = np.nan
        return out


def _model_dir(tmp_path, name="m1", revision="lane-seg-20260930-00000001"):
    d = tmp_path / name
    d.mkdir()
    (d / "model.onnx").write_bytes(b"fake-" + name.encode())
    sha = hashlib.sha256((d / "model.onnx").read_bytes()).hexdigest()
    (d / "model_manifest.json").write_text(json.dumps({
        "schema": "rosy.perception.model/1", "model_revision": revision, "task": "lane_seg",
        "files": [{"name": "model.onnx", "sha256": sha, "precision": "fp32"}],
        "input": {"shape": [1, 3, 240, 320], "color": "rgb", "scale": 1 / 255,
                  "mean": [0, 0, 0], "std": [1, 1, 1], "layout": "nchw"},
        "output": {"layout": "nchw_logits", "classes": [
            {"index": 0, "name": "floor", "role": "background"},
            {"index": 1, "name": "line", "role": "lane_marking"}]},
        "dataset": {"repo": "org/d", "revision": "a" * 40},
        "camera_profile_revision": "cam-1"}), encoding="utf-8")
    return d


def _factory(**kw):
    return lambda path, threads: FakeSession(**kw)


def test_open_and_infer(tmp_path):
    m = LaneSegModel.open(_model_dir(tmp_path), session_factory=_factory())
    r = m.infer(np.zeros((240, 320, 3), np.uint8))
    assert r.model_revision == "lane-seg-20260930-00000001"
    assert r.evidence.visible and abs(r.evidence.error) < 0.05
    assert r.latency_ms >= 0


def test_open_refuses_tampered_file(tmp_path):
    d = _model_dir(tmp_path)
    (d / "model.onnx").write_bytes(b"other")
    with pytest.raises(ManifestError):
        LaneSegModel.open(d, session_factory=_factory())


def test_open_refuses_wrong_class_count(tmp_path):
    with pytest.raises(ManifestError, match="output"):
        LaneSegModel.open(_model_dir(tmp_path), session_factory=_factory(n_classes=3))


def test_open_refuses_nan_warmup(tmp_path):
    with pytest.raises(ManifestError, match="warm-up"):
        LaneSegModel.open(_model_dir(tmp_path), session_factory=_factory(nan=True))


def test_slot_swaps_and_keeps_previous_on_failure(tmp_path):
    good = _model_dir(tmp_path, "m1", "lane-seg-20260930-00000001")
    good2 = _model_dir(tmp_path, "m2", "lane-seg-20260930-00000002")
    bad = _model_dir(tmp_path, "m3", "lane-seg-20260930-00000003")
    (bad / "model.onnx").write_bytes(b"tampered")
    pointer = tmp_path / "shadow"
    now = [0.0]
    slot = ModelSlot(pointer, opener=lambda p: LaneSegModel.open(p, session_factory=_factory()),
                     clock=lambda: now[0], poll_s=1.0)

    assert slot.poll() is None and slot.current is None       # no pointer yet
    pointer.write_text(str(good), encoding="utf-8")
    now[0] = 1.0
    assert slot.poll().model_revision.endswith("01")
    pointer.write_text(str(bad), encoding="utf-8")
    now[0] = 2.0
    assert slot.poll().model_revision.endswith("01")           # kept
    assert "sha256" in slot.last_error
    pointer.write_text(str(good2), encoding="utf-8")
    now[0] = 2.5
    assert slot.poll().model_revision.endswith("01")           # rate-limited
    now[0] = 3.0
    assert slot.poll().model_revision.endswith("02")
    assert slot.last_error is None


def test_real_onnxruntime_roundtrip(tmp_path):
    ort = pytest.importorskip("onnxruntime")
    onnx = pytest.importorskip("onnx")
    from onnx import TensorProto, helper
    # 1x1 conv 3->2 channels: class 1 logit = R channel, class 0 = constant 0.5
    w = np.zeros((2, 3, 1, 1), np.float32)
    w[1, 0, 0, 0] = 1.0
    b = np.array([0.5, 0.0], np.float32)
    graph = helper.make_graph(
        [helper.make_node("Conv", ["x", "w", "b"], ["y"])], "g",
        [helper.make_tensor_value_info("x", TensorProto.FLOAT, [1, 3, 240, 320])],
        [helper.make_tensor_value_info("y", TensorProto.FLOAT, [1, 2, 240, 320])],
        [helper.make_tensor("w", TensorProto.FLOAT, w.shape, w.flatten()),
         helper.make_tensor("b", TensorProto.FLOAT, b.shape, b)])
    model = helper.make_model(graph, opset_imports=[helper.make_opsetid("", 17)])
    model.ir_version = 8
    d = _model_dir(tmp_path)
    onnx.save(model, d / "model.onnx")
    doc = json.loads((d / "model_manifest.json").read_text())
    doc["files"][0]["sha256"] = hashlib.sha256((d / "model.onnx").read_bytes()).hexdigest()
    (d / "model_manifest.json").write_text(json.dumps(doc))
    m = LaneSegModel.open(d)
    frame = np.zeros((240, 320, 3), np.uint8)
    frame[:, 250:270, 2] = 255  # red stripe right of centre
    assert m.infer(frame).evidence.error > 0.5


def test_slot_retries_same_path_after_failure(tmp_path):
    d = _model_dir(tmp_path)
    pointer = tmp_path / "shadow"
    pointer.write_text(str(d), encoding="utf-8")
    now = [0.0]
    ok = [False]

    def opener(p):
        if not ok[0]:
            raise ManifestError("transient")
        return LaneSegModel.open(p, session_factory=_factory())

    slot = ModelSlot(pointer, opener=opener, clock=lambda: now[0], poll_s=1.0)
    assert slot.poll() is None and slot.last_error
    ok[0] = True
    now[0] = 1.0
    assert slot.poll() is None                                 # backing off (poll_s * 5)
    now[0] = 5.0
    assert slot.poll() is not None and slot.last_error is None


def test_slot_backs_off_on_repeated_open_failure(tmp_path):
    d = _model_dir(tmp_path)
    pointer = tmp_path / "shadow"
    pointer.write_text(str(d), encoding="utf-8")
    now = [0.0]
    calls = []

    def opener(p):
        calls.append(now[0])
        raise ManifestError("broken")

    slot = ModelSlot(pointer, opener=opener, clock=lambda: now[0], poll_s=1.0)
    for t in (0.0, 1.0, 2.0, 3.0, 4.0, 5.0, 6.0, 9.0, 10.0):
        now[0] = t
        slot.poll()
    assert calls == [0.0, 5.0, 10.0]
    # a different target is not held back by the failed one
    d2 = _model_dir(tmp_path, "m2", "lane-seg-20260930-00000002")
    pointer.write_text(str(d2), encoding="utf-8")
    now[0] = 11.0
    slot.poll()
    assert calls[-1] == 11.0


def test_slot_clears_stale_pointer_error_when_read_recovers(tmp_path):
    d = _model_dir(tmp_path)
    pointer = tmp_path / "shadow"
    pointer.write_text(str(d), encoding="utf-8")
    now = [0.0]
    slot = ModelSlot(pointer, opener=lambda p: LaneSegModel.open(p, session_factory=_factory()),
                     clock=lambda: now[0], poll_s=1.0)
    assert slot.poll() is not None
    slot.last_error = "pointer: transient read error"
    now[0] = 1.0
    assert slot.poll() is not None
    assert slot.last_error is None


def test_slot_reopens_when_manifest_mtime_changes(tmp_path):
    import os
    d = _model_dir(tmp_path)
    pointer = tmp_path / "shadow"
    pointer.write_text(str(d), encoding="utf-8")
    now = [0.0]
    opened = []

    def opener(p):
        opened.append(p)
        return LaneSegModel.open(p, session_factory=_factory())

    slot = ModelSlot(pointer, opener=opener, clock=lambda: now[0], poll_s=1.0)
    slot.poll()
    now[0] = 1.0
    slot.poll()
    assert len(opened) == 1
    m = d / "model_manifest.json"
    st = m.stat()
    os.utime(m, ns=(st.st_atime_ns, st.st_mtime_ns + 5_000_000_000))
    now[0] = 2.0
    slot.poll()
    assert len(opened) == 2


def test_slot_poll_never_raises_on_bad_pointer(tmp_path):
    pointer = tmp_path / "shadow"
    pointer.write_bytes(bytes([0xff, 0xfe, 0x00]) + b"bad")
    slot = ModelSlot(pointer, opener=lambda p: None, clock=lambda: 0.0)
    assert slot.poll() is None
    assert slot.last_error
