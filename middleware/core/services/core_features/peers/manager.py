"""Peer pose sharing — the peers table this CORE keeps (design §4.3).

Pure logic with an injected clock. ``robot_id`` stays what the beacon claims;
the API route (``PEER_SHARE`` grant) is the trust boundary, not this table.
"""
from __future__ import annotations

import math
import threading

from core_common.protocol.schemas import PeerBeacon, PeerRow


class PeersManager:
    """Latest self-localized pose per peer robot; silent peers leave through ``max_age_s``."""

    def __init__(self, *, now, max_age_s: float = 5.0) -> None:
        self._now = now
        self.max_age_s = float(max_age_s)
        self._lock = threading.Lock()
        self._rows: dict[str, dict] = {}

    def observe(self, beacon: PeerBeacon) -> bool:
        """Accept one beacon. A stale or duplicate seq is a no-op; a new ``boot_id`` resets it."""
        pose = beacon.pose
        if pose is not None and not all(
                math.isfinite(value) for value in (pose.x, pose.y, pose.yaw)):
            pose = None
        row = {
            "robot_id": beacon.robot_id,
            "boot_id": beacon.boot_id,
            "seq": beacon.seq,
            "map_id": beacon.map_id,
            "pose": pose,
            "localization_state": beacon.localization_state,
            "at": self._now(),
        }
        with self._lock:
            previous = self._rows.get(beacon.robot_id)
            if (previous is not None and previous["boot_id"] == beacon.boot_id
                    and beacon.seq <= previous["seq"]):
                return False
            self._rows[beacon.robot_id] = row
            return True

    def snapshot(self) -> list[PeerRow]:
        """Fresh rows sorted by robot id. Also the StateSnapshot provider."""
        now = self._now()
        with self._lock:
            fresh = [row for row in self._rows.values() if now - row["at"] <= self.max_age_s]
            self._rows = {row["robot_id"]: row for row in fresh}
            return [PeerRow(**{key: value for key, value in row.items() if key != "at"},
                            age_s=max(0.0, now - row["at"]))
                    for row in sorted(fresh, key=lambda row: row["robot_id"])]
