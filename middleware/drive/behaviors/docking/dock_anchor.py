"""core_features.docking.dock_anchor — the seat anchor: "this robot is seated in bay X right now" as a pair (odom pose, bay) for Fleet.

Emitted at DOCKED (LiDAR-confirmed seat, else inferred from the charge contact) and after a CORE (re)start when a stationary LiDAR probe finds the robot seated in a
reference-scan bay (CORE restart resets odom: Fleet drops its anchor, and the SLAM origin resets with rosy-navigation). It is an instant pair, never "kept true": the
status hides it once its odom epoch ended; consumers bridge by odom displacement and the camera track takes over. ROS-free; the probe scan is matched by the bridge.
"""

from __future__ import annotations

import math
import threading
import time
from typing import Any, Callable, Optional

from core_common.protocol.docking import DockAnchor
from core_common.protocol.native_receipts import BOOT_ID


class DockAnchorKeeper:
    def __init__(self, cfg: Any, odom_provider: Callable[[], Any], map_id_provider: Callable[[], Optional[str]], emit: Callable[[str, str, dict], None],
                 wall: Callable[[], float] = time.time, mono: Callable[[], float] = time.monotonic,
                 map_generation_provider: Optional[Callable[[], Optional[int]]] = None) -> None:
        self._cfg, self._odom, self._map_id, self._emit = cfg, odom_provider, map_id_provider, emit
        self._map_generation = map_generation_provider or (lambda: None)
        self._wall, self._mono = wall, mono
        self._lock = threading.Lock()
        self._anchor: Optional[DockAnchor] = None
        self._seq, self._open = 0, None              # the open probe: (id, dock id, odom pose at the request, asked at)
        self._tries: dict = {}
        self._first_eligible: Optional[float] = None
        self._still: Optional[tuple] = None          # (x, y, yaw, since) of the odom pose the robot has held

    # --- the record ---------------------------------------------------------------------------

    def record(self, dock_id: str, source: str, seat: dict) -> Optional[DockAnchor]:
        """Pair the newest odom pose with the bay. None (and no anchor) when there is no fresh odom or no complete LiDAR seat error: a seat the scan did not confirm names no bay."""
        odom = self._odom()
        wall = self._wall()
        if odom is None or not 0.0 <= wall - odom.stamp <= self._cfg.anchor_odom_max_age_s:
            return None
        if not seat or any(not isinstance(seat.get(k), (int, float)) or not math.isfinite(seat[k]) for k in ("along_m", "lateral_m", "heading_deg", "inliers", "margin")):
            return None
        anchor = DockAnchor(dock_id=dock_id, source=source, odom_pose=odom, boot_id=str(BOOT_ID), map_id=self._map_id(),
                            map_generation=self._map_generation(), along_m=seat["along_m"], lateral_m=seat["lateral_m"], heading_deg=seat["heading_deg"],
                            inliers=seat["inliers"], margin=seat["margin"], at=wall)
        with self._lock:
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

    def probe_request(self, can_probe: bool, docks: list) -> Optional[tuple]:
        """From the LiDAR callback (no manager lock): (request id, dock id, reference scan) when a stationary robot should be checked against a bay's reference scan."""
        cfg, now = self._cfg, self._mono()
        with self._lock:
            if self._anchor is not None or not can_probe or not docks:
                self._still = None
                return None
            if self._first_eligible is None:
                self._first_eligible = now
            if now - self._first_eligible > cfg.anchor_probe_window_s:
                return None
            odom = self._odom()
            if odom is None:
                return None
            pose = (odom.x, odom.y, odom.yaw)
            if self._still is None or math.hypot(pose[0] - self._still[0], pose[1] - self._still[1]) > 0.002 or abs(_wrap(pose[2] - self._still[2])) > 0.01:
                self._still = (*pose, now)
                return None
            if now - self._still[3] < cfg.anchor_probe_still_s:
                return None
            if self._open is not None and now - self._open[3] < cfg.anchor_probe_interval_s:
                return None
            for dock in docks:
                if self._tries.get(dock.id, 0) < cfg.anchor_probe_tries:
                    self._tries[dock.id] = self._tries.get(dock.id, 0) + 1
                    self._seq += 1
                    self._open = (self._seq, dock.id, pose, now)
                    return self._seq, dock.id, dock.metadata["reference_scan"]
            return None

    def note_probe_match(self, match: Any, request_id: Optional[int]) -> Optional[DockAnchor]:
        """The bridge's answer. Accepted only for the open request, with the robot still where the request found it, and a fit that passes the ROW gates and sits at the
        seated reference pose within the anchor tolerances."""
        cfg = self._cfg
        with self._lock:
            open_ = self._open
            if open_ is None or request_id != open_[0]:
                return None
            self._open = None
        odom = self._odom()
        if odom is None or math.hypot(odom.x - open_[2][0], odom.y - open_[2][1]) > 0.003 or abs(_wrap(odom.yaw - open_[2][2])) > 0.01:
            return None                                              # it moved while the scan was matched
        if match is None or not all(math.isfinite(v) for v in (match.x, match.y, match.heading, match.inliers, match.margin)):
            return None
        if (match.inliers < cfg.bay_scan_inlier_min or match.margin < cfg.bay_scan_margin_min or abs(match.x) > cfg.anchor_seat_along_m
                or abs(match.y) > cfg.anchor_seat_lateral_m or abs(match.heading) > cfg.anchor_seat_heading_rad):
            return None
        return self.record(open_[1], "startup_probe",
                           {"along_m": match.x, "lateral_m": -match.y, "heading_deg": math.degrees(match.heading), "inliers": match.inliers, "margin": match.margin})


def _wrap(a: float) -> float:
    return math.atan2(math.sin(a), math.cos(a))
