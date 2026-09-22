#!/usr/bin/env python3
"""260919 lane graph: lane_rules.yaml anchors snapped to the STL paint.

Usage: python lane_graph.py   (writes ../lane_graph.yaml)

Each road's coarse anchors are densified to SPACING_M, every point is moved
along its normal (within SNAP_SEARCH_M) to the maximum of the distance to the
nearest boundary line -- the point equidistant from both lines -- then
smoothed and resampled. Crosswalk bars are not boundary lines (extent under
LINE_MIN_EXTENT_M) so they neither pull the snap nor fail the check. The
ring is the rules' circle; a node is where a road's end direction meets it.
ROS-free and byte-deterministic.
"""

import importlib.util
import math
from pathlib import Path

import cv2
import numpy as np
import yaml

HERE = Path(__file__).resolve().parent
BUNDLE = HERE.parent
RULES = BUNDLE / "lane_rules.yaml"
OUT = BUNDLE / "lane_graph.yaml"

RASTER_M = 0.002
#: Crosswalk bars are 0.121 m; boundary lines run for metres.
LINE_MIN_EXTENT_M = 0.25
SNAP_SEARCH_M = 0.04
SPACING_M = 0.01
SMOOTH_POINTS = 5
#: Lane centre to nearest line paint: half-width 92.5 mm minus half a line
#: width 12.5 mm is 80 mm on a straight; bends and joints vary it.
CLEAR_MIN_M, CLEAR_MAX_M = 0.060, 0.100
#: No exemption: measured clearance holds within CLEAR_MIN_M/CLEAR_MAX_M of
#: every segment point, including at the ring nodes (2026-09-23 review).
NODE_EXEMPT_M = 0.0
DECIMALS = 4
RING_ORDER = (("ring_n", "NE", "NW"), ("ring_w", "NW", "SW"),
              ("ring_s", "SW", "SE"), ("ring_e", "SE", "NE"))


def _source_path():
    matches = sorted(BUNDLE.glob("260919*.STL"))
    if not matches:
        raise FileNotFoundError(
            f"no 260919*.STL file found in {BUNDLE} -- the map bundle is incomplete")
    return matches[0]


def load_scene():
    spec = importlib.util.spec_from_file_location("stl_scene", HERE / "stl_scene.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod.load_scene(_source_path())


class LineField:
    """Distance (m) from a floor point to the nearest boundary-line paint."""

    def __init__(self, scene):
        self.x0, self.y1 = -scene.size_x / 2.0, scene.size_y / 2.0
        w = int(math.ceil(scene.size_x / RASTER_M)) + 1
        h = int(math.ceil(scene.size_y / RASTER_M)) + 1
        paint = np.zeros((h, w), np.uint8)
        for tri in scene.lines:
            pts = np.array([[(v[0] - self.x0) / RASTER_M, (self.y1 - v[1]) / RASTER_M]
                            for v in tri])
            cv2.fillPoly(paint, [np.rint(pts * 16).astype(np.int32)], 255, shift=4)
        count, labels, stats, _ = cv2.connectedComponentsWithStats(paint, connectivity=8)
        keep = np.zeros(count, bool)
        for k in range(1, count):
            extent = max(stats[k, cv2.CC_STAT_WIDTH], stats[k, cv2.CC_STAT_HEIGHT]) * RASTER_M
            keep[k] = extent >= LINE_MIN_EXTENT_M
        lines = keep[labels]
        self.distance = cv2.distanceTransform(
            (~lines).astype(np.uint8), cv2.DIST_L2, cv2.DIST_MASK_PRECISE) * RASTER_M

    def at(self, x, y):
        col = int(round((x - self.x0) / RASTER_M))
        row = int(round((self.y1 - y) / RASTER_M))
        if not (0 <= row < self.distance.shape[0] and 0 <= col < self.distance.shape[1]):
            return 0.0
        return float(self.distance[row, col])


def densify(points, spacing):
    pts = np.asarray(points, float)
    out = [pts[0]]
    for a, b in zip(pts[:-1], pts[1:]):
        n = max(1, int(math.ceil(np.linalg.norm(b - a) / spacing)))
        out.extend(a + (b - a) * k / n for k in range(1, n + 1))
    return np.array(out)


def resample(points, spacing):
    pts = np.asarray(points, float)
    seg = np.linalg.norm(np.diff(pts, axis=0), axis=1)
    s = np.concatenate([[0.0], np.cumsum(seg)])
    n = max(2, int(round(s[-1] / spacing)) + 1)
    t = np.linspace(0.0, s[-1], n)
    return np.stack([np.interp(t, s, pts[:, 0]), np.interp(t, s, pts[:, 1])], axis=1)


def snap(points, field):
    pts = densify(points, SPACING_M)
    offsets = np.arange(-SNAP_SEARCH_M, SNAP_SEARCH_M + 1e-9, RASTER_M)
    out = [pts[0]]
    for i in range(1, len(pts) - 1):
        t = pts[i + 1] - pts[i - 1]
        t /= np.linalg.norm(t)
        normal = np.array([-t[1], t[0]])
        # Maximum clearance; ties go to the smallest move (flat ridge).
        best = max(offsets, key=lambda o: (round(field.at(*(pts[i] + o * normal)), 4), -abs(o)))
        out.append(pts[i] + best * normal)
    out.append(pts[-1])
    out = np.array(out)
    k = SMOOTH_POINTS // 2
    smooth = out.copy()
    for i in range(k, len(out) - k):
        smooth[i] = out[i - k:i + k + 1].mean(axis=0)
    return resample(smooth, SPACING_M)


def ring_meeting(end, before, centre, radius):
    """Where the road's end direction (before -> end) meets the ring circle."""
    d = np.asarray(end, float) - np.asarray(before, float)
    d /= np.linalg.norm(d)
    p = np.asarray(end, float) - np.asarray(centre, float)
    b = float(np.dot(d, p))
    c = float(np.dot(p, p)) - radius * radius
    if c <= 0:
        raise ValueError("road end anchor is inside or on the roundabout circle")
    disc = b * b - c
    if disc < 0:
        raise ValueError("road end direction misses the roundabout")
    t = -b - math.sqrt(disc)
    if t < 0:
        raise ValueError("road end direction meets the roundabout behind the anchor")
    return np.asarray(end, float) + t * d


def _angle(point, centre):
    return math.atan2(point[1] - centre[1], point[0] - centre[0])


def arc(centre, radius, a0, a1):
    """CCW arc from angle a0 to a1 at SPACING_M."""
    while a1 <= a0:
        a1 += 2 * math.pi
    n = max(2, int(round(radius * (a1 - a0) / SPACING_M)) + 1)
    a = np.linspace(a0, a1, n)
    return np.stack([centre[0] + radius * np.cos(a), centre[1] + radius * np.sin(a)], axis=1)


def _length(points):
    return float(np.sum(np.linalg.norm(np.diff(np.asarray(points), axis=0), axis=1)))


def _round(points):
    return [[round(float(x), DECIMALS), round(float(y), DECIMALS)] for x, y in points]


def build(rules_path=RULES):
    rules = yaml.safe_load(Path(rules_path).read_text(encoding="utf-8"))
    ring = rules["roundabout"]
    if ring["direction"] != "ccw":
        raise ValueError("only a ccw roundabout is modelled")
    centre, radius = np.array(ring["centre"], float), float(ring["radius"])
    scene = load_scene()
    field = LineField(scene)
    nodes, segments = {}, {}
    ends = {"west": ("SW", "NW"), "east": ("NE", "SE")}
    for name, road in rules["roads"].items():
        anchors = np.array(road["anchors"], float)
        start = ring_meeting(anchors[0], anchors[1], centre, radius)
        end = ring_meeting(anchors[-1], anchors[-2], centre, radius)
        # Both nodes are pinned points in the input: snap() never moves
        # pts[0]/pts[-1], and densify() spaces the node-to-anchor run at
        # SPACING_M just like every other run, so the whole road is
        # uniformly sampled with no leftover raw-anchor jump at either end.
        points = snap(np.vstack([[start], anchors, [end]]), field)
        a, b = ends[name]
        nodes[a], nodes[b] = start, end
        segments[name] = {"from": a, "to": b,
                          "directions": ["forward", "reverse"] if road["two_way"] else ["forward"],
                          "points": points}
    for name, a, b in RING_ORDER:
        points = arc(centre, radius, _angle(nodes[a], centre), _angle(nodes[b], centre))
        points[0], points[-1] = nodes[a], nodes[b]
        segments[name] = {"from": a, "to": b, "directions": ["forward"], "points": points}
    park = rules["parking"]
    spur = resample([park["entry"], park["spot"][:2]], SPACING_M)
    graph = {
        "source_sha256": scene.source_sha256,
        "roundabout": {"centre": _round([centre])[0], "radius": round(radius, DECIMALS),
                       "direction": "ccw"},
        "nodes": {k: _round([v])[0] for k, v in sorted(nodes.items())},
        "segments": {},
        "parking": {"road": park["road"], "spot": [round(float(v), DECIMALS) for v in park["spot"]],
                    "points": _round(spur), "length_m": round(_length(spur), DECIMALS)},
    }
    for name in sorted(segments):
        seg = segments[name]
        graph["segments"][name] = {"from": seg["from"], "to": seg["to"],
                                   "directions": seg["directions"],
                                   "length_m": round(_length(seg["points"]), DECIMALS),
                                   "points": _round(seg["points"])}
    return graph


def clearance_violations(graph, field):
    nodes = [np.array(v) for v in graph["nodes"].values()]
    bad = []
    for name, seg in graph["segments"].items():
        for x, y in seg["points"]:
            if min(math.dist((x, y), n) for n in nodes) <= NODE_EXEMPT_M:
                continue
            clear = field.at(x, y)
            if not CLEAR_MIN_M <= clear <= CLEAR_MAX_M:
                bad.append((name, x, y, round(clear, 4)))
    return bad


def write(graph, path=OUT):
    text = yaml.safe_dump(graph, sort_keys=True, default_flow_style=None, width=100)
    Path(path).write_text("# Generated by scripts/lane_graph.py from lane_rules.yaml. Do not edit.\n"
                          + text, encoding="utf-8", newline="\n")


if __name__ == "__main__":
    write(build())
