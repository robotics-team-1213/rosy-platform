"""Check a measured ROSY World display transform from R08 cell to site map."""
import argparse
from datetime import datetime
import gzip
import hashlib
import json
import math
from pathlib import Path

from slam_map_align import AlignError, fit_rigid, flipped_fit, mirror_fit


def digest(content):
    return hashlib.sha256(content).hexdigest()


def bundle_identity(bundle):
    site_map = (bundle / "data/site-map.json").read_bytes()
    cell_model = (bundle / "data/cell-equipment.json.gz").read_bytes()
    site = json.loads(site_map)
    cell = json.loads(gzip.decompress(cell_model))
    manifest = json.loads((bundle / "manifest.json").read_bytes())
    if (site["map"]["schema"] != "rosy.site_map/1" or type(site["version"]) is not int or
            cell["schema"] != "rosy.world.meshes.v1"):
        raise ValueError("expected a Fleet map and an R08 cell model in the bundle")
    return {
        "site_map_id": site["map"]["map_id"],
        "site_map_version": site["version"],
        "site_map_sha256": digest(site_map),
        "site_cad_sha256": manifest.get("site_cad", {}).get("source_sha256"),
        "cell_layout_sha256": cell["layout_sha256"],
        "cell_model_sha256": digest(cell_model),
    }


def number(value):
    return type(value) in (int, float) and math.isfinite(value)


def coordinates(row, key):
    point = row[key]
    if not isinstance(point, list) or len(point) != 3 or not all(map(number, point)):
        raise ValueError(f"{row['id']} needs three finite {key} coordinates")
    return point


def evaluate(bundle, measurements):
    identity = bundle_identity(bundle)
    if not isinstance(measurements, dict) or measurements.get("schema") != "rosy.world.registration-points.v1":
        raise ValueError("expected rosy.world.registration-points.v1")
    if measurements.get("bundle") != identity:
        raise ValueError("measurement map version, cell layout, or asset hash differs from the bundle")
    basis = measurements["basis"]
    if basis not in ("archived-cad", "field") or (basis == "archived-cad" and not identity["site_cad_sha256"]):
        raise ValueError("record field or archived CAD as the point basis")
    source = measurements["source"]
    if (not isinstance(source, str) or not source.strip() or
            datetime.fromisoformat(measurements["captured_at"]).utcoffset() is None):
        raise ValueError("record the measurement source and timezone-aware capture time")
    limits = {"fit": measurements["max_fit_error_m"], "check": measurements["max_check_error_m"]}
    if not all(number(limit) and limit > 0 for limit in limits.values()):
        raise ValueError("record both positive error limits in metres before measuring")

    marks = measurements["points"]
    ids = [row["id"] for row in marks]
    roles = [row["role"] for row in marks]
    if (not all(isinstance(name, str) and name.strip() for name in ids) or len(set(ids)) != len(ids) or
            set(roles) != {"fit", "check"} or roles.count("fit") < 3):
        raise ValueError("use three or more named fit points and at least one separate check point")
    pairs = [(name, role, coordinates(row, "cell_m"), coordinates(row, "site_m"))
             for name, role, row in zip(ids, roles, marks)]
    if any(len({tuple(pairs[i][column]) for i in range(len(pairs))}) != len(pairs) for column in (2, 3)):
        raise ValueError("each fit and check point must have its own location in both frames")

    fit_pairs = [pair for pair in pairs if pair[1] == "fit"]
    cell = [pair[2][:2] for pair in fit_pairs]
    site = [pair[3][:2] for pair in fit_pairs]
    transform = fit_rigid(cell, site)
    dz = sum(pair[3][2] - pair[2][2] for pair in fit_pairs) / len(fit_pairs)

    def residuals(fit, mirrored=False):
        return [
            {"id": name, "role": role, "error_m": math.dist(
                (*fit.apply((x, -y if mirrored else y)), z + dz), target)}
            for name, role, (x, y, z), target in pairs
        ]

    def within_limits(errors):
        return all(row["error_m"] <= limits[row["role"]] for row in errors)

    errors = residuals(transform)
    alternatives = {
        "reversed": within_limits(residuals(flipped_fit(cell, site, transform))),
        "reflected": within_limits(residuals(mirror_fit(cell, site), mirrored=True)),
    }
    passed = within_limits(errors) and not any(alternatives.values())
    report = {
        "schema": "rosy.world.registration-check.v1",
        "status": "candidate" if passed else "rejected",
        "use": "display-only",
        "basis": basis,
        "bundle": identity,
        "source": source,
        "captured_at": measurements["captured_at"],
        "limits_m": limits,
        "errors": errors,
        "alternatives_within_limits": alternatives,
    }
    if passed:
        report["site_from_cell"] = {
            "yaw_rad": transform.yaw, "translation_m": [transform.tx, transform.ty, dz],
        }
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--bundle", type=Path, required=True)
    parser.add_argument("--points", type=Path, required=True)
    args = parser.parse_args()
    try:
        report = evaluate(args.bundle, json.loads(args.points.read_bytes()))
    except (OSError, KeyError, TypeError, ValueError, OverflowError, AlignError) as error:
        print(json.dumps({"status": "rejected", "reason": str(error)}, ensure_ascii=True))
        return 2
    print(json.dumps(report, indent=2, allow_nan=False))
    return 0 if report["status"] == "candidate" else 2


if __name__ == "__main__":
    raise SystemExit(main())
