"""Peer pose sharing — the outbound beacon loop (design §4.1).

One daemon thread per CORE when ``peers.enabled`` and hosts are configured.
The poster is injected, so tests drive ``tick()`` synchronously.
"""
from __future__ import annotations

import logging
import threading
import time

from core_common.protocol.schemas import PeerBeacon

logger = logging.getLogger("peers.beacon")

DEFAULT_RATE_HZ = 1.0
RATE_RANGE_HZ = (0.2, 5.0)
DEFAULT_PORT = 8080


class BeaconSender:
    """Sends this robot's self-localized map pose to configured peer COREs."""

    def __init__(self, *, robot_id: str, boot_id: str, snapshot, peers_cfg: dict,
                 poster, clock=time.monotonic, sleep=time.sleep) -> None:
        self.robot_id = robot_id
        self.boot_id = boot_id
        self._snapshot = snapshot      # callable -> StateSnapshot
        self._poster = poster          # callable(url, token, payload, ca_file=None) -> bool
        self._clock = clock
        self._sleep = sleep
        self._seq = 0
        self._stop = threading.Event()
        rate = float((peers_cfg or {}).get("rate_hz", DEFAULT_RATE_HZ))
        low, high = RATE_RANGE_HZ
        if not low <= rate <= high:
            raise ValueError(f"peers.rate_hz must be within {low}-{high}")
        self._period = 1.0 / rate
        self.hosts: list[tuple[str, str, str | None]] = []
        for entry in (peers_cfg or {}).get("hosts") or ():
            host = str(entry.get("host", "")).strip()
            token = str(entry.get("token", "")).strip()
            if not host or not token:
                raise ValueError("peers.hosts entries need host and token")
            port = int(entry.get("port", DEFAULT_PORT))
            ca_file = entry.get("ca_file") or None
            self.hosts.append((f"https://{host}:{port}/api/v1/peers/beacon", token, ca_file))
        self._thread: threading.Thread | None = None

    def beacon(self) -> PeerBeacon:
        """The pose leaves only when localization reports LOCALIZED (design §4.1)."""
        snap = self._snapshot()
        localization = getattr(snap, "localization", None)
        state = getattr(localization, "state", None)
        pose = getattr(snap, "pose", None)
        localized = str(state) == "LOCALIZED" and pose is not None
        return PeerBeacon(
            robot_id=self.robot_id,
            boot_id=self.boot_id,
            seq=self._seq,
            map_id=getattr(snap, "map_id", None),
            pose=pose if localized else None,
            localization_state=None if state is None else str(state),
            stamp=self._clock(),
        )

    def tick(self) -> int:
        """Send one beacon to every configured peer; returns the success count."""
        self._seq += 1
        payload = self.beacon().model_dump(mode="json")
        sent = 0
        for url, token, ca_file in self.hosts:
            try:
                if self._poster(url, token, payload, ca_file=ca_file):
                    sent += 1
            except Exception:
                logger.debug("beacon to %s failed", url, exc_info=True)
        return sent

    def start(self) -> None:
        """Spawn the loop thread. No-op without hosts, so a disabled robot never starts one."""
        if self._thread is not None or not self.hosts:
            return
        self._thread = threading.Thread(target=self._run, name="peers-beacon", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()

    def _run(self) -> None:
        while not self._stop.is_set():
            self.tick()
            self._stop.wait(self._period)
