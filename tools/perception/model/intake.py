"""Model intake: shadow-deployment eligibility report (D-356).

intake.py <model_folder | store-inbox:<folder> | hf:org/repo@<40-hex sha>>
          --out data/perception/models [--store <store folder>]

store-inbox:<folder> is <store>/models/inbox/<folder>, taken only when its READY
marker matches its content (D-373 decision 8). hf: is the optional HF backend.

manifest + sha256 -> onnxruntime open -> replay MP4 frames through the model
and the rule-based detector -> intake_report.json. Pass: the folder is copied
to <out>/<model_revision>/ with the report. Fail: the report is written next
to the source and the exit code is 1. A missing Python package (onnx,
onnxruntime) is a configuration error of this host, not the model's: exit
CONFIG_EXIT (4), report "config_error": true. Not the D-205 selection gate.
D-423: the manifest task picks the replay -- lane_seg against the rule-based lane
detector, object_det through ObjectDetModel (latency, NaN, error and box-count
statistics) -- and the gate file's per-task section overrides the shared keys."""

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
from control.sensing.perception.learned.detector import ObjectDetModel  # noqa: E402
from control.sensing.perception.learned.manifest import TASKS  # noqa: E402
from control.sensing.perception.learned.runner import LaneSegModel  # noqa: E402

DEFAULT_GATE = Path(__file__).resolve().parent / "intake_gate.yaml"
REPORT_NAME = "intake_report.json"
_HF = re.compile(r"^hf:(?P<repo>[^@\s]+/[^@\s]+)@(?P<rev>[^@\s]*)$")
_SHA = re.compile(r"^[0-9a-f]{40}$")


QDQ_OPS = frozenset({"QuantizeLinear", "DequantizeLinear"})
CONFIG_EXIT = 4  # a required package is missing here: fix the environment, not the model


def graph_precision(path) -> str:
    """"int8" when the ONNX graph holds QuantizeLinear/DequantizeLinear nodes
    (onnxruntime quantize_static output), else "fp32"."""
    import onnx  # lazy: the site host's ML environment has it, like onnxruntime

    graph = onnx.load(str(path), load_external_data=False).graph
    return "int8" if any(n.op_type in QDQ_OPS for n in graph.node) else "fp32"


def check_precision(manifest) -> None:
    """Refuse a manifest whose declared precision the graph contradicts."""
    for f in manifest.files:
        if f.name.endswith(".onnx"):
            found = graph_precision(manifest.folder / f.name)
            if found != f.precision:
                raise ManifestError(
                    f"files[{f.name}].precision is {f.precision} but the graph is {found} "
                    f"({'has' if found == 'int8' else 'has no'} QuantizeLinear/DequantizeLinear)")


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
    rel_cap = gate.get("max_int8_vs_fp32_rel")
    if rel_cap is not None and stats.get("precision") == "int8":
        rel = stats.get("int8_vs_fp32_rel")
        if rel is None:
            reasons.append("int8 model without int8_vs_fp32_rel (convert.py --int8 records it)")
        elif rel > rel_cap:
            reasons.append(f"int8 vs fp32 {rel:.3g} > {rel_cap} (relative, on random probes)")
    cap = gate.get("max_detections_per_frame_p95")
    p95 = (stats.get("detections_per_frame") or {}).get("p95")
    if cap is not None and p95 is not None and p95 > cap:
        reasons.append(f"detections per frame p95 {p95} > {cap}")
    vis = stats.get("visible_fraction", 0.0)
    if "min_visible_fraction" in gate and stats.get("frames", 0) > 0 and vis < gate["min_visible_fraction"]:
        reasons.append(f"visible fraction {vis:.3f} < {gate['min_visible_fraction']}")
    return ("fail" if reasons else "pass"), reasons


STORE_INBOX = "store-inbox:"


def _store_inbox(source: str, store_root) -> Path:
    if store_root is None:
        raise ValueError(f"{source}: no store configured (--store / rosy_ml `store`)")
    perception = str(Path(__file__).resolve().parents[1])
    if perception not in sys.path:
        sys.path.insert(0, perception)
    import store
    st = store.Store(store_root)
    try:
        folder = st.inbox_folder(source.removeprefix(STORE_INBOX))
    except store.StoreError as exc:
        raise ValueError(str(exc)) from exc
    if not st.inbox_ready(folder.name):
        raise ValueError(f"{source}: not complete (no READY marker matching its content)")
    return folder


def resolve_source(source: str, downloader=None, workdir=None, store=None) -> Path:
    """Local folder, store-inbox:<folder> (needs store), or hf:org/repo@<40-hex commit>
    (tags and branches move: refused).

    The HF cache links snapshot files into blobs, which verify_files refuses, so
    the snapshot goes to a local_dir under workdir; any symlink left is copied
    out as a real file."""
    if source.startswith(STORE_INBOX):
        return _store_inbox(source, store)
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


def int8_metrics(manifest) -> dict:
    """precision and convert.py's int8_vs_fp32_rel from the manifest (D-423 review M1)."""
    int8 = any(getattr(f, "precision", None) == "int8" for f in getattr(manifest, "files", ()))
    rel = ((getattr(manifest, "raw", None) or {}).get("metrics") or {}).get("int8_vs_fp32_rel")
    return {"precision": "int8" if int8 else "fp32",
            "int8_vs_fp32_rel": float(rel) if isinstance(rel, (int, float)) and not isinstance(rel, bool) else None}


def task_gate(gate: dict, task: str) -> dict:
    """The shared keys overlaid by the task's section; other tasks' sections dropped (D-423)."""
    shared = {k: v for k, v in gate.items() if k not in TASKS}
    if task == "lane_seg":
        return shared
    shared.pop("min_visible_fraction", None)  # lane evidence only
    return {**shared, **(gate.get(task) or {})}


def replay_detections(model, videos, max_frames: int) -> dict:
    """object_det replay statistics: no rule-based reference exists for these classes."""
    latencies, counts, classes = [], [], {}
    frames = nan_frames = error_frames = 0
    for video in videos:
        for bgr in _video_frames(video, max_frames):
            frames += 1
            try:
                result = model.infer(bgr)
            except ValueError as exc:
                nan_frames += isinstance(exc, NonFiniteLogits)
                error_frames += not isinstance(exc, NonFiniteLogits)
                continue
            latencies.append(result.latency_ms)
            counts.append(len(result.detections))
            for d in result.detections:
                classes[d["label"]] = classes.get(d["label"], 0) + 1
    pct = lambda values, q: float(np.percentile(values, q)) if values else None  # noqa: E731
    return {"frames": frames, "latency_ms": {"p50": pct(latencies, 50), "p95": pct(latencies, 95)},
            "nan_frames": nan_frames, "error_frames": error_frames,
            "detections_per_frame": {"mean": float(np.mean(counts)) if counts else None,
                                     "p95": pct(counts, 95)},
            "class_counts": classes}


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
    ap.add_argument("source", help="model folder, store-inbox:<folder> or hf:org/repo@<sha>")
    ap.add_argument("--store", help="store folder, for store-inbox: sources")
    ap.add_argument("--out", default=str(ROOT / "data" / "perception" / "models"))
    ap.add_argument("--gate", default=str(DEFAULT_GATE))
    ap.add_argument("--root", default=str(ROOT), help="base for gate replay_sources globs")
    ap.add_argument("--max-frames", type=int, help="override max_frames_per_source")
    args = ap.parse_args(argv)
    return run(args.source, out=args.out, gate_path=args.gate, root=args.root,
               max_frames=args.max_frames, store=args.store)[0]


def replay_videos(gate: dict, root) -> list[Path]:
    """The replay clips the gate names under root (rosy_ml doctor checks it too)."""
    return sorted({Path(p) for pat in gate["replay_sources"]
                   for p in glob.glob(str(Path(root) / pat))})


def run(source: str, *, out, gate_path=DEFAULT_GATE, root=ROOT, max_frames=None,
        downloader=None, store=None) -> tuple[int, dict]:
    """(exit code, report). main() and model/watch.py (in-process, own downloader)."""
    gate = load_gate(gate_path)
    max_frames = max_frames or gate["max_frames_per_source"]
    # transient: the run failed for an infrastructure reason (disk, network, HF,
    # missing runtime, video decode), not on the model; watch.py retries those.
    report = {"model_revision": None, "verdict": "fail", "reasons": [], "gate": gate,
              "tool_commit": _tool_commit(), "transient": False}
    folder = None
    try:
        folder = resolve_source(source, downloader=downloader, workdir=Path(out) / ".incoming",
                                store=store)
        manifest = load_manifest(folder)
        report["model_revision"] = manifest.model_revision
        verify_files(manifest)
        check_precision(manifest)
        # deliver.py push refuses a model whose files differ from these.
        report["files"] = [{"name": f.name, "sha256": f.sha256} for f in manifest.files]
        report["task"] = task = getattr(manifest, "task", "lane_seg")
        gate = report["gate"] = task_gate(gate, task)
        videos = replay_videos(gate, root)
        if task == "object_det":
            stats = {**replay_detections(ObjectDetModel.open(folder), videos, max_frames),
                     **int8_metrics(manifest)}
        else:
            stats = replay(LaneSegModel.open(folder), videos, max_frames)
        report.update(stats)
        report["sources"] = [str(v) for v in videos]
        report["verdict"], report["reasons"] = judge(stats, gate)
        if stats["frames"] == 0:  # no clips under root: a setup error, not the model's
            report["transient"] = True
            report["reasons"].append(f"no replay clips for {gate['replay_sources']} under {root}")
    except ImportError as exc:  # onnx / onnxruntime missing: the host's setup
        report["reasons"] = [f"{type(exc).__name__}: {exc} (install it in this venv)"]
        report["config_error"] = True
    except (ManifestError, ValueError, OSError, cv2.error) as exc:
        report["reasons"] = [f"{type(exc).__name__}: {exc}"]
        report["transient"] = isinstance(exc, (OSError, cv2.error))

    text = json.dumps(report, indent=2, ensure_ascii=False) + "\n"
    if report["verdict"] == "pass":
        dest = Path(out) / report["model_revision"]
        shutil.copytree(folder, dest, dirs_exist_ok=True,
                        ignore=shutil.ignore_patterns(".cache", ".git*", REPORT_NAME, "READY"))
        (dest / REPORT_NAME).write_text(text, encoding="utf-8")
        if source.startswith("hf:"):  # downloaded snapshot (and its .real copy)
            for d in (folder, Path(str(folder).removesuffix(".real"))):
                shutil.rmtree(d, ignore_errors=True)
        print(f"PASS {report['model_revision']} -> {dest}")
        return 0, report
    if folder and not source.startswith(STORE_INBOX):
        target = Path(folder).parent / f"{Path(folder).name}.{REPORT_NAME}"
    else:  # hf: (nothing downloaded) or the store inbox: under --out, never the cwd or inbox
        name = re.sub(r"[^A-Za-z0-9._@-]", "_",
                      source.removeprefix("hf:").removeprefix(STORE_INBOX).replace("/", "__"))
        target = Path(out) / "_failed" / f"{name}.{REPORT_NAME}"
        target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(text, encoding="utf-8")
    print(f"FAIL {report['model_revision']}: {'; '.join(report['reasons'])} (report: {target})",
          file=sys.stderr)
    return (CONFIG_EXIT if report.get("config_error") else 1), report


if __name__ == "__main__":
    sys.exit(main())
