"""Verify fixed inputs and create pending pixel drafts on the model PC.

    pixel_label_job.py doctor --config config.json --out private-dir
    pixel_label_job.py draft --config config.json --out new-or-resumable-job-dir

Doctor reads inputs and reports HOLD when the model PC GPU is unavailable.
Drafts are unapproved; neither command creates training requests or model READY.
"""
from __future__ import annotations

import argparse
import csv
import json
import math
import os
import re
import subprocess
import sys
from pathlib import Path

import cv2
import numpy as np

HERE = Path(__file__).resolve().parent
TRAINING = HERE.parent / "training"
for directory in (HERE, TRAINING):
    if str(directory) not in sys.path:
        sys.path.insert(0, str(directory))

import build  # noqa: E402
import edge_review  # noqa: E402
import prelabel  # noqa: E402
import review_ingest  # noqa: E402
import train_job  # noqa: E402
from job_state import Job, JobError, receipt, sha  # noqa: E402


def _digest(value, name, length=64):
    if not isinstance(value, str) or not re.fullmatch(f"[0-9a-f]{{{length}}}", value):
        raise ValueError(f"{name} must be a lowercase SHA-256/commit digest")
    return value


def _file(ref, name):
    if not isinstance(ref, dict):
        raise ValueError(f"{name} reference required")
    expected = _digest(ref.get("sha256"), f"{name} hash")
    if not isinstance(ref.get("path"), str) or not ref["path"]:
        raise ValueError(f"{name} path required")
    path = Path(ref["path"])
    if not path.is_file() or sha(path) != expected:
        raise ValueError(f"{name} missing or changed")
    return path


def verify_inputs(config):
    """Return public-safe provenance only when every source byte still matches."""
    if not isinstance(config, dict):
        raise ValueError("doctor config must be an object")
    source = _digest(config.get("source_commit"), "source commit", 40)
    environment = _digest(config.get("environment_fingerprint"), "environment fingerprint")
    classes = _file({"path": config.get("classes"), "sha256": config.get("classes_sha256")},
                    "classes")
    build.load_classes(classes)
    checkpoint = _file(config.get("checkpoint"), "checkpoint")
    evaluations = config.get("eval_sets")
    if not isinstance(evaluations, list) or not evaluations:
        raise ValueError("fixed eval sets required")
    for ref in evaluations:
        path = _file(ref, "eval set")
        if not isinstance(json.loads(path.read_text(encoding="utf-8")).get("frames"), list):
            raise ValueError("eval set frames required")
    catalog = Path(config.get("catalog", ""))
    if not catalog.is_file():
        raise ValueError("verified input catalog required")
    rows = [json.loads(line) for line in catalog.read_text(encoding="utf-8-sig").splitlines()
            if line.strip()]
    if not 1 <= len(rows) <= 2000:
        raise ValueError("1..2000 source frames required")
    seen = set()
    for row in rows:
        if not isinstance(row, dict) or not all(isinstance(row.get(key), str) and row[key].strip()
                                                for key in ("source_session", "capture_group")):
            raise ValueError("source session and capture group required")
        if not re.fullmatch(r"[A-Za-z0-9._-]{1,128}", row["source_session"]):
            raise ValueError("source session must be a safe name")
        index = row.get("video_frame")
        if type(index) is not int or index < 0:
            raise ValueError("original video frame required")
        video_hash = _digest(row.get("source_video_sha256"), "source video hash")
        video = edge_review.bound(catalog.parent, row.get("source_video"))
        if not video.is_file() or sha(video) != video_hash:
            raise ValueError("source video missing or changed")
        image = edge_review.bound(catalog.parent, row.get("image"))
        raw = review_ingest.bounded(image)
        review_ingest.image(raw, row.get("image_sha256"), row.get("width"), row.get("height"))
        identity = (row["source_session"], row["capture_group"], video_hash, index)
        if identity in seen:
            raise ValueError("duplicate source frame")
        seen.add(identity)
    geometry = config.get("geometry")
    if config.get("sensor_sources") and not geometry:
        raise ValueError("sensor source requires verified geometry")
    geometry_hash = None if geometry is None else sha(_file(geometry, "geometry"))
    return {"frames": len(rows), "catalog_sha256": sha(catalog),
            "classes_sha256": sha(classes), "checkpoint_sha256": sha(checkpoint),
            "eval_set_sha256": [ref["sha256"] for ref in evaluations],
            "source_commit": source, "environment_fingerprint": environment,
            "geometry": geometry_hash}


def _active_code(config):
    path = config.get("model_code_state")
    if not isinstance(path, str) or not path:
        raise ValueError("model-code state required")
    state = json.loads(Path(path).read_text(encoding="utf-8"))
    if (state.get("source_commit") != config["source_commit"] or
            state.get("environment_sha256") != config["environment_fingerprint"]):
        raise ValueError("active model-code source or environment differs")


def probe_gpu():
    """A small live CUDA check; no installation or GPU job is started."""
    if sys.platform != "linux":
        return {"verdict": "hold", "reason": "Linux model PC required"}
    try:
        output = subprocess.run(
            ["nvidia-smi", "--query-gpu=name,memory.total,memory.free,driver_version",
             "--format=csv,noheader,nounits"], check=True, capture_output=True,
            text=True, timeout=10).stdout
        rows = list(csv.reader(output.splitlines()))
        if not rows or len(rows[0]) != 4:
            raise ValueError("GPU inventory missing")
        name, total, free, driver = (value.strip() for value in rows[0])
        import torch
        if not torch.cuda.is_available():
            raise ValueError("torch CUDA unavailable")
        if (torch.ones(1, device="cuda") + 1).item() != 2:
            raise ValueError("CUDA operation failed")
        return {"verdict": "pass", "name": name, "memory_total_mib": int(total),
                "memory_free_mib": int(free), "driver": driver,
                "torch_cuda": True, "torch_device": torch.cuda.get_device_name(0)}
    except (OSError, subprocess.SubprocessError, ValueError, ImportError, RuntimeError) as exc:
        return {"verdict": "hold", "reason": type(exc).__name__}


def draft_mask(logits, classes, size, min_confidence):
    """Original-size indexed candidate; model-only drivable remains unlabelled."""
    h, w = size
    values = np.asarray(logits)
    if (values.ndim != 4 or values.shape[0] != 1 or values.shape[1] != len(classes)
            or values.shape[2] < 1 or values.shape[3] < 1 or not np.isfinite(values).all()):
        raise ValueError("invalid model logits")
    z = values[0].astype(np.float64)
    z -= z.max(axis=0, keepdims=True)
    probabilities = np.exp(z)
    probabilities /= probabilities.sum(axis=0, keepdims=True)
    candidates = probabilities.argmax(axis=0).astype(np.uint8)
    confidence = probabilities.max(axis=0)
    mask = cv2.resize(candidates, (w, h), interpolation=cv2.INTER_NEAREST)
    confidence = cv2.resize(confidence, (w, h), interpolation=cv2.INTER_NEAREST)
    mask[confidence < min_confidence] = 255
    for item in classes:
        if item.role == "drivable":
            mask[mask == item.index] = 255  # requires path or human evidence
    return mask


def run_draft(config, out, min_confidence=0.6):
    if not isinstance(min_confidence, (int, float)) or not math.isfinite(min_confidence) or not 0 < min_confidence <= 1:
        raise ValueError("min confidence must be in (0,1]")
    proof = verify_inputs(config)
    _active_code(config)
    out = Path(out)
    catalog = Path(config["catalog"])
    rows = [json.loads(line) for line in catalog.read_text(encoding="utf-8-sig").splitlines() if line.strip()]
    with train_job.gpu_lease():
        gpu = probe_gpu()
        if gpu["verdict"] != "pass":
            raise JobError("model PC GPU unavailable")
        model, session = prelabel._open_model(Path(config["checkpoint"]["path"]).parent,
                                              providers=["CUDAExecutionProvider"])
        checkpoint = Path(config["checkpoint"]["path"]).resolve()
        if model.manifest.onnx_file().resolve() != checkpoint:
            raise ValueError("model manifest checkpoint differs from verified input")
        prelabel.resolve_classes(build.load_classes(Path(config["classes"]), require_color=False),
                                 model.manifest.classes)
        inputs = {**proof, "min_confidence": min_confidence, "model_revision": model.model_revision,
                  "model_manifest_sha256": sha(model.manifest.folder / "model_manifest.json")}
        from control.sensing.perception.learned.lane_mask import preprocess
        frames = []
        with Job(out, inputs) as job:
            for catalog_index, row in enumerate(rows):
                name = f"{catalog_index:06d}"
                target = out / "drafts" / f"{name}.png"

                def create(_attempt, row=row, target=target):
                    image = edge_review.bound(catalog.parent, row["image"])
                    raw = review_ingest.bounded(image)
                    review_ingest.image(raw, row["image_sha256"], row["width"], row["height"])
                    bgr = cv2.imdecode(np.frombuffer(raw, np.uint8), cv2.IMREAD_COLOR)
                    logits = session.run(preprocess(bgr, model.manifest.input))
                    mask = draft_mask(logits, model.manifest.classes,
                                      (row["height"], row["width"]), min_confidence)
                    ok, encoded = cv2.imencode(".png", mask)
                    if not ok:
                        raise JobError("indexed draft PNG encoding failed")
                    target.parent.mkdir(parents=True, exist_ok=True)
                    temp = target.with_suffix(".png.tmp")
                    temp.write_bytes(encoded.tobytes())
                    os.replace(temp, target)
                    return receipt({"unlabelled_pixels": int((mask == 255).sum()),
                                    "transform": "nearest_original_size"}, [target])

                values = job.step(name, create)
                frames.append({"catalog_index": catalog_index,
                               "source_session": row["source_session"],
                               "capture_group": row["capture_group"],
                               "source_video_sha256": row["source_video_sha256"],
                               "video_frame": row["video_frame"],
                               "image_sha256": row["image_sha256"],
                               "mask": str(target.resolve()), "mask_sha256": sha(target), **values})
            job.finish()
        target = out / "draft-receipt.json"
        temporary = target.with_suffix(".json.tmp")
        temporary.write_text(json.dumps({"status": "draft_complete", "model_revision": model.model_revision,
                                         "input": inputs, "gpu": gpu, "frames": frames}, sort_keys=True,
                                        indent=2, allow_nan=False) + "\n", encoding="utf-8")
        os.replace(temporary, target)
        classes_copy = out / "classes.yaml"
        classes_raw = Path(config["classes"]).read_bytes()
        if classes_copy.exists() and classes_copy.read_bytes() != classes_raw:
            raise JobError("job classes copy changed")
        if not classes_copy.exists():
            temporary = classes_copy.with_suffix(".yaml.tmp")
            temporary.write_bytes(classes_raw)
            os.replace(temporary, classes_copy)
        indexed = out / "verified-inputs.jsonl"
        temporary = indexed.with_suffix(".jsonl.tmp")
        with temporary.open("w", encoding="utf-8") as stream:
            for row, frame in zip(rows, frames):
                entry = dict(row, image=str(edge_review.bound(catalog.parent, row["image"])),
                             mask={"indexed_png": f"drafts/{frame['catalog_index']:06d}.png",
                                   "sha256": frame["mask_sha256"],
                                   "classes_sha256": proof["classes_sha256"]})
                stream.write(json.dumps(entry, sort_keys=True, allow_nan=False) + "\n")
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, indexed)
    return len(frames)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    doctor = sub.add_parser("doctor")
    doctor.add_argument("--config", type=Path, required=True)
    doctor.add_argument("--out", type=Path, required=True)
    draft = sub.add_parser("draft")
    draft.add_argument("--config", type=Path, required=True)
    draft.add_argument("--out", type=Path, required=True)
    draft.add_argument("--min-confidence", type=float, default=0.6)
    args = parser.parse_args(argv)
    if args.command == "draft":
        try:
            count = run_draft(json.loads(args.config.read_text(encoding="utf-8")), args.out,
                              args.min_confidence)
        except (OSError, ValueError, JobError, TypeError, KeyError, RuntimeError,
                json.JSONDecodeError) as exc:
            print(f"HOLD: {exc}", file=sys.stderr)
            return 1
        print(f"draft complete: {count} frames; human pixel review required")
        return 0
    try:
        config = json.loads(args.config.read_text(encoding="utf-8"))
        proof = verify_inputs(config)
        _active_code(config)
    except (OSError, ValueError, KeyError, TypeError, json.JSONDecodeError) as exc:
        print(f"HOLD: {exc}", file=sys.stderr)
        return 1
    gpu = probe_gpu()
    args.out.mkdir(parents=True, exist_ok=True)
    target = args.out / "doctor.json"
    temporary = target.with_suffix(".json.tmp")
    with temporary.open("w", encoding="utf-8") as stream:
        json.dump({"input_verdict": "pass", **proof, "gpu": gpu}, stream,
                  sort_keys=True, indent=2, allow_nan=False)
        stream.write("\n")
        stream.flush()
        os.fsync(stream.fileno())
    os.replace(temporary, target)
    print("doctor PASS" if gpu["verdict"] == "pass" else "doctor HOLD: GPU unknown")
    return 0 if gpu["verdict"] == "pass" else 1


if __name__ == "__main__":
    raise SystemExit(main())
