"""Model intake: shadow-deployment eligibility report (D-356).

intake.py <model_folder | hf:org/repo@<40-hex sha>> --out data/perception/models

manifest + sha256 -> onnxruntime open -> replay MP4 frames through the model
and the rule-based detector -> intake_report.json. Pass: the folder is copied
to <out>/<model_revision>/ with the report. Fail: the report is written next
to the source and the exit code is 1. Not the D-205 selection gate."""

from __future__ import annotations

import argparse
import glob
import json
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

import cv2
import numpy as np

ROOT = Path(__file__).resolve().parents[3]
_SENSING = ROOT / "src" / "runtime" / "sensing"
if str(_SENSING) not in sys.path:
    sys.path.insert(0, str(_SENSING))

from control.sensing.perception.lane import detect_lane_error  # noqa: E402
from control.sensing.perception.learned.lane_mask import NonFiniteLogits  # noqa: E402
from control.sensing.perception.learned.manifest import (  # noqa: E402
    ManifestError, load_manifest, verify_files)
from control.sensing.perception.learned.runner import LaneSegModel  # noqa: E402

DEFAULT_GATE = Path(__file__).resolve().parent / "intake_gate.yaml"
REPORT_NAME = "intake_report.json"
_HF = re.compile(r"^hf:(?P<repo>[^@\s]+/[^@\s]+)@(?P<rev>[^@\s]*)$")
_SHA = re.compile(r"^[0-9a-f]{40}$")


def judge(stats: dict, gate: dict) -> tuple[str, list[str]]:
    reasons = []
    if stats.get("frames", 0) <= 0:
        reasons.append("no replay frames")
    p50 = (stats.get("latency_ms") or {}).get("p50")
    if p50 is not None and p50 > gate["max_host_latency_ms_p50"]:
        reasons.append(f"latency p50 {p50:.1f} ms > {gate['max_host_latency_ms_p50']} ms")
    if stats.get("nan_frames", 0) > gate["max_nan_frames"]:
        reasons.append(f"NaN frames {stats['nan_frames']} > {gate['max_nan_frames']}")
    if stats.get("error_frames", 0) > 0:
        reasons.append(f"inference error frames {stats['error_frames']} > 0")
    vis = stats.get("visible_fraction", 0.0)
    if stats.get("frames", 0) > 0 and vis < gate["min_visible_fraction"]:
        reasons.append(f"visible fraction {vis:.3f} < {gate['min_visible_fraction']}")
    return ("fail" if reasons else "pass"), reasons


def resolve_source(source: str, downloader=None, workdir=None) -> Path:
    """Local folder, or hf:org/repo@<40-hex commit> (tags and branches move: refused).

    The HF cache links snapshot files into blobs, which verify_files refuses, so
    the snapshot goes to a local_dir under workdir; any symlink left is copied
    out as a real file."""
    if not source.startswith("hf:"):
        return Path(source)
    m = _HF.match(source)
    if not m or not _SHA.match(m["rev"]):
        raise ValueError(f"{source}: expected hf:org/repo@<40 hex commit sha>")
    if downloader is None:
        from huggingface_hub import snapshot_download  # lazy: tools-only dependency
        downloader = snapshot_download
    workdir = Path(workdir) if workdir else Path(tempfile.mkdtemp(prefix="rosy-intake-"))
    target = workdir / f"{m['repo'].replace('/', '__')}@{m['rev']}"
    real = target.with_name(target.name + ".real")
    for d in (target, real):
        shutil.rmtree(d, ignore_errors=True)
    got = Path(downloader(repo_id=m["repo"], revision=m["rev"], local_dir=str(target)))
    if any(p.is_symlink() for p in [got, *got.rglob("*")]):
        shutil.copytree(got, real, symlinks=False)
        return real
    return got


def load_gate(path) -> dict:
    import yaml
    return yaml.safe_load(Path(path).read_text(encoding="utf-8"))


def even_stride(total: int, max_frames: int) -> int:
    return max(1, total // max_frames) if total > 0 and max_frames > 0 else 1


def _video_frames(path: Path, max_frames: int):
    """Up to max_frames evenly spaced frames, read sequentially (seeking is slow)."""
    cap = cv2.VideoCapture(str(path))
    if not cap.isOpened():
        raise ValueError(f"cannot open video: {path}")
    try:
        stride = even_stride(int(cap.get(cv2.CAP_PROP_FRAME_COUNT)), max_frames)
        i = taken = 0
        while taken < max_frames:
            if i % stride == 0:
                ok, bgr = cap.read()
                if not ok:
                    break
                taken += 1
                yield bgr
            elif not cap.grab():
                break
            i += 1
    finally:
        cap.release()


def replay(model, videos, max_frames: int) -> dict:
    latencies, deltas, fractions = [], [], []
    frames = nan_frames = error_frames = visible = 0
    for video in videos:
        for bgr in _video_frames(video, max_frames):
            frames += 1
            try:
                result = model.infer(bgr)
            except ValueError as exc:
                if isinstance(exc, NonFiniteLogits):  # lane_evidence's NaN/inf refusal
                    nan_frames += 1
                else:
                    error_frames += 1
                continue
            latencies.append(result.latency_ms)
            ev = result.evidence
            fractions.append(ev.class_fractions)
            if not ev.visible:
                continue
            visible += 1
            rule = detect_lane_error(bgr)
            if rule is not None:
                deltas.append(abs(ev.error - rule.error))

    def pct(values, q):
        return float(np.percentile(values, q)) if values else None

    names = fractions[0].keys() if fractions else ()
    return {
        "frames": frames,
        "latency_ms": {"p50": pct(latencies, 50), "p95": pct(latencies, 95)},
        "nan_frames": nan_frames,
        "error_frames": error_frames,
        "visible_fraction": visible / frames if frames else 0.0,
        "error_delta": {"median": pct(deltas, 50), "p95": pct(deltas, 95), "n": len(deltas)},
        "class_fractions_mean": {n: float(np.mean([f[n] for f in fractions])) for n in names},
    }


def _tool_commit() -> str | None:
    try:
        r = subprocess.run(["git", "rev-parse", "HEAD"], cwd=Path(__file__).parent,
                           capture_output=True, text=True, timeout=10)
    except (OSError, subprocess.SubprocessError):
        return None
    return (r.stdout.strip() or None) if r.returncode == 0 else None


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("source", help="model folder or hf:org/repo@<40-hex sha>")
    ap.add_argument("--out", default=str(ROOT / "data" / "perception" / "models"))
    ap.add_argument("--gate", default=str(DEFAULT_GATE))
    ap.add_argument("--root", default=str(ROOT), help="base for gate replay_sources globs")
    ap.add_argument("--max-frames", type=int, help="override max_frames_per_source")
    args = ap.parse_args(argv)

    gate = load_gate(args.gate)
    max_frames = args.max_frames or gate["max_frames_per_source"]
    report = {"model_revision": None, "verdict": "fail", "reasons": [], "gate": gate,
              "tool_commit": _tool_commit()}
    folder = None
    try:
        folder = resolve_source(args.source, workdir=Path(args.out) / ".incoming")
        manifest = load_manifest(folder)
        report["model_revision"] = manifest.model_revision
        verify_files(manifest)
        model = LaneSegModel.open(folder)
        videos = sorted({Path(p) for pat in gate["replay_sources"]
                         for p in glob.glob(str(Path(args.root) / pat))})
        stats = replay(model, videos, max_frames)
        report.update(stats)
        report["sources"] = [str(v) for v in videos]
        report["verdict"], report["reasons"] = judge(stats, gate)
    except (ManifestError, ValueError, ImportError, OSError, cv2.error) as exc:
        report["reasons"] = [f"{type(exc).__name__}: {exc}"]

    text = json.dumps(report, indent=2, ensure_ascii=False) + "\n"
    if report["verdict"] == "pass":
        dest = Path(args.out) / report["model_revision"]
        shutil.copytree(folder, dest, dirs_exist_ok=True,
                        ignore=shutil.ignore_patterns(".cache", ".git*", REPORT_NAME))
        (dest / REPORT_NAME).write_text(text, encoding="utf-8")
        if args.source.startswith("hf:"):  # downloaded snapshot (and its .real copy)
            for d in (folder, Path(str(folder).removesuffix(".real"))):
                shutil.rmtree(d, ignore_errors=True)
        print(f"PASS {report['model_revision']} -> {dest}")
        return 0
    src = Path(folder) if folder else Path(args.source.replace(":", "_").replace("/", "_"))
    target = src.parent / f"{src.name}.{REPORT_NAME}"
    target.write_text(text, encoding="utf-8")
    print(f"FAIL {report['model_revision']}: {'; '.join(report['reasons'])} (report: {target})",
          file=sys.stderr)
    return 1


if __name__ == "__main__":
    sys.exit(main())
