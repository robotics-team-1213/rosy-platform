"""D-431: repeatable image replay benchmark; this is not live-camera/field acceptance."""

from __future__ import annotations

import argparse
import hashlib
import json
import platform
import sys
import time
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[4]
for path in (ROOT / "src/runtime/sensing", ROOT / "contracts/foundation"):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))


def summarize(latencies, *, errors, max_p95_ms):
    if not np.isfinite(max_p95_ms) or max_p95_ms <= 0:
        raise ValueError("max_p95_ms must be finite and positive")
    values = np.asarray(latencies, dtype=np.float64)
    finite = bool(values.size) and bool(np.isfinite(values).all()) and bool((values >= 0).all())
    p50, p95 = (float(np.median(values)), float(np.percentile(values, 95))) if finite else (None, None)
    return {"ok": finite and errors == 0 and p95 <= max_p95_ms, "frames": len(values), "errors": errors,
            "latency_ms_p50": p50, "latency_ms_p95": p95, "max_p95_ms": max_p95_ms}


def benchmark(folder, frames, *, iterations=100, warmup=5, max_p95_ms, duration_s=0):
    import cv2
    from control.sensing.perception.learned.detector import ObjectDetModel
    from control.sensing.perception.learned.runner import LaneSegModel
    from control.sensing.perception.learned.manifest import load_manifest
    if iterations < 1 or warmup < 0 or not np.isfinite(duration_s) or duration_s < 0:
        raise ValueError("invalid benchmark iteration/warm-up/duration")
    paths = [Path(p) for p in frames]
    if not paths:
        raise ValueError("benchmark requires camera frames")
    manifest = load_manifest(folder)
    model = (ObjectDetModel if manifest.task == "object_det" else LaneSegModel).open(folder)
    latencies, errors, last_error = [], 0, None
    start, cpu_start = time.perf_counter(), time.process_time()
    i = 0
    while i < warmup + iterations or time.perf_counter() - start < duration_s:
        if i == warmup:
            start, cpu_start = time.perf_counter(), time.process_time()
        image = cv2.imread(str(paths[i % len(paths)]))
        if image is None:
            raise ValueError("unreadable benchmark frame")
        try:
            result = model.infer(image)
            if i >= warmup:
                latencies.append(result.latency_ms)
        except Exception as exc:
            errors += 1
            last_error = str(exc)
        i += 1
    elapsed, cpu = time.perf_counter() - start, time.process_time() - cpu_start
    stats = summarize(latencies, errors=errors, max_p95_ms=max_p95_ms)
    try:
        import psutil
        rss = psutil.Process().memory_info().rss
    except ImportError:
        rss = None
    stats.update(kind="recorded-image-replay", backend=manifest.backend, model_revision=manifest.model_revision,
                 architecture=platform.machine(), python=platform.python_version(),
                 duration_s=elapsed, cpu_percent=cpu / elapsed * 100, rss_bytes=rss,
                 throughput_hz=len(latencies) / elapsed, last_error=last_error,
                 manifest_sha256=hashlib.sha256((Path(folder) / "model_manifest.json").read_bytes()).hexdigest(),
                 frame_sha256=[hashlib.sha256(p.read_bytes()).hexdigest() for p in paths])
    # Thermal readings are evidence, not a substitute for defined device load gates.
    thermal = Path("/sys/class/thermal/thermal_zone0/temp")
    stats["temperature_c"] = int(thermal.read_text()) / 1000 if thermal.is_file() else None
    return stats


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("model")
    ap.add_argument("--frames", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--max-p95-ms", type=float, required=True)
    ap.add_argument("--iterations", type=int, default=100)
    ap.add_argument("--duration-s", type=float, default=0)
    args = ap.parse_args(argv)
    frames = sorted(p for p in Path(args.frames).iterdir() if p.suffix.lower() in (".png", ".jpg", ".jpeg"))
    report = benchmark(args.model, frames, iterations=args.iterations, max_p95_ms=args.max_p95_ms,
                       duration_s=args.duration_s)
    Path(args.out).write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report))
    return 0 if report["ok"] else 1


if __name__ == "__main__":
    sys.exit(main())
