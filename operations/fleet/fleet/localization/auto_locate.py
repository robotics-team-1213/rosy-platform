"""D-989: fit a robot's SLAM map to the site map from the camera's LED-confirmed track.

Pure: numbers in, a verdict out. Each sample pairs the robot's own map pose with its D-472 confirmed
track position. Two ways reach a transform (site = R * slam + t), and a person pins neither:

- ``span``: pairs at least MIN_SPAN_M apart, solved as a rigid fit (no scale, no mirror).
- ``peer_heading``: a standing robot's lidar objects toward other confirmed robots give its heading
  in the site frame, so one position is enough. Only an object at the camera's predicted distance
  counts, and two candidates for one peer make that peer no evidence.

A later sample that disagrees over MAX_DISAGREE_M / MAX_DISAGREE_DEG (the map pose max_jump values)
latches DEGRADED until the camera, either map or the session changes. Nothing is ever corrected
silently: a swapped identity or a moved camera ends the fit. Missing or stale input reads UNKNOWN.

The transform relates two fixed maps, so it outlives the camera session: ALIGNED lasts VALID_S after
the last camera sample. Nothing here moves a robot or changes a limit. ``anchor_sample`` offers it to
map pose, which takes it only for a robot in ``fleet.map_pose.auto_locate_robots`` (D-989).
"""

from __future__ import annotations

import math
from collections import deque
from dataclasses import dataclass
from typing import Mapping, Optional, Sequence

from rosy.world.state.projections.map_pose import odom_from_snapshot

from fleet.localization import cues, service_logic, trust

UNKNOWN, ALIGNED, DEGRADED = "UNKNOWN", "ALIGNED", "DEGRADED"

MAX_DISAGREE_M = 0.15
MAX_DISAGREE_DEG = 20.0
#: Provisional: at about 5 cm camera error this keeps the fit's yaw within about 6 deg. Measure on site.
MIN_SPAN_M = 0.5
#: A robot moved less than this adds no new pair.
MIN_STEP_M = 0.05
MAX_PAIRS = 32
#: Camera track older than this is not paired with the robot's current pose.
PAIR_FRESH_S = 0.5
#: After the last camera sample the transform is no longer reported. Provisional: map drift is unmeasured.
VALID_S = 900.0
#: A peer's lidar return is on its near side, so its range reads short of the camera's centre distance.
PEER_RANGE_TOL_M = 0.12
#: Closer than this, camera error alone swings the bearing past the disagreement limit.
MIN_PEER_DIST_M = 0.3


@dataclass(frozen=True)
class Fit:
    yaw: float
    tx: float
    ty: float
    residual_max_m: float
    span_m: float
    evidence: str

    def site_xy(self, x: float, y: float) -> tuple[float, float]:
        c, s = math.cos(self.yaw), math.sin(self.yaw)
        return c * x - s * y + self.tx, s * x + c * y + self.ty


def fit_rigid(pairs: Sequence[tuple[tuple[float, float], tuple[float, float]]]) -> Optional[Fit]:
    """Least squares site = R * slam + t over (slam, site) pairs; None below two distinct points."""
    if len(pairs) < 2:
        return None
    ax = sum(p[0][0] for p in pairs) / len(pairs)
    ay = sum(p[0][1] for p in pairs) / len(pairs)
    bx = sum(p[1][0] for p in pairs) / len(pairs)
    by = sum(p[1][1] for p in pairs) / len(pairs)
    dot = cross = 0.0
    for (sx, sy), (mx, my) in pairs:
        dot += (sx - ax) * (mx - bx) + (sy - ay) * (my - by)
        cross += (sx - ax) * (my - by) - (sy - ay) * (mx - bx)
    if dot == 0.0 and cross == 0.0:
        return None
    yaw = math.atan2(cross, dot)
    c, s = math.cos(yaw), math.sin(yaw)
    fit = Fit(yaw, bx - (c * ax - s * ay), by - (s * ax + c * ay), 0.0, _span([p[0] for p in pairs]), "span")
    residual = max(math.dist(fit.site_xy(*slam), site) for slam, site in pairs)
    return Fit(fit.yaw, fit.tx, fit.ty, residual, fit.span_m, "span")


def _span(points: Sequence[tuple[float, float]]) -> float:
    return max((math.dist(a, b) for i, a in enumerate(points) for b in points[i + 1:]), default=0.0)


def heading_from_peers(objects: Sequence, own: tuple[float, float],
                       peers: Mapping[str, tuple[float, float]]) -> tuple[Optional[float], Optional[str]]:
    """(the robot's site-frame yaw, None), or (None, reason) when the lidar does not settle it.

    ``objects`` are base_link points with .x/.y. A peer counts only with exactly one object at its
    camera distance, and every counted peer must agree."""
    votes = []
    for peer in peers.values():
        distance = math.dist(own, peer)
        if distance < MIN_PEER_DIST_M:
            continue
        near = [o for o in objects if abs(math.hypot(o.x, o.y) - distance) <= PEER_RANGE_TOL_M]
        if len(near) == 1:
            votes.append(math.atan2(peer[1] - own[1], peer[0] - own[0]) - math.atan2(near[0].y, near[0].x))
    if not votes:
        return None, "NO_PEER_EVIDENCE"
    if any(abs(math.degrees(cues.wrap(v - votes[0]))) > MAX_DISAGREE_DEG for v in votes):
        return None, "PEERS_DISAGREE"
    return cues.wrap(math.atan2(sum(math.sin(v) for v in votes), sum(math.cos(v) for v in votes))), None


def _robot_pose(state: Optional[Mapping]) -> Optional[tuple[float, float, float]]:
    try:
        pose = (state or {})["pose"]
        found = float(pose["x"]), float(pose["y"]), float(pose["yaw"])
    except (KeyError, TypeError, ValueError):
        return None
    return found if all(math.isfinite(v) for v in found) else None


class AlignmentTracker:
    """One robot's fit over one (robot map, site map, camera revision) identity."""

    def __init__(self, robot_id: str) -> None:
        self.robot_id = robot_id
        self._key: Optional[tuple] = None
        self._reset()

    def _reset(self) -> None:
        self._pairs: deque = deque(maxlen=MAX_PAIRS)
        self._fit: Optional[Fit] = None
        self._peer_yaw: Optional[float] = None
        self._degraded: Optional[str] = None
        self._reason = "NO_SAMPLE"
        self._seen_at: Optional[float] = None
        self._objects_seen: Optional[tuple] = None

    def observe(self, now: float, track: Mapping, state: Optional[Mapping],
                peers: Mapping[str, tuple[float, float]]) -> None:
        """One tick. ``track`` is IdentityService.confirmed_track_pose; ``peers`` the others' positions."""
        if track.get("state") != "CONFIRMED":
            self._reason = track.get("reason") or "NO_CAMERA_TRACK"
            return
        age = track.get("age_s")
        if not isinstance(age, (int, float)) or not 0.0 <= age <= PAIR_FRESH_S:
            self._reason = "STALE_CAMERA_TRACK"
            return
        status, pose = trust.status_of(state), _robot_pose(state)
        if status is None or pose is None or status.state.value != "LOCALIZED" or status.pose_frame.value != "map":
            self._reason = "ROBOT_NOT_LOCALIZED"
            return
        robot_map = (state or {}).get("map_id")
        if not isinstance(robot_map, str) or not robot_map:
            self._reason = "ROBOT_MAP_UNKNOWN"
            return
        key = (robot_map, track.get("map_id"), track.get("calibration_revision"), track.get("source_id"))
        if key != self._key:
            self._key = key
            self._reset()
        if self._degraded is not None:
            return
        site, slam = (float(track["x"]), float(track["y"])), pose[:2]
        self._seen_at, self._reason = now, "NOT_ENOUGH_SPREAD"
        if self._fit is not None and math.dist(self._fit.site_xy(*slam), site) > MAX_DISAGREE_M:
            self._degraded = "CAMERA_DISAGREES"
            return
        self._add_pair(slam, site)
        peer_yaw = self._peer_heading(now, status, site, peers)
        if peer_yaw is not None:
            self._peer_yaw = cues.wrap(peer_yaw - pose[2])
        self._refit(slam, site)
        if self._degraded is None and self._fit is not None and self._fit.evidence == "span":
            self._check_peers(now, status, slam, pose[2], peers)

    def _add_pair(self, slam: tuple[float, float], site: tuple[float, float]) -> None:
        if self._pairs and math.dist(self._pairs[-1][0], slam) < MIN_STEP_M:
            self._pairs[-1] = (slam, site)
        else:
            self._pairs.append((slam, site))

    def _fresh_objects(self, now: float, status) -> Sequence:
        if status.objects_stamp is None:
            return ()
        if self._objects_seen is None or self._objects_seen[0] != status.objects_stamp:
            self._objects_seen = (status.objects_stamp, now)
        return status.unmapped_objects if now - self._objects_seen[1] <= service_logic.REPORT_FRESH_S else ()

    def _peer_heading(self, now: float, status, site: tuple[float, float],
                      peers: Mapping[str, tuple[float, float]]) -> Optional[float]:
        yaw, reason = heading_from_peers(self._fresh_objects(now, status), site, peers)
        if reason == "PEERS_DISAGREE":
            self._degraded = reason
        return yaw

    def _refit(self, slam: tuple[float, float], site: tuple[float, float]) -> None:
        if self._degraded is not None:
            return
        rigid = fit_rigid(list(self._pairs))
        if rigid is not None and rigid.span_m >= MIN_SPAN_M:
            if rigid.residual_max_m > MAX_DISAGREE_M:
                self._degraded = "FIT_RESIDUAL"
            elif (self._peer_yaw is not None
                  and abs(math.degrees(cues.wrap(rigid.yaw - self._peer_yaw))) > MAX_DISAGREE_DEG):
                self._degraded = "PEER_HEADING_DISAGREES"
            else:
                self._fit = rigid
        elif self._peer_yaw is not None:
            c, s = math.cos(self._peer_yaw), math.sin(self._peer_yaw)
            self._fit = Fit(self._peer_yaw, site[0] - (c * slam[0] - s * slam[1]),
                            site[1] - (s * slam[0] + c * slam[1]), 0.0, 0.0, "peer_heading")

    def _check_peers(self, now: float, status, slam: tuple[float, float], yaw: float,
                     peers: Mapping[str, tuple[float, float]]) -> None:
        """A peer seen at its 180-degree twin means the fit is the wrong way round."""
        placed = (*self._fit.site_xy(*slam), cues.wrap(yaw + self._fit.yaw))
        targets = {rid: (*xy, 0.0) for rid, xy in peers.items()}
        seen = service_logic.peer_observations(self._fresh_objects(now, status), placed, targets)
        for rid, observed in seen.items():
            if math.dist(observed[:2], targets[rid][:2]) > service_logic.PEER_EVIDENCE_M:
                self._degraded = "PEER_SEEN_AT_MIRROR"

    def view(self, now: float) -> dict:
        base = {"robot_id": self.robot_id, "use": "observation-only", "state": UNKNOWN, "reason": self._reason,
                "robot_map_id": None, "site_map_id": None, "calibration_revision": None, "transform": None,
                "evidence": None, "residual_max_m": None, "span_m": None, "pairs": len(self._pairs),
                "valid_left_s": None,
                "age_s": None if self._seen_at is None else round(now - self._seen_at, 3)}
        if self._key is not None:
            base.update(robot_map_id=self._key[0], site_map_id=self._key[1], calibration_revision=self._key[2])
        if self._degraded is not None:
            return base | {"state": DEGRADED, "reason": self._degraded}
        if self._fit is None:
            return base
        if self._seen_at is None or not 0.0 <= now - self._seen_at <= VALID_S:
            return base | {"reason": "EXPIRED"}
        fit = self._fit
        return base | {"state": ALIGNED, "reason": None, "evidence": fit.evidence,
                       "transform": {"yaw": round(fit.yaw, 4), "tx": round(fit.tx, 4), "ty": round(fit.ty, 4)},
                       "residual_max_m": round(fit.residual_max_m, 4), "span_m": round(fit.span_m, 3),
                       "valid_left_s": round(VALID_S - (now - self._seen_at), 1)}

    @property
    def source_id(self) -> Optional[str]:
        return None if self._key is None else self._key[3]

    def anchor_sample(self, now: float, state: Optional[Mapping],
                      revision: Optional[str]) -> tuple[Optional[tuple], Optional[str]]:
        """((x, y, yaw, at, site_map_id), None) from this robot state, or (None, why not)."""
        view = self.view(now)
        if view["state"] != ALIGNED:
            return None, view["reason"]
        if revision != view["calibration_revision"]:
            return None, "CALIBRATION_CHANGED"
        status, pose = trust.status_of(state), _robot_pose(state)
        if status is None or pose is None or status.state.value != "LOCALIZED" or status.pose_frame.value != "map":
            return None, "ROBOT_NOT_LOCALIZED"
        if (state or {}).get("map_id") != view["robot_map_id"]:
            return None, "ROBOT_MAP_CHANGED"
        odom = odom_from_snapshot(state)
        if odom is None:
            return None, "ODOM_UNKNOWN"
        # shortcut: the snapshot's map pose and odom are not read atomically; D-984 fixes that in CORE when it lands.
        x, y = self._fit.site_xy(*pose[:2])
        return (x, y, cues.wrap(pose[2] + self._fit.yaw), odom.stamp, view["site_map_id"]), None
