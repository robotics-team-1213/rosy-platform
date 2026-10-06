"""Verify fixed inputs before a model-PC pixel draft job.

    pixel_label_job.py doctor --config config.json --out private-dir

This command reads inputs and reports HOLD when the model PC GPU is unavailable.
It never creates draft labels, training requests, or model READY markers.
"""
from __future__ import annotations

import argparse
import csv
import json
import os
import re
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
TRAINING = HERE.parent / "training"
for directory in (HERE, TRAINING):
    if str(directory) not in sys.path:
        sys.path.insert(0, str(directory))

import build  # noqa: E402
import edge_review  # noqa: E402
import review_ingest  # noqa: E402
from job_state import sha  # noqa: E402


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


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    doctor = sub.add_parser("doctor")
    doctor.add_argument("--config", type=Path, required=True)
    doctor.add_argument("--out", type=Path, required=True)
    args = parser.parse_args(argv)
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
