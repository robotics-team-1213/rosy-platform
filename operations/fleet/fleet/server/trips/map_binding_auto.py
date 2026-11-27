"""D-1022: re-bind a robot whose map file was redrawn in the same frame (grid id changed, frame did not).

A binding maps the robot's map frame to the site frame, and that frame is defined by the map raster's origin,
resolution and size. So a new grid with the SAME raster metadata as the grid the binding was approved on, and only a
few cells different (map_binding.same_raster), is the same frame redrawn. Fleet then approves the old transform for
the new grid id as ``fleet:auto-rebind``, only when all of these hold; any failure leaves the operator approval as it was:

1. the robot is LOCALIZED, IDLE and standing (fresh zero velocity) and the active site map is the one bound;
2. the bound grid's signature was stored (at approval, or by the first read while the binding matched) and the
   new grid passes same_raster: no signature, no auto-rebind;
3. the bound grid is not symmetric (check_not_symmetric): no turned or mirrored twin within the cell budget;
4. a ceiling-camera fix of the robot at most CAMERA_MAX_AGE_S old, against the robot's SLAM pose through the old
   transform, passes the store's own hold-out judge (``MAX_HOLDOUT_M``, not loosened: a fix further off refuses).

The new binding re-issues the old fit's pairs, so the transform is exactly the old one. Nothing here moves a
robot. The last attempt's reason is kept in ``store.auto_notes`` for the map-binding read.
"""

from __future__ import annotations

import math
import time
from typing import Awaitable, Callable, Mapping, Optional

from fleet.localization.map_binding import BindingError, check_not_symmetric, grid_signature, same_raster
from fleet.server.map_binding_store import _site_matches
from fleet.server.transient_loc_hold import _standing

PRINCIPAL = "fleet:auto-rebind"
CAMERA_MAX_AGE_S = 2.0
RETRY_S = 10.0  # a failed proof is not re-fetched every trip tick


def camera_sighting(map_pose, robot_id: str) -> Optional[tuple[float, float]]:
    """The newest ceiling-camera fix of the robot in site coordinates (not the odom-bridged pose), or None when
    it is older than CAMERA_MAX_AGE_S."""
    pose = map_pose.arbitrated_pose(robot_id)
    if (pose is None or pose.camera_x is None or pose.camera_y is None or pose.camera_residual_m is None
            or pose.last_sighting_age_s is None or pose.last_sighting_age_s > CAMERA_MAX_AGE_S):
        return None
    return (pose.camera_x, pose.camera_y)


async def read_signature(grid: Callable[[str], Awaitable[dict]], state_of: Callable[[str], Awaitable[Mapping]],
                         robot_id: str, state: Mapping, bound_grid_id: Optional[str] = None) -> Optional[dict]:
    """Signature of the grid the robot loaded, or None. CORE's map endpoint carries no grid id, so this is best
    effort: the id must be the same before and after the read, and equal to bound_grid_id (the grid of the
    binding being captured)."""
    try:
        raster = await grid(robot_id)
        after = await state_of(robot_id)
    except Exception:  # noqa: BLE001 - an unreadable robot has no signature to keep
        return None
    ids = {after.get("map_grid_id"), state.get("map_grid_id"), bound_grid_id or state.get("map_grid_id")}
    return grid_signature(raster) if len(ids) == 1 else None


class AutoRebind:
    def __init__(self, site_maps, *, grid: Callable[[str], Awaitable[dict]],
                 state: Callable[[str], Awaitable[Mapping]], camera: Callable[[str], Optional[tuple[float, float]]],
                 clock: Callable[[], float] = time.time) -> None:
        self._maps, self._grid, self._state, self._camera, self._clock = site_maps, grid, state, camera, clock
        self._tried: dict[str, float] = {}

    async def __call__(self, robot_id: str, state: Mapping) -> bool:
        """True when a new binding was approved. A matching binding without a signature gets one stored."""
        bindings, active = self._maps.map_bindings, self._maps.active()
        site = None if active is None else (active[1].map_id, active[0])
        reason = bindings.matching_fit(robot_id, state, site)[1]
        if reason not in ("", "MAP_BINDING_GRID_CHANGED"):
            return False
        old = bindings.active(robot_id)
        if reason == "" and old["grid_sig"] is not None:
            return False
        now = self._clock()
        if now - self._tried.get(robot_id, -math.inf) < RETRY_S:
            return False
        self._tried[robot_id] = now
        if reason == "":  # the grid is the bound one: keep its signature for a later swap
            if _standing(state) and state.get("mode") == "IDLE":
                sig = await read_signature(self._grid, self._state, robot_id, state, old["robot_grid_id"])
                if sig is not None:
                    bindings.set_grid_sig(old["binding_id"], sig)
            return False
        try:
            detail = await self._attempt(robot_id, state, site, old)
        except BindingError as exc:
            bindings.auto_notes[robot_id] = {"code": exc.code, "detail": str(exc), "at": now}
            return False
        except Exception as exc:  # noqa: BLE001 - an unreadable robot proves nothing
            bindings.auto_notes[robot_id] = {"code": "ROBOT_UNREADABLE", "detail": type(exc).__name__, "at": now}
            return False
        bindings.auto_notes[robot_id] = {"code": "APPROVED", "detail": "", "at": now}
        self._maps.record_event("map_binding_auto_rebind", PRINCIPAL, {"robot_id": robot_id, **detail})
        return True

    async def _attempt(self, robot_id: str, state: Mapping, site: tuple[str, int], old: dict) -> dict:
        bindings = self._maps.map_bindings
        # The store's own rule: a later site revision with the same frame hash is still the bound site frame
        # (2026-11-27 the site map went v395 -> v407 with the frame unchanged).
        if not _site_matches(old, site, getattr(bindings, "_frame_for_version", None)):
            raise BindingError("SITE_REVISION_CHANGED", "the active site map is not the frame that was bound")
        if state.get("mode") != "IDLE" or not _standing(state):
            raise BindingError("NOT_STANDING", "the robot must be IDLE and standing")
        if old["grid_sig"] is None:
            raise BindingError("GRID_SIGNATURE_MISSING", "the bound grid has no stored signature")
        check_not_symmetric(old["grid_sig"])
        raster = await self._grid(robot_id)
        after = await self._state(robot_id)  # the same grid id before and after the read: it is the grid read
        if (not raster or after.get("map_grid_id") != state.get("map_grid_id") or after.get("mode") != "IDLE"
                or not _standing(after)):
            raise BindingError("STATE_CHANGED", "the robot's grid or motion changed while it was read")
        new_sig = grid_signature(raster)
        differing = same_raster(old["grid_sig"], new_sig)
        pose = after.get("pose") or {}
        if not all(isinstance(pose.get(k), (int, float)) for k in ("x", "y")):
            raise BindingError("ROBOT_NOT_LOCALIZED", "the robot reports no map pose")
        cam = self._camera(robot_id)
        if cam is None:
            raise BindingError("NO_CAMERA_HOLDOUT", f"no ceiling-camera fix of the robot at most {CAMERA_MAX_AGE_S:g} s old")
        current = self._maps.active()
        if current is None or (current[1].map_id, current[0]) != site:
            raise BindingError("SITE_REVISION_CHANGED", "the active site map changed while the proof ran")
        new = bindings.approve(  # the old pairs re-issue the old transform; the store's judge enforces the hold-out
            robot_id, after, site, [{"robot": p["robot"], "site": p["site"]} for p in old["fit"]["pairs"]],
            [{"robot": [pose["x"], pose["y"]], "site": list(cam)}], PRINCIPAL, grid_sig=new_sig)
        return {"old_binding_id": old["binding_id"], "binding_id": new["binding_id"],
                "robot_grid_id": new["robot_grid_id"], "differing_cells": differing,
                "holdout_err_m": round(new["fit"]["holdout"][0]["err_m"], 4)}
