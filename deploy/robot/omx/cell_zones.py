"""Two arms over one pallet: each reach enters its own side or the shared middle, never the other arm's side, and the
middle holds one arm at a time (2026-11-04, arm_a and arm_b on the field cell).

Zones are cut in the shared top camera's pixels: a reach target (the arm's own x, y) goes through that arm's own map to
a pixel column. Left of `zone.split_px - zone.middle_px` is the left side, right of `split + middle` the right side,
between them the middle. An arm's side is `zone_side` in its cell config. The middle is an exclusive file lock
(`flock`) with durable owner-bound occupancy: a crashed carry stays blocked until that same guarded owner parks.
All zone readers must run this protocol together; old readers ignore occupancy records and are incompatible.
"""
from __future__ import annotations

import fcntl
import json
import os
import re
import time
from pathlib import Path

import numpy as np

import cell_calibration as cal
import cell_params as prm

SCHEMA = "rosy.omx-zone-occupancy.v1"


def valid_owner(owner):
    return (isinstance(owner, dict)
            and set(owner) == {"device_id", "instance_id", "robot_config_sha256", "profile_sha256"}
            and all(isinstance(owner[k], str) and re.fullmatch(r"[A-Za-z0-9_.-]{1,128}", owner[k])
                    for k in ("device_id", "instance_id"))
            and all(isinstance(owner[k], str) and re.fullmatch(r"[0-9a-f]{64}", owner[k])
                    for k in ("robot_config_sha256", "profile_sha256")))


class Zones:
    def __init__(self, config: dict, calibration: dict, *, lock_dir=None, incidents=None, clock=time.monotonic,
                 sleep=time.sleep):
        self.side, self.site = config["zone_side"], config.get("zone_map_site", "pallet")
        self.peer = config.get("zone_peer")
        self.params, self.calibration, self.clock, self.sleep = config.get("params"), calibration, clock, sleep
        self.dir = Path(lock_dir or Path.home() / "rosy-omx")
        self.incidents = Path(incidents or config.get("incidents_dir", "incidents"))
        self.held = {}  # lock name -> fd, all released on leave()
        self.owner, self.session_id = None, None

    def bind(self, owner, session_id):
        if (not valid_owner(owner) or not isinstance(session_id, str)
                or re.fullmatch(r"[0-9a-f]{32}", session_id) is None):
            raise ValueError("zone occupancy needs the verified operating profile and session")
        if self.held and (owner != self.owner or session_id != self.session_id):
            raise ValueError("zone owner changed while occupied")
        self.owner, self.session_id = dict(owner), session_id

    def zone_of(self, xy) -> str | None:
        """left / middle / right of the arm-frame point, or None when this arm has no map for the site."""
        site = (self.calibration.get("sites") or {}).get(self.site)
        if not site or "homography" not in site:
            return None
        u = cal.to_pixel(np.array(site["homography"]), tuple(xy))[0]
        split, middle = prm.get(self.params, "zone.split_px"), prm.get(self.params, "zone.middle_px")
        return "middle" if abs(u - split) <= middle else "left" if u < split else "right"

    def _claim(self, name) -> bool:
        if name in self.held:
            return True
        if self.owner is None:
            return False
        self.dir.mkdir(parents=True, exist_ok=True)
        fd, deadline = os.open(self.dir / f"zone-{name}.lock", os.O_CREAT | os.O_RDWR, 0o644), self.clock() + prm.get(self.params, "zone.wait_s")
        while True:
            try:
                fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
                if os.fstat(fd).st_size:
                    os.close(fd)  # stale/invalid occupancy is never proof that the arm folded
                    return False
                record = json.dumps({"schema": SCHEMA, "owner": self.owner, "session_id": self.session_id}).encode()
                if os.write(fd, record) != len(record):
                    raise OSError("incomplete zone occupancy write")
                os.fsync(fd)
                self.held[name] = fd
                return True
            except BlockingIOError:
                if self.clock() >= deadline:
                    os.close(fd)
                    return False
                self.sleep(0.5)
            except OSError:
                os.close(fd)
                raise

    def enter(self, xy) -> tuple[bool, str]:
        """Claim own side or middle. Peer-side takeover has no validated physical-clearance producer."""
        zone = self.zone_of(xy)
        if zone is None:
            return False, f"no {self.site} map for this arm: its zone is unknown"
        if zone == "middle":
            if self.peer and (self.incidents / f"HOLD-{self.peer}.json").exists():
                return False, "peer HOLD: middle clearance unknown; recover the peer under guarded supervision first"
            return ((True, "middle") if self._claim("middle") else
                    (False, "the other arm holds the middle; its guarded owner must park before recovery"))
        if zone == self.side:
            return ((True, zone) if self._claim(f"side-{zone}") else
                    (False, f"{zone} side occupancy unknown; its guarded owner must park before recovery"))
        # HOLD and an idle session do not establish fresh physical clearance; takeover stays refused.
        return False, f"{zone} side belongs to the other arm"

    def leave(self) -> None:
        """Only after Gate verifies guarded home: clear this physical owner's live or interrupted claims."""
        if self.owner is None:
            return
        for name in ("middle", "side-left", "side-right"):
            fd = self.held.get(name)
            if fd is None:
                try:
                    fd = os.open(self.dir / f"zone-{name}.lock", os.O_RDWR)
                    fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
                except FileNotFoundError:
                    continue
                except BlockingIOError:
                    os.close(fd)
                    continue
            try:
                os.lseek(fd, 0, os.SEEK_SET)
                if os.fstat(fd).st_size > 4096:
                    continue
                record = json.loads(os.read(fd, 4096))
                if (set(record) == {"schema", "owner", "session_id"} and record["schema"] == SCHEMA
                        and valid_owner(record["owner"]) and record["owner"] == self.owner
                        and isinstance(record["session_id"], str) and re.fullmatch(r"[0-9a-f]{32}", record["session_id"])):
                    os.ftruncate(fd, 0)
                    os.fsync(fd)
            except (ValueError, TypeError):
                pass  # corrupt occupancy remains blocked, including after a confirmed park
            finally:
                os.close(fd)
        self.held = {}
