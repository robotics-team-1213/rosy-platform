#!/usr/bin/env python3
"""Export a lossless crop from a saved ceiling JPEG and print its evidence as JSON.

Pixel coordinates refer to the decoded source image. Field readings must be supplied
explicitly. This tool does not read ruler ticks, query Fleet, or use robot localization.
"""

import argparse
import hashlib
import json
import math
import sys
from pathlib import Path

import cv2


PADDING_PX = 240


def crop_bounds(corners, width, height, roi):
    xs, ys = zip(*corners)
    xmin, xmax, ymin, ymax = min(xs), max(xs), min(ys), max(ys)
    bounds = roi if roi is not None else (
        max(0, math.floor(xmin) - PADDING_PX), max(0, math.floor(ymin) - PADDING_PX),
        min(width, math.floor(xmax) + PADDING_PX + 1), min(height, math.floor(ymax) + PADDING_PX + 1),
    )
    x0, y0, x1, y1 = bounds
    if not (0 <= x0 < x1 <= width and 0 <= y0 < y1 <= height):
        raise ValueError("ROI must be inside the source image")
    if not (x0 <= xmin <= xmax < x1 and y0 <= ymin <= ymax < y1):
        raise ValueError("ROI must include the selected marker")
    return bounds


def image_evidence(source, out, marker_id, roi):
    # Use Vision's raw marker detector from a repository checkout without a Fleet connection.
    root = Path(__file__).resolve().parents[2]
    sys.path[:0] = [str(root / "operations/overhead"), str(root / "contracts/foundation")]
    from rosy_vision.detect import detect_markers

    jpeg = source.read_bytes()
    if not jpeg.startswith(b"\xff\xd8\xff"):
        raise ValueError("source must be a JPEG")
    markers = detect_markers(jpeg, reread_qr=False, expected_marker_ids={marker_id})
    if markers.image is None:
        raise ValueError("could not decode source JPEG")
    corners = markers.get(marker_id)
    if corners is None or marker_id in markers.qr_ids:
        raise ValueError(f"ArUco marker {marker_id} was not detected")

    height, width = markers.image.shape[:2]
    x0, y0, x1, y1 = crop_bounds(corners, width, height, roi)
    ok, encoded = cv2.imencode(".png", markers.image[y0:y1, x0:x1])
    if not ok:
        raise ValueError("could not encode crop as PNG")
    crop = encoded.tobytes()
    with out.open("xb") as output:
        output.write(crop)
    return {
        "source_path": str(source.resolve()),
        "source_sha256": hashlib.sha256(jpeg).hexdigest(),
        "source_size_px": [width, height],
        "marker_id": marker_id,
        "marker_corners_xy": corners,
        "crop_path": str(out.resolve()),
        "crop_sha256": hashlib.sha256(crop).hexdigest(),
        "crop_xyxy": [x0, y0, x1, y1],
        "crop_size_px": [x1 - x0, y1 - y0],
    }


def field_measurement(args):
    station, marker = args.station_end_wall_mm, args.marker_wall_mm
    if all(value is None for value in (station, marker, args.datum, args.field_marker)):
        return None
    datum = (args.datum or "").strip()
    if not datum or any(value is None or not math.isfinite(value) or value < 0 for value in (station, marker)):
        raise ValueError("field readings require two nonnegative distances in mm and their common --datum")
    return {
        "source": "field_reported",
        "datum": datum,
        "marker_id": args.marker if args.field_marker is None else args.field_marker,
        "station_end_wall_mm": station,
        "marker_wall_mm": marker,
        "inset_mm": station - marker,
    }


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("jpeg", type=Path)
    parser.add_argument("--marker", required=True, type=int, help="ArUco ID to locate in the saved source")
    parser.add_argument("--out", required=True, type=Path, help="New crop PNG in an existing directory")
    parser.add_argument("--roi", type=int, nargs=4, metavar=("X0", "Y0", "X1", "Y1"),
                        help="Source pixel bounds, right and bottom exclusive. Default pads the marker by 240 px.")
    parser.add_argument("--datum", help="Common wall face or other datum for the field readings")
    parser.add_argument("--station-end-wall-mm", type=float, help="Field-reported station end distance from datum")
    parser.add_argument("--marker-wall-mm", type=float, help="Field-reported marker distance from datum")
    parser.add_argument("--field-marker", type=int, help="Marker the field reading concerns, if different from --marker")
    args = parser.parse_args(argv)
    if args.marker not in range(50) or (args.field_marker is not None and args.field_marker not in range(50)):
        parser.error("marker IDs must be in the ArUco DICT_4X4_50 range 0–49")
    if args.out.suffix.lower() != ".png":
        parser.error("--out must name a PNG file")
    try:
        field = field_measurement(args)
        image = image_evidence(args.jpeg, args.out, args.marker, args.roi)
    except (OSError, ValueError) as exc:
        parser.error(str(exc))
    print(json.dumps({"image_evidence": image, "field_measurement": field}, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
