"""Two arms over one pallet: each reach enters its own side or the shared middle, never the other arm's side, and the
middle holds one arm at a time (2026-11-04, arm_a and arm_b on the field cell).

Zones are cut in the shared top camera's pixels: a reach target (the arm's own x, y) goes through that arm's own map to
a pixel column. Left of `zone.split_px - zone.middle_px` is the left side, right of `split + middle` the right side,
between them the middle. An arm's side is `zone_side` in its cell config. The middle is an exclusive file lock
(`flock`), so a crashed carry frees it. All three numbers are cell_params: change the file, not this code.
"""
from __future__ import annotations

import fcntl
import os
import time
from pathlib import Path

import numpy as np

import cell_calibration as cal
import cell_params as prm


class Zones:
    def __init__(self, config: dict, calibration: dict, *, lock_dir=None, clock=time.monotonic, sleep=time.sleep):
        self.side, self.site = config["zone_side"], config.get("zone_map_site", "pallet")
        self.params, self.calibration, self.clock, self.sleep = config.get("params"), calibration, clock, sleep
        self.lock = Path(lock_dir or Path.home() / "rosy-omx") / "zone-middle.lock"
        self.held = None

    def zone_of(self, xy) -> str | None:
        """left / middle / right of the arm-frame point, or None when this arm has no map for the site."""
        site = (self.calibration.get("sites") or {}).get(self.site)
        if not site or "homography" not in site:
            return None
        u = cal.to_pixel(np.array(site["homography"]), tuple(xy))[0]
        split, middle = prm.get(self.params, "zone.split_px"), prm.get(self.params, "zone.middle_px")
        return "middle" if abs(u - split) <= middle else "left" if u < split else "right"

    def enter(self, xy) -> tuple[bool, str]:
        """Claim the zone of a reach target; (allowed, why)."""
        zone = self.zone_of(xy)
        if zone is None:
            return False, f"no {self.site} map for this arm: its zone is unknown"
        if zone not in (self.side, "middle"):
            return False, f"{zone} side belongs to the other arm"
        if zone == self.side or self.held:
            return True, zone
        self.lock.parent.mkdir(parents=True, exist_ok=True)
        fd, deadline = os.open(self.lock, os.O_CREAT | os.O_RDWR, 0o644), self.clock() + prm.get(self.params, "zone.wait_s")
        while True:
            try:
                fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
                self.held = fd
                return True, "middle"
            except BlockingIOError:
                if self.clock() >= deadline:
                    os.close(fd)
                    return False, "the other arm holds the middle"
                self.sleep(0.5)

    def leave(self) -> None:
        if self.held is not None:
            fcntl.flock(self.held, fcntl.LOCK_UN)
            os.close(self.held)
            self.held = None
