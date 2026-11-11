"""charge_bay_return.py — Low-battery evaluation and empty charging bay selection for Nav2 return-home/charging.

Provides:
- `ChargeBaySpec`: Charging bay coordinates `(id, x, y, yaw)` (defaults to Fleet R's C1/C2/C3 bays).
- `is_occupancy_cell_free`: Checks whether a `(x, y)` map point and its clearance radius are obstacle-free
  on a `/api/v1/map` occupancy grid (`cost < 65`, non-unknown).
- `select_empty_charge_bay`: Chooses the first charging bay that is not occupied by any peer pose
  (within `bay_radius_m`) and is obstacle-free on the occupancy grid (plus optional LiDAR range check).
- `evaluate_low_battery_charge_return`: Reads `/api/v1/power/health` (`battery.percent`, `battery.filtered_voltage`,
  `battery.level`), decides whether the robot should return to an empty charging bay (`percent <= go_percent`
  or `voltage <= go_voltage_v` or `level in ("warning", "critical", "deep")`), and selects the target bay.
- `dispatch_low_battery_charge_return`: Dispatches Nav2 (`POST /api/v1/navigation/goal`) to the selected
  empty charging bay and waits for `ARRIVED` (`result == SUCCEEDED`) when low battery is triggered.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Callable, Sequence

OCCUPIED_COST = 65
AT_BAY_RADIUS_M = 0.18
DEFAULT_GO_PERCENT = 15.0
DEFAULT_GO_VOLTAGE_V = 7.25


@dataclass(frozen=True)
class ChargeBaySpec:
    id: str
    x: float
    y: float
    yaw: float = 0.0


# Default Fleet R site map (`world_261026`) charging bays C1, C2, C3 + local map-frame charging bays
DEFAULT_CHARGE_BAYS: tuple[ChargeBaySpec, ...] = (
    ChargeBaySpec("C1", 0.0, 0.0, 0.0),
    ChargeBaySpec("C2", 0.22, 0.0, 0.0),
    ChargeBaySpec("C3", -0.22, 0.0, 0.0),
)

SITE_MAP_CHARGE_BAYS: tuple[ChargeBaySpec, ...] = (
    ChargeBaySpec("C1", -0.414, 0.47, -1.5708),
    ChargeBaySpec("C2", -0.190, 0.47, -1.5708),
    ChargeBaySpec("C3", 0.032, 0.47, -1.5708),
)


def parse_charge_bays(spec_str: str | None) -> tuple[ChargeBaySpec, ...]:
    """Parse `'C1:0.0,0.0,0.0;C2:0.22,0.0,0.0'` into `ChargeBaySpec` items, or return `DEFAULT_CHARGE_BAYS`."""
    if not spec_str or not spec_str.strip():
        return DEFAULT_CHARGE_BAYS
    if spec_str.strip().lower() == "site":
        return SITE_MAP_CHARGE_BAYS
    bays: list[ChargeBaySpec] = []
    for item in spec_str.split(";"):
        item = item.strip()
        if not item:
            continue
        bay_id, coords = item.split(":", 1)
        parts = [float(x.strip()) for x in coords.split(",")]
        if len(parts) == 2:
            bays.append(ChargeBaySpec(bay_id.strip(), parts[0], parts[1], 0.0))
        elif len(parts) == 3:
            bays.append(ChargeBaySpec(bay_id.strip(), parts[0], parts[1], parts[2]))
        else:
            raise ValueError(f"Invalid charge bay spec: {item}")
    return tuple(bays)


def is_occupancy_cell_free(
    map_payload: dict | None,
    x: float,
    y: float,
    clearance_m: float = 0.10,
    occupied_cost: int = OCCUPIED_COST,
) -> bool:
    """Return True if `(x, y)` and cells within `clearance_m` are free (`0 <= cost < occupied_cost`) on `/api/v1/map`."""
    if not isinstance(map_payload, dict) or "data" not in map_payload:
        return True
    try:
        width = int(map_payload["width"])
        height = int(map_payload["height"])
        res = float(map_payload["resolution"])
        data = map_payload["data"]
        origin = map_payload.get("origin") or {}
        ox = float(origin.get("x", 0.0))
        oy = float(origin.get("y", 0.0))
        oyaw = float(origin.get("yaw", origin.get("theta", 0.0)) or 0.0)
    except (KeyError, TypeError, ValueError):
        return True
    if width <= 0 or height <= 0 or res <= 0 or not isinstance(data, (list, tuple)) or len(data) < width * height:
        return True

    dx, dy = x - ox, y - oy
    cos_y, sin_y = math.cos(-oyaw), math.sin(-oyaw)
    gx = dx * cos_y - dy * sin_y
    gy = dx * sin_y + dy * cos_y
    cx, cy = int(math.floor(gx / res)), int(math.floor(gy / res))
    rad_cells = max(0, int(math.ceil(clearance_m / res)))

    for j in range(cy - rad_cells, cy + rad_cells + 1):
        for i in range(cx - rad_cells, cx + rad_cells + 1):
            if math.hypot(i - cx, j - cy) * res > clearance_m + 1e-6:
                continue
            if i < 0 or j < 0 or i >= width or j >= height:
                return False
            val = data[j * width + i]
            if val < 0 or val >= occupied_cost:
                return False
    return True


def select_empty_charge_bay(
    bays: Sequence[ChargeBaySpec],
    occupied_poses: Sequence[tuple[float, float]] = (),
    map_payload: dict | None = None,
    bay_radius_m: float = AT_BAY_RADIUS_M,
    clearance_m: float = 0.10,
) -> tuple[ChargeBaySpec | None, list[dict]]:
    """Select the first empty charging bay that is neither occupied by another robot nor blocked on the map grid."""
    statuses: list[dict] = []
    chosen: ChargeBaySpec | None = None

    for bay in bays:
        peer_hit = any(math.dist((bay.x, bay.y), (px, py)) <= bay_radius_m for px, py in occupied_poses)
        grid_free = is_occupancy_cell_free(map_payload, bay.x, bay.y, clearance_m=clearance_m)
        if peer_hit:
            state = "occupied_by_robot"
        elif not grid_free:
            state = "blocked_on_map"
        else:
            state = "free"
            if chosen is None:
                chosen = bay
                state = "selected"
        statuses.append({"bay": bay.id, "x": bay.x, "y": bay.y, "yaw": bay.yaw, "state": state})

    return chosen, statuses


def evaluate_low_battery_charge_return(
    power_health: dict | None,
    bays: Sequence[ChargeBaySpec] = DEFAULT_CHARGE_BAYS,
    occupied_poses: Sequence[tuple[float, float]] = (),
    map_payload: dict | None = None,
    go_percent: float = DEFAULT_GO_PERCENT,
    go_voltage_v: float = DEFAULT_GO_VOLTAGE_V,
    bay_radius_m: float = AT_BAY_RADIUS_M,
    clearance_m: float = 0.10,
) -> dict:
    """Evaluate battery health and select an empty charging bay when battery is at or below threshold."""
    bat = (power_health or {}).get("battery") if isinstance(power_health, dict) and "battery" in power_health else (power_health or {})
    pct = bat.get("percent")
    volt = bat.get("filtered_voltage")
    level = str(bat.get("level") or "").lower()

    pct_val = float(pct) if isinstance(pct, (int, float)) and math.isfinite(pct) else None
    volt_val = float(volt) if isinstance(volt, (int, float)) and math.isfinite(volt) else None

    triggers: list[str] = []
    if pct_val is not None and pct_val <= go_percent:
        triggers.append(f"percent_low({pct_val:.1f}%<={go_percent:.1f}%)")
    if volt_val is not None and volt_val <= go_voltage_v:
        triggers.append(f"voltage_low({volt_val:.3f}V<={go_voltage_v:.3f}V)")
    if level in ("warning", "critical", "deep"):
        triggers.append(f"level_{level}")

    low_battery = bool(triggers)
    chosen, bay_statuses = select_empty_charge_bay(
        bays, occupied_poses=occupied_poses, map_payload=map_payload, bay_radius_m=bay_radius_m, clearance_m=clearance_m
    )

    if not low_battery:
        action = "continue_work"
        reason = "battery_ok"
    elif chosen is None:
        action = "hold_wait_bay"
        reason = "no_empty_charge_bay"
    else:
        action = "go_charge"
        reason = ",".join(triggers)

    return {
        "low_battery": low_battery,
        "action": action,
        "reason": reason,
        "battery": {"percent": pct_val, "filtered_voltage": volt_val, "level": level or None},
        "thresholds": {"go_percent": go_percent, "go_voltage_v": go_voltage_v},
        "selected_bay": None if chosen is None else {"id": chosen.id, "x": chosen.x, "y": chosen.y, "yaw": chosen.yaw},
        "bays": bay_statuses,
    }


def dispatch_low_battery_charge_return(
    api: Callable[[str, dict | None, str | None], dict | None],
    token: str,
    wait_goal_fn: Callable[..., dict],
    bays: Sequence[ChargeBaySpec] = DEFAULT_CHARGE_BAYS,
    occupied_poses: Sequence[tuple[float, float]] = (),
    go_percent: float = DEFAULT_GO_PERCENT,
    go_voltage_v: float = DEFAULT_GO_VOLTAGE_V,
    goal_timeout_s: float = 35.0,
    clearance_m: float = 0.10,
) -> dict:
    """Check `/api/v1/power/health` and `/api/v1/map`; if battery is low, navigate to the first empty charging bay."""
    power_health = api("/api/v1/power/health", None, token) or {}
    try:
        map_payload = api("/api/v1/map", None, token) or {}
    except Exception:
        map_payload = {}
    decision = evaluate_low_battery_charge_return(
        power_health,
        bays=bays,
        occupied_poses=occupied_poses,
        map_payload=map_payload,
        go_percent=go_percent,
        go_voltage_v=go_voltage_v,
        clearance_m=clearance_m,
    )
    if decision["action"] != "go_charge":
        return {**decision, "dispatched": False, "charge_outcome": None}

    bay = decision["selected_bay"]
    charge_goal = {"x": round(bay["x"], 3), "y": round(bay["y"], 3), "theta": round(bay["yaw"], 3)}
    dispatch_resp = api("/api/v1/navigation/goal", charge_goal, token)
    outcome = wait_goal_fn(api, token, timeout_s=goal_timeout_s)
    if outcome.get("navigation") != "ARRIVED":
        raise RuntimeError(f"Low-battery charging bay navigation did not arrive: {outcome}")

    return {
        **decision,
        "dispatched": True,
        "charge_goal": charge_goal,
        "charge_dispatch": dispatch_resp,
        "charge_outcome": outcome,
    }
