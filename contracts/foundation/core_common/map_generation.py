"""core_common.map_generation — a counter that changes whenever the robot's SLAM map origin MAY have changed.

The signal is the lifecycle transition of the map-owning navigation nodes to ACTIVE (`slam_toolbox/transition_event`, `map_server/transition_event`: ros_bridge ->
map_observation.lifecycle): a restart of the navigation stack publishes it, and slam_toolbox starts a new map at the robot's pose then. It is also bumped once at every CORE
start: rosy-navigation Requires rosy-core (its restart follows CORE's), and a restart that happened while CORE was not subscribed leaves no event. It is persisted
(atomic file under the CORE data dir) so a CORE restart does not repeat a value; with no readable file it starts at the wall-clock second. Consumers compare for INEQUALITY only (never
order) and read it together with boot_id.
Independent of boot_id, map_id and map_grid_id (the grid hash changes as the grid grows). ROS-free.

Cannot detect: a slam_toolbox internal reset or map replacement WITHOUT a lifecycle transition (clear/deserialize services), a loop-closure shift of map->odom, an AMCL restart (the
frame is unchanged, only the estimate is lost), and a transition event missed while CORE is subscribed late (the CORE-start bump covers that window).
"""

from __future__ import annotations

import logging
import os
import threading
import time
from pathlib import Path
from typing import Callable, Optional

_LOG = logging.getLogger(__name__)


class MapGenerationCounter:
    def __init__(self, path: Optional[Path] = None, wall: Callable[[], float] = time.time) -> None:
        self._path = None if path is None else Path(path)
        self._lock = threading.Lock()
        self._io = threading.Lock()
        self._warned = False
        previous = self._read()
        self._value = (previous if previous is not None else int(wall())) + (1 if previous is not None else 0)
        self._write()                                    # the CORE-start bump is persisted before anything can observe it

    @property
    def value(self) -> int:
        return self._value                               # one int read, no lock: the state snapshot (10 Hz) must never wait for a disk write

    def bump(self, reason: str = "") -> int:
        with self._lock:                                 # the increment only
            self._value += 1
            value = self._value
        self._write()                                    # the disk write is OUTSIDE the lock; it persists the newest value
        _LOG.info("map generation %d (%s)", value, reason or "bump")
        return value

    def _read(self) -> Optional[int]:
        if self._path is None:
            return None
        try:
            value = int(self._path.read_text(encoding="utf-8").strip())
        except (OSError, ValueError):
            return None
        return value if value >= 0 else None

    def _write(self) -> None:
        if self._path is None:
            return
        with self._io:                                   # writes are serialised; each writes the value current at that moment
            self._write_locked()

    def _write_locked(self) -> None:
        try:
            self._path.parent.mkdir(parents=True, exist_ok=True)
            tmp = self._path.with_name(self._path.name + ".tmp")
            with open(tmp, "w", encoding="utf-8") as handle:
                handle.write("%d\n" % self._value)
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(tmp, self._path)
        except OSError as exc:                           # the counter still runs in memory for this boot; the next boot falls back to the wall clock
            if not self._warned:
                self._warned = True
                _LOG.warning("map generation not persisted: %s", exc)
