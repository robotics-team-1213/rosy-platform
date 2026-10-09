"""Frozen lane model + drivable head (training/drivable_head.py, user decision 2026-10-07)."""
import json
import sys
from pathlib import Path

import pytest

torch = pytest.importorskip("torch")
cv2 = pytest.importorskip("cv2")
np = pytest.importorskip("numpy")

ROOT = Path(__file__).resolve().parents[4]
TRAINING = ROOT / "learning" / "training" / "perception" / "training"
if str(TRAINING) not in sys.path:
    sys.path.insert(0, str(TRAINING))

import drivable_head as dh  # noqa: E402
import rosy_lane_model as rlm  # noqa: E402

LANE_CLASSES = [("background", "background"), ("lane_left", "lane_marking"),
                ("lane_right", "lane_marking"), ("crosswalk", "ignore"), ("speed_bump", "ignore")]


def _lane(seed=0):
    """Random lane model whose argmax is background on about half the pixels."""
    torch.manual_seed(seed)
    lane = rlm.LaneUNet(n_classes=5, base=4).eval()
    with torch.no_grad():
        out = lane(torch.rand(2, 3, 240, 320))
        lane.head.bias[0] += (out[:, 1:].amax(1) - out[:, 0]).median() + 1e-3  # no exact ties
    return lane


def _scripted(tmp_path, lane):
    path = tmp_path / "lane.torchscript.pt"
    torch.jit.trace(lane, torch.rand(1, 3, 240, 320)).save(str(path))
    return path


class HalfDrivable(torch.nn.Module):
    """Stand-in head: drivable on the left half, not on the right."""

    def forward(self, features):
        s = torch.full_like(features[:, :1], -5.0)
        s[..., :160] = 5.0
        return s


class PixelLane(rlm.LaneUNet):
    """Lane model whose features are the pixel colours, so a head can learn from them."""

    def features(self, x):
        return torch.cat([x, x[:, :1]], 1)


def test_lane_answer_is_kept_and_only_background_turns_drivable():
    lane = _lane()
    model = dh.LaneWithDrivable(lane).eval()
    model.drivable = HalfDrivable()
    x = torch.rand(2, 3, 240, 320)
    with torch.no_grad():
        want = lane(x).argmax(1)
        out = model(x)
        got = out.argmax(1)
    assert out.shape[1] == 6
    drivable = got == 5
    assert drivable.any() and (got == 0).any()
    assert torch.equal(torch.where(drivable, torch.zeros_like(got), got), want)
    assert bool((want[drivable] == 0).all())


def test_ignore_top_rows_are_background():
    model = dh.LaneWithDrivable(_lane(), ignore_top=110).eval()
    torch.nn.init.constant_(model.drivable[-1].bias, 50.0)  # drivable everywhere it may be
    with torch.no_grad():
        got = model(torch.rand(1, 3, 240, 320)).argmax(1)
    assert bool((got[:, :110] == 0).all())
    assert bool((got[:, 110:] != 0).any())


@pytest.mark.parametrize("head", ["context", "context_lane"])
def test_context_heads_keep_lane_answer_and_export(tmp_path, head):
    lane = _lane(8)
    x = torch.rand(2, 3, 240, 320)
    with torch.no_grad():
        features, deep = dh.lane_features_and_bottleneck(lane, x)
        assert torch.equal(lane.head(features), lane(x)) and deep.shape == (2, 64, 15, 20)
    model = dh.LaneWithDrivable(lane, ignore_top=110, head=head).eval()
    with torch.no_grad():
        model.drivable.fuse[-1].bias.fill_(5.0)
        lane_out, s = model.drivable_logit(x)
        out = model(x)
    assert s.shape == (2, 1, 240, 320) and out.shape == (2, 6, 240, 320)
    want, got = lane(x).argmax(1), out.argmax(1)
    drivable = got == 5
    assert drivable.any() and torch.equal(torch.where(drivable, torch.zeros_like(got), got)[:, 110:],
                                          want[:, 110:])
    pytest.importorskip("onnx")
    pytest.importorskip("onnxruntime")
    parent, candidate = tmp_path / "parent.onnx", tmp_path / "candidate.onnx"
    for module, path in ((lane, parent), (model, candidate)):
        torch.onnx.export(module, torch.rand(1, 3, 240, 320), str(path), opset_version=17,
                          input_names=["x"], output_names=["logits"])
    parity = dh.verify_candidate_lane_parity(parent, candidate, [x[:1]], ignore_top=110)
    assert parity["parent_lane_pixels_preserved"]
    with pytest.raises(ValueError, match="head must be"):
        dh.LaneWithDrivable(lane, head="wide")


def test_load_frozen_lane_renames_keys_and_checks_parity(tmp_path):
    lane = _lane(1)
    loaded, n = dh.load_frozen_lane(_scripted(tmp_path, lane), classes=LANE_CLASSES)
    assert n == 5 and not any(p.requires_grad for p in loaded.parameters())
    x = torch.rand(1, 3, 240, 320)
    with torch.no_grad():
        assert torch.equal(loaded(x), lane(x))
    with pytest.raises(ValueError, match="classes given"):
        dh.load_frozen_lane(_scripted(tmp_path, lane), classes=LANE_CLASSES[:4])


def test_parent_torchscript_and_delivered_onnx_agree_on_input_frames(tmp_path):
    pytest.importorskip('onnx')
    pytest.importorskip('onnxruntime')
    lane = _lane(3)
    script = _scripted(tmp_path, lane)
    parent, _ = dh.load_frozen_lane(script, classes=LANE_CLASSES)
    onnx = tmp_path / 'parent.onnx'
    torch.onnx.export(lane, torch.rand(1, 3, 240, 320), str(onnx),
                      opset_version=17, input_names=['x'], output_names=['logits'])
    frames = [torch.rand(1, 3, 240, 320), torch.rand(1, 3, 240, 320)]
    assert dh.verify_parent_parity(parent, script, onnx, frames, ignore_top=110)['samples'] == 2

    class Roi(torch.nn.Module):  # the delivered v11 wrapper: rows above ignore_top forced
        def __init__(self, inner):
            super().__init__()
            self.inner = inner

        def forward(self, x):
            y = self.inner(x)
            top = y[:, :, :110]
            forced = torch.cat([top.amax(dim=1, keepdim=True) + 1.0, top[:, 1:] - 1000.0], 1)
            return torch.cat([forced, y[:, :, 110:]], 2)
    torch.onnx.export(Roi(lane).eval(), torch.rand(1, 3, 240, 320), str(onnx),
                      opset_version=17, input_names=['x'], output_names=['logits'])
    assert dh.verify_parent_parity(parent, script, onnx, frames, ignore_top=110)['max_abs'] < 1e-3
    other = _lane(4)
    torch.onnx.export(other, torch.rand(1, 3, 240, 320), str(onnx),
                      opset_version=17, input_names=['x'], output_names=['logits'])
    with pytest.raises(ValueError, match='ONNX'):
        dh.verify_parent_parity(parent, script, onnx, frames, ignore_top=110)


def test_candidate_onnx_preserves_parent_lane_pixels(tmp_path):
    pytest.importorskip('onnx')
    pytest.importorskip('onnxruntime')
    lane = _lane(5)
    model = dh.LaneWithDrivable(lane, ignore_top=110).eval()
    with torch.no_grad():
        model.drivable[-1].bias.fill_(5.0)
    parent = tmp_path / 'parent.onnx'
    candidate = tmp_path / 'candidate.onnx'
    for module, path in ((lane, parent), (model, candidate)):
        torch.onnx.export(module, torch.rand(1, 3, 240, 320), str(path), opset_version=17,
                          input_names=['x'], output_names=['logits'])
    frames = [torch.rand(1, 3, 240, 320)]
    parity = dh.verify_candidate_lane_parity(parent, candidate, frames, ignore_top=110)
    assert parity['samples'] == 1 and parity['parent_lane_pixels_preserved']
    assert parity['ambiguous_pixels'] >= 0
    other = _lane(6)
    torch.onnx.export(other, torch.rand(1, 3, 240, 320), str(parent), opset_version=17,
                      input_names=['x'], output_names=['logits'])
    with pytest.raises(ValueError, match='parent lane pixels'):
        dh.verify_candidate_lane_parity(parent, candidate, frames, ignore_top=110)


def test_pinky_lane_segmentation_names_map_to_lane_unet():
    names = ["enc1.body.0.weight", "middle.4.running_var", "dec1.body.3.weight", "head.bias"]
    renamed = []
    for key in names:
        for old, new in dh.KEY_RENAMES:
            key = key.replace(old, new)
        renamed.append(key)
    assert set(renamed) <= set(rlm.LaneUNet(n_classes=5, base=4).state_dict())


def _dataset(root: Path, *, classes=None, drivable_index=1) -> Path:
    """Left half drivable (index 1), right half floor (0), top rows unlabelled (255)."""
    classes = classes or [{"index": 0, "name": "floor", "role": "background", "color": [0, 0, 0]},
                          {"index": 1, "name": "drivable", "role": "drivable", "color": [0, 255, 0]}]
    frames = []
    for split in ("train", "val"):
        for i in range(2):
            img, mask = f"images/{split}{i}.png", f"masks/{split}{i}.png"
            (root / "images").mkdir(parents=True, exist_ok=True)
            (root / "masks").mkdir(parents=True, exist_ok=True)
            bgr = np.zeros((240, 320, 3), np.uint8)
            bgr[:, :160] = (40, 200, 40)
            m = np.zeros((240, 320), np.uint8)
            m[:, :160] = drivable_index
            m[:20] = 255
            cv2.imwrite(str(root / img), bgr)
            cv2.imwrite(str(root / mask), m)
            frames.append({"image": img, "mask": mask, "session": split, "split": split})
    (root / "manifest.json").write_text(json.dumps({
        "schema": "rosy.perception.dataset/1", "classes": classes, "frames": frames,
        "ignore_index": 255}), encoding="utf-8")
    return root


def test_training_moves_only_the_head_and_learns(tmp_path):
    torch.manual_seed(2)
    lane = PixelLane(n_classes=5, base=4).eval()
    with torch.no_grad():
        lane.head.bias[0] += 100.0  # background everywhere: only the head decides drivable
    before = {k: v.clone() for k, v in lane.state_dict().items()}
    model = dh.LaneWithDrivable(lane)
    root = _dataset(tmp_path / "ds")
    train, val = rlm.RosyLaneDataset(root, "train"), rlm.RosyLaneDataset(root, "val")
    result = dh.train_head(model, train, val, epochs=30, lr=1e-2, batch_size=2,
                           device="cpu", log=None, pos_weight=1.0, fp_lambda=1.0)
    after = lane.state_dict()
    assert all(torch.equal(before[k], after[k]) for k in before)  # weights and BN stats
    assert result["val_drivable_iou"] > 0.5
    assert result["val_drivable_iou_all"] is not None
    assert result["val_outside_band_fp"] < 0.5  # floor beside drivable rows stays floor
    near = result["val_near_centre_drivable"]  # left half drivable: cols 110-159 of 110-210
    assert near["label"] == pytest.approx(50 / 101) and near["pred"] > 0.8 * near["label"]
    assert result["val_outside_band_fp_raw"] is not None and result["val_near_centre_drivable_raw"]
    assert result["val_beyond_line_fp"] is None  # no lane_left / lane_right classes in this set
    assert result["selection"]["fp_lambda"] == 1.0 and result["selection"]["pos_weight"] == 1.0
    best = next(r for r in result["history"] if r["epoch"] == result["best_epoch"])
    assert best["score"] == max(r["score"] for r in result["history"] if r["score"] is not None)
    assert best["score"] == pytest.approx(best["val_drivable_iou"] - best["val_outside_band_fp"])


def test_dataset_without_one_drivable_class_is_refused(tmp_path):
    root = _dataset(tmp_path / "ds")
    doc = json.loads((root / "manifest.json").read_text(encoding="utf-8"))
    doc["classes"][1]["role"] = "lane_marking"
    (root / "manifest.json").write_text(json.dumps(doc), encoding="utf-8")
    ds = rlm.RosyLaneDataset(root, "train")
    with pytest.raises(ValueError, match="exactly one class with role drivable"):
        dh.train_head(dh.LaneWithDrivable(_lane()), ds, ds, epochs=1, lr=1e-3,
                      batch_size=2, device="cpu", log=None)


@pytest.mark.skipif(not torch.cuda.is_available(), reason='candidate job needs model PC CUDA')
def test_candidate_job_exports_without_ready_or_lane_changes(tmp_path, monkeypatch):
    pytest.importorskip('onnx')
    pytest.importorskip('onnxruntime')
    from contextlib import nullcontext
    import hashlib
    import train_job

    lane = _lane(7)
    with torch.no_grad():
        lane.head.bias[0] += 100  # all pixels are parent background
    parent_dir = tmp_path / 'parent'; parent_dir.mkdir()
    script = _scripted(parent_dir, lane)
    onnx = parent_dir / 'model.onnx'
    torch.onnx.export(lane, torch.rand(1, 3, 240, 320), str(onnx), opset_version=17,
                      input_names=['x'], output_names=['logits'])
    classes = [{'index': i, 'name': name, 'role': role, 'color': [0, 0, 0]}
               for i, (name, role) in enumerate([*LANE_CLASSES, ('drivable', 'drivable')])]
    dataset = _dataset(tmp_path / ('a' * 64), classes=classes, drivable_index=5)
    profile = tmp_path / 'camera.json'; profile.write_text('{"accepted":true}')
    parent = {'torchscript': script, 'onnx': onnx,
              'input': {'color': 'rgb', 'scale': 1 / 255, 'mean': (0, 0, 0),
                        'std': (1, 1, 1)},
              'lineage': {'model_revision': 'lane-seg-synthetic',
                          'onnx_sha256': hashlib.sha256(onnx.read_bytes()).hexdigest(),
                          'torchscript_sha256': hashlib.sha256(script.read_bytes()).hexdigest()}}
    config = {'dataset': 'synthetic@' + dataset.name}
    training = {'seed': 7, 'epochs': 1, 'lr': 0.001, 'batch_size': 2,
                'ignore_top': 110, 'model_version': 'v13.1.00'}
    monkeypatch.setattr(train_job, 'gpu_lease', nullcontext)
    out = tmp_path / 'candidate-job'
    result = train_job._run_drivable_candidate(config, out, dataset, profile, training,
                                                parent, {'test': 'synthetic', 'camera_provenance': 'accepted'},
                                                lambda: None)
    assert result['status'] == 'candidate'
    assert result['revision'].startswith('v13-drivable-')
    assert json.loads((Path(result['artifact']) / 'model_manifest.json').read_text())['camera_provenance'] == 'accepted'
    assert json.loads((out / 'state.json').read_text())['outcome'] == 'candidate'
    assert (Path(result['artifact']) / 'candidate_parity.json').is_file()
    assert not list(tmp_path.rglob('READY'))
