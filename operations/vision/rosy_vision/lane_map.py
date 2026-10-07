"""Calibrated camera paint -> centreline site-map draft. No motion or activation.

Run ``python -m rosy_vision.lane_map --help``. White boundary pairs and a measured
lane width are required; occluded or unpaired paint is not bridged.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
from pathlib import Path
import re
import ssl
import sys
import urllib.parse
import urllib.request

import cv2
import numpy as np

from rosy_vision.map_register import _line_mask


def _thin(mask):
    """Zhang-Suen thinning, using numpy already required by Vision."""
    pixels = np.pad(mask != 0, 1)
    while True:
        changed = False
        for step in (0, 1):
            p = [pixels[:-2, 1:-1], pixels[:-2, 2:], pixels[1:-1, 2:],
                 pixels[2:, 2:], pixels[2:, 1:-1], pixels[2:, :-2],
                 pixels[1:-1, :-2], pixels[:-2, :-2]]
            count = sum(v.astype(np.uint8) for v in p)
            transitions = sum((~a & b).astype(np.uint8) for a, b in zip(p, p[1:] + p[:1]))
            first = p[0] & p[2] & p[4 if step == 0 else 6]
            second = p[2 if step == 0 else 0] & p[4] & p[6]
            remove = pixels[1:-1, 1:-1] & (count >= 2) & (count <= 6) \
                & (transitions == 1) & ~first & ~second
            changed |= bool(remove.any())
            pixels[1:-1, 1:-1][remove] = False
        if not changed:
            return pixels[1:-1, 1:-1]


def _graph(skeleton, origin, resolution, lane_width, map_id):
    pixels = set(zip(*np.nonzero(skeleton)))

    def neighbours(p):
        y, x = p
        return sorted((y + dy, x + dx) for dy in (-1, 0, 1) for dx in (-1, 0, 1)
                      if (dy or dx) and (y + dy, x + dx) in pixels
                      and not (dy and dx and ((y + dy, x) in pixels or (y, x + dx) in pixels)))

    # Remove short terminal branches before classifying junctions. Merely dropping
    # their final edges would leave false junctions splitting an otherwise valid road.
    while pixels:
        links = {p: neighbours(p) for p in pixels}
        remove = set()
        for start in sorted(p for p in pixels if len(links[p]) == 1):
            path, previous, current, length = [start], start, links[start][0], 0.0
            while True:
                length += math.dist(previous, current) * resolution
                if len(links[current]) != 2 or length > max(0.10, lane_width):
                    break
                path.append(current)
                previous, current = current, next(p for p in links[current] if p != previous)
            if length <= max(0.10, lane_width):
                remove.update(path)
        if not remove:
            break
        pixels -= remove
    links = {p: neighbours(p) for p in pixels}
    node_pixels = {p for p in pixels if len(links[p]) != 2}
    # A skeletonized junction occupies several pixels. Collapse its short *observed*
    # links into one place, never endpoints separated by a missing/occluded section.
    for start in sorted(node_pixels):
        for nxt in links[start]:
            path, previous, current, length = [], start, nxt, 0.0
            while current not in node_pixels:
                length += math.dist(previous, current) * resolution
                if length > 0.05 or len(links[current]) != 2:
                    break
                path.append(current)
                previous, current = current, next(p for p in links[current] if p != previous)
            if current in node_pixels and length + math.dist(previous, current) * resolution <= 0.05:
                node_pixels.update(path)
    # Closed rings have no endpoints: split each into three reachable places.
    unseen = set(pixels)
    while unseen:
        seed = min(unseen)
        stack, component = [seed], set()
        while stack:
            p = stack.pop()
            if p not in unseen:
                continue
            unseen.remove(p)
            component.add(p)
            stack.extend(links[p])
        if component and not component & node_pixels:
            path, visited, previous, current = [], set(), None, seed
            while current not in visited:
                path.append(current)
                visited.add(current)
                nxt = next(p for p in links[current] if p != previous)
                previous, current = current, nxt
            node_pixels.update(path[len(path) * i // 3] for i in range(3))
    owners, positions = {}, []
    while node_pixels:
        seed = min(node_pixels)
        stack, group = [seed], []
        while stack:
            p = stack.pop()
            if p not in node_pixels:
                continue
            node_pixels.remove(p)
            owners[p] = len(positions)
            group.append(p)
            stack.extend(links[p])
        positions.append(np.mean(group, axis=0))
    if len(positions) > 500:
        raise ValueError("too many lane junctions; check paint noise and calibration")
    walked, edges = set(), []

    def xy(p):
        return [round(origin[0] + float(p[1]) * resolution, 4),
                round(origin[1] - float(p[0]) * resolution, 4)]

    def add_edge(path, first, last):
        points = np.array([xy(p) for p in path], np.float32)
        points[0], points[-1] = xy(positions[first]), xy(positions[last])
        points = cv2.approxPolyDP(points, resolution * 1.5, False).reshape(-1, 2)
        if sum(np.linalg.norm(np.diff(points, axis=0), axis=1)) <= max(0.10, lane_width):
            return
        if np.linalg.norm(points[0] - points[-1]) <= 0.05:
            return
        edges.append({"id": f"lane_{len(edges)}", "from": f"p{first}", "to": f"p{last}",
                      "polyline": [[round(float(v), 4) for v in p] for p in points],
                      "direction": "two_way", "width_m": lane_width,
                      "speed_cap_mps": 0.03, "drive_mode": "lane"})

    for start in sorted(owners):
        for nxt in links[start]:
            if nxt in owners or frozenset((start, nxt)) in walked:
                continue
            path, previous, current = [start], start, nxt
            while True:
                walked.add(frozenset((previous, current)))
                path.append(current)
                if current in owners:
                    break
                choices = [p for p in links[current] if p != previous]
                if len(choices) != 1:
                    break
                previous, current = current, choices[0]
            if current not in owners:
                continue
            first, last = owners[start], owners[current]
            if first == last:  # an observed loop attached to a junction
                a, b = len(path) // 3, len(path) * 2 // 3
                middle = len(positions)
                positions.extend([np.asarray(path[a]), np.asarray(path[b])])
                add_edge(path[:a + 1], first, middle)
                add_edge(path[a:b + 1], middle, middle + 1)
                add_edge(path[b:], middle + 1, last)
            else:
                add_edge(path, first, last)
    if not edges or len(edges) > 1000:
        raise ValueError("no usable lane boundary pairs, or too many lanes")
    used = {edge[key] for edge in edges for key in ("from", "to")}
    places = [{"id": f"p{i}", "name": f"p{i}", "x": xy(p)[0], "y": xy(p)[1],
               "kind": "junction"} for i, p in enumerate(positions) if f"p{i}" in used]
    if len(places) > 500 or sum(len(edge["polyline"]) for edge in edges) > 20_000:
        raise ValueError("generated lane map exceeds the site-map limits")
    # Nearby separate ends are ambiguous, not a reason to silently join roads.
    for i, place in enumerate(places):
        if any(math.dist((place["x"], place["y"]), (q["x"], q["y"])) <= 0.05 for q in places[i + 1:]):
            raise ValueError("ambiguous nearby lane ends; improve the camera view")
    return {"schema": "rosy.site_map/1", "map_id": map_id, "places": places, "edges": edges,
            "turn_bans": []}


def generate_map(image, calibration, *, lane_width_m, map_id="camera"):
    """Extract only observed paired white boundaries in a calibrated, metric plane."""
    # ponytail: white paint and one measured width; add a trained segmenter for other markings.
    if not re.fullmatch(r"[A-Za-z0-9_.-]{1,64}", map_id):
        raise ValueError("invalid map_id")
    if not math.isfinite(lane_width_m) or not 0.05 <= lane_width_m <= 2:
        raise ValueError("lane width must be measured, between 0.05 and 2 m")
    if image is None or image.ndim != 3 or image.shape[2] != 3 or not 64 <= min(image.shape[:2]) \
            or max(image.shape[:2]) > 8192:
        raise ValueError("expected a BGR image between 64 and 8192 pixels")
    height, width = image.shape[:2]
    if not isinstance(calibration, dict) or calibration.get("image_size") != [width, height]:
        raise ValueError("calibration image_size must match this camera frame exactly")
    homography = np.asarray(calibration.get("image_to_map"), dtype=np.float64)
    if homography.shape != (3, 3) or not np.isfinite(homography).all() \
            or abs(np.linalg.det(homography)) < 1e-12:
        raise ValueError("invalid metric image_to_map homography")
    corners = np.array([[0, 0, 1], [width - 1, 0, 1], [width - 1, height - 1, 1],
                        [0, height - 1, 1]], np.float64) @ homography.T
    if np.any(np.abs(corners[:, 2]) < 1e-9) or not (np.all(corners[:, 2] > 0) or np.all(corners[:, 2] < 0)):
        raise ValueError("calibration horizon crosses the image")
    corners = corners[:, :2] / corners[:, 2:]
    lo, hi = corners.min(axis=0), corners.max(axis=0)
    bounds = calibration.get("bounds_m")
    if bounds is not None:
        if not isinstance(bounds, dict) or set(bounds) != {"min_x", "max_x", "min_y", "max_y"}:
            raise ValueError("bounds_m needs min_x, max_x, min_y and max_y")
        limits = np.array([bounds[k] for k in ("min_x", "min_y", "max_x", "max_y")], np.float64)
        if not np.isfinite(limits).all() or np.any(limits[:2] >= limits[2:]):
            raise ValueError("invalid measured map bounds")
        lo, hi = np.maximum(lo, limits[:2]), np.minimum(hi, limits[2:])
    extent = hi - lo
    if not np.isfinite(extent).all() or min(extent) < 0.1 or max(extent) > 20:
        raise ValueError("calibrated view must span 0.1 to 20 m")
    resolution = max(0.005, float(max(extent)) / 1000)
    if lane_width_m / resolution < 8:
        raise ValueError("camera map resolution is too coarse for this lane width")
    raster = np.array([[1 / resolution, 0, -lo[0] / resolution],
                       [0, -1 / resolution, hi[1] / resolution], [0, 0, 1]])
    size = tuple((np.ceil(extent / resolution).astype(int) + 1).tolist())
    # Resizing before the existing white-paint detector keeps its local contrast window
    # consistent with the map registrar, including high-resolution phone images.
    scale = min(1.0, 640 / max(width, height))
    small = cv2.resize(image, (round(width * scale), round(height * scale)), interpolation=cv2.INTER_AREA)
    sx, sy = small.shape[1] / width, small.shape[0] / height
    to_small = np.array([[sx, 0, (sx - 1) / 2], [0, sy, (sy - 1) / 2], [0, 0, 1]])
    paint = cv2.warpPerspective(_line_mask(small), raster @ homography @ np.linalg.inv(to_small),
                                size, flags=cv2.INTER_NEAREST)
    # Speckled carpet, robot highlights and short crosswalk bars are not lane borders.
    count, components, stats, _ = cv2.connectedComponentsWithStats(paint, connectivity=8)
    keep = np.zeros(count, np.uint8)
    for index in range(1, count):
        if max(stats[index, cv2.CC_STAT_WIDTH], stats[index, cv2.CC_STAT_HEIGHT]) * resolution >= lane_width_m * 1.5:
            keep[index] = 255
    paint = keep[components]
    visible = cv2.warpPerspective(np.ones((height, width), np.uint8), raster @ homography,
                                  size, flags=cv2.INTER_NEAREST) != 0
    if not np.any(paint):
        raise ValueError("no white lane paint observed")
    free = (paint == 0).astype(np.uint8)
    distance, labels = cv2.distanceTransformWithLabels(free, cv2.DIST_L2, 5, labelType=cv2.DIST_LABEL_PIXEL)
    py, px = np.nonzero(paint)
    nearest = np.zeros((int(labels.max()) + 1, 2), np.int32)
    nearest[labels[py, px]] = np.stack((py, px), axis=1)
    ys, xs = np.indices(paint.shape)
    boundary = nearest[labels]
    tolerance = max(1, round(lane_width_m * 0.1 / resolution))
    paint_band = cv2.dilate(paint, np.ones((2 * tolerance + 1, 2 * tolerance + 1), np.uint8))
    opposite = np.zeros(paint.shape, bool)
    dy, dx = ys - boundary[:, :, 0], xs - boundary[:, :, 1]
    # Junction corners fan out instead of remaining parallel. Require observed paint
    # on the opposite side within 45 degrees; never join across an unobserved gap.
    for angle in (-math.pi / 4, 0, math.pi / 4):
        for factor in (0.8, 1.0, 1.4):
            oy = np.rint(ys + factor * (math.cos(angle) * dy + math.sin(angle) * dx)).astype(int)
            ox = np.rint(xs + factor * (math.cos(angle) * dx - math.sin(angle) * dy)).astype(int)
            inside = (oy >= 0) & (oy < size[1]) & (ox >= 0) & (ox < size[0])
            opposite[inside] |= paint_band[oy[inside], ox[inside]] != 0
    corridor = visible & opposite & (distance * resolution >= lane_width_m * 0.35) \
        & (distance * resolution <= lane_width_m * 0.8)
    # Never let the edge of the camera coverage masquerade as a road boundary.
    observed_clearance = cv2.distanceTransform(np.pad(visible.astype(np.uint8), 1), cv2.DIST_L2, 5)[1:-1, 1:-1]
    corridor &= observed_clearance * resolution > lane_width_m / 2
    draft = _graph(_thin(corridor), (lo[0], hi[1]), resolution, lane_width_m, map_id)
    evidence = {"generator": "camera-lanes/1", "calibration": calibration,
                "lane_width_m": lane_width_m, "resolution_m": resolution,
                "paint_pixels": int(np.count_nonzero(paint)), "proposal_only": True,
                "warnings": ["Review road direction, junctions, obstacles and occlusions before activation."]}
    return draft, evidence


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        raise ValueError("camera frame redirects are not allowed")


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    source = parser.add_mutually_exclusive_group(required=True)
    source.add_argument("--image", type=Path, help="raw camera JPEG/PNG")
    source.add_argument("--frame-url", help="HTTPS Vision frame URL from a short-lived preview lease")
    parser.add_argument("--token-env", default="ROSY_VISION_LEASE")
    parser.add_argument("--ca", type=Path, help="trusted site CA for direct Vision reads")
    parser.add_argument("--calibration", type=Path, required=True, help="JSON image_size and metric image_to_map")
    parser.add_argument("--lane-width-m", type=float, required=True)
    parser.add_argument("--map-id", default="camera")
    parser.add_argument("--output", type=Path, required=True, help="Fleet site-map draft JSON; does not activate")
    args = parser.parse_args(argv)
    try:
        if args.frame_url:
            parsed = urllib.parse.urlsplit(args.frame_url)
            token = os.environ.get(args.token_env, "")
            if parsed.scheme != "https" or not parsed.hostname or parsed.username or parsed.password or not token:
                raise ValueError("direct camera read needs HTTPS and a preview lease in --token-env")
            opener = urllib.request.build_opener(_NoRedirect(), urllib.request.HTTPSHandler(
                context=ssl.create_default_context(cafile=str(args.ca) if args.ca else None)))
            with opener.open(urllib.request.Request(args.frame_url, headers={"Authorization": "Bearer " + token}),
                             timeout=10) as response:
                raw = response.read(8 * 1024 * 1024 + 1)
                age = float(response.headers.get("X-Frame-Age-Ms", "inf"))
                if not math.isfinite(age) or not 0 <= age <= 3000:
                    raise ValueError("camera frame freshness is unavailable or stale")
                if response.headers.get("X-Frame-Rectified") != "false":
                    raise ValueError("camera map needs the raw, unrectified Vision frame")
        else:
            if args.image.stat().st_size > 8 * 1024 * 1024:
                raise ValueError("camera image exceeds 8 MiB")
            raw = args.image.read_bytes()
        if len(raw) > 8 * 1024 * 1024:
            raise ValueError("camera image exceeds 8 MiB")
        image = cv2.imdecode(np.frombuffer(raw, np.uint8), cv2.IMREAD_COLOR)
        calibration = json.loads(args.calibration.read_text(encoding="utf-8-sig"))
        draft, evidence = generate_map(image, calibration, lane_width_m=args.lane_width_m, map_id=args.map_id)
        evidence["frame_sha256"] = hashlib.sha256(raw).hexdigest()
        # Refuse replacement: an existing operator draft is not expendable scratch.
        evidence_path = args.output.with_suffix(".evidence.json")
        if args.output.exists() or evidence_path.exists():
            raise ValueError("output exists; choose a new draft filename")
        with evidence_path.open("x", encoding="utf-8") as stream:
            json.dump(evidence, stream, indent=2, allow_nan=False)
        with args.output.open("x", encoding="utf-8") as stream:
            json.dump(draft, stream, indent=2, allow_nan=False)
        print(f"Created map draft: {len(draft['places'])} places, {len(draft['edges'])} lanes")
        return 0
    except ValueError as exc:
        print(f"Camera map generation rejected: {exc}", file=sys.stderr)
        return 2
    except (OSError, cv2.error):
        # Never print URL errors: exceptions may contain query credentials.
        print("Camera map generation failed; check frame, calibration, lane width and output path.", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
