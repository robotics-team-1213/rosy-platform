"""Zone-centered S3 precision-stop baseline for ``world_261026``."""

from __future__ import annotations

import argparse
import copy
import hashlib
import json
import math
from pathlib import Path

from fleet.routing.cost import wrap

S3_ZONE_PRECISION_STOP = {
    "reference_pose": [0.745, -0.207, 3.141592],
    "longitudinal_m": 0.04,
    "lateral_m": 0.025,
    "heading_rad": 0.12,
    "position_uncertainty_m": 0.005,
    "heading_uncertainty_rad": 0.02,
    "max_correction_m": 0.04,
    "evidence_ref": "sim-zone-center:world_261026-v368-s3-2026-11-24",
}


def validate_limits(limits: dict) -> dict:
    ref = limits["reference_pose"]
    if not isinstance(ref, list | tuple) or len(ref) != 3 or not all(isinstance(v, int | float) and math.isfinite(v) for v in ref):
        raise ValueError("reference_pose must be [x, y, yaw]")
    lon = float(limits["longitudinal_m"])
    lat = float(limits["lateral_m"])
    head = float(limits["heading_rad"])
    xy_err = float(limits["position_uncertainty_m"])
    yaw_err = float(limits["heading_uncertainty_rad"])
    max_corr = float(limits.get("max_correction_m", lon))
    if not (0 < xy_err < min(lon, lat) <= max(lon, lat) <= 0.10):
        raise ValueError("position tolerance/uncertainty out of contract range")
    if not (0 < yaw_err < head <= math.pi / 2):
        raise ValueError("heading tolerance/uncertainty out of contract range")
    if not (0.005 <= max_corr <= 0.10):
        raise ValueError("max_correction_m out of range [0.005, 0.10]")
    ref_text = limits.get("evidence_ref")
    if not isinstance(ref_text, str) or not ref_text.strip():
        raise ValueError("evidence_ref is required")
    return {
        "reference_pose": [float(v) for v in ref],
        "longitudinal_m": lon,
        "lateral_m": lat,
        "heading_rad": head,
        "position_uncertainty_m": xy_err,
        "heading_uncertainty_rad": yaw_err,
        "max_correction_m": max_corr,
        "evidence_ref": ref_text,
    }


def apply_s3_zone_baseline(envelope: dict, *, limits: dict | None = None) -> dict:
    """Return a deep-copied site-map envelope with S3 ``precision_stop`` populated."""
    updated = copy.deepcopy(envelope)
    site = updated.get("map")
    if not isinstance(site, dict) or site.get("schema") != "rosy.site_map/1" or site.get("map_id") != "world_261026":
        raise ValueError("expected a rosy.site_map/1 envelope for world_261026")
    if type(updated.get("version")) is not int or updated["version"] < 1:
        raise ValueError("site map envelope requires a positive integer version")
    places = site.get("places")
    s3_list = [p for p in (places or []) if isinstance(p, dict) and p.get("id") == "S3"]
    if len(s3_list) != 1:
        raise ValueError(f"expected exactly one S3 place, found {len(s3_list)}")
    clean = validate_limits(limits or S3_ZONE_PRECISION_STOP)
    s3 = s3_list[0]
    ref_x, ref_y, ref_yaw = clean["reference_pose"]
    s3_yaw = s3.get("yaw")
    if (math.dist((float(s3["x"]), float(s3["y"])), (ref_x, ref_y)) > 0.002
            or s3_yaw is None or abs(wrap(float(s3_yaw) - ref_yaw)) > 0.005):
        raise ValueError("map S3 place pose differs from zone-center reference_pose")
    s3["precision_stop"] = clean
    return updated


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--in", dest="src", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    if args.src.resolve() == args.out.resolve():
        parser.error("--out must differ from --in")
    envelope = json.loads(args.src.read_text(encoding="utf-8"))
    updated = apply_s3_zone_baseline(envelope)
    payload = (json.dumps(updated, indent=2, ensure_ascii=False, allow_nan=False) + "\n").encode("utf-8")
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_bytes(payload)
    print(json.dumps({
        "version": updated["version"],
        "sha256": hashlib.sha256(payload).hexdigest(),
        "s3_precision_stop": updated["map"]["places"][next(
            i for i, p in enumerate(updated["map"]["places"]) if p["id"] == "S3"
        )]["precision_stop"],
    }, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
