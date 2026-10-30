#!/usr/bin/env python3
"""A bench scale read through a cell camera, so an object's mass is measured catalogue data (2026-10-30, D-934).

D-911 refuses even a supervised trial without a measured payload, and per-object facts belong in the catalogue. A
person zeroes the scale and puts the object on it; this reads the scale's 7-segment display in a camera frame,
accepts a value only after it repeats (`scale.repeats`), and writes `mass_kg` into that catalogue entry. With
--conditions it also copies mass and size into a cell config's `operating_conditions`.

  "scale": {"camera": "top", "display_px": [[x, y] top-left, top-right, bottom-right, bottom-left],
            "digits": 5, "decimals": 2, "unit": "g", "dark_digits": true,
            "digit_frac": 0.75}   (display_px spans whole digit pitches; a digit is digit_frac of its pitch wide)
  cell_scale.py read  --config cell.json
  cell_scale.py enrol --config cell.json --catalog catalog.json --object container-2 [--conditions cell.json]

The decimal point is not read: `decimals` is the scale's fixed resolution. A frame that does not give a digit on
every position is unreadable (None), never a guess.
"""
from __future__ import annotations

import argparse
import json
import sys
import time
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent))
import cell_params as prm  # noqa: E402

CELL_W, CELL_H = 40, 70  # one digit after rectifying, px
# segment bands in a digit as fractions (x0, y0, x1, y1, horizontal): a top, b top-right, c bottom-right, d bottom,
# e bottom-left, f top-left, g middle. A band is wider than the stroke; what counts is how much of its length a
# stroke covers, so stroke width and a small offset do not matter (thin 18 px strokes half-filled a tight box).
SEGMENTS = ((0.25, 0.0, 0.75, 0.16, True), (0.7, 0.12, 1.0, 0.45, False), (0.7, 0.55, 1.0, 0.88, False),
            (0.25, 0.84, 0.75, 1.0, True), (0.0, 0.55, 0.3, 0.88, False), (0.0, 0.12, 0.3, 0.45, False),
            (0.25, 0.42, 0.75, 0.58, True))
PATTERNS = {(1, 1, 1, 1, 1, 1, 0): "0", (0, 1, 1, 0, 0, 0, 0): "1", (1, 1, 0, 1, 1, 0, 1): "2",
            (1, 1, 1, 1, 0, 0, 1): "3", (0, 1, 1, 0, 0, 1, 1): "4", (1, 0, 1, 1, 0, 1, 1): "5",
            (1, 0, 1, 1, 1, 1, 1): "6", (0, 0, 1, 1, 1, 1, 1): "6", (1, 1, 1, 0, 0, 0, 0): "7",
            (1, 1, 1, 0, 0, 1, 0): "7", (1, 1, 1, 1, 1, 1, 1): "8", (1, 1, 1, 1, 0, 1, 1): "9",
            (1, 1, 1, 0, 0, 1, 1): "9", (0, 0, 0, 0, 0, 0, 1): "-", (0, 0, 0, 0, 0, 0, 0): " "}


def read_display(img, spec: dict, params=None) -> float | None:
    """The value on the display in `spec["unit"]`, or None when any digit position is not a digit, blank or sign."""
    import cv2

    digits = int(spec["digits"])
    w, h = CELL_W * digits, CELL_H
    M = cv2.getPerspectiveTransform(np.float32(spec["display_px"]), np.float32([[0, 0], [w, 0], [w, h], [0, h]]))
    grey = img if img.ndim == 2 else cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
    flat = cv2.GaussianBlur(cv2.warpPerspective(grey, M, (w, h), flags=cv2.INTER_CUBIC), (3, 3), 0)
    _, on = cv2.threshold(flat, 0, 1, (cv2.THRESH_BINARY_INV if spec.get("dark_digits", True) else cv2.THRESH_BINARY)
                          + cv2.THRESH_OTSU)
    fill, wide = prm.get(params, "scale.segment_fill"), CELL_W * float(spec.get("digit_frac", 0.75))
    text = ""
    for i in range(digits):  # a digit takes digit_frac of its pitch; the rest is the gap to the next one
        cell = on[:, i * CELL_W:(i + 1) * CELL_W]
        lit = tuple(int(cell[int(y0 * h):int(y1 * h), int(x0 * wide):int(x1 * wide)].any(axis=0 if across else 1).mean()
                        >= fill) for x0, y0, x1, y1, across in SEGMENTS)
        if lit not in PATTERNS:
            return None
        text += PATTERNS[lit]
    text = text.strip()
    if not text or text == "-" or " " in text or "-" in text[1:]:
        return None
    return int(text) / 10 ** int(spec.get("decimals", 0))


def stable(read, params=None, wait=time.sleep, clock=time.monotonic, accept=lambda v: True) -> float | None:
    """The first value `read()` gives `scale.repeats` times in a row that `accept` takes, within `scale.timeout_s`."""
    need, end, last, run = int(prm.get(params, "scale.repeats")), clock() + prm.get(params, "scale.timeout_s"), None, 0
    while clock() < end:
        value = read()
        run = run + 1 if value is not None and value == last else (1 if value is not None else 0)
        last = value
        if value is not None and run >= need and accept(value):
            return value
        wait(0.2)
    return None


def to_kg(value: float, unit: str) -> float:
    return round(value / {"g": 1000.0, "kg": 1.0, "mg": 1e6}[unit], 6)


def enrol(catalog_path: Path, object_id: str, mass_kg: float, reading: str, conditions_path: Path | None = None) -> dict:
    """Write mass_kg into the catalogue entry (and the cell config's operating_conditions); the updated entry."""
    catalog = json.loads(catalog_path.read_text(encoding="utf-8"))
    entry = next((o for o in catalog["objects"] if o["id"] == object_id), None)
    if entry is None:
        raise SystemExit(f"{object_id} is not in {catalog_path}: an unknown object is not enrolled")
    entry.update(mass_kg=mass_kg, mass_measured={"at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
                                                 "source": "cell_scale", "reading": reading})
    catalog_path.write_text(json.dumps(catalog, indent=1) + "\n", encoding="utf-8")
    if conditions_path:
        config = json.loads(conditions_path.read_text(encoding="utf-8"))
        conditions = config.setdefault("operating_conditions", {})
        conditions.update(payload_kg=mass_kg, object_revision=object_id, object_dimensions_m=[
            entry["length_mm"] / 1000, entry["width_mm"] / 1000, entry["top_height_mm"] / 1000])
        conditions_path.write_text(json.dumps(config, indent=1) + "\n", encoding="utf-8")
    return entry


def main(argv=None):
    import cv2

    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("action", choices=("read", "enrol"))
    ap.add_argument("--config", required=True, type=Path)
    ap.add_argument("--catalog", type=Path)
    ap.add_argument("--object")
    ap.add_argument("--conditions", type=Path, help="cell config whose operating_conditions take the mass")
    args = ap.parse_args(argv)
    config = json.loads(args.config.read_text(encoding="utf-8"))
    spec, params = config["scale"], config.get("params")
    camera = config["cameras"][spec["camera"]]

    def frame():
        with urllib.request.urlopen(camera["url"], timeout=10) as reply:
            return cv2.imdecode(np.frombuffer(reply.read(), np.uint8), cv2.IMREAD_GRAYSCALE)

    if camera.get("device"):  # an over- or under-exposed display reads as nothing
        import cell_preflight

        print(json.dumps({"exposure": cell_preflight.expose(camera["device"], frame, params)}), file=sys.stderr)
    read = lambda: read_display(frame(), spec, params)  # noqa: E731
    if args.action == "read":
        value = stable(read, params)
        print(json.dumps({"value": value, "unit": spec["unit"], "ok": value is not None}))
        return 0 if value is not None else 1
    if not (args.catalog and args.object):
        ap.error("enrol needs --catalog and --object")
    print("waiting for the empty scale to read 0", file=sys.stderr)
    if stable(read, params, accept=lambda v: v == 0) is None:
        print(json.dumps({"ok": False, "why": "the empty scale never read 0: zero it, check display_px and the light"}))
        return 1
    print(f"put {args.object} on the scale", file=sys.stderr)
    value = stable(read, params, accept=lambda v: v > 0)
    if value is None:
        print(json.dumps({"ok": False, "why": "no steady reading with the object on the scale"}))
        return 1
    reading = f"{value:.{int(spec.get('decimals', 0))}f} {spec['unit']}"
    entry = enrol(args.catalog, args.object, to_kg(value, spec["unit"]), reading, args.conditions)
    print(json.dumps({"ok": True, "object": args.object, "mass_kg": entry["mass_kg"], "reading": reading}))
    return 0


if __name__ == "__main__":
    sys.exit(main())
