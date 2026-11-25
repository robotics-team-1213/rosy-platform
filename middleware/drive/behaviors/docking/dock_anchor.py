"""core_features.docking.dock_anchor — the seat anchor: "this robot is seated in bay X right now" as a pair (odom pose, bay) for Fleet.

Emitted at DOCKED (LiDAR-confirmed seat, else inferred from the charge contact) and after a CORE (re)start when a stationary LiDAR probe finds the robot seated in a
reference-scan bay (CORE restart resets odom: Fleet drops its anchor, and the SLAM origin resets with rosy-navigation). It is an instant pair, never "kept true": the
status hides it once its odom epoch ended; consumers bridge by odom displacement and the camera track takes over. ROS-free; the probe scan is matched by the bridge.
"""

from __future__ import annotations

import math
from copy import deepcopy
from dataclasses import dataclass
import threading
import time
from typing import Any, Callable, Optional

from core_common.protocol.docking import DockAnchor
from core_common.protocol.native_receipts import BOOT_ID
from core_common.protocol.localization import OdomPose
from core_features.docking.bay_zone import scan_geometry


@dataclass(frozen=True)
class SeatObservation:
    pose: OdomPose
    seen_at: float
    stamp_ns: Optional[int]


@dataclass(frozen=True, eq=False)
class SeatComparison:
    request_id: int
    run_id: Any
    dock_id: str
    observation: Optional[SeatObservation]
    refs: dict


@dataclass
class PendingSeatAnchor:
    frame: SeatComparison
    identity: Any = None
    docked_geometry: Optional[tuple] = None


def docked_seat_evidence(seat, tracked, cfg, staging_offset_m, wheel_pose, current_pose):
    """The alias-tested seat fit must agree with the operational fit and the wheels must remain at the scan pose."""
    measured = scan_geometry(seat, staging_offset_m, cfg) if seat is not None else None
    if measured is None or tracked is None or wheel_pose is None or current_pose is None:
        return None
    if (abs(measured[0] - tracked[0]) > cfg.anchor_seat_along_m or abs(measured[1] - tracked[1]) > cfg.anchor_seat_lateral_m
            or abs(_wrap(measured[2] - tracked[2])) > cfg.anchor_seat_heading_rad
            or math.hypot(current_pose[0] - wheel_pose[0], current_pose[1] - wheel_pose[1]) > 0.003
            or abs(_wrap(current_pose[2] - wheel_pose[2])) > 0.01):
        return None
    return {"along_m": measured[0], "lateral_m": measured[1], "heading_deg": math.degrees(measured[2]), "inliers": seat.inliers, "margin": seat.margin}


class DockAnchorKeeper:
    def __init__(self, cfg: Any, odom_provider: Callable[[], Any], map_id_provider: Callable[[], Optional[str]], emit: Callable[[str, str, dict], None],
                 wall: Callable[[], float] = time.time, mono: Callable[[], float] = time.monotonic,
                 map_generation_provider: Optional[Callable[[], Optional[int]]] = None, odom_window_provider=None, reference_provider=None) -> None:
        self._cfg, self._odom, self._map_id, self._emit = cfg, odom_provider, map_id_provider, emit
        self._map_generation = map_generation_provider or (lambda: None)
        self._history = odom_window_provider
        self._references = reference_provider
        self._probed_refs = None
        self._wall, self._mono = wall, mono
        self._lock = threading.RLock()
        self._matcher = threading.Lock()
        self._anchor: Optional[DockAnchor] = None
        self._seq, self._open = 0, None
        self._tries: dict = {}
        self._first_eligible: Optional[float] = None
        self._probe_epoch = self._last_probe_at = None
        self._still: Optional[tuple] = None          # (odom, since) while this epoch remains stationary

    # --- the record ---------------------------------------------------------------------------

    def submit_comparison(self, compare) -> bool:
        """One extra anchor worker, no queue. The normal docking matcher never waits for it."""
        if not self._matcher.acquire(blocking=False):
            return False
        def run():
            try:
                compare()
            finally:
                self._matcher.release()
        try:
            threading.Thread(target=run, name="dock-anchor-comparison", daemon=True).start()
        except RuntimeError:
            self._matcher.release()
            return False
        return True

    def observe(self, scan_lag_s: float = 0.0, stamp_ns=None) -> Optional[SeatObservation]:
        """Capture the wheel pose and scan time before dispatching the asynchronous fit."""
        try:
            pose = self._odom()
        except Exception:  # noqa: BLE001 - unavailable anchor odometry must not interrupt the docking scan
            return None
        if (pose is None or pose.epoch is None or not 0 <= scan_lag_s <= self._cfg.bay_scan_fresh_s
                or not 0 <= self._wall() - pose.stamp <= self._cfg.anchor_odom_max_age_s):
            return None
        if stamp_ns is not None:
            pose = self._stationary_window(stamp_ns, pose, bracket=False)
            if pose is None:
                return None
        elif scan_lag_s != 0 or self._history is not None:
            return None
        return SeatObservation(pose, self._mono() - scan_lag_s, stamp_ns)

    def _stationary_window(self, stamp_ns, now_pose, *, bracket):
        """Prove no movement or odom gap between capture and use, on both ROS and receipt clocks."""
        frames = self._history(stamp_ns) if self._history else ()
        gap = self._cfg.bay_scan_fresh_s
        if not frames or frames[0][0] > stamp_ns or (stamp_ns - frames[0][0]) / 1e9 > gap:
            return None
        if bracket and frames[-1][0] < stamp_ns:
            return None
        first = frames[0][1]
        last_ns, last = frames[0]
        for ns, pose in frames:
            if (pose.mono_s is None or last.mono_s is None or not 0 <= (ns - last_ns) / 1e9 <= gap
                    or not 0 <= pose.mono_s - last.mono_s <= gap or pose.epoch != first.epoch
                    or math.hypot(pose.x - first.x, pose.y - first.y) > 0.003 or abs(_wrap(pose.yaw - first.yaw)) > 0.01):
                return None
            last_ns, last = ns, pose
        if last != now_pose or not 0 <= self._mono() - last.mono_s <= gap:
            return None
        return first

    def record(self, dock_id: str, source: str, seat: dict, observation: Optional[SeatObservation], *, expected_refs=None) -> Optional[DockAnchor]:
        """Pair the newest odom pose with the bay. None (and no anchor) when there is no fresh odom or no complete LiDAR seat error: a seat the scan did not confirm names no bay."""
        odom = self._odom()
        wall = self._wall()
        if (observation is None or not 0 <= self._mono() - observation.seen_at <= self._cfg.bay_req_timeout_s
                or odom is None or not 0.0 <= wall - odom.stamp <= self._cfg.anchor_odom_max_age_s
                or observation.pose.epoch != odom.epoch or abs(_wrap(odom.yaw - observation.pose.yaw)) > 0.01
                or math.hypot(odom.x - observation.pose.x, odom.y - observation.pose.y) > 0.003):
            return None
        if observation.stamp_ns is not None and self._stationary_window(observation.stamp_ns, odom, bracket=True) is None:
            return None
        if not seat or any(not isinstance(seat.get(k), (int, float)) or not math.isfinite(seat[k]) for k in ("along_m", "lateral_m", "heading_deg", "inliers", "margin")):
            return None
        if seat["inliers"] < self._cfg.bay_scan_inlier_min or seat["margin"] < self._cfg.bay_scan_margin_min:
            return None
        anchor = DockAnchor(dock_id=dock_id, source=source, odom_pose=odom, boot_id=str(BOOT_ID), map_id=self._map_id(),
                            map_generation=self._map_generation(), along_m=seat["along_m"], lateral_m=seat["lateral_m"], heading_deg=seat["heading_deg"],
                            inliers=seat["inliers"], margin=seat["margin"], at=wall)
        with self._lock:
            if expected_refs is not None and (self._references is None or self._references() != expected_refs):
                if source == "startup_probe":
                    self._discard_probe_registry(self._mono())
                return None
            self._anchor = anchor
            self._open = None
        self._emit("docking.anchor", "info", {"dock_id": dock_id, "confirmation": anchor.confirmation, "source": source, "odom_epoch": odom.epoch, "odom_stamp": odom.stamp,
                                              "along_m": anchor.along_m, "lateral_m": anchor.lateral_m, "heading_deg": anchor.heading_deg})
        return anchor

    def current(self) -> Optional[DockAnchor]:
        """The anchor with its age, or None when none was recorded or its odom frame ended (a new epoch)."""
        with self._lock:
            anchor = self._anchor
        if anchor is None:
            return None
        odom = self._odom()
        if odom is None or anchor.odom_pose.epoch is None or odom.epoch != anchor.odom_pose.epoch:
            return None
        return anchor.model_copy(update={"age_s": max(0.0, self._wall() - anchor.at)})

    # --- the startup probe --------------------------------------------------------------------

    def probe_request(self, can_probe: bool, docks: list, scan_lag_s: float = 0.0, stamp_ns=None) -> Optional[tuple]:
        """Match the same stationary frame against all configured reference bays."""
        cfg, now = self._cfg, self._mono()
        with self._lock:
            if not can_probe or not docks:
                self._still = None
                self._open = None
                if can_probe and not docks and self._probed_refs is not None:
                    self._discard_probe_registry(now)
                return None
            observation = self.observe(scan_lag_s, stamp_ns)
            if observation is None:
                self._open = self._still = None
                return None
            odom = observation.pose
            if odom.epoch != self._probe_epoch:
                self._first_eligible, self._probe_epoch = now, odom.epoch
                self._open = self._still = None
                self._tries.clear()
                if self._anchor is not None and self._anchor.odom_pose.epoch != odom.epoch:
                    self._anchor = None
            if self._anchor is not None:
                return None
            refs = {d.id: d.metadata["reference_scan"] for d in docks}
            if self._probed_refs is not None and self._probed_refs != refs:
                self._discard_probe_registry(now)
            if now - self._first_eligible > cfg.anchor_probe_window_s:
                return None
            if self._last_probe_at is not None and not 0 <= now - self._last_probe_at <= cfg.bay_scan_fresh_s:
                self._open = self._still = None
            self._last_probe_at = now
            if (self._still is None or odom.epoch != self._still[0].epoch
                    or math.hypot(odom.x - self._still[0].x, odom.y - self._still[0].y) > 0.002
                    or abs(_wrap(odom.yaw - self._still[0].yaw)) > 0.01):
                self._still = (odom, now, stamp_ns)
                self._open = None
                return None
            if now - self._still[1] < cfg.anchor_probe_still_s:
                return None
            if self._still[2] is not None and self._stationary_window(self._still[2], self._odom(), bracket=True) is None:
                self._open, self._still = None, (odom, now, stamp_ns)
                return None
            if self._open is not None and now - self._open[2].seen_at < cfg.anchor_probe_interval_s:
                return None
            if any(self._tries.get(d.id, 0) >= cfg.anchor_probe_tries for d in docks):
                return None
            self._probed_refs = deepcopy(refs)
            for dock in docks:
                self._tries[dock.id] = self._tries.get(dock.id, 0) + 1
            self._seq += 1
            self._open = (self._seq, self._probed_refs, observation)
            return self._seq, self._probed_refs

    def _discard_probe_registry(self, now):
        self._open = self._probed_refs = None
        self._tries.clear()
        self._first_eligible = now

    def note_probe_match(self, matches: dict, request_id: Optional[int]) -> Optional[DockAnchor]:
        """The bridge's answer. Accepted only for the open request, with the robot still where the request found it, and a fit that passes the ROW gates and sits at the
        seated reference pose within the anchor tolerances."""
        with self._lock:
            open_ = self._open
            if open_ is None or request_id != open_[0]:
                return None
            self._open = None
            if self._last_probe_at is None or not 0 <= self._mono() - self._last_probe_at <= self._cfg.bay_scan_fresh_s:
                return None
            winner = self.unique_seat(matches, open_[1].keys())
            if not winner:
                return None
            dock_id, match = winner
            return self.record(dock_id, "startup_probe",
                               {"along_m": match.x, "lateral_m": -match.y, "heading_deg": math.degrees(match.heading),
                                "inliers": match.inliers, "margin": match.margin}, open_[2], expected_refs=open_[1])

    def unique_seat(self, matches, expected_ids):
        if (matches.keys() != expected_ids or any(m is None or not all(math.isfinite(v) for v in (m.x, m.y, m.heading, m.inliers, m.margin))
                                                 for m in matches.values())):
            return None
        candidates = [(dock_id, match) for dock_id, match in matches.items() if self._fits_seat(match)]
        return candidates[0] if len(candidates) == 1 else None

    def _fits_seat(self, match: Any) -> bool:
        cfg = self._cfg
        return (match.inliers >= cfg.bay_scan_inlier_min and match.margin >= cfg.bay_scan_margin_min and abs(match.x) <= cfg.anchor_seat_along_m
                and abs(match.y) <= cfg.anchor_seat_lateral_m and abs(match.heading) <= cfg.anchor_seat_heading_rad)


def _wrap(a: float) -> float:
    return math.atan2(math.sin(a), math.cos(a))
