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
    def __init__(self, config: dict, calibration: dict, *, lock_dir=None, incidents=None, clock=time.monotonic,
                 sleep=time.sleep):
        self.side, self.site = config["zone_side"], config.get("zone_map_site", "pallet")
        self.peer = config.get("zone_peer")  # the other arm: its side may be taken over while it is held
        self.params, self.calibration, self.clock, self.sleep = config.get("params"), calibration, clock, sleep
        self.dir = Path(lock_dir or Path.home() / "rosy-omx")
        self.incidents = Path(incidents or config.get("incidents_dir", "incidents"))
        self.held = {}  # lock name -> fd, all released on leave()

    def zone_of(self, xy) -> str | None:
        """left / middle / right of the arm-frame point, or None when this arm has no map for the site."""
        site = (self.calibration.get("sites") or {}).get(self.site)
        if not site or "homography" not in site:
            return None
        u = cal.to_pixel(np.array(site["homography"]), tuple(xy))[0]
        split, middle = prm.get(self.params, "zone.split_px"), prm.get(self.params, "zone.middle_px")
        return "middle" if abs(u - split) <= middle else "left" if u < split else "right"

    def peer_out_of_service(self) -> str | None:
        """Why the other arm's side may be taken over (it is held for a person and runs no session), else None."""
        if not self.peer or not prm.get(self.params, "zone.takeover"):
            return None
        if not (self.incidents / f"HOLD-{self.peer}.json").exists():
            return None
        fd = os.open(self.dir / f"session-{self.peer}.lock", os.O_CREAT | os.O_RDWR, 0o644)
        try:
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)  # its record_session holds this lock while it runs
            fcntl.flock(fd, fcntl.LOCK_UN)
            return f"{self.peer} is held for a person and runs no session"
        except BlockingIOError:
            return None
        finally:
            os.close(fd)

    def _claim(self, name) -> bool:
        if name in self.held:
            return True
        self.dir.mkdir(parents=True, exist_ok=True)
        fd, deadline = os.open(self.dir / f"zone-{name}.lock", os.O_CREAT | os.O_RDWR, 0o644), self.clock() + prm.get(self.params, "zone.wait_s")
        while True:
            try:
                fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
                self.held[name] = fd
                return True
            except BlockingIOError:
                if self.clock() >= deadline:
                    os.close(fd)
                    return False
                self.sleep(0.5)

    def enter(self, xy) -> tuple[bool, str]:
        """Claim the zone of a reach target; (allowed, why). A side is locked too, so an arm that took over its
        peer's side keeps the peer out until it folds home (2026-11-04: one arm stands in for a failed one)."""
        zone = self.zone_of(xy)
        if zone is None:
            return False, f"no {self.site} map for this arm: its zone is unknown"
        if zone == "middle":
            return (True, "middle") if self._claim("middle") else (False, "the other arm holds the middle")
        if zone == self.side:
            return (True, zone) if self._claim(f"side-{zone}") else (False, f"the other arm has taken over the {zone} side")
        why = self.peer_out_of_service()
        if why is None:
            return False, f"{zone} side belongs to the other arm"
        if self._claim("middle") and self._claim(f"side-{zone}"):  # the way there crosses the middle
            return True, f"{zone} (taken over: {why})"
        self.leave()
        return False, f"the {zone} side or the middle is busy"

    def leave(self) -> None:
        for fd in self.held.values():
            fcntl.flock(fd, fcntl.LOCK_UN)
            os.close(fd)
        self.held = {}
