#!/usr/bin/env python3
"""Draw a D-370 surface icon SVG to PNG with Pillow (store listings, docs, silhouette checks).

The icons in ``src/hmi/web_common/icons/`` use ``<path>`` elements only, with absolute
M/L/H/V/A/Z commands, and either a fill or a round-capped stroke. That subset is what
this renderer reads; anything else raises. Output PNGs are not kept in the repository:
write them under X:\\DevTemp (or another scratch folder) when a listing or doc needs one.

    python tools/icons/render_png.py src/hmi/web_common/icons/pilot.svg X:/DevTemp/pilot.png
    python tools/icons/render_png.py <svg> <png> --size 48 --mono
"""

from __future__ import annotations

import argparse
import math
import re
import xml.etree.ElementTree as ET
from pathlib import Path

from PIL import Image, ImageDraw

SVG_NS = "{http://www.w3.org/2000/svg}"
GRID = 108.0
_TOKEN = re.compile(r"[MLHVAZ]|-?\d*\.?\d+(?:e-?\d+)?", re.I)


def _arc(x1, y1, rx, ry, large, sweep, x2, y2, steps=48):
    """SVG endpoint arc (no rotation) as points, excluding the start point."""
    dx, dy = (x1 - x2) / 2, (y1 - y2) / 2
    scale = (dx * dx) / (rx * rx) + (dy * dy) / (ry * ry)
    if scale > 1:
        rx, ry = rx * math.sqrt(scale), ry * math.sqrt(scale)
    num = rx * rx * ry * ry - rx * rx * dy * dy - ry * ry * dx * dx
    den = rx * rx * dy * dy + ry * ry * dx * dx
    coef = math.sqrt(max(0.0, num / den)) if den else 0.0
    if large == sweep:
        coef = -coef
    cxp, cyp = coef * rx * dy / ry, -coef * ry * dx / rx
    cx, cy = cxp + (x1 + x2) / 2, cyp + (y1 + y2) / 2
    start = math.atan2((dy - cyp) / ry, (dx - cxp) / rx)
    end = math.atan2((-dy - cyp) / ry, (-dx - cxp) / rx)
    delta = end - start
    if sweep and delta < 0:
        delta += 2 * math.pi
    elif not sweep and delta > 0:
        delta -= 2 * math.pi
    return [(cx + rx * math.cos(start + delta * i / steps),
             cy + ry * math.sin(start + delta * i / steps)) for i in range(1, steps + 1)]


def subpaths(d: str) -> list[tuple[list[tuple[float, float]], bool]]:
    """Flatten a path into (points, closed) runs."""
    tokens = _TOKEN.findall(d)
    runs, points, x, y, i, closed = [], [], 0.0, 0.0, 0, False
    command = None
    while i < len(tokens):
        if tokens[i].isalpha():
            command = tokens[i]
            i += 1
            if command in "Zz":
                runs.append((points, True))
                points, closed = [], True
                continue
        if command not in {"M", "L", "H", "V", "A"}:
            raise ValueError(f"unsupported path command {command!r} (absolute M/L/H/V/A/Z only)")
        take = {"M": 2, "L": 2, "H": 1, "V": 1, "A": 7}[command]
        values = [float(value) for value in tokens[i:i + take]]
        i += take
        if command == "M":
            if points:
                runs.append((points, False))
            x, y = values
            points = [(x, y)]
            command = "L"
        elif command == "L":
            x, y = values
            points.append((x, y))
        elif command == "H":
            x = values[0]
            points.append((x, y))
        elif command == "V":
            y = values[0]
            points.append((x, y))
        else:
            rx, ry, rotation, large, sweep, nx, ny = values
            if rotation:
                raise ValueError("rotated arcs are not supported")
            points.extend(_arc(x, y, rx, ry, int(large), int(sweep), nx, ny))
            x, y = nx, ny
    if points:
        runs.append((points, closed))
    return runs


def shapes(svg: Path) -> list[dict]:
    """Every drawable path in document order: id, d, fill, stroke, width."""
    root = ET.parse(svg).getroot()
    found = []
    for element in root.iter():
        tag = element.tag.removeprefix(SVG_NS)
        if tag in {"svg", "g", "title", "desc"} or not isinstance(element.tag, str):
            continue
        if tag != "path":
            raise ValueError(f"{svg.name}: only <path> is allowed, found <{tag}>")
        found.append({"id": element.get("id"), "d": element.get("d"),
                      "fill": element.get("fill", "none"), "stroke": element.get("stroke", "none"),
                      "width": float(element.get("stroke-width", "0"))})
    return found


def render(svg: Path, size: int = 512, *, mono: bool = False, supersample: int = 4) -> Image.Image:
    """RGBA icon. ``mono`` drops the background and paints every glyph white on transparent."""
    big = size * supersample
    scale = big / GRID
    image = Image.new("RGBA", (big, big), (0, 0, 0, 0))
    draw = ImageDraw.Draw(image)
    for shape in shapes(svg):
        if mono and shape["id"] == "background":
            continue
        for points, closed in subpaths(shape["d"]):
            scaled = [(px * scale, py * scale) for px, py in points]
            if shape["fill"] != "none":
                draw.polygon(scaled, fill="#ffffff" if mono else shape["fill"])
            if shape["stroke"] != "none":
                colour = "#ffffff" if mono else shape["stroke"]
                width = shape["width"] * scale
                line = scaled + scaled[:1] if closed else scaled
                draw.line(line, fill=colour, width=max(1, round(width)), joint="curve")
                for px, py in (line[0], line[-1]):
                    r = width / 2
                    draw.ellipse((px - r, py - r, px + r, py + r), fill=colour)
    return image.resize((size, size), Image.LANCZOS)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("svg", type=Path)
    parser.add_argument("png", type=Path)
    parser.add_argument("--size", type=int, default=512)
    parser.add_argument("--mono", action="store_true", help="theme-icon silhouette, no background")
    args = parser.parse_args()
    render(args.svg, args.size, mono=args.mono).save(args.png)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
