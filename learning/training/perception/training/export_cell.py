"""Trainer-side export: model.onnx + model_manifest.json (D-356, rosy.perception.model/1).

Copy this file into the training notebook (or import it) and call export() at the end.
write_manifest() needs no torch; export() imports torch lazily."""

from __future__ import annotations

import datetime
import hashlib
import inspect
import json
import re
from pathlib import Path

SCHEMA = "rosy.perception.model/1"
INPUT_SHAPE = (1, 3, 240, 320)
ONNX_NAME = "model.onnx"
PRECISIONS = ("fp32", "int8")  # == control...learned.manifest.PRECISIONS
ROLES = ("background", "lane_marking", "drivable", "stop_line", "ignore", "wall")  # = manifest.ROLES
COLORS = ("rgb", "bgr")
EXPERIMENT_KEYS = {  # metrics.experiment, per tracker, nothing else
    "wandb": ("tracker", "run_id", "url", "project"),
    "local": ("tracker", "run_id", "path"),
}


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


RUN_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")


def _experiment_doc(experiment: dict) -> dict:
    """metrics.experiment: known keys per tracker only; a local run is validated (no host paths)."""
    tracker = experiment.get("tracker", "wandb")
    if tracker not in EXPERIMENT_KEYS:
        raise ValueError(f"experiment.tracker must be one of {tuple(EXPERIMENT_KEYS)}")
    if tracker == "local":
        run_id, path = experiment.get("run_id"), experiment.get("path")
        if not isinstance(run_id, str) or not RUN_ID_RE.match(run_id):
            raise ValueError("experiment.run_id must match [A-Za-z0-9][A-Za-z0-9._-]{0,127}")
        if (not isinstance(path, str) or not path or path[0] in "/\\" or "\\" in path
                or re.match(r"^[A-Za-z]:", path) or ".." in path.split("/")):
            raise ValueError("experiment.path must be relative with forward slashes: no leading slash, "
                             "no drive letter, no '..'")
    doc = {k: experiment.get(k) for k in EXPERIMENT_KEYS[tracker]}
    doc["tracker"] = tracker  # same position as before; a missing tracker means wandb
    return doc


def write_manifest(out_dir, *, onnx_path, classes, color, scale, mean, std,
                   dataset_repo, dataset_revision, camera_profile_revision, trainer,
                   val_iou=None, date=None, precision="fp32", experiment=None,
                   revision_prefix="lane-seg", parent_lane_model=None, dataset_annotation=None,
                   camera_provenance=None, model_version=None) -> dict:
    """precision: "fp32", or "int8" for a QDQ graph (onnxruntime quantize_static);
    intake.py refuses a label the graph contradicts. experiment: optional tracker link
    {"tracker": "wandb", "run_id", "url", "project"} or {"tracker": "local", "run_id", "path"} (path relative, e.g. runs/<run_id>)
    (a missing tracker means wandb), stored as metrics.experiment (only those keys; never a
    key or token)."""
    entries = _class_entries(classes)
    _validate(entries, color, mean, std, scale)
    if revision_prefix not in ("lane-seg", "v13-drivable"):
        raise ValueError("unsupported model revision prefix")
    if revision_prefix == "v13-drivable" and sum(c["role"] == "drivable" for c in entries) != 1:
        raise ValueError("v13-drivable requires exactly one drivable class")
    if revision_prefix == "v13-drivable":
        if entries[-1]["role"] != "drivable":
            raise ValueError("v13-drivable requires drivable as the last output class")
        if not isinstance(dataset_revision, str) or not re.fullmatch(r"[0-9a-f]{64}", dataset_revision):
            raise ValueError("v13-drivable dataset_revision must be 64 lowercase hex chars")
        if (not isinstance(parent_lane_model, dict) or set(parent_lane_model) != {
                "model_revision", "onnx_sha256", "torchscript_sha256"}
                or not isinstance(parent_lane_model["model_revision"], str)
                or not re.fullmatch(r"lane-seg-[A-Za-z0-9._-]+", parent_lane_model["model_revision"])
                or not isinstance(parent_lane_model["onnx_sha256"], str)
                or not re.fullmatch(r"[0-9a-f]{64}", parent_lane_model["onnx_sha256"])
                or not isinstance(parent_lane_model["torchscript_sha256"], str)
                or not re.fullmatch(r"[0-9a-f]{64}", parent_lane_model["torchscript_sha256"])):
            raise ValueError("v13-drivable parent_lane_model needs lane-seg revision, ONNX and TorchScript sha256")
        if camera_provenance not in (None, "accepted", "provisional"):
            raise ValueError("camera_provenance must be accepted or provisional")
        if model_version is not None and not re.fullmatch(r"v13\.\d+\.\d{2}", str(model_version)):
            raise ValueError("v13-drivable model_version must be v13.<minor>.<two-digit patch> (D-558)")
    elif (parent_lane_model is not None or dataset_annotation is not None or camera_provenance is not None
          or model_version is not None):
        raise ValueError("parent_lane_model, dataset_annotation, camera_provenance and model_version "
                         "only apply to v13-drivable")
    exp_doc = _experiment_doc(experiment) if experiment is not None else None
    if precision not in PRECISIONS:
        raise ValueError(f"precision must be one of {PRECISIONS}, not {precision!r}")
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
        "model_revision": f"{revision_prefix}-{date}-{sha[:8]}",
        "task": "lane_seg",
        "files": [{"name": ONNX_NAME, "sha256": sha, "precision": precision}],
        "input": {"shape": list(INPUT_SHAPE), "layout": "nchw", "color": color,
                  "scale": float(scale), "mean": [float(v) for v in mean],
                  "std": [float(v) for v in std]},
        "output": {"layout": "nchw_logits", "classes": entries},
        "dataset": {"repo": dataset_repo, "revision": dataset_revision, **(dataset_annotation or {})},
        "camera_profile_revision": camera_profile_revision,
        "metrics": {"val_iou": val_iou or {}},
        "trainer": trainer,
    }
    if exp_doc is not None:
        doc["metrics"]["experiment"] = exp_doc
    if parent_lane_model is not None:
        doc["parent_lane_model"] = dict(parent_lane_model)
    if camera_provenance is not None:
        doc["camera_provenance"] = camera_provenance
    if model_version is not None:
        doc["model_version"] = model_version
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
