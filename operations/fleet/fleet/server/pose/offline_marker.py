"""Short-lived, obstacle-only clearance for an unreachable enrolled peer (D-587, D-1010)."""
from copy import deepcopy
import logging
import math
import time

from rosy.world.state.projections.map_pose import STILL_PATH_M

from fleet.localization import trust
from fleet.localization.relative_search_prior import MAX_FRAME_AGE_S, pose3


# D-587 bounds sticker location, height/parallax and the calibrated floor fit at this site.
MARKER_ERROR_M = 0.10
#: A disconnected peer whose marker stayed within STILL_PATH_M this long is a parked obstacle,
#: seen at least STATIC_MIN_FRAMES times with no gap above STATIC_MAX_GAP_S.
STATIC_HOLD_S = 2.0
STATIC_MAX_GAP_S = 0.6
STATIC_MIN_FRAMES = 5
#: A disconnected peer unseen this long by every covering camera that still reports other markers is off the track.
ABSENT_S = 5.0
_LOG = logging.getLogger("fleet.console")


class OfflineMarkerClearance:
    def __init__(self, sightings, active, config, calibration, *, wall=time.time, clock=time.monotonic):
        self.sightings, self.active, self.config = sightings, active, config
        self.calibration = calibration
        self.wall, self.clock = wall, clock
        self.offline = {}
        self.frames = {}
        self.still = {}
        self.source_seen = {}
        self.source_live_since = {}
        self.robot_seen = {}
        self.last_decision = {}

    def link(self, row):
        rid = row["robot_id"]
        if row.get("online") is False and not row.get("state"):
            self.offline[rid] = self.clock()
        elif row.get("online") is True or row.get("state"):
            self.offline.pop(rid, None)
            self.last_decision.pop(rid, None)

    def observe(self, row):
        """Only the accepted sighting ingress calls this; nothing is hydrated on restart."""
        active = self.active()
        rid, source_id = row["robot_id"], row["source_id"]
        key = rid, source_id
        if active is None or row.get("map_id") != active[1].map_id:
            self.frames.pop(key, None)
            self.still.pop(key, None)
            return
        point, run, stamp = pose3(row), self.still.get(key), row["captured_at"]
        previous = self.source_seen.get(source_id)
        if previous is None or not 0 <= stamp - previous <= self.config.sighting_lease_s:
            if previous is None or stamp > previous:
                self.source_live_since[source_id] = stamp       # camera stream (re)started: absence counts from here
        self.source_seen[source_id] = max(stamp, previous if previous is not None else stamp)
        self.robot_seen[key] = max(stamp, self.robot_seen.get(key, stamp))
        basis = (active[0], row.get("calibration_revision"), row.get("calibration_source"),
                 row.get("processor_revision"))
        if point is None:
            self.still.pop(key, None)
        elif (run is None or run["basis"] != basis or not math.dist(run["xy"], point[:2]) <= STILL_PATH_M
                or not 0 < stamp - run["last"] <= STATIC_MAX_GAP_S):
            self.still[key] = {"basis": basis, "xy": point[:2], "since": stamp, "last": stamp, "count": 1}
        else:
            run["last"], run["count"] = stamp, run["count"] + 1
        prior = self.frames.get(key, ())
        recent = [item for item in prior if item[0] == active[0]
                  and 0 < row["captured_at"] - item[1]["captured_at"] <= self.config.sighting_lease_s]
        self.frames[key] = [*recent[-63:], (active[0], row)]

    def evidence(self, rid):
        """A detached, bounded receipt for the caller's trip ledger."""
        return deepcopy(self.last_decision.get(rid))

    def _decision(self, rid, reason, value, **facts):
        previous = self.last_decision.get(rid)
        self.last_decision[rid] = {"robot_id": rid, "reason": reason, "clear": value, "checked_at": self.wall(), **facts}
        if previous is None or previous["reason"] != reason:
            _LOG.info("offline peer clearance robot=%s reason=%s %s", rid, reason, facts)
        return value

    def _absent_s(self, rid, map_id, now):
        """Seconds the marker has been missing from every live covering camera, or None when not proven."""
        lease, covering = self.config.sighting_lease_s, []
        for source in self.sightings.sources:
            if source.map_id != map_id or rid not in source.robot_ids or type(dict(source.robot_markers).get(rid)) is not int:
                continue
            seen = self.source_seen.get(source.source_id)
            if seen is None or not 0 <= now - seen <= lease:
                return None
            last = max(self.robot_seen.get((rid, source.source_id), -math.inf), self.source_live_since[source.source_id])
            covering.append(now - last)
        if not covering or min(covering) < ABSENT_S:
            return None
        return min(covering)

    def clear(self, console, rid, site_route, keep_out, independent):
        last_loss = self.offline.get(rid)
        if last_loss is None:
            return None
        if rid not in self.sightings.known_robot_ids or not site_route or not site_route[1]:
            return self._decision(rid, "roster_or_route_unverified", False)
        if (console.trip_busy(rid) or any(rid in table for table in (console._goals, console._goal_busy,
                console._queued, console._claims, console._site_claims, console._yielding, console.goal_leases.pending))
                or rid in console._formation_members()):
            return self._decision(rid, "peer_has_motion_owner", False)
        if not 0 <= self.clock() - last_loss <= self.config.max_odom_age_s:
            return self._decision(rid, "link_sample_expired", False if independent is None else None)
        active = self.active()
        if active is None or active[1].map_id != site_route[0]:
            return self._decision(rid, "active_map_mismatch", False)
        now = self.wall()
        samples = []
        for source in self.sightings.sources:
            marker_id = dict(source.robot_markers).get(rid)
            if (source.map_id != site_route[0] or rid not in source.robot_ids or type(marker_id) is not int
                    or sum(other == marker_id for _, other in source.robot_markers) != 1):
                continue
            frames = self.frames.get((rid, source.source_id), ())
            if not frames or frames[-1][0] != active[0]:
                continue
            row = frames[-1][1]
            age = now - row["captured_at"]
            revision = row.get("calibration_revision")
            point = pose3(row)
            run = self.still.get((rid, source.source_id)) or {}
            still_s = (row["captured_at"] - run["since"]
                       if run.get("last") == row["captured_at"] and run["count"] >= STATIC_MIN_FRAMES else 0.0)
            parked = still_s >= STATIC_HOLD_S
            # Camera latency (~0.25 s) plus frame period (~0.35 s) exceeds MAX_FRAME_AGE_S; a parked
            # marker adds no travel with age, so it stays usable for the whole sighting lease.
            max_age = self.config.sighting_lease_s if parked else min(MAX_FRAME_AGE_S, self.config.sighting_lease_s)
            if (not 0 <= age <= max_age or point is None
                    or not revision or row.get("calibration_source") != "approved_record"
                    or row.get("quality") is not None and row["quality"] < self.config.min_quality
                    or self.sightings.approved_sighting_revision(source.source_id, site_route[0]) != revision):
                continue
            record = self.calibration(source.source_id)
            if record is None or record.map_id != site_route[0] or record.calibration_revision != revision:
                return self._decision(rid, "calibration_record_changed", False)
            x0, y0, x1, y1 = record.track_bounds_m
            if not (x0 <= point[0] <= x1 and y0 <= point[1] <= y1):
                return self._decision(rid, "outside_calibrated_area", False)
            if row["captured_at"] - frames[0][1]["captured_at"] < 0.1:
                return self._decision(rid, "stationary_interval_pending", False)
            for _, prior in frames[:-1]:
                previous = pose3(prior)
                if (previous is None or prior.get("calibration_source") != "approved_record"
                        or prior.get("calibration_revision") != revision
                        or prior.get("processor_revision") != row.get("processor_revision")
                        or row["seq"] == prior["seq"] or math.dist(previous[:2], point[:2]) > STILL_PATH_M):
                    return self._decision(rid, "peer_marker_moved_or_changed", False)
            # Fleet cannot command a disconnected peer, so a marker held still is a parked obstacle and
            # frame age adds no travel; a moving marker keeps the speed allowance and the moved check above.
            margin = MARKER_ERROR_M + (0.0 if parked else self.config.max_speed_mps * age)
            samples.append((point[:2], margin, {"source_id": source.source_id, "enrolled_marker_id": marker_id,
                                                 "calibration_revision": revision, "seq": row["seq"],
                                                 "captured_at": row["captured_at"], "age_s": age,
                                                 "still_s": still_s}))
        if not samples:
            absent_s = self._absent_s(rid, site_route[0], now)
            if absent_s is not None and independent is None:
                # A powered-off robot taken off the floor must not stall the site: every covering camera is
                # live (it reports other markers) and none has seen this marker for ABSENT_S.
                return self._decision(rid, "peer_absent_from_track", True, absent_s=absent_s)
            return self._decision(rid, "approved_marker_unavailable", False if independent is None else None)
        if independent is not None:
            if independent[0] != site_route[0]:
                return self._decision(rid, "peer_pose_frame_mismatch", False)
            samples.append((independent[1:3], 0.0, {"source_id": "independent_site_pose"}))
        obstacles = [{**info, "x": point[0], "y": point[1], "uncertainty_m": margin,
                      "route_distance_m": trust.route_distance(site_route[1], point), "keep_out_m": keep_out + margin}
                     for point, margin, info in samples]
        facts = {"map_id": site_route[0], "map_version": active[0], "min_route_distance_m": min(
            obs["route_distance_m"] for obs in obstacles), "observations": obstacles}
        for index, (point, margin, _) in enumerate(samples):
            if any(math.dist(point, other) > margin + error for other, error, _ in samples[:index]):
                return self._decision(rid, "peer_pose_conflict", False, **facts)
        if any(obs["route_distance_m"] <= obs["keep_out_m"] for obs in obstacles):
            return self._decision(rid, "keep_out_intersection", False, **facts)
        return self._decision(rid, "peer_clear", True, **facts)
