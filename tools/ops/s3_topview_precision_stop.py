#!/usr/bin/env python3
"""Operator script: put the top-view precision stop on S3 in a site-map JSON (2026-11-27). It does not publish.

Usage: python tools/ops/s3_topview_precision_stop.py --in map_v395.json --out map_v396_draft.json
The map comes from the Fleet site-map export; the result is imported as a draft and activated by the coordinator
through the Fleet draft/activate API. S3 moves to the training target of model S (deploy/site/cell-topview/s3.json,
"site_target"), stays pinned, and gets precision_stop limits whose reference_pose equals that place (Fleet
validates this). Fleet starts using the top view only when ROSY_FLEET_CELL_TOPVIEW names that data file too.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
DATA = ROOT / "deploy/site/cell-topview/s3.json"


def apply_precision_stop(raw: dict, data: dict) -> dict:
    target = data["site_target"]
    place = next((p for p in raw.get("places", []) if p.get("id") == data["place"]), None)
    if place is None or place.get("kind") != "stop":
        raise SystemExit(f"{data['place']} is not a stop of this map")
    pose = [target["x"], target["y"], target["yaw"]]
    place.update(x=pose[0], y=pose[1], yaw=pose[2], pinned=True)
    place["precision_stop"] = {**data["precision_stop"], "reference_pose": pose}
    return raw


def main(argv=None) -> None:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("--in", dest="source", required=True)
    parser.add_argument("--out", required=True)
    parser.add_argument("--data", default=str(DATA))
    args = parser.parse_args(argv)
    raw = json.loads(Path(args.source).read_text(encoding="utf-8-sig"))
    before = next((p for p in raw.get("places", []) if p.get("id") == "S3"), {})
    old = (before.get("x"), before.get("y"), before.get("yaw"))
    out = apply_precision_stop(raw, json.loads(Path(args.data).read_text(encoding="utf-8")))
    sys.path[:0] = [str(ROOT / "operations/fleet"), str(ROOT / "contracts/foundation")]
    from fleet.site_map import SiteMap

    SiteMap.model_validate(out)  # the same validation Fleet applies on import
    Path(args.out).write_text(json.dumps(out, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    place = next(p for p in out["places"] if p["id"] == "S3")
    print(f"S3 {old} -> {(place['x'], place['y'], place['yaw'])}, precision_stop added; wrote {args.out}. Not published.")


if __name__ == "__main__":
    main()
