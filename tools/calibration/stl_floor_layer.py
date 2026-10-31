"""Cut a large CAD world STL down to its floor layer for the Fleet drawing upload (D-825).

Fleet takes at most 16 MB / 200,000 triangles, and its projection only rotates and scales
(no mirror). A Y-up CAD world (track, arms, frames) is therefore reduced here to the upward
faces from the floor (the height with the most upward area) up to `--above-mm`, and written
Z-up by the proper rotation (x, y, z) -> (x, -z, y). Upload the result and project it with
plane `xy`. Units stay those of the source (usually mm); nothing is scaled or recentred.

    python tools/calibration/stl_floor_layer.py <world.stl> <floor.stl> [--above-mm 80] [--y-up]
"""

from __future__ import annotations

import argparse
import struct
import sys
from pathlib import Path

UP_MIN = 0.95
FLEET_MAX_TRIANGLES = 200_000
FLEET_MAX_BYTES = 16 * 1024 * 1024


def _read(data: bytes):
    count = struct.unpack_from("<I", data, 80)[0]
    if len(data) != 84 + 50 * count:
        raise ValueError("not a binary STL: size does not match triangle count")
    for i in range(count):
        yield struct.unpack_from("<12f", data, 84 + 50 * i)


def floor_layer(data: bytes, above: float, y_up: bool) -> tuple[list, float]:
    up_axis = 1 if y_up else 2
    up = [t for t in _read(data) if t[up_axis] >= UP_MIN]
    if not up:
        raise ValueError("no upward faces; check --y-up")

    def height(t):
        return (t[3 + up_axis] + t[6 + up_axis] + t[9 + up_axis]) / 3.0

    def area(t):
        a, b = (0, 2) if y_up else (0, 1)
        p = [(t[3 + 3 * k + a], t[3 + 3 * k + b]) for k in range(3)]
        return abs((p[1][0] - p[0][0]) * (p[2][1] - p[0][1]) - (p[2][0] - p[0][0]) * (p[1][1] - p[0][1])) / 2

    by_height: dict[float, float] = {}
    for t in up:
        by_height[round(height(t), 1)] = by_height.get(round(height(t), 1), 0.0) + area(t)
    floor = max(by_height, key=by_height.get)
    kept = [t for t in up if floor - 0.05 <= height(t) <= floor + above]

    def z_up(t):
        if not y_up:
            return t
        out = []
        for k in range(4):  # normal and three vertices
            x, y, z = t[3 * k:3 * k + 3]
            out += [x, -z, y]
        return tuple(out)

    return [z_up(t) for t in kept], floor


def write(triangles, path: Path, label: str) -> None:
    body = bytearray(label.encode("ascii", "replace")[:80].ljust(80, b" ") + struct.pack("<I", len(triangles)))
    for t in triangles:
        body += struct.pack("<12fH", *t, 0)
    path.write_bytes(bytes(body))


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("source", type=Path)
    parser.add_argument("output", type=Path)
    parser.add_argument("--above-mm", type=float, default=80.0, help="keep upward faces up to this above the floor")
    parser.add_argument("--z-up", dest="y_up", action="store_false", help="source is already Z-up")
    args = parser.parse_args(argv[1:])
    triangles, floor = floor_layer(args.source.read_bytes(), args.above_mm, args.y_up)
    write(triangles, args.output, f"floor layer of {args.source.name} (Z-up, source units)")
    size = args.output.stat().st_size
    print(f"floor at {floor} source units; kept {len(triangles)} upward faces; {size} bytes")
    if len(triangles) > FLEET_MAX_TRIANGLES or size > FLEET_MAX_BYTES:
        print("over the Fleet drawing limit; lower --above-mm", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
