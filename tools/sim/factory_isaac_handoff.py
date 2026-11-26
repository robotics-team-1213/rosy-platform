"""Prepare Isaac input from an isolated SIM stop and claim bound to a measured S3.

Usage: python tools/sim/factory_isaac_handoff.py --receipts RUN/prefix.json
       --site-map RUN/active-map.json --out RUN/isaac-intake.json

The first evidence JSON file in the s3_stop receipt must carry
rosy.factory-s3-stop-observation.v1: the receipt bindings, source_kind
"gazebo_odom", pose_frame "site_map", place_id "S3", and samples with
sim_time_s, pose_xy_yaw, linear_m_s and angular_rad_s. The first evidence JSON
in cell_claim carries rosy.factory-sim-cell-claim.v1, the same bindings,
scope "isolated_sim", cell_id, stop_sha256 and claimed_sim_time_s.
The validator emits an input envelope only. It never starts either simulator
or changes a Fleet task.
"""

import argparse
import hashlib
import json
import math
from pathlib import Path

from factory_flow_receipts import BINDING_FIELDS, STAGES, is_placeholder, verify

PREFIX = STAGES[:4]
LINEAR_STOP_M_S = 0.001
ANGULAR_STOP_RAD_S = 0.01


def number(value):
    if type(value) not in (float, int) or not math.isfinite(value):
        raise ValueError("expected a finite measurement")
    return value


def pose(value):
    if not isinstance(value, list) or len(value) != 3:
        raise ValueError("expected site x, y and yaw")
    return tuple(map(number, value))


def evidence(receipt, base):
    entry = receipt["evidence"][0]
    path = (base / entry["path"]).resolve(strict=True)
    if not path.is_relative_to(base) or not path.is_file():
        raise ValueError("evidence must be a file inside the run directory")
    content = path.read_bytes()
    actual_sha = hashlib.sha256(content).hexdigest()
    if actual_sha != entry["sha256"].lower():
        raise ValueError("evidence changed after receipt verification")
    return json.loads(content), actual_sha


def prepare(receipt_path, map_path):
    errors, report = verify(receipt_path, expected_stages=PREFIX)
    if errors:
        raise ValueError("; ".join(errors))
    binding = report["bindings"]
    source = map_path.read_bytes()
    if hashlib.sha256(source).hexdigest() != binding["site_map_sha256"].lower():
        raise ValueError("site map does not match the run")
    envelope = json.loads(source)
    site = envelope["map"]
    stops = [item for item in site["places"] if item["id"] == "S3"]
    if site.get("schema") != "rosy.site_map/1" or type(envelope["version"]) is not int or len(stops) != 1:
        raise ValueError("expected one S3 in the versioned Fleet map")
    limits = stops[0].get("precision_stop")
    if not isinstance(limits, dict) or not isinstance(limits.get("evidence_ref"), str) or is_placeholder(limits["evidence_ref"]):
        raise ValueError("S3 map has no measured precision stop limits")
    x, y, yaw = pose(limits["reference_pose"])
    longitudinal, lateral, heading, xy_error, yaw_error = (
        number(limits[name]) for name in ("longitudinal_m", "lateral_m", "heading_rad",
                                          "position_uncertainty_m", "heading_uncertainty_rad"))
    if not (0 < xy_error < min(longitudinal, lateral) <= max(longitudinal, lateral) <= .10
            and 0 < yaw_error < heading <= math.pi / 2):
        raise ValueError("invalid S3 precision stop limits")

    receipts = report["verified_receipts"]
    base = receipt_path.resolve().parent
    stop, stop_sha = evidence(receipts[2], base)
    claim, claim_sha = evidence(receipts[3], base)
    for item in (stop, claim):
        if not isinstance(item, dict) or any(item.get(key) != binding[key] for key in BINDING_FIELDS):
            raise ValueError("stop and claim must match the run binding")
    if (stop.get("schema") != "rosy.factory-s3-stop-observation.v1" or stop.get("place_id") != "S3"
            or stop.get("source_kind") != "gazebo_odom" or stop.get("pose_frame") != "site_map"):
        raise ValueError("S3 requires isolated Gazebo evidence mapped to the Fleet site frame")

    times = []
    positions = []
    for sample in stop["samples"]:
        times.append(number(sample["sim_time_s"]))
        px, py, direction = pose(sample["pose_xy_yaw"])
        positions.append((px, py, direction))
        dx, dy = px - x, py - y
        if (abs(number(sample["linear_m_s"])) > LINEAR_STOP_M_S
                or abs(number(sample["angular_rad_s"])) > ANGULAR_STOP_RAD_S
                or abs(dx * math.cos(yaw) + dy * math.sin(yaw)) + xy_error > longitudinal
                or abs(-dx * math.sin(yaw) + dy * math.cos(yaw)) + xy_error > lateral
                or abs(math.remainder(direction - yaw, math.tau)) + yaw_error > heading):
            raise ValueError("S3 observation is moving or outside measured stop bounds")
    if (len(times) < 2 or times[0] < 0 or times[-1] - times[0] < 1.0
            or any(not 0 < b - a <= .5 for a, b in zip(times, times[1:]))):
        raise ValueError("S3 requires at least one second of continuous, advancing stop observations")
    if (claim.get("schema") != "rosy.factory-sim-cell-claim.v1" or claim.get("scope") != "isolated_sim"
            or claim.get("cell_id") != "cell_s" or claim.get("stop_sha256") != stop_sha
            or not 0 <= number(claim.get("claimed_sim_time_s")) - times[-1] <= 2):
        raise ValueError("cell claim must reference the fresh S3 stop from this run")
    return {
        "schema": "rosy.factory-isaac-intake.v1", "scope": "isolated_sim",
        "bindings": binding, "cell_id": "cell_s", "place_id": "S3",
        "site_map_version": envelope["version"], "site_xy_yaw": positions[-1],
        "stop_sha256": stop_sha, "claim_sha256": claim_sha,
        "prefix_stages": list(PREFIX), "pending_stages": list(STAGES[4:]),
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--receipts", type=Path, required=True)
    parser.add_argument("--site-map", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    try:
        result = prepare(args.receipts, args.site_map)
        with args.out.open("x", encoding="utf-8") as stream:
            json.dump(result, stream, indent=2, allow_nan=False)
    except (OSError, OverflowError, KeyError, TypeError, ValueError) as error:
        parser.exit(1, f"S3 intake refused: {error}\n")


if __name__ == "__main__":
    main()
