"""Summarize read-only ROS 2 echo captures without publishing their raw messages."""

import argparse
import json
import math
import re
from collections import Counter
from itertools import groupby
from pathlib import Path


def text_from_capture(path):
    data = path.read_bytes()
    return data.decode("utf-16" if data.startswith((b"\xff\xfe", b"\xfe\xff")) else "utf-8")


def analyze(keep_path, image_header_path):
    keep = []
    for line in text_from_capture(keep_path).splitlines():
        if line.startswith("data: '"):
            if not line.endswith("'") or "..." in line:
                raise ValueError("keep_debug capture is truncated")
            keep.append(json.loads(line[7:-1].replace("''", "'")))
    headers = []
    for block in text_from_capture(image_header_path).split("---"):
        sec, nsec = re.search(r"\bsec: (\d+)\b", block), re.search(r"\bnanosec: (\d+)\b", block)
        if sec and nsec:
            headers.append(int(sec.group(1)) + int(nsec.group(1)) / 1e9)
    if not keep or not headers:
        raise ValueError("both captures need at least one complete message")
    stamps = [row["stamp"] for row in keep]
    if not all(isinstance(t, (int, float)) and math.isfinite(t) for t in stamps):
        raise ValueError("invalid debug image stamp")
    if not all(b > a for a, b in zip(stamps, stamps[1:])):
        raise ValueError("debug image stamps must increase")
    strategies = [row.get("strategy") for row in keep]
    projections = {json.dumps(row.get("ground_projection"), sort_keys=True) for row in keep}
    matched = [any(abs(stamp - header) < 1e-6 for header in headers) for stamp in stamps]
    return {
        "scope": "live_output_continuity_not_ground_truth_or_driving_acceptance",
        "debug_frames": len(keep),
        "camera_headers": len(headers),
        "matched_image_stamp": sum(matched),
        "unmatched_before_first_header": sum(not found and stamp < headers[0]
                                             for found, stamp in zip(matched, stamps)),
        "time_span_s": round(stamps[-1] - stamps[0], 4),
        "strategy_counts": dict(Counter(strategies)),
        "reason_counts": dict(Counter(row.get("reason") for row in keep)),
        "strategy_transitions": sum(a != b for a, b in zip(strategies, strategies[1:])),
        "longest_none_run": max((sum(1 for _ in run) for strategy, run in groupby(strategies)
                                 if strategy == "none"), default=0),
        "target_frames": sum(row.get("target_m") is not None for row in keep),
        "paint_used": dict(Counter(row.get("paint_source_used") for row in keep)),
        "ground_labels": dict(Counter(row.get("ground") for row in keep)),
        "geometry_sources": dict(Counter(row.get("camera_geometry_source") for row in keep)),
        "projection_count": len(projections),
        "projection": keep[0].get("ground_projection"),
    }


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--keep", type=Path, required=True)
    parser.add_argument("--image-headers", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    args.out.write_text(json.dumps(analyze(args.keep, args.image_headers),
                                   indent=2, sort_keys=True) + "\n", encoding="utf-8")
