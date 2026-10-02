"""A trained .pt to a robot model folder, on the PC only, with a parity check (D-423 §3.3).

convert.py SOURCE.pt --kind torchscript|state_dict|ultralytics --task lane_seg|object_det
    --out DIR [--model-class NAME] [--input H W] [--classes classes.yaml]
    [--int8 --calib DIR] --dataset-repo R --dataset-revision SHA
    --camera-profile-revision REV --trainer ID

kinds
  torchscript   torch.jit.load(SOURCE)
  state_dict    torch.load(SOURCE) into MODEL_REGISTRY[--model-class] (code from this repo)
  ultralytics   ultralytics YOLO(SOURCE).export(format="onnx"); object_det only

The same fixed-seed probes go through the PyTorch model and onnxruntime; a max
absolute difference above --tolerance (1e-3) or any shape change fails and
writes nothing. --int8 adds a QDQ copy (onnxruntime quantize_static on frames
from --calib) and records its distance from fp32 in the manifest metrics; the
intake gate, not this tool, decides whether it is good enough.

The robot never runs this file and never needs torch: it receives the ONNX
folder through intake -> deliver (D-356, D-373). torch, onnx, onnxruntime and
ultralytics are imported only inside the functions that need them.
lane_seg manifests are written by training/export_cell.write_manifest (one writer);
object_det manifests by write_object_manifest here."""

from __future__ import annotations

import argparse
import datetime
import hashlib
import importlib
import inspect
import json
import sys
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[3]
for _p in (ROOT / "tools" / "perception" / "training", ROOT / "src" / "runtime" / "sensing"):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

from control.sensing.perception.learned.manifest import (  # noqa: E402
    LAYOUTS, OBJECT_CLASSES, OBJECT_ROLE, SCHEMA, TASKS, load_manifest, verify_files)

PARITY_TOLERANCE = 1e-3
ONNX_NAME = "model.onnx"
OPSET = 17
#: state_dict loading needs the model's code: only classes registered here, from this repo.
MODEL_REGISTRY = {"lane_unet": ("rosy_lane_model", "LaneUNet")}
LANE_INPUT = (240, 320)
OBJECT_INPUT = (256, 320)  # the 320x240 frame letterboxed to stride 32


def resolve_class(name: str):
    if name not in MODEL_REGISTRY:
        raise ValueError(f"model class {name!r} is not in the registry {sorted(MODEL_REGISTRY)}")
    module, attr = MODEL_REGISTRY[name]
    return getattr(importlib.import_module(module), attr)


def probe_inputs(shape, count=3, seed=0) -> list:
    rng = np.random.default_rng(seed)
    return [rng.random(shape, dtype=np.float32) for _ in range(count)]


def parity(reference, candidate, inputs, tolerance=PARITY_TOLERANCE) -> dict:
    """{ok, max_abs_diff, reason}: both callables map one float32 NCHW array to one array."""
    worst = 0.0
    for x in inputs:
        ref, got = np.asarray(reference(x)), np.asarray(candidate(x))
        if ref.shape != got.shape:
            return {"ok": False, "max_abs_diff": None, "reason": f"shape {got.shape} != {ref.shape}"}
        diff = float(np.max(np.abs(got.astype(np.float64) - ref.astype(np.float64))))
        worst = max(worst, diff)
    ok = bool(worst <= tolerance)
    return {"ok": ok, "max_abs_diff": worst,
            "reason": None if ok else f"max_abs_diff {worst:.3g} > {tolerance}"}


def _first(out):
    return out[0] if isinstance(out, (tuple, list)) else out


def load_torch_model(path, kind, model_class=None):
    import torch  # PC only
    if kind == "torchscript":
        return torch.jit.load(str(path), map_location="cpu").eval()
    model = resolve_class(model_class)()
    model.load_state_dict(torch.load(str(path), map_location="cpu", weights_only=True))
    return model.eval()


def torch_runner(model):
    import torch

    def run(x):
        with torch.no_grad():
            return _first(model(torch.from_numpy(x))).numpy()
    return run


def onnx_runner(path):
    import onnxruntime as ort
    session = ort.InferenceSession(str(path), providers=["CPUExecutionProvider"])
    name = session.get_inputs()[0].name
    return lambda x: session.run(None, {name: x})[0]


def export_torch(model, onnx_path, shape):
    import torch
    extra = {"dynamo": False} if "dynamo" in inspect.signature(torch.onnx.export).parameters else {}
    with torch.no_grad():
        torch.onnx.export(model, torch.zeros(*shape), str(onnx_path), opset_version=OPSET,
                          input_names=["x"], output_names=["y"], **extra)


def export_ultralytics(source, onnx_path, hw):
    """(reference runner, onnx path): ultralytics' own exporter, raw head (no NMS in the graph)."""
    from ultralytics import YOLO  # PC only, optional
    yolo = YOLO(str(source))
    exported = Path(yolo.export(format="onnx", imgsz=list(hw), opset=OPSET, dynamic=False,
                                simplify=False, nms=False))
    Path(onnx_path).write_bytes(exported.read_bytes())
    return torch_runner(yolo.model.eval())


def quantize_int8(fp32_path, int8_path, calib_dir, hw):
    """onnxruntime quantize_static (QDQ) with letterboxed frames from calib_dir."""
    import cv2
    from onnxruntime.quantization import CalibrationDataReader, QuantFormat, quantize_static
    from control.sensing.perception.learned.detector import letterbox

    frames = sorted(p for p in Path(calib_dir).iterdir() if p.suffix.lower() in (".jpg", ".png"))
    if not frames:
        raise ValueError(f"no calibration images in {calib_dir}")

    class Reader(CalibrationDataReader):
        def __init__(self):
            self._it = iter(frames)

        def get_next(self):
            path = next(self._it, None)
            if path is None:
                return None
            image = letterbox(cv2.imread(str(path)), hw[1], hw[0])[0][..., ::-1]
            return {"x": np.ascontiguousarray(image.transpose(2, 0, 1)[None], np.float32) / 255.0}

    quantize_static(str(fp32_path), str(int8_path), Reader(), quant_format=QuantFormat.QDQ)


def write_object_manifest(out_dir, *, onnx_path, input_hw, color, scale, mean, std, dataset_repo,
                          dataset_revision, camera_profile_revision, trainer, precision="fp32",
                          metrics=None, date=None) -> dict:
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    data = Path(onnx_path).read_bytes()
    sha = hashlib.sha256(data).hexdigest()
    target = out_dir / ONNX_NAME
    if Path(onnx_path).resolve() != target.resolve():
        target.write_bytes(data)
    date = date or datetime.date.today().strftime("%Y%m%d")
    doc = {
        "schema": SCHEMA, "model_revision": f"object-det-{date}-{sha[:8]}", "task": "object_det",
        "files": [{"name": ONNX_NAME, "sha256": sha, "precision": precision}],
        "input": {"shape": [1, 3, int(input_hw[0]), int(input_hw[1])], "layout": "nchw",
                  "color": color, "scale": float(scale), "mean": [float(v) for v in mean],
                  "std": [float(v) for v in std]},
        "output": {"layout": LAYOUTS["object_det"], "classes": [
            {"index": i, "name": n, "role": OBJECT_ROLE} for i, n in enumerate(OBJECT_CLASSES)]},
        "dataset": {"repo": dataset_repo, "revision": dataset_revision},
        "camera_profile_revision": camera_profile_revision,
        "metrics": dict(metrics or {}), "trainer": trainer,
    }
    (out_dir / "model_manifest.json").write_text(json.dumps(doc, indent=2) + "\n", encoding="utf-8")
    verify_files(load_manifest(out_dir))  # the robot-side loader is the judge
    return doc


def _arguments():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("source")
    ap.add_argument("--kind", choices=("torchscript", "state_dict", "ultralytics"), required=True)
    ap.add_argument("--task", choices=TASKS, required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--model-class", help=f"state_dict only; one of {sorted(MODEL_REGISTRY)}")
    ap.add_argument("--input", type=int, nargs=2, metavar=("H", "W"))
    ap.add_argument("--classes", help="lane_seg: classes.yaml (roles cannot be guessed)")
    ap.add_argument("--color", choices=("rgb", "bgr"), default="rgb")
    ap.add_argument("--tolerance", type=float, default=PARITY_TOLERANCE)
    ap.add_argument("--int8", action="store_true")
    ap.add_argument("--calib", help="--int8: folder of calibration frames (.jpg/.png)")
    for name in ("--dataset-repo", "--dataset-revision", "--camera-profile-revision", "--trainer"):
        ap.add_argument(name, required=True)
    return ap


def _refusal(args):
    if args.kind == "state_dict" and not args.model_class:
        return "state_dict needs --model-class (the model's code is not in a state_dict)"
    if args.kind == "ultralytics" and args.task != "object_det":
        return "ultralytics exports are object_det models only"
    hw = tuple(args.input) if args.input else (OBJECT_INPUT if args.task == "object_det" else LANE_INPUT)
    if args.task == "object_det" and (hw[0] % 32 or hw[1] % 32):
        return f"object_det input {hw} must be a multiple of 32"
    if args.task == "lane_seg" and hw != LANE_INPUT:
        return f"lane_seg input is fixed at {LANE_INPUT} (training/export_cell.INPUT_SHAPE)"
    if args.task == "lane_seg" and not args.classes:
        return "lane_seg needs --classes"
    if args.int8 and not args.calib:
        return "--int8 needs --calib"
    return None


def main(argv=None) -> int:
    args = _arguments().parse_args(argv)
    why = _refusal(args)
    if why:
        print(f"refused: {why}", file=sys.stderr)
        return 2
    hw = tuple(args.input) if args.input else (OBJECT_INPUT if args.task == "object_det" else LANE_INPUT)
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    staged = out / f".{ONNX_NAME}.fp32"
    if args.kind == "ultralytics":
        reference = export_ultralytics(args.source, staged, hw)
    else:
        model = load_torch_model(args.source, args.kind, args.model_class)
        export_torch(model, staged, (1, 3, *hw))
        reference = torch_runner(model)
    probes = probe_inputs((1, 3, *hw))
    result = parity(reference, onnx_runner(staged), probes, args.tolerance)
    print(f"parity {result}")
    if not result["ok"]:
        staged.unlink(missing_ok=True)
        print(f"FAIL: {result['reason']}", file=sys.stderr)
        return 1
    metrics = {"export_parity_max_abs_diff": result["max_abs_diff"], "export_kind": args.kind}
    final, precision = staged, "fp32"
    if args.int8:
        final, precision = out / f".{ONNX_NAME}.int8", "int8"
        quantize_int8(staged, final, args.calib, hw)
        metrics["int8_vs_fp32"] = parity(onnx_runner(staged), onnx_runner(final), probes, float("inf"))["max_abs_diff"]
    common = dict(dataset_repo=args.dataset_repo, dataset_revision=args.dataset_revision,
                  camera_profile_revision=args.camera_profile_revision, trainer=args.trainer,
                  precision=precision)
    if args.task == "object_det":
        doc = write_object_manifest(out, onnx_path=final, input_hw=hw, color=args.color, scale=1 / 255,
                                    mean=[0, 0, 0], std=[1, 1, 1], metrics=metrics, **common)
    else:
        from export_cell import write_manifest
        from export_onnx import load_classes
        doc = write_manifest(out, onnx_path=final, classes=load_classes(args.classes), color=args.color,
                             scale=1 / 255, mean=[0, 0, 0], std=[1, 1, 1], **common)
        doc["metrics"].update(metrics)
        (out / "model_manifest.json").write_text(json.dumps(doc, indent=2) + "\n", encoding="utf-8")
    for leftover in (staged, out / f".{ONNX_NAME}.int8"):
        leftover.unlink(missing_ok=True)
    print(f"OK {doc['model_revision']} -> {out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
