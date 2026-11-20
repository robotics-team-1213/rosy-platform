"""Push the active site map's wall grid to every robot that runs the SLAM fallback supervisor (2026-11-18).

Fleet is the external client of CORE, so Fleet pushes: a robot whose state carries a slam_fallback block and whose staged wall map is not
the active map's gets the grid, once per (robot, sha256) until the map changes or the push fails. The robot verifies the sha256 itself
(CORE, then the privileged host half); nothing here is trusted by the robot.
"""
from __future__ import annotations

import base64
import logging
from typing import Awaitable, Callable, Mapping, Optional

from fleet.localization import wall_grid

logger = logging.getLogger("fleet.wall_map_sync")
RETRY_S = 60.0


class WallMapSync:
    def __init__(self, site_maps, clients: Callable[[], Mapping[str, object]],
                 clock: Callable[[], float], build=wall_grid.build) -> None:
        self._site_maps, self._clients, self._clock, self._build = site_maps, clients, clock, build
        self._built: Optional[tuple] = None   # ((map_id, version), artifact)
        self._pushed: dict[str, tuple[str, float]] = {}   # robot -> (sha256, Fleet time)

    def artifact(self) -> Optional[dict]:
        active = self._site_maps.active()
        if active is None or not active[1].walls:
            return None
        key = (active[1].map_id, active[0])
        if self._built is None or self._built[0] != key:
            self._built = (key, self._build(active[1].map_id, active[0], [w.face for w in active[1].walls]))
        return self._built[1]

    async def sync(self, states: Mapping[str, dict]) -> None:
        wanted = [rid for rid, state in states.items() if isinstance(state.get("slam_fallback"), dict)]
        if not wanted:
            return
        artifact = self.artifact()
        if artifact is None:
            return
        now = self._clock()
        for rid in wanted:
            staged = (states[rid]["slam_fallback"].get("wall_map") or {}).get("sha256")
            sent = self._pushed.get(rid)
            if staged == artifact["sha256"] or (sent and sent[0] == artifact["sha256"] and now - sent[1] < RETRY_S):
                continue
            client = self._clients().get(rid)
            push = getattr(client, "slam_fallback_wall_map", None)
            if push is None:
                continue
            self._pushed[rid] = (artifact["sha256"], now)
            payload = {"map_id": artifact["map_id"], "version": artifact["version"], "sha256": artifact["sha256"],
                       "resolution": artifact["resolution"], "origin": artifact["yaml"]["origin"],
                       "pgm_base64": base64.b64encode(artifact["pgm"]).decode("ascii")}
            try:
                await push(payload)
                logger.info("wall map %s v%s pushed to %s", artifact["map_id"], artifact["version"], rid)
            except Exception as exc:  # noqa: BLE001 - one robot's refusal must not stop the others
                logger.warning("wall map push to %s failed: %s", rid, exc)
