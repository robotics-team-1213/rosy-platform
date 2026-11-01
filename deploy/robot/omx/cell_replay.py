#!/usr/bin/env python3
"""A carry's decisions on a saved top frame, offline: what it would observe, refuse, pick and where it would place,
as JSON and a picture (2026-10-30). No arm, no camera, no session.

Each change to detection, finger room or place fit used to need the lit cell and a dry run on the Fleet PC; three
throwaway probe scripts were written for it in one night. The same run_auto dry run reads the saved frame here.

  cell_replay.py --config C --catalog K --frame F.jpg --from board --dest belt [--roi x0 y0 x1 y1] [--out pic.png]
"""
from __future__ import annotations

import argparse
import json
import sys
import tempfile
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent))
import cell_auto_pick as ap  # noqa: E402
import cell_calibration as cal  # noqa: E402
import cell_objects  # noqa: E402
import cell_place_fit  # noqa: E402


class FrameCell:
    """Every camera answers with the saved frame; any arm command is refused (a dry run sends none)."""

    def __init__(self, img):
        self.img, self.commands = img, []

    def frame(self, camera: str):
        return self.img

    def act(self, command: str) -> dict:
        self.commands.append(command)
        return {"ok": False, "error": "replay: no arm"}


def replay(config: dict, calibration: dict, catalog: list, img, source: str, dest: str, roi=None,
           calibration_path=None) -> dict:
    """run_auto's dry run on `img`; the bias regions are read from calibration_path's bias file, never written."""
    import cell_choices

    roi = roi or config["sites"][source]["auto_roi"]
    with tempfile.TemporaryDirectory() as work:
        cell = FrameCell(img)
        out = ap.run_auto(cell, config, calibration, calibration_path or Path(work) / "none.json", catalog, roi, source, dest, Path(work),
                          cell_choices.Choices(Path(work) / "choices.json"), dry_run=True, log=lambda *a: None)
    assert not cell.commands, cell.commands  # a dry run must not move anything
    return out


def picture(config: dict, calibration: dict, catalog: list, img, out: dict, source: str):
    """The frame with the source and destination surfaces, the chosen pick (green) and the place footprint (cyan)."""
    import cv2

    vis = img.copy()
    for s in config["sites"].values():
        if s.get("surface_px"):
            cv2.polylines(vis, [np.asarray(s["surface_px"], np.int32)], True, (0, 200, 255), 1)
    row = (out.get("attempts") or [{}])[0]
    plan, chosen = row.get("plan"), row.get("chosen") or {}
    if plan:
        entry = {e["id"]: e for e in catalog}[chosen["object"]]
        dest_site, _ = ap.parse_dest(config, source, out["to"])
        pick = ap.predicted_pixel(config, calibration, source, (plan["pick"]["x"], plan["pick"]["y"]))
        cv2.circle(vis, (round(pick[0]), round(pick[1])), 5, (0, 255, 0), 2)
        held = row["long_axis_deg"] - plan["pick"]["yaw_deg"]  # the box's axis relative to the tool, as cell_place_fit
        pts = np.asarray([ap.predicted_pixel(config, calibration, dest_site, p) for p in cell_place_fit.footprint(
            (plan["place"]["x"], plan["place"]["y"]), plan["place"]["yaw_deg"] + held, entry["length_mm"], entry["width_mm"])],
            np.float32)
        cv2.polylines(vis, [cv2.convexHull(pts).astype(np.int32)], True, (255, 255, 0), 2)
    return vis


def main(argv=None):
    import cv2

    ap_ = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap_.add_argument("--config", required=True, type=Path)
    ap_.add_argument("--catalog", required=True)
    ap_.add_argument("--frame", required=True)
    ap_.add_argument("--from", dest="source", required=True)
    ap_.add_argument("--dest", required=True)
    ap_.add_argument("--roi", type=int, nargs=4)
    ap_.add_argument("--out")
    args = ap_.parse_args(argv)
    config = ap.load_config(args.config)
    calibration_path = Path(config["calibration_path"]).expanduser()
    calibration = cal.load(calibration_path)
    catalog = cell_objects.load_catalog(args.catalog)
    img = cv2.imread(args.frame)
    out = replay(config, calibration, catalog, img, args.source, args.dest, args.roi, calibration_path)
    print(json.dumps(out, indent=1, default=str))
    if args.out:
        cv2.imwrite(args.out, picture(config, calibration, catalog, img, out, args.source))
    return 0 if out["result"] == "planned" else 1


if __name__ == "__main__":
    sys.exit(main())
