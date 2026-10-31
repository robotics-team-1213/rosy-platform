"""Guards that keep a pick from using a scene that may no longer be there (2026-10-27, arm S).

A person touched the cell (hub reconnect, top camera moved, boxes rearranged) and two picks still aimed at the
old box position. Rule: after a session (re)start, a reconnect or any human intervention, observe again before a
target from an older observation is used. The operator or session start writes config["scene_since"] (UTC iso);
a map measured before it, a map of another camera (record "camera_id" vs config cameras.<name>.id), or a detection
older than it is refused with the reason, and the seat proposes a re-map.

Also: the wrist-view yaw that keeps the wrist roll continuous, and whether open jaws clear a stored fixture."""
from __future__ import annotations

import math
from datetime import datetime, timezone

import cell_calibration as cal


def _utc(text) -> datetime | None:
    try:
        t = datetime.fromisoformat(str(text).replace("Z", "+00:00"))
    except ValueError:
        return None
    return t if t.tzinfo else t.replace(tzinfo=timezone.utc)


def scene_check(config: dict, calibration: dict, found: dict) -> str | None:
    """Why the maps or the detection behind `found` may describe an older scene, or None."""
    since = _utc(config.get("scene_since"))
    seen = _utc(found.get("observed"))
    if since is not None and seen is not None and seen < since:
        return f"detection from {found['observed']} is older than the scene change at {config['scene_since']}"
    for e in found.get("estimates", []):
        record = calibration["sites"].get(e["map"]) or {}
        made = _utc(record.get("measured"))
        if since is not None and made is not None and made < since:
            return f"{e['camera']}: map {e['map']} measured {record['measured']}, before the scene change at {config['scene_since']}"
        wanted, had = (config["cameras"].get(e["camera"]) or {}).get("id"), record.get("camera_id")
        if wanted and had and wanted != had:
            return f"{e['camera']}: map {e['map']} was fitted for another camera ({had}, now {wanted})"
    return None


def view_yaw(yaw_deg: float, previous_deg: float, limit_deg: float, square: bool = True, margin_deg: float = 20.0) -> float:
    """The equivalent yaw for a wrist-camera view that turns the wrist least from `previous_deg`. Symmetric jaws
    take yaw or yaw+180; a square box also yaw+-90. 2026-10-27: the roll jumped +61 -> -34 between two views
    2 cm apart and the visual servo diverged. Candidates inside +-(limit - margin) are preferred, so a roll near
    its limit takes the +90 turn instead of being forced to flip."""
    step = 90 if square else 180
    cands = [yaw_deg + k * step for k in range(-8, 9)]
    cands = [c for c in cands if abs(c) <= limit_deg]
    if not cands:
        raise ValueError(f"no equivalent yaw of {yaw_deg} within +-{limit_deg}")
    roomy = [c for c in cands if abs(c) <= limit_deg - margin_deg]
    return min(roomy or cands, key=lambda c: abs(c - previous_deg))


def fixture_clear(data: dict, x: float, y: float, z: float, yaw_deg: float, open_m: float, margin_m: float = 0.002):
    """None when both open fingertips, at grasp height z, clear every stored fixture surface, else the blocking
    (finger point, fixture name, its z). 2026-10-27: open jaws (56) landed on a tray rim about 2 cm above the
    box top four times. Assumes the jaws open along the yaw direction; unmeasured on the arm, and a fixture
    without a touched point near the finger is not seen (surface_z only knows what was touched)."""
    for sign in (-1, 1):
        fx, fy = x + sign * open_m / 2 * math.cos(math.radians(yaw_deg)), y + sign * open_m / 2 * math.sin(math.radians(yaw_deg))
        hit = cal.surface_z(data, fx, fy, kinds=("fixture",))
        if hit and hit[0] > z + margin_m:
            return (round(fx, 4), round(fy, 4)), hit[1], hit[0]
    return None
