"""D-431: staged YOLO export, versioned bundle and real-frame parity; PC only."""

from __future__ import annotations

import datetime
import hashlib
import importlib.metadata
import json
import os
import shutil
import tempfile
from pathlib import Path

from compare_backends import compare_frames
from control.sensing.perception.learned.manifest import (
    LAYOUTS, NCNN_FAMILIES, NCNN_SCHEMA, OBJECT_CLASSES, load_manifest, verify_files)
from control.sensing.perception.learned.ncnn_session import NcnnSession


def set_revision(doc):
    """Revision identifies the entire inference contract and its hashed evidence."""
    identity = hashlib.sha256(json.dumps({k: v for k, v in doc.items() if k != "model_revision"},
                                         sort_keys=True, allow_nan=False).encode()).hexdigest()
    prefix = "object-det" if doc["task"] == "object_det" else "lane-seg"
    doc["model_revision"] = f"{prefix}-ncnn-{datetime.date.today():%Y%m%d}-{identity[:12]}"


def _blob_names(param):
    """Read graph inputs and terminal outputs; reject multi-head or unsupported graphs."""
    lines = [line.strip() for line in param.read_text(encoding="utf-8").splitlines() if line.strip()]
    if not lines or lines[0] != "7767517":
        raise ValueError("unsupported NCNN param magic")
    produced, consumed, inputs = [], set(), []
    for line in lines[2:]:
        parts = line.split()
        bottom, top = int(parts[2]), int(parts[3])
        consumed.update(parts[4:4 + bottom])
        outputs = parts[4 + bottom:4 + bottom + top]
        produced.extend(outputs)
        if parts[0] == "Input":
            inputs.extend(outputs)
    terminals = [name for name in produced if name not in consumed]
    if len(inputs) != 1 or len(terminals) != 1:
        raise ValueError("NCNN export needs exactly one input and one raw detection output")
    return inputs[0], terminals[0]


def bundle(folder, exported, *, args, hw, family, exporter_version):
    folder, exported = Path(folder), Path(exported)
    params = sorted(p for p in exported.glob("*.param") if not p.name.endswith(".pnnx.param"))
    bins = sorted(p for p in exported.glob("*.bin") if not p.name.endswith(".pnnx.bin"))
    if len(params) != 1 or len(bins) != 1 or params[0].stem != bins[0].stem:
        raise ValueError("NCNN export needs exactly one matching param/bin pair")
    iblob, oblob = _blob_names(params[0])
    files = []
    # Metadata participates in the signed bundle; generated Python export code is not executed or shipped.
    artifacts = [params[0], bins[0], *sorted(exported.glob("*.yaml")), *sorted(exported.glob("*.json"))]
    for path in artifacts:
        shutil.copyfile(path, folder / path.name)
        files.append({"name": path.name, "sha256": hashlib.sha256(path.read_bytes()).hexdigest(), "precision": "fp32"})
    sha = hashlib.sha256(Path(args.source).read_bytes()).hexdigest()
    classes = [{"index": i, "name": name, "role": "object"} for i, name in enumerate(OBJECT_CLASSES)]
    if args.task == "lane_seg":
        from export_onnx import load_classes
        classes = [dict(c, index=i) for i, c in enumerate(load_classes(args.classes))]
    doc = {
        "schema": NCNN_SCHEMA, "backend": "ncnn", "task": args.task,
        "files": files,
        "input": {"shape": [1, 3, *hw], "layout": "nchw", "color": args.color, "scale": 1 / 255,
                  "mean": [0, 0, 0], "std": [1, 1, 1]},
        "output": {"layout": LAYOUTS[args.task], "classes": classes},
        "runtime": {"param": params[0].name, "bin": bins[0].name, "input_blob": iblob, "output_blob": oblob,
                    "model_family": family, "model_version": sha, "exporter_version": exporter_version,
                    "runtime_version": importlib.metadata.version("ncnn")},
        "dataset": {"repo": args.dataset_repo, "revision": args.dataset_revision},
        "camera_profile_revision": args.camera_profile_revision, "trainer": args.trainer,
        "metrics": {"export_kind": args.kind, "source_sha256": sha},
    }
    set_revision(doc)
    (folder / "model_manifest.json").write_text(json.dumps(doc, indent=2) + "\n", encoding="utf-8")
    verify_files(load_manifest(folder))
    return doc


def publish(model_folder, doc, report, probe_result, out):
    """Only a complete, parity-verified bundle is copied, with the manifest last."""
    if not report["ok"] or not probe_result["ok"]:
        raise ValueError("NCNN parity failed; no deployable bundle written")
    proof = model_folder / "export_parity.json"
    proof.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    doc["files"].append({"name": proof.name, "sha256": hashlib.sha256(proof.read_bytes()).hexdigest(),
                         "precision": "fp32"})
    doc["metrics"].update(export_parity_max_abs_diff=probe_result["max_abs_diff"],
                          export_real_frames=report["frames"], export_real_frames_ok=True)
    set_revision(doc)
    (model_folder / "model_manifest.json").write_text(json.dumps(doc, indent=2) + "\n", encoding="utf-8")
    verify_files(load_manifest(model_folder))
    if out.exists() and any(out.iterdir()):
        raise ValueError("NCNN output folder must be empty; existing bundles are never overwritten")
    out.mkdir(parents=True, exist_ok=True)
    copied = []
    try:
        for path in sorted(model_folder.iterdir(), key=lambda p: p.name == "model_manifest.json"):
            copied.append(out / path.name)
            shutil.copyfile(path, out / path.name)
    except Exception:
        for path in copied:
            path.unlink(missing_ok=True)
        raise
    print(f"NCNN parity passed on {report['frames']} frames; model_revision {doc['model_revision']}")
    return 0


def convert_ncnn(args, hw, out):
    from ultralytics import YOLO
    from convert import parity, probe_inputs, torch_runner
    root = Path(os.environ.get("ROSY_MODEL_SCRATCH", "X:/DevTemp/rosy-model-export" if os.name == "nt"
                               else tempfile.gettempdir()))
    root.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="ncnn-", dir=root) as scratch:
        staging = Path(scratch)
        checkpoint = staging / "source.pt"
        shutil.copyfile(args.source, checkpoint)
        yolo = YOLO(str(checkpoint), task="detect")
        names = tuple(yolo.names[i] for i in range(len(yolo.names)))
        if names != OBJECT_CLASSES or yolo.task != "detect":
            raise ValueError(f"YOLO class order must be {OBJECT_CLASSES}; got {names}")
        config = str(yolo.model.yaml.get("yaml_file", "")).lower()
        family = next((f for f in NCNN_FAMILIES if f in config), None)
        if family is None or getattr(yolo.model, "end2end", False):
            raise ValueError("supported families are raw-head YOLOv8/YOLO11 detection only")
        exported = Path(yolo.export(format="ncnn", imgsz=list(hw), device="cpu", batch=1,
                                    quantize=None, nms=False, dynamic=False, half=False))
        model_folder = staging / "bundle"
        model_folder.mkdir()
        doc = bundle(model_folder, exported, args=args, hw=hw, family=family,
                     exporter_version=importlib.metadata.version("ultralytics"))
        session = NcnnSession(load_manifest(model_folder))
        reference = torch_runner(yolo.model.cpu().float().eval())
        probe_result = parity(reference, session.run, probe_inputs((1, 3, *hw)), args.tolerance, args.rtol)
        if not probe_result["ok"]:
            raise ValueError(f"NCNN probe parity failed: {probe_result}")
        frames = sorted(p for p in Path(args.frames).iterdir() if p.suffix.lower() in (".png", ".jpg", ".jpeg"))
        if len(frames) < args.min_eval_frames:
            raise ValueError(f"need at least {args.min_eval_frames} readable evaluation frames")
        report = compare_frames(reference, session.run, load_manifest(model_folder), frames,
                                atol=args.tolerance, rtol=args.rtol, min_iou=args.box_iou,
                                confidence_tolerance=args.confidence_tolerance)
        report["min_eval_frames"] = args.min_eval_frames
        return publish(model_folder, doc, report, probe_result, out)
