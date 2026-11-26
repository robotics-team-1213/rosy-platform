"""Build an offline B-route image-observation fragment; output goes to stdout, never to cell config.

The stand report identifies the four pins and the independent deck marks. The ship report uses
the 38/98 mm CAD pin grid and predicts the reserved target pocket from the other pockets.
The same two captured RGB files must be bound to both reports.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
from pathlib import Path
import sys

import cv2
import numpy as np


STAND = "tmp-b-2"
SHIP = "ship-h1r2"
SOURCE = "user_cleared_fit"
HOLDOUT = "user_cleared_holdout"


def finite_values(values, count):
    if not isinstance(values, list) or len(values) != count or not all(
        type(value) in (int, float) and math.isfinite(value) and value >= 0 for value in values
    ):
        raise ValueError(f"expected {count} finite nonnegative numbers")
    return values


def image_info(path):
    data = path.read_bytes()
    image = cv2.imdecode(np.frombuffer(data, dtype=np.uint8), cv2.IMREAD_GRAYSCALE) if data else None
    if image is None:
        raise ValueError(f"cannot decode image: {path}")
    return hashlib.sha256(data).hexdigest(), image.shape


def in_frame(point, shape):
    x, y = finite_values(point, 2)
    if x >= shape[1] or y >= shape[0]:
        raise ValueError(f"center outside image: {point}")
    return [x, y]


def source_rows(stand, ship, hashes, shape):
    if stand["route"] != STAND + "-l1" or stand["image_sha256"] != hashes:
        raise ValueError("stand route or capture hashes do not match")
    if [ship["sources"][key]["sha256"] for key in (SOURCE, HOLDOUT)] != hashes:
        raise ValueError("ship capture hashes do not match the stand images")
    if SHIP not in ship["held_out_sites"]:
        raise ValueError("ship target was not withheld")
    fit = ship["fits"]["pitch38_spacing98"]
    test = fit["common_frozen_holdout"]
    if (test["fit_source"], test["holdout_source"], test["target"]) != (SOURCE, HOLDOUT, SHIP):
        raise ValueError("ship holdout was not evaluated from the common frozen fit")
    errors = test["errors"]
    if type(errors["n"]) is not int or errors["n"] != 12:
        raise ValueError("all 12 reserved ship pins are required")
    ship_error = finite_values([errors["max_px"]], 1)[0]
    stand_errors = finite_values(stand["heldout_frame_pin_error_px"], 4)
    marks = finite_values(stand["images"]["holdout"]["check_error_px"], 3)
    return {
        STAND: (in_frame(stand["center_px"], shape), max(*stand_errors, *marks)),
        SHIP: (in_frame(fit["frames"][SOURCE]["same_frame_center_px"], shape), ship_error),
    }


def read_report(path):
    report = json.loads(path.read_text(encoding="utf-8-sig"))
    if not isinstance(report, dict):
        raise ValueError(f"expected report object: {path}")
    return report


def fragment(stand_report, ship_report, reference=None, capture=None, holdout=None):
    stand, ship = read_report(stand_report), read_report(ship_report)
    capture = capture or stand_report.parent / stand["fit_rgb"]
    holdout = holdout or stand_report.parent / stand["test_rgb"]
    source_hash, source_shape = image_info(capture)
    test_hash, test_shape = image_info(holdout)
    if source_hash == test_hash or source_shape != test_shape:
        raise ValueError("fit and holdout must be distinct images of equal dimensions")
    rows = source_rows(stand, ship, [source_hash, test_hash], source_shape)
    reference_hash, shape = image_info(reference) if reference else (source_hash, source_shape)
    diagnostics = []
    if reference and reference_hash != source_hash:
        from omx_cad_reference import project_centers

        centers = {name: xy for name, (xy, _) in rows.items()}
        def registered_centers(selected):
            adjusted, proof = project_centers(capture, reference, selected)
            for name in selected:
                residual = finite_values([proof["local"][name]["max_residual_px"]], 1)[0]
                rows[name] = (rows[name][0], max(rows[name][1], residual))
            return adjusted

        try:
            centers = registered_centers(centers)
        except ValueError as joint_error:
            diagnostics.append(f"joint reference registration failed: {joint_error}")
            registered = {}
            for name, xy in centers.items():
                try:
                    one = registered_centers({name: xy})
                    registered[name] = one[name]
                except ValueError as site_error:
                    if name == STAND:
                        from omx_cad_stand import project_stand_center

                        try:
                            projected, evidence = project_stand_center(capture, reference, xy)
                            extra = finite_values([evidence["holdout_max_px"]], 1)[0]
                            rows[name] = (xy, max(rows[name][1], extra))
                            registered[name] = projected
                            diagnostics.append("stand registered by direct CAD landmarks")
                            continue
                        except ValueError as direct_error:
                            diagnostics.append(f"stand landmark registration failed: {direct_error}")
                    diagnostics.append(f"skipped {name}: {site_error}")
            if not registered:
                raise ValueError("; ".join([*diagnostics, "no verified site registration"]))
            centers = registered
    else:
        centers = {name: xy for name, (xy, _) in rows.items()}
    return {"cad_image_observations": {
        name: {"center_px": in_frame(xy, shape), "capture_sha256": source_hash,
               "holdout_sha256": test_hash, "holdout_max_px": rows[name][1],
               "camera_reference_sha256": reference_hash}
        for name, xy in centers.items()
    }}, diagnostics


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--stand", type=Path, required=True)
    parser.add_argument("--ship", type=Path, required=True)
    parser.add_argument("--reference", type=Path, help="project into this operational reference image")
    parser.add_argument("--capture", type=Path, help="override fit image path, preserving its digest")
    parser.add_argument("--holdout", type=Path, help="override holdout image path, preserving its digest")
    args = parser.parse_args()
    try:
        result, notes = fragment(args.stand, args.ship, args.reference, args.capture, args.holdout)
    except (ValueError, OSError, TypeError, KeyError, IndexError, cv2.error) as exc:
        parser.exit(1, f"CAD image evidence rejected: {exc}\n")
    for note in notes:
        print(note, file=sys.stderr)
    print(json.dumps(result, indent=2, allow_nan=False))


if __name__ == "__main__":
    main()
