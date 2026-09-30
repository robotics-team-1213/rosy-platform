"""D-373 decision 7: baseline trainer module used by rosy_lane_training.ipynb."""
import json
import math
import sys
from pathlib import Path

import pytest

torch = pytest.importorskip("torch")
cv2 = pytest.importorskip("cv2")
np = pytest.importorskip("numpy")

ROOT = Path(__file__).resolve().parents[3]
TRAINING = ROOT / "tools" / "perception" / "training"
if str(TRAINING) not in sys.path:
    sys.path.insert(0, str(TRAINING))

import rosy_lane_model as rlm  # noqa: E402

CLASSES = [
    {"index": 0, "name": "floor", "role": "background", "color": [40, 40, 40]},
    {"index": 1, "name": "line_a", "role": "lane_marking", "color": [255, 0, 0]},
    {"index": 2, "name": "line_b", "role": "lane_marking", "color": [0, 200, 255]},
    {"index": 3, "name": "wall", "role": "ignore", "color": [255, 200, 0]},
]
BGR = (10, 100, 200)


def _mini_dataset(root: Path) -> Path:
    """build.py-shaped folder: 640x480 camera JPEGs, class-index PNG masks, session split."""
    frames = []
    for session, split in (("s_train", "train"), ("s_val", "val")):
        for index in range(2):
            img_rel = f"images/{session}/{session}__{index:06d}.jpg"
            mask_rel = f"masks/{session}/{session}__{index:06d}.png"
            (root / img_rel).parent.mkdir(parents=True, exist_ok=True)
            (root / mask_rel).parent.mkdir(parents=True, exist_ok=True)
            img = np.zeros((480, 640, 3), np.uint8)
            img[:] = BGR
            cv2.imwrite(str(root / img_rel), img, [cv2.IMWRITE_JPEG_QUALITY, 100])
            mask = np.zeros((480, 640), np.uint8)
            mask[:, :320] = 1
            mask[:40] = 3
            cv2.imwrite(str(root / mask_rel), mask)
            frames.append({"image": img_rel, "mask": mask_rel, "session": session, "split": split})
    # A stray file that no frame references must never be read.
    cv2.imwrite(str(root / "images" / "s_train" / "s_train__000099.jpg"),
                np.zeros((8, 8, 3), np.uint8))
    manifest = {"schema": "rosy.perception.dataset/1", "classes": CLASSES, "frames": frames,
                "deleted_indexes": [], "sources": []}
    (root / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
    return root


def _fused_param_count(model) -> int:
    """Parameter count once BatchNorm is folded into the preceding conv, as in the ONNX."""
    n = 0
    for m in model.modules():
        if isinstance(m, (torch.nn.Conv2d, torch.nn.ConvTranspose2d)):
            n += m.weight.numel() + (m.bias.numel() if m.bias is not None else 0)
        elif isinstance(m, torch.nn.BatchNorm2d):
            n += m.num_features
    return n


def test_forward_shape_and_baseline_structure():
    model = rlm.LaneUNet().eval()
    with torch.no_grad():
        out = model(torch.zeros(1, 3, 240, 320))
    assert tuple(out.shape) == (1, 4, 240, 320)
    sd = model.state_dict()
    assert tuple(sd["up4.weight"].shape) == (256, 128, 2, 2)
    assert tuple(sd["up1.weight"].shape) == (32, 16, 2, 2)
    assert tuple(sd["head.weight"].shape) == (4, 16, 1, 1)
    # The deployed 0930 ONNX (lane-seg-20260930-05ac31c0) holds exactly this many values.
    assert _fused_param_count(model) == 1_941_156


def test_forward_other_class_count():
    with torch.no_grad():
        out = rlm.LaneUNet(n_classes=3, base=4).eval()(torch.zeros(2, 3, 240, 320))
    assert tuple(out.shape) == (2, 3, 240, 320)


def test_class_iou_math():
    pred = torch.tensor([0, 0, 1, 1])
    target = torch.tensor([0, 1, 1, 1])
    iou = rlm.class_iou(pred, target, 3)
    assert iou[0] == pytest.approx(0.5)
    assert iou[1] == pytest.approx(2 / 3)
    assert iou[2] is None  # absent in both: undefined, not 0 or 1


def test_class_iou_ignore_index():
    pred = torch.tensor([0, 1, 1, 0])
    target = torch.tensor([0, 1, 255, 255])
    iou = rlm.class_iou(pred, target, 2, ignore_index=255)
    assert iou == [pytest.approx(1.0), pytest.approx(1.0)]


def test_preprocess_matches_robot_formula_and_manifest():
    pre = rlm.Preprocess(color="bgr", scale=1.0, mean=(1, 2, 3), std=(2, 2, 2))
    bgr = np.full((2, 2, 3), BGR, np.uint8)
    x = pre.apply(bgr)
    assert x.shape == (3, 2, 2) and x.dtype == np.float32
    assert x[:, 0, 0].tolist() == pytest.approx([(10 - 1) / 2, (100 - 2) / 2, (200 - 3) / 2])
    rgb = rlm.Preprocess().apply(bgr)
    assert rgb[:, 0, 0].tolist() == pytest.approx([200 / 255, 100 / 255, 10 / 255])
    assert pre.manifest_kwargs() == {"color": "bgr", "scale": 1.0,
                                     "mean": [1.0, 2.0, 3.0], "std": [2.0, 2.0, 2.0]}
    with pytest.raises(ValueError):
        rlm.Preprocess(color="hsv")


def test_dataset_reads_manifest_paths_resizes_and_preprocesses(tmp_path):
    root = _mini_dataset(tmp_path / "ds")
    train = rlm.RosyLaneDataset(root, "train", color="rgb", scale=1 / 255,
                                mean=(0, 0, 0), std=(1, 1, 1))
    val = rlm.RosyLaneDataset(root, "val", color="rgb", scale=1 / 255,
                              mean=(0, 0, 0), std=(1, 1, 1))
    assert len(train) == 2 and len(val) == 2
    assert [c["name"] for c in train.classes] == ["floor", "line_a", "line_b", "wall"]
    assert train.preprocess == rlm.Preprocess("rgb", 1 / 255, (0, 0, 0), (1, 1, 1))
    x, y = train[0]
    assert tuple(x.shape) == (3, 240, 320) and x.dtype == torch.float32
    assert tuple(y.shape) == (240, 320) and y.dtype == torch.int64
    assert x[:, 120, 160].tolist() == pytest.approx([200 / 255, 100 / 255, 10 / 255], abs=3 / 255)
    assert set(torch.unique(y).tolist()) == {0, 1, 3}   # nearest: no blended class values
    assert y[120, 10].item() == 1 and y[120, 310].item() == 0 and y[5, 160].item() == 3


def test_dataset_rejects_unknown_split(tmp_path):
    root = _mini_dataset(tmp_path / "ds")
    with pytest.raises(ValueError):
        rlm.RosyLaneDataset(root, "test")


def test_class_mismatch():
    ok = [("floor", "background"), ("line_a", "lane_marking"),
          ("line_b", "lane_marking"), ("wall", "ignore")]
    assert rlm.class_mismatch(ok, CLASSES) is None
    assert "order" in rlm.class_mismatch(list(reversed(ok)), CLASSES)
    bad_role = ok[:3] + [("wall", "background")]
    assert "wall" in rlm.class_mismatch(bad_role, CLASSES)
    assert rlm.class_mismatch(ok[:3], CLASSES) is not None


class _Synthetic(torch.utils.data.Dataset):
    """Bright pixels are class 1, dark ones class 0."""

    classes = [{"index": 0, "name": "floor", "role": "background"},
               {"index": 1, "name": "lane", "role": "lane_marking"}]

    def __init__(self, n, seed):
        g = torch.Generator().manual_seed(seed)
        self.x = torch.rand(n, 3, 240, 320, generator=g)
        self.y = (self.x.mean(1) > 0.5).long()

    def __len__(self):
        return len(self.x)

    def __getitem__(self, i):
        return self.x[i], self.y[i]


def test_train_reduces_loss_and_reports_iou():
    torch.manual_seed(0)
    model = rlm.LaneUNet(n_classes=2, base=4)
    result = rlm.train(model, _Synthetic(8, 1), _Synthetic(2, 2), epochs=2, lr=5e-3,
                       batch_size=4, device="cpu", num_workers=0)
    history = result["history"]
    assert len(history) == 2
    assert history[-1]["train_loss"] < history[0]["train_loss"]
    assert set(history[-1]["val_iou"]) == {"floor", "lane"}
    assert all(v is None or 0.0 <= v <= 1.0 for v in history[-1]["val_iou"].values())
    assert math.isfinite(history[-1]["val_loss"])


def test_train_restores_best_epoch():
    torch.manual_seed(1)
    model = rlm.LaneUNet(n_classes=2, base=4)
    val = _Synthetic(2, 2)
    result = rlm.train(model, _Synthetic(8, 1), val, epochs=3, lr=5e-2, batch_size=4,
                       device="cpu", num_workers=0)
    best = result["best_epoch"]
    rows = result["history"]
    score = lambda r: sum(v for v in r["val_iou"].values() if v is not None) / max(
        1, sum(v is not None for v in r["val_iou"].values()))
    assert best == max(rows, key=score)["epoch"]  # max() keeps the first of ties
    assert result["val_iou"] == rows[best - 1]["val_iou"]
    # The model left behind is the best epoch's, not the last one's.
    with torch.no_grad():
        pred = model.eval()(val.x).argmax(1)
    assert dict(zip(["floor", "lane"], rlm.class_iou(pred, val.y, 2))) == pytest.approx(
        result["val_iou"])


def _frame_folder(root, image, mask, classes=CLASSES):
    root.mkdir(parents=True)
    cv2.imwrite(str(root / "f.png"), image)
    cv2.imwrite(str(root / "m.png"), mask)
    manifest = {"schema": "rosy.perception.dataset/1", "classes": classes, "sources": [],
                "frames": [{"image": "f.png", "mask": "m.png", "session": "s", "split": "train"}]}
    (root / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
    return root


@pytest.mark.parametrize("pre", [
    dict(color="rgb", scale=1 / 255, mean=(0.485, 0.456, 0.406), std=(0.229, 0.224, 0.225)),
    dict(color="bgr", scale=1.0, mean=(0.0, 0.0, 0.0), std=(1.0, 1.0, 1.0)),
])
def test_dataset_matches_robot_preprocess_exactly(tmp_path, pre):
    from control.sensing.perception.learned.lane_mask import preprocess
    from control.sensing.perception.learned.manifest import InputSpec

    image = np.random.default_rng(3).integers(0, 256, (480, 640, 3), dtype=np.uint8)
    root = _frame_folder(tmp_path / "ds", image, np.zeros((480, 640), np.uint8))
    x, _ = rlm.RosyLaneDataset(root, "train", **pre)[0]
    spec = InputSpec(shape=(1, 3, 240, 320), color=pre["color"], scale=pre["scale"],
                     mean=pre["mean"], std=pre["std"])
    robot = preprocess(cv2.imread(str(root / "f.png"), cv2.IMREAD_COLOR), spec)
    assert np.array_equal(x.numpy()[None], robot)


def test_dataset_rejects_bad_masks(tmp_path):
    image = np.zeros((48, 64, 3), np.uint8)
    rgb_mask = _frame_folder(tmp_path / "a", image, np.zeros((48, 64, 3), np.uint8))
    with pytest.raises(ValueError, match="m.png"):
        rlm.RosyLaneDataset(rgb_mask, "train")[0]
    too_big = np.zeros((48, 64), np.uint8)
    too_big[0, 0] = 4   # four classes -> valid indexes are 0..3
    big = _frame_folder(tmp_path / "b", image, too_big)
    with pytest.raises(ValueError, match="m.png"):
        rlm.RosyLaneDataset(big, "train")[0]


def test_export_via_export_cell_passes_check_manifest(tmp_path):
    pytest.importorskip("onnx")
    pytest.importorskip("onnxruntime")
    import check_manifest
    import export_cell

    pre = rlm.Preprocess()
    out = tmp_path / "lane_model"
    doc = export_cell.export(
        rlm.LaneUNet(base=4), out,
        classes=[(c["name"], c["role"]) for c in CLASSES], **pre.manifest_kwargs(),
        dataset_repo="org/ds", dataset_revision="a" * 40, camera_profile_revision="cam-1",
        trainer="tester colab:rosy_lane_training.ipynb@abc1234", val_iou={"line_a": 0.5})
    assert check_manifest.main([str(out)]) == 0
    assert check_manifest.check(str(out)) == doc["model_revision"]
    assert doc["input"]["color"] == "rgb" and doc["input"]["scale"] == pytest.approx(1 / 255)
