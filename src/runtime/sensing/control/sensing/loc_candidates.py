"""Subject: every map/scan pose hypothesis worth arbitrating (D-395).

`MapAgreement.global_match` answers "is there exactly one pose?" and refuses on
the 180-degree symmetric map_v2_fleet track. Arbitration needs the opposite:
every distinct base pose the scan supports, each with its own fit, so Fleet can
tell the true pose from its mirror with cues the robot does not hold. Nothing
here authorizes motion; a decision still passes the 3 s check (loc_verify).

Poses are base_link in the map frame unless a name says sensor. The lidar is
mounted rotated (scan 0 is the rear), so the conversion goes through `Mount`.

Cost: the global search scales with map cells x 72 headings (one 4 cm seed grid
per 5 deg), on top of one full-map `clear_poses`. The slot search checks only
the slot boxes. Callers that run both compute the clear mask once and pass it as
`clear=`. Requirement for Phase 2: measure the global search on the Pi with the
deployed map, and bound it with a pooled grid or a time budget before it runs
on the device.
"""
from __future__ import annotations

import math
from dataclasses import dataclass

import numpy as np

from .localization import apart, valid_beams, wrap

#: D-395 §5: a candidate within 10 cm / 20 deg of a slot earns the slot prior;
#: the same box bounds where a robot "placed on the square" can really stand.
SLOT_XY_M = .10
SLOT_YAW_RAD = math.radians(20.)
SLOT_OFFSETS = np.array(np.meshgrid(
    np.arange(-SLOT_XY_M, SLOT_XY_M + 1e-9, .02), np.arange(-SLOT_XY_M, SLOT_XY_M + 1e-9, .02),
    np.radians(np.arange(-20., 20.1, 4.)), indexing='ij')).reshape(3, -1).T
#: Final stage for distinct global candidates only: +-3 cm in 1 cm, +-3 deg in 0.5 deg (637 poses).
FINE_OFFSETS = np.array(np.meshgrid(
    np.arange(-.03, .031, .01), np.arange(-.03, .031, .01), np.radians(np.arange(-3., 3.1, .5)),
    indexing='ij')).reshape(3, -1).T


@dataclass(frozen=True)
class Mount:
    """Lidar pose in base_link: metres and radians (nominal yaw is pi, D-397)."""
    x: float
    y: float
    yaw: float


@dataclass(frozen=True)
class PoseCandidate:
    """One base_link pose hypothesis in the map frame and how well the scan fits it."""
    x: float
    y: float
    yaw: float
    scan_fit: float
    origin: str  # 'global' or 'slot:<square id>'


@dataclass(frozen=True)
class ReferenceSquare:
    """A floor square from lane_rules.yaml; robots placed on it face along `axis_rad`, either way."""
    id: str
    x: float
    y: float
    axis_rad: float


def reference_squares(rules):
    """Squares from a parsed lane_rules.yaml mapping; [] when the map has none.

    A malformed root or square raises ValueError naming the square."""
    if rules is None:
        return []
    if not isinstance(rules, dict):
        raise ValueError('lane rules must be a mapping to hold reference_squares')
    out = []
    for s in rules.get('reference_squares') or ():
        if not isinstance(s, dict):
            raise ValueError(f'reference square {s!r} must be a mapping')
        try:
            out.append(ReferenceSquare(str(s['id']), float(s['centre'][0]), float(s['centre'][1]),
                                       math.radians(float(s['heading_axis_deg']))))
        except (KeyError, IndexError, TypeError, ValueError) as exc:
            raise ValueError(f'reference square {s.get("id")!r} needs id, centre [x, y] and '
                             f'heading_axis_deg: {exc!r}') from exc
    return out


def base_from_sensor(sensor, mount):
    yaw = wrap(sensor[2] - mount.yaw)
    c, s = math.cos(yaw), math.sin(yaw)
    return (float(sensor[0] - c*mount.x + s*mount.y), float(sensor[1] - s*mount.x - c*mount.y), yaw)


def sensor_from_base(base, mount):
    c, s = math.cos(base[2]), math.sin(base[2])
    return (base[0] + c*mount.x - s*mount.y, base[1] + s*mount.x + c*mount.y, wrap(base[2] + mount.yaw))


def distinct(results, minimum_fit=.9, keep_within=.05, limit=4):
    """(sensor_pose, agreement) for each distinct hypothesis near the best one.

    `results` is `MapAgreement.global_results` output, best first. A pose is
    kept when its scan agreement reaches `minimum_fit` and its combined score is
    within `keep_within` of the best; the mirror on a symmetric map is both."""
    if not results:
        return []
    best = results[0][0]
    picked = []
    for combined, agreement, pose in results:
        if combined < best - keep_within:
            break  # best first: nothing later is inside the window
        if agreement < minimum_fit:
            continue
        if all(apart(pose, other) for other, _ in picked):
            picked.append((pose, float(agreement)))
        if len(picked) >= limit:
            break
    return picked


def global_candidates(field, ranges, angles, radius, mount, minimum_fit=.9, keep_within=.05, limit=4,
                      clear=None, fine_scan=None):
    """Every distinct global pose; [] when the scan or the map cannot support one.

    `clear` is an optional precomputed `field.clear_poses(radius)` mask.
    `fine_scan`: the full-resolution (ranges, angles). When given, each distinct
    pose is refined once more by FINE_OFFSETS on it and re-scored (S1 re-run R3:
    a 1 deg refinement on a strided scan left a candidate 2-3 deg off)."""
    if fine_scan is not None and clear is None:
        clear = field.clear_poses(radius)
    results, _ = field.global_results(ranges, angles, radius, clear=clear)
    picked = distinct(results, minimum_fit, keep_within, limit)
    if fine_scan is not None:
        fine_ranges, fine_angles = valid_beams(*fine_scan)
        picked = [_fine(field, pose, fit, fine_ranges, fine_angles, clear) for pose, fit in picked]
    return [PoseCandidate(*base_from_sensor(pose, mount), scan_fit=fit, origin='global')
            for pose, fit in picked]


def _fine(field, pose, fit, ranges, angles, clear):
    """The best FINE_OFFSETS refinement of one sensor pose, or the pose itself when none qualifies."""
    if len(ranges) < 30:
        return pose, fit
    refined = field.refine([pose], ranges, angles, clear, FINE_OFFSETS)
    if not refined:
        return pose, fit
    _, agreement, best = max(refined, key=lambda item: item[0])
    return best, float(agreement)


def slot_candidates(field, squares, ranges, angles, radius, mount, minimum_fit=.9, clear=None):
    """Axis and axis+180 at each square (D-395 rev. 2), refined within the slot box.

    The square is off-centre along its axis, so the front and rear walls differ
    and the scan fit keeps one heading; a blocked view can keep both or neither.
    `clear` is an optional precomputed `field.clear_poses(radius)` mask; without
    it only the cells inside the slot boxes get a footprint check."""
    ranges, angles = valid_beams(ranges, angles)
    if len(ranges) < 30 or not squares:
        return []
    seeds = [(square, np.array(sensor_from_base((square.x, square.y, wrap(yaw)), mount)))
             for square in squares for yaw in (square.axis_rad, square.axis_rad + math.pi)]
    if clear is None:
        clear = np.zeros(field.grid.shape, dtype=bool)
        h, w = clear.shape
        for _, seed in seeds:
            cells = np.floor((seed[:2] + SLOT_OFFSETS[:, :2] - field.origin) / field.resolution).astype(int)
            for ix, iy in np.unique(cells, axis=0):
                if 0 <= ix < w and 0 <= iy < h and not clear[iy, ix]:
                    clear[iy, ix] = field.footprint_clear(field.origin[0] + (ix + .5) * field.resolution,
                                                          field.origin[1] + (iy + .5) * field.resolution, radius)
    out = []
    for square, seed in seeds:
        refined = field.refine([seed], ranges, angles, clear, SLOT_OFFSETS)
        best = max((r for r in refined if r[1] >= minimum_fit), key=lambda item: item[0], default=None)
        if best is not None:
            out.append(PoseCandidate(*base_from_sensor(best[2], mount), scan_fit=float(best[1]),
                                     origin='slot:' + square.id))
    return out


def merge(slot, global_):
    """Slot candidates first, then global ones that are not the same hypothesis."""
    out = list(slot)
    for candidate in global_:
        pose = (candidate.x, candidate.y, candidate.yaw)
        if all(apart(pose, (o.x, o.y, o.yaw)) for o in out):
            out.append(candidate)
    return out
