"""A trained .pt to a robot model folder, on the PC only, with a parity check (D-423 §3.3).

convert.py SOURCE.pt --kind torchscript|state_dict|ultralytics --task lane_seg|object_det
    --out DIR [--model-class NAME] [--input H W] [--classes classes.yaml]
    [--int8 --calib DIR] --dataset-repo R --dataset-revision SHA
    --camera-profile-revision REV --trainer ID

kinds
  torchscript   torch.jit.load(SOURCE)
  state_dict    torch.load(SOURCE) into MODEL_REGISTRY[--model-class] (code from this repo)
  ultralytics   ultralytics YOLO(SOURCE).export(format="onnx"); object_det only; needs
                ultralytics >= 8.3 (the export `nms` argument); not exercised on this repo's CI

The same fixed-seed probes go through the PyTorch model and onnxruntime; a max
absolute difference above --tolerance (1e-3) or any shape change fails and
writes nothing (--rtol adds a relative bound for pixel-valued box outputs).
--int8 adds a QDQ copy (onnxruntime quantize_static on --calib frames in the
--color order, fed under the model's own input name) and records its distance
from fp32 on the random probes (int8_vs_fp32, and int8_vs_fp32_rel scaled by the
output peak) in the manifest metrics; the intake gate's max_int8_vs_fp32_rel
judges it. Random probes are not camera frames, so that distance is coarse.

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

ROOT = Path(__file__).resolve().parents[4]
for _p in (ROOT / "learning" / "training" / "perception" / "training", ROOT / "src" / "runtime" / "sensing",
           ROOT / "contracts" / "foundation"):
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


def parity(reference, candidate, inputs, tolerance=PARITY_TOLERANCE, rtol=0.0) -> dict:
    """{ok, max_abs_diff, peak_abs_ref, reason}: |got - ref| <= tolerance + rtol * |ref| everywhere.

    Both callables map one float32 NCHW array to one array. rtol matters for outputs in
    pixels (detection boxes), where a fixed absolute bound alone is meaningless."""
    worst, peak, ok = 0.0, 0.0, True
    for x in inputs:
        ref = np.asarray(reference(x)).astype(np.float64)
        got = np.asarray(candidate(x)).astype(np.float64)
        if ref.shape != got.shape:
            return {"ok": False, "max_abs_diff": None, "peak_abs_ref": None,
                    "reason": f"shape {got.shape} != {ref.shape}"}
        diff = np.abs(got - ref)
        worst, peak = max(worst, float(diff.max())), max(peak, float(np.abs(ref).max()))
        ok = ok and bool(np.all(diff <= tolerance + rtol * np.abs(ref)))
    return {"ok": ok, "max_abs_diff": worst, "peak_abs_ref": peak,
            "reason": None if ok else f"max_abs_diff {worst:.3g} > {tolerance} + {rtol}*|ref|"}


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


def calibration_frames(calib_dir, hw, color):
    """Letterboxed NCHW float32 frames (scale 1/255, the manifest's) in the model's colour order."""
    import cv2
    from control.sensing.perception.learned.detector import letterbox

    paths = sorted(p for p in Path(calib_dir).iterdir() if p.suffix.lower() in (".jpg", ".png"))
    if not paths:
        raise ValueError(f"no calibration images in {calib_dir}")
    for path in paths:
        image = letterbox(cv2.imread(str(path)), hw[1], hw[0])[0]  # cv2 decodes BGR
        if color == "rgb":
            image = image[..., ::-1]
        yield np.ascontiguousarray(image.transpose(2, 0, 1)[None], np.float32) / 255.0


def quantize_int8(fp32_path, int8_path, calib_dir, hw, color):
    """onnxruntime quantize_static (QDQ), fed under the fp32 model's own input name."""
    import onnxruntime as ort
    from onnxruntime.quantization import CalibrationDataReader, QuantFormat, quantize_static

    name = ort.InferenceSession(str(fp32_path), providers=["CPUExecutionProvider"]).get_inputs()[0].name
    frames = calibration_frames(calib_dir, hw, color)

    class Reader(CalibrationDataReader):
        def get_next(self):
            frame = next(frames, None)
            return None if frame is None else {name: frame}

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
    ap.add_argument("--backend", choices=("onnx", "ncnn"), default="onnx")
    ap.add_argument("--frames", help="ncnn: held-out camera images (.png/.jpg/.jpeg) for real-frame parity")
    ap.add_argument("--min-eval-frames", type=int, default=20)
    ap.add_argument("--box-iou", type=float, default=0.95)
    ap.add_argument("--confidence-tolerance", type=float, default=0.01)
    ap.add_argument("--min-pixel-agreement", type=float, default=0.999)
    ap.add_argument("--model-class", help=f"state_dict only; one of {sorted(MODEL_REGISTRY)}")
    ap.add_argument("--input", type=int, nargs=2, metavar=("H", "W"))
    ap.add_argument("--classes", help="lane_seg: classes.yaml (roles cannot be guessed)")
    ap.add_argument("--color", choices=("rgb", "bgr"), default="rgb")
    ap.add_argument("--tolerance", type=float, default=PARITY_TOLERANCE, help="parity atol")
    ap.add_argument("--rtol", type=float, default=PARITY_TOLERANCE, help="parity rtol (box pixels)")
    ap.add_argument("--int8", action="store_true")
    ap.add_argument("--calib", help="--int8: folder of calibration frames (.jpg/.png)")
    for name in ("--dataset-repo", "--dataset-revision", "--camera-profile-revision", "--trainer"):
        ap.add_argument(name, required=True)
    return ap


def _refusal(args):
    if args.backend == "ncnn":
        if (args.kind, args.task) not in (("ultralytics", "object_det"), ("torchscript", "lane_seg")):
            return "ncnn supports ultralytics object_det or independently verified torchscript lane_seg"
        if args.int8:
            return "ncnn int8 is not supported; --int8 is ONNX QDQ only"
        if not args.frames:
            return "ncnn needs --frames for real-camera parity"
        if args.kind == "ultralytics" and args.color != "rgb":
            return "ultralytics ncnn needs rgb input"
        if args.min_eval_frames < 1 or not 0.95 <= args.box_iou <= 1 or not 0 <= args.confidence_tolerance <= 0.01:
            return "invalid ncnn frame/detection parity limits"
        if not 0.999 <= args.min_pixel_agreement <= 1:
            return "min-pixel-agreement must be in [0.999, 1]"
    if not all(np.isfinite(v) and v >= 0 for v in (args.tolerance, args.rtol)):
        return "parity tolerance and rtol must be finite and nonnegative"
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


def _convert(args, hw, out, staged, staged_int8):
    """Export, parity, optional int8, manifest. The manifest document, or None on a parity failure."""
    if args.kind == "ultralytics":
        reference = export_ultralytics(args.source, staged, hw)
    else:
        model = load_torch_model(args.source, args.kind, args.model_class)
        export_torch(model, staged, (1, 3, *hw))
        reference = torch_runner(model)
    probes = probe_inputs((1, 3, *hw))
    result = parity(reference, onnx_runner(staged), probes, args.tolerance, args.rtol)
    print(f"parity {result}")
    if not result["ok"]:
        print(f"FAIL: {result['reason']}", file=sys.stderr)
        return None
    metrics = {"export_parity_max_abs_diff": result["max_abs_diff"], "export_kind": args.kind}
    final, precision = staged, "fp32"
    if args.int8:
        final, precision = staged_int8, "int8"
        quantize_int8(staged, final, args.calib, hw, args.color)
        # Random probes, not camera frames: a coarse, scale-free distance for the intake gate.
        q = parity(onnx_runner(staged), onnx_runner(final), probes, float("inf"))
        metrics["int8_vs_fp32"] = q["max_abs_diff"]
        metrics["int8_vs_fp32_rel"] = q["max_abs_diff"] / max(q["peak_abs_ref"], 1e-12)
    common = dict(dataset_repo=args.dataset_repo, dataset_revision=args.dataset_revision,
                  camera_profile_revision=args.camera_profile_revision, trainer=args.trainer,
                  precision=precision)
    if args.task == "object_det":
        return write_object_manifest(out, onnx_path=final, input_hw=hw, color=args.color, scale=1 / 255,
                                     mean=[0, 0, 0], std=[1, 1, 1], metrics=metrics, **common)
    from export_cell import write_manifest
    from export_onnx import load_classes
    doc = write_manifest(out, onnx_path=final, classes=load_classes(args.classes), color=args.color,
                         scale=1 / 255, mean=[0, 0, 0], std=[1, 1, 1], **common)
    doc["metrics"].update(metrics)
    (out / "model_manifest.json").write_text(json.dumps(doc, indent=2) + "\n", encoding="utf-8")
    return doc


def main(argv=None) -> int:
    args = _arguments().parse_args(argv)
    why = _refusal(args)
    if why:
        print(f"refused: {why}", file=sys.stderr)
        return 2
    hw = tuple(args.input) if args.input else (OBJECT_INPUT if args.task == "object_det" else LANE_INPUT)
    out = Path(args.out)
    if args.backend == "ncnn":
        if args.task == "lane_seg":
            from export_ncnn_lane import convert_lane_ncnn
            return convert_lane_ncnn(args, hw, out)
        from export_ncnn import convert_ncnn
        return convert_ncnn(args, hw, out)
    out.mkdir(parents=True, exist_ok=True)
    staged, staged_int8 = out / f".{ONNX_NAME}.fp32", out / f".{ONNX_NAME}.int8"
    try:
        doc = _convert(args, hw, out, staged, staged_int8)
    finally:  # every path, success or not: no staged copy stays next to the bundle
        for leftover in (staged, staged_int8):
            leftover.unlink(missing_ok=True)
    if doc is None:
        return 1
    print(f"OK {doc['model_revision']} -> {out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
