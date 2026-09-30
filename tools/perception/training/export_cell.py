"""Trainer-side export: model.onnx + model_manifest.json (D-356, rosy.perception.model/1).

Copy this file into the training notebook (or import it) and call export() at the end.
write_manifest() needs no torch; export() imports torch lazily."""

from __future__ import annotations

import datetime
import hashlib
import inspect
import json
from pathlib import Path

SCHEMA = "rosy.perception.model/1"
INPUT_SHAPE = (1, 3, 240, 320)
ONNX_NAME = "model.onnx"
ROLES = ("background", "lane_marking", "drivable", "stop_line", "ignore", "wall")  # = manifest.ROLES
COLORS = ("rgb", "bgr")


def _class_entries(classes) -> list[dict]:
    """classes: [(name, role), ...] in output-channel order, or [{"name","role"}, ...]."""
    out = []
    for index, c in enumerate(classes):
        name, role = (c["name"], c["role"]) if isinstance(c, dict) else c
        out.append({"index": index, "name": name, "role": role})
    return out


def _validate(entries, color, mean, std, scale) -> None:
    """Same rules the robot-side loader enforces, checked before any file is written."""
    if len(entries) < 2:
        raise ValueError("classes: at least two")
    names = [e["name"] for e in entries]
    if len(set(names)) != len(names):
        raise ValueError("classes: duplicate name")
    for e in entries:
        if e["role"] not in ROLES:
            raise ValueError(f"classes[{e['index']}].role must be one of {ROLES}")
    if not any(e["role"] == "lane_marking" for e in entries):
        raise ValueError("classes: no lane_marking role")
    if color not in COLORS:
        raise ValueError(f"color must be one of {COLORS}")
    if len(mean) != 3 or len(std) != 3 or any(float(v) <= 0 for v in std) or float(scale) <= 0:
        raise ValueError("mean/std need 3 values, std and scale must be > 0")


def write_manifest(out_dir, *, onnx_path, classes, color, scale, mean, std,
                   dataset_repo, dataset_revision, camera_profile_revision, trainer,
                   val_iou=None, date=None) -> dict:
    entries = _class_entries(classes)
    _validate(entries, color, mean, std, scale)
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    data = Path(onnx_path).read_bytes()
    sha = hashlib.sha256(data).hexdigest()
    target = out_dir / ONNX_NAME
    if Path(onnx_path).resolve() != target.resolve():
        target.write_bytes(data)
    date = date or datetime.date.today().strftime("%Y%m%d")
    doc = {
        "schema": SCHEMA,
        "model_revision": f"lane-seg-{date}-{sha[:8]}",
        "task": "lane_seg",
        "files": [{"name": ONNX_NAME, "sha256": sha, "precision": "fp32"}],
        "input": {"shape": list(INPUT_SHAPE), "layout": "nchw", "color": color,
                  "scale": float(scale), "mean": [float(v) for v in mean],
                  "std": [float(v) for v in std]},
        "output": {"layout": "nchw_logits", "classes": entries},
        "dataset": {"repo": dataset_repo, "revision": dataset_revision},
        "camera_profile_revision": camera_profile_revision,
        "metrics": {"val_iou": val_iou or {}},
        "trainer": trainer,
    }
    (out_dir / "model_manifest.json").write_text(
        json.dumps(doc, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    # Fail here rather than at intake: validate with the robot-side loader when importable.
    try:
        from control.sensing.perception.learned.manifest import load_manifest, verify_files
    except ImportError:
        return doc
    manifest = load_manifest(out_dir)
    verify_files(manifest)
    return doc


def export(model, out_dir, **manifest_kwargs) -> dict:
    """torch.onnx.export at 1x3x240x320, opset 17, then write_manifest()."""
    import torch  # lazy: only the trainer needs it

    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    onnx_path = out_dir / ONNX_NAME
    _validate(_class_entries(manifest_kwargs["classes"]), manifest_kwargs["color"],
              manifest_kwargs["mean"], manifest_kwargs["std"], manifest_kwargs["scale"])
    model = model.eval()
    extra = {"dynamo": False} if "dynamo" in inspect.signature(torch.onnx.export).parameters else {}
    with torch.no_grad():
        torch.onnx.export(model, torch.zeros(*INPUT_SHAPE), str(onnx_path),
                          opset_version=17, input_names=["x"], output_names=["logits"], **extra)
    return write_manifest(out_dir, onnx_path=onnx_path, **manifest_kwargs)
