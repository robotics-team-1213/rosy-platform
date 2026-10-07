"""Frozen lane model + trained drivable head (user decision 2026-10-07).

A delivered lane model (now2466 pinky-lane-segmentation v11, TorchScript) stays
frozen; only a small head on its last decoder features learns drivable. The
exported model keeps every lane class's logit as delivered and appends one
drivable channel, so argmax gives the lane model's own answer everywhere it does
not say background, and splits its background into background / drivable:

    background' = bg - relu(s)    drivable = bg - relu(-s)    (s = head logit)

max(background', drivable) == bg, so lane pixels never change (an exact tie
between bg and a lane class with s > 0 goes to the lane class instead of drivable). Rows above
ignore_top are forced to background, as the delivered v11 ROI wrapper does.

    python drivable_head.py --lane v11.torchscript.pt --dataset <dataset/1 folder> \
        --out <model folder> [--ignore-top 110] [--epochs 20]

The dataset needs exactly one class with role "drivable"; its other classes only
count as "not drivable", and its ignore_index pixels are left out.
"""

from __future__ import annotations

import argparse
import copy
import hashlib
import json
from pathlib import Path

import torch
from torch import nn

from rosy_lane_model import HEIGHT, WIDTH, LaneUNet, RosyLaneDataset

# State-dict names of the pinky-lane-segmentation LaneUNet -> rosy_lane_model.LaneUNet.
KEY_RENAMES = ((".body.", "."), ("middle.", "bottleneck."))
PARITY_MAX_ABS = 1e-5


def load_frozen_lane(path, *, classes=None) -> tuple[LaneUNet, int]:
    """TorchScript lane model -> frozen LaneUNet with the same output (checked), and its class count."""
    script = torch.jit.load(str(path), map_location="cpu").eval()
    state = {}
    for key, value in script.state_dict().items():
        for old, new in KEY_RENAMES:
            key = key.replace(old, new)
        state[key] = value
    n_classes, base = state["head.weight"].shape[0], state["enc1.0.weight"].shape[0]
    lane = LaneUNet(n_classes=n_classes, base=base)
    lane.load_state_dict(state, strict=True)
    lane.eval().requires_grad_(False)
    x = torch.rand(1, 3, HEIGHT, WIDTH, generator=torch.Generator().manual_seed(0))
    with torch.no_grad():
        diff = float((lane(x) - script(x)).abs().max())
    if diff > PARITY_MAX_ABS:
        raise ValueError(f"{path}: rebuilt lane model differs from the TorchScript by {diff}")
    if classes is not None and len(classes) != n_classes:
        raise ValueError(f"{path}: {n_classes} output channels, {len(classes)} classes given")
    return lane, n_classes


class LaneWithDrivable(nn.Module):
    """1x3xHxW -> 1x(C+1)xHxW logits: the lane model's C channels, then drivable."""

    def __init__(self, lane: LaneUNet, *, ignore_top: int = 0):
        super().__init__()
        if not 0 <= ignore_top < HEIGHT:
            raise ValueError(f"ignore_top must be in [0, {HEIGHT - 1}]")
        self.lane, self.ignore_top = lane, int(ignore_top)
        width = lane.head.in_channels
        self.drivable = nn.Sequential(
            nn.Conv2d(width, width, 3, padding=1, bias=False), nn.BatchNorm2d(width),
            nn.ReLU(inplace=True), nn.Conv2d(width, 1, 1))

    def train(self, mode: bool = True):
        super().train(mode)
        self.lane.eval()  # frozen: its BatchNorm statistics never move
        return self

    def drivable_logit(self, x):
        """(lane logits, head logit s) for the same features."""
        with torch.no_grad():
            features = self.lane.features(x)
            lane = self.lane.head(features)
        return lane, self.drivable(features)

    def forward(self, x):
        lane, s = self.drivable_logit(x)
        bg = lane[:, :1]
        out = torch.cat([bg - torch.relu(s), lane[:, 1:], bg - torch.relu(-s)], 1)
        if self.ignore_top:
            top = out[:, :, :self.ignore_top]
            peak = top.amax(dim=1, keepdim=True)
            forced = torch.cat([peak + 1.0, top[:, 1:] - 1000.0], 1)
            out = torch.cat([forced, out[:, :, self.ignore_top:]], 2)
        return out


def drivable_target(mask, drivable_index: int, ignore_index, ignore_top: int = 0):
    """Class-index mask -> (float target 1/0, bool keep)."""
    keep = torch.ones_like(mask, dtype=torch.bool)
    if ignore_index is not None:
        keep &= mask != ignore_index
    if ignore_top:
        keep[..., :ignore_top, :] = False
    return (mask == drivable_index).float(), keep


def _drivable_index(dataset) -> int:
    found = [c["index"] for c in dataset.classes if c["role"] == "drivable"]
    if len(found) != 1:
        raise ValueError(f"dataset needs exactly one class with role drivable, has {len(found)}")
    return found[0]


def train_head(model: LaneWithDrivable, train_ds, val_ds, *, epochs, lr, batch_size, device,
               log=print) -> dict:
    """Adam on the head only, BCE on labelled pixels; ends with the best val drivable IoU's weights."""
    index, ignore = _drivable_index(train_ds), train_ds.ignore_index
    if _drivable_index(val_ds) != index:
        raise ValueError("train and val disagree on the drivable class index")
    model = model.to(device)
    drivable_channel = model.lane.head.out_channels
    opt = torch.optim.Adam(model.drivable.parameters(), lr=lr)
    bce = nn.BCEWithLogitsLoss(reduction="none")
    loader = dict(batch_size=batch_size, num_workers=0)
    train_dl = torch.utils.data.DataLoader(train_ds, shuffle=True, **loader)
    val_dl = torch.utils.data.DataLoader(val_ds, **loader)
    history, best, best_state = [], None, None
    for epoch in range(1, epochs + 1):
        model.train()
        total, count = 0.0, 0
        for x, y in train_dl:
            x, y = x.to(device), y.to(device)
            target, keep = drivable_target(y, index, ignore, model.ignore_top)
            if not keep.any():
                continue
            _, s = model.drivable_logit(x)
            loss = bce(s[:, 0], target)[keep].mean()
            opt.zero_grad()
            loss.backward()
            opt.step()
            total, count = total + loss.item() * len(x), count + len(x)
        model.eval()
        inter = union = 0
        with torch.no_grad():
            for x, y in val_dl:
                x, y = x.to(device), y.to(device)
                target, keep = drivable_target(y, index, ignore, model.ignore_top)
                pred = model(x).argmax(1) == drivable_channel
                truth = target.bool()
                inter += int((pred & truth & keep).sum())
                union += int(((pred | truth) & keep).sum())
        iou = inter / union if union else None
        row = {"epoch": epoch, "train_loss": total / max(count, 1), "val_drivable_iou": iou}
        history.append(row)
        if iou is not None and (best is None or iou > best["val_drivable_iou"]):
            best, best_state = row, copy.deepcopy(model.drivable.state_dict())
        if log:
            log(f"epoch {epoch}/{epochs} loss {row['train_loss']:.4f} "
                f"drivable={'-' if iou is None else f'{iou:.3f}'}")
    if best_state is not None:
        model.drivable.load_state_dict(best_state)
    return {"history": history, "best_epoch": best["epoch"] if best else None,
            "val_drivable_iou": best["val_drivable_iou"] if best else None}


def _sha256(path) -> str:
    with open(path, "rb") as f:
        return hashlib.file_digest(f, "sha256").hexdigest()


def main(argv=None) -> int:
    p = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    p.add_argument("--lane", required=True, help="frozen lane model, TorchScript")
    p.add_argument("--lane-manifest", required=True,
                   help="the lane model's model_manifest.json (its classes and input are kept)")
    p.add_argument("--dataset", required=True, help="rosy.perception.dataset/1 folder with a drivable class")
    p.add_argument("--out", required=True)
    p.add_argument("--ignore-top", type=int, default=0)
    p.add_argument("--epochs", type=int, default=20)
    p.add_argument("--lr", type=float, default=3e-4)
    p.add_argument("--batch-size", type=int, default=16)
    p.add_argument("--seed", type=int, default=0)
    p.add_argument("--device", default="cuda" if torch.cuda.is_available() else "cpu")
    args = p.parse_args(argv)

    import export_cell  # torch-free import; export() needs torch, which we have

    torch.manual_seed(args.seed)
    lane_doc = json.loads(Path(args.lane_manifest).read_text(encoding="utf-8"))
    lane_classes = [(c["name"], c["role"]) for c in lane_doc["output"]["classes"]]
    lane, _ = load_frozen_lane(args.lane, classes=lane_classes)
    pre = {k: lane_doc["input"][k] for k in ("color", "scale", "mean", "std")}
    train_ds = RosyLaneDataset(args.dataset, "train", **pre)
    val_ds = RosyLaneDataset(args.dataset, "val", **pre)
    model = LaneWithDrivable(lane, ignore_top=args.ignore_top)
    result = train_head(model, train_ds, val_ds, epochs=args.epochs, lr=args.lr,
                        batch_size=args.batch_size, device=args.device)
    if result["val_drivable_iou"] is None:
        raise SystemExit("no val drivable IoU: the val split has no labelled drivable/non-drivable pixels")
    out = Path(args.out)
    model = model.cpu().eval()
    dataset = Path(args.dataset).resolve()  # store layout: datasets/<name>/<content_sha>
    doc = export_cell.export(
        model, out, classes=lane_classes + [("drivable", "drivable")],
        dataset_repo=dataset.parent.name, dataset_revision=dataset.name,
        camera_profile_revision=lane_doc.get("camera_profile_revision", "unknown"),
        trainer=f"drivable_head (frozen {lane_doc['model_revision']})",
        val_iou={"drivable": result["val_drivable_iou"]}, **pre)
    (out / "drivable_head_run.json").write_text(json.dumps({
        "lane_model_revision": lane_doc["model_revision"], "lane_sha256": _sha256(args.lane),
        "ignore_top": args.ignore_top, "seed": args.seed, "epochs": args.epochs, "lr": args.lr,
        **result}, indent=2) + "\n", encoding="utf-8")
    print(f"OK {doc['model_revision']} drivable IoU {result['val_drivable_iou']:.3f} -> {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
