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


def test_load_frozen_lane_renames_keys_and_checks_parity(tmp_path):
    lane = _lane(1)
    loaded, n = dh.load_frozen_lane(_scripted(tmp_path, lane), classes=LANE_CLASSES)
    assert n == 5 and not any(p.requires_grad for p in loaded.parameters())
    x = torch.rand(1, 3, 240, 320)
    with torch.no_grad():
        assert torch.equal(loaded(x), lane(x))
    with pytest.raises(ValueError, match="classes given"):
        dh.load_frozen_lane(_scripted(tmp_path, lane), classes=LANE_CLASSES[:4])


def test_pinky_lane_segmentation_names_map_to_lane_unet():
    names = ["enc1.body.0.weight", "middle.4.running_var", "dec1.body.3.weight", "head.bias"]
    renamed = []
    for key in names:
        for old, new in dh.KEY_RENAMES:
            key = key.replace(old, new)
        renamed.append(key)
    assert set(renamed) <= set(rlm.LaneUNet(n_classes=5, base=4).state_dict())


def _dataset(root: Path) -> Path:
    """Left half drivable (index 1), right half floor (0), top rows unlabelled (255)."""
    classes = [{"index": 0, "name": "floor", "role": "background", "color": [0, 0, 0]},
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
            m[:, :160] = 1
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
                           device="cpu", log=None)
    after = lane.state_dict()
    assert all(torch.equal(before[k], after[k]) for k in before)  # weights and BN stats
    assert result["val_drivable_iou"] > 0.5
    assert result["val_drivable_iou_all"] is not None


def test_dataset_without_one_drivable_class_is_refused(tmp_path):
    root = _dataset(tmp_path / "ds")
    doc = json.loads((root / "manifest.json").read_text(encoding="utf-8"))
    doc["classes"][1]["role"] = "lane_marking"
    (root / "manifest.json").write_text(json.dumps(doc), encoding="utf-8")
    ds = rlm.RosyLaneDataset(root, "train")
    with pytest.raises(ValueError, match="exactly one class with role drivable"):
        dh.train_head(dh.LaneWithDrivable(_lane()), ds, ds, epochs=1, lr=1e-3,
                      batch_size=2, device="cpu", log=None)
