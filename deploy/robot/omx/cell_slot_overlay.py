#!/usr/bin/env python3
"""Read-only overlay for choosing a cell's target slots (D-1057): the slot ROI table of `cell_area_zones` and each site's place
point, drawn on one top-camera frame. Nothing is written but the PNG; the config is never changed.

    python3 cell_slot_overlay.py --config cell-arm-b-stack.json --frame top.jpg --out overlay.png [--calibration stack-calibration.json]

Place points need the cell's calibration (`cell_observe.predicted_pixel`, the existing coordinate to pixel conversion). Without
`--calibration`, or where it cannot convert a site, that point is left out and listed on stdout and in the picture caption.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

import cv2

from cell_area_zones import TOP_ROI_BY_COL_ROW

SLOT_COLOUR, SITE_COLOUR, POINT_COLOUR = (0, 200, 0), (255, 160, 0), (0, 0, 255)


def draw(image, config: dict, calibration: dict | None) -> tuple[object, list[str]]:
    """(annotated copy of `image`, names of sites whose place point could not be drawn)."""
    out, omitted = image.copy(), []
    for (col, row), (x0, y0, x1, y1) in sorted(TOP_ROI_BY_COL_ROW.items()):
        cv2.rectangle(out, (x0, y0), (x1, y1), SLOT_COLOUR, 1)
        cv2.putText(out, f"c{col}r{row}", (x0 + 3, y0 + 14), cv2.FONT_HERSHEY_SIMPLEX, 0.45, SLOT_COLOUR, 1)
    for name, site in sorted((config.get("sites") or {}).items()):
        roi = site.get("auto_roi")
        if isinstance(roi, list) and len(roi) == 4:
            cv2.rectangle(out, tuple(int(v) for v in roi[:2]), tuple(int(v) for v in roi[2:]), SITE_COLOUR, 1)
            cv2.putText(out, name, (int(roi[0]) + 3, int(roi[3]) - 5), cv2.FONT_HERSHEY_SIMPLEX, 0.45, SITE_COLOUR, 1)
        pixel = None
        if calibration is not None and site.get("place") is not None and "z" in site:
            from cell_observe import predicted_pixel

            try:
                pixel = predicted_pixel(config, calibration, name, tuple(site["place"]))
            except (KeyError, TypeError, ValueError, IndexError):
                pixel = None
        if pixel is None:
            if site.get("place") is not None:
                omitted.append(name)
            continue
        centre = (int(round(pixel[0])), int(round(pixel[1])))
        cv2.drawMarker(out, centre, POINT_COLOUR, cv2.MARKER_CROSS, 14, 2)
        cv2.putText(out, f"{name} place", (centre[0] + 8, centre[1] - 6), cv2.FONT_HERSHEY_SIMPLEX, 0.45, POINT_COLOUR, 1)
    if omitted:
        cv2.putText(out, "no place point (no calibration conversion): " + ", ".join(omitted), (6, out.shape[0] - 8),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.45, POINT_COLOUR, 1)
    return out, omitted


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--config", required=True, type=Path)
    ap.add_argument("--frame", required=True, type=Path, help="one top-camera frame (image file)")
    ap.add_argument("--out", required=True, type=Path, help="PNG to write; must not be the config or the frame")
    ap.add_argument("--calibration", type=Path, help="the cell's calibration JSON (config calibration_path), for the place points")
    args = ap.parse_args(argv)
    if args.out.resolve() in (args.config.resolve(), args.frame.resolve()) or args.out.suffix.lower() != ".png":
        print("refused: --out must be a new .png path", file=sys.stderr)
        return 2
    image = cv2.imread(str(args.frame))
    if image is None:
        print(f"refused: cannot read the frame {args.frame}", file=sys.stderr)
        return 2
    config = json.loads(args.config.read_text(encoding="utf-8"))
    calibration = json.loads(args.calibration.read_text(encoding="utf-8")) if args.calibration else None
    out, omitted = draw(image, config, calibration)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    cv2.imwrite(str(args.out), out)
    print(json.dumps({"out": str(args.out), "slots": len(TOP_ROI_BY_COL_ROW), "place_points_omitted": omitted}))
    return 0


if __name__ == "__main__":
    sys.exit(main())
