#!/usr/bin/env python3
"""Maps are data: validate a Nav2 map and drop a saved one into a bundle (ROS-free, stdlib only).

    map_bundle.py check  <map.yaml>
    map_bundle.py import <saved.yaml> <dest_dir> --name NAME [--margin-m 0.20] [--source "robot/date/how"]

`check` lists what is wrong with a map (an empty answer is a pass). `import` takes a map saved by
SLAM (`map_saver`, slam_toolbox save_map) and writes <dest_dir>/maps/NAME.{pgm,yaml} plus
manifest.json, after padding the image with an OCCUPIED margin so that everything outside the
saved area is wall (rule: the world is closed; nothing beyond the map is ever open space).
The bundle's own files are the source of truth; no generator rewrites them.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import sys
from pathlib import Path

OCCUPIED = 0
KEYS = ("image", "resolution", "origin", "occupied_thresh", "free_thresh")


def _parse_yaml(path: Path) -> dict:
    out = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.split("#", 1)[0].strip()
        if ":" not in line:
            continue
        key, value = (part.strip() for part in line.split(":", 1))
        out[key] = value
    missing = [k for k in KEYS if k not in out]
    if missing:
        raise ValueError(f"map yaml lacks {', '.join(missing)}")
    origin = [float(v) for v in out["origin"].strip("[]").split(",")]
    if len(origin) != 3:
        raise ValueError("origin must be [x, y, yaw]")
    return dict(image=out["image"].strip("'\""), resolution=float(out["resolution"]), origin=origin,
                occupied_thresh=float(out["occupied_thresh"]), free_thresh=float(out["free_thresh"]),
                negate=int(out.get("negate", "0")))


def _read_pgm(path: Path):
    data = path.read_bytes()
    tokens, pos = [], 0
    while len(tokens) < 4:  # magic, width, height, maxval; '#' starts a comment line
        while data[pos:pos + 1].isspace():
            pos += 1
        if data[pos:pos + 1] == b"#":
            pos = data.index(b"\n", pos) + 1
            continue
        end = pos
        while end < len(data) and not data[end:end + 1].isspace():
            end += 1
        tokens.append(data[pos:end])
        pos = end
    if tokens[0] != b"P5" or tokens[3] != b"255":
        raise ValueError("image is not an 8-bit binary PGM (P5, maxval 255)")
    width, height = int(tokens[1]), int(tokens[2])
    pixels = data[pos + 1:]
    if width <= 0 or height <= 0 or len(pixels) != width * height:
        raise ValueError("PGM size does not match its pixel data")
    return width, height, [pixels[r * width:(r + 1) * width] for r in range(height)]


def load(yaml_path) -> dict:
    yaml_path = Path(yaml_path)
    meta = _parse_yaml(yaml_path)
    width, height, rows = _read_pgm(yaml_path.parent / meta["image"])
    return dict(meta, width=width, height=height, rows=rows, path=yaml_path)


def _is_occupied(meta, pixel) -> bool:
    prob = (pixel if meta["negate"] else 255 - pixel) / 255.0
    return prob > meta["occupied_thresh"]


def problems(yaml_path) -> list[str]:
    """Everything wrong with a map; [] means it can be used."""
    try:
        m = load(yaml_path)
    except (OSError, ValueError, IndexError) as exc:
        return [f"unreadable map: {exc}"]
    found = []
    if not 0.005 <= m["resolution"] <= 0.2:
        found.append(f"resolution {m['resolution']} m outside 0.005..0.2")
    if not 0.0 <= m["free_thresh"] < m["occupied_thresh"] <= 1.0:
        found.append("thresholds must satisfy 0 <= free < occupied <= 1")
    rows = m["rows"]
    border = list(rows[0]) + list(rows[-1]) + [r[0] for r in rows] + [r[-1] for r in rows]
    open_border = sum(not _is_occupied(m, p) for p in border)
    if open_border:
        found.append(f"{open_border} border cells are not occupied: the outside of the map must be wall")
    if not any(not _is_occupied(m, p) and p > 0 for r in rows for p in r):
        found.append("the map has no free or unknown cell")
    return found


def import_saved(src_yaml, dest_dir, name: str, margin_m: float = 0.20, source: str = "") -> Path:
    """Copy a saved map into <dest_dir>/maps with an occupied margin; returns the written yaml."""
    m = load(src_yaml)
    pad = max(1, math.ceil(margin_m / m["resolution"]))
    width, height = m["width"] + 2 * pad, m["height"] + 2 * pad
    blank = bytes([OCCUPIED]) * width
    rows = [blank] * pad + [bytes([OCCUPIED]) * pad + bytes(r) + bytes([OCCUPIED]) * pad for r in m["rows"]] + [blank] * pad
    ox, oy, oyaw = m["origin"]
    # Padding adds cells to the left and bottom: the image origin moves by pad cells, rotated by the map yaw.
    shift = pad * m["resolution"]
    ox, oy = ox - shift * math.cos(oyaw) + shift * math.sin(oyaw), oy - shift * math.sin(oyaw) - shift * math.cos(oyaw)
    maps = Path(dest_dir) / "maps"
    maps.mkdir(parents=True, exist_ok=True)
    pgm = f"P5\n# rosy map bundle: {name}\n{width} {height}\n255\n".encode() + b"".join(rows)
    (maps / f"{name}.pgm").write_bytes(pgm)
    (maps / f"{name}.yaml").write_text(
        f"image: {name}.pgm\nmode: trinary\nresolution: {m['resolution']}\n"
        f"origin: [{ox:.6f}, {oy:.6f}, {oyaw}]\nnegate: {m['negate']}\n"
        f"occupied_thresh: {m['occupied_thresh']}\nfree_thresh: {m['free_thresh']}\n", encoding="utf-8", newline="\n")
    manifest = dict(name=name, source=source, margin_cells=pad, resolution=m["resolution"],
                    source_pgm_sha256=hashlib.sha256((Path(src_yaml).parent / m["image"]).read_bytes()).hexdigest(),
                    pgm_sha256=hashlib.sha256(pgm).hexdigest())
    (Path(dest_dir) / "maps" / "manifest.json").write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n",
                                                            encoding="utf-8", newline="\n")
    bad = problems(maps / f"{name}.yaml")
    if bad:
        raise ValueError("imported map is not usable: " + "; ".join(bad))
    return maps / f"{name}.yaml"


def main(argv=None) -> int:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = p.add_subparsers(dest="cmd", required=True)
    c = sub.add_parser("check")
    c.add_argument("yaml", type=Path)
    i = sub.add_parser("import")
    i.add_argument("yaml", type=Path)
    i.add_argument("dest", type=Path)
    i.add_argument("--name", required=True)
    i.add_argument("--margin-m", type=float, default=0.20)
    i.add_argument("--source", default="")
    args = p.parse_args(argv)
    if args.cmd == "check":
        found = problems(args.yaml)
        print("\n".join(found) if found else "ok")
        return 1 if found else 0
    print(import_saved(args.yaml, args.dest, args.name, args.margin_m, args.source))
    return 0


if __name__ == "__main__":
    sys.exit(main())
