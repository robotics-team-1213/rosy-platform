"""TorchScript -> ONNX model folder with a parity check (D-356).

export_onnx.py <model.torchscript.pt> --out <dir> --classes classes.yaml --color rgb
    --scale 0.00392156862745098 --mean 0 0 0 --std 1 1 1 --dataset-repo <r>
    --dataset-revision <sha> --camera-profile-revision <rev> --trainer <id>

Opset 17 at 1x3x240x320. The same fixed-seed random input goes through
TorchScript and onnxruntime; max_abs_diff > 1e-3 fails. The manifest is
written by training/export_cell.write_manifest (one writer, no copy).
--classes is required: class roles cannot be guessed."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
for _p in (ROOT / "tools" / "perception" / "training", ROOT / "src" / "runtime" / "sensing"):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

from export_cell import INPUT_SHAPE, ONNX_NAME, write_manifest  # noqa: E402

PARITY_TOLERANCE = 1e-3


def load_classes(path) -> list[dict]:
    """classes.yaml: {classes: [{index?, name, role, color?}]} in output-channel order."""
    import yaml
    doc = yaml.safe_load(Path(path).read_text(encoding="utf-8"))
    items = doc.get("classes") if isinstance(doc, dict) else doc
    if not isinstance(items, list) or not items:
        raise ValueError(f"{path}: expected a non-empty 'classes' list")
    out = []
    for pos, item in enumerate(items):
        if not isinstance(item, dict) or "name" not in item or "role" not in item:
            raise ValueError(f"{path}: classes[{pos}] needs name and role")
        if "index" in item and item["index"] != pos:
            raise ValueError(f"{path}: classes[{pos}].index is {item['index']}, expected {pos}")
        out.append({"name": item["name"], "role": item["role"]})
    return out


def _first_tensor(out):
    return out[0] if isinstance(out, (tuple, list)) else out


def export_and_check(ts_path, onnx_path, seed: int = 0) -> float:
    import numpy as np
    import onnxruntime as ort
    import torch
    model = torch.jit.load(str(ts_path), map_location="cpu").eval()
    with torch.no_grad():
        torch.onnx.export(model, torch.zeros(*INPUT_SHAPE), str(onnx_path), opset_version=17,
                          input_names=["x"], output_names=["logits"], dynamo=False)
        gen = torch.Generator().manual_seed(seed)
        x = torch.rand(*INPUT_SHAPE, generator=gen)
        ref = _first_tensor(model(x)).numpy()
    sess = ort.InferenceSession(str(onnx_path), providers=["CPUExecutionProvider"])
    got = sess.run(None, {sess.get_inputs()[0].name: x.numpy()})[0]
    if got.shape != ref.shape:
        raise ValueError(f"onnx output shape {got.shape} != torchscript {ref.shape}")
    return float(np.max(np.abs(got.astype(np.float64) - ref.astype(np.float64))))


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("torchscript")
    ap.add_argument("--out", required=True)
    ap.add_argument("--classes", required=True, help="classes.yaml (roles cannot be guessed)")
    ap.add_argument("--color", choices=("rgb", "bgr"), default="rgb")
    ap.add_argument("--scale", type=float, default=1 / 255)
    ap.add_argument("--mean", type=float, nargs=3, default=[0.0, 0.0, 0.0])
    ap.add_argument("--std", type=float, nargs=3, default=[1.0, 1.0, 1.0])
    ap.add_argument("--dataset-repo", required=True)
    ap.add_argument("--dataset-revision", required=True)
    ap.add_argument("--camera-profile-revision", required=True)
    ap.add_argument("--trainer", required=True)
    args = ap.parse_args(argv)

    classes = load_classes(args.classes)
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    onnx_path = out / ONNX_NAME
    diff = export_and_check(args.torchscript, onnx_path)
    print(f"parity max_abs_diff={diff:.3g}")
    if not diff <= PARITY_TOLERANCE:
        onnx_path.unlink(missing_ok=True)
        print(f"FAIL: parity {diff:.3g} > {PARITY_TOLERANCE}", file=sys.stderr)
        return 1
    doc = write_manifest(out, onnx_path=onnx_path, classes=classes, color=args.color,
                         scale=args.scale, mean=args.mean, std=args.std,
                         dataset_repo=args.dataset_repo, dataset_revision=args.dataset_revision,
                         camera_profile_revision=args.camera_profile_revision,
                         trainer=args.trainer)
    doc["metrics"]["export_parity_max_abs_diff"] = diff
    (out / "model_manifest.json").write_text(
        json.dumps(doc, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    from control.sensing.perception.learned.manifest import load_manifest, verify_files
    verify_files(load_manifest(out))
    print(f"OK {doc['model_revision']} -> {out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
