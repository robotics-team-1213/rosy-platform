"""The pick's pure geometry, split from cell_auto_pick at its 600-line cap (D-766 2):
site heights and grasp depth, destination parsing, the closing yaw, the jaw opening for
a width, and the reachable end shifts of a long box. No I/O; `cell_auto_pick` keeps the
names re-exported for its callers and tests."""
import math

import cell_params as prm
import cell_place_fit
from cell_observe import wrap90


def grasp_depth(config: dict, site: str) -> float:
    """How far under the object's top this site grips (`grasp_depth_m`); also sets the release height so the box lands flat."""
    s = config["sites"].get(site) or cell_place_fit.with_tiers(config)[0]["sites"][site]
    return s.get("grasp_depth_m", prm.get(config.get("params"), "auto.grasp_depth_m", 0.015))


def surface_z(config: dict, site: str) -> float:
    """The site's surface height (m), which every auto-pick site must state (grasp height = top height - grasp depth)."""
    s = config["sites"].get(site) or cell_place_fit.with_tiers(config)[0]["sites"][site]
    if "surface_z" not in s:
        raise SystemExit(f"site {site!r}: auto pick needs `surface_z` (the surface height in metres)")
    z0, depth = round(s["surface_z"] + s.get("layer", 0) * s.get("tier_step_m", 0.0), 4), grasp_depth(config, site)
    if "z" in s and s["z"] < z0 + depth - 1e-9:
        raise SystemExit(f"site {site!r}: z {s['z']} is below surface_z {z0} + grasp depth {depth}")
    return z0


def parse_dest(config: dict, source: str, dest: str):
    """A site name, or 'x,y' metres on the source surface -> (site, (x, y))."""
    return (dest, tuple(config["sites"][dest]["place"])) if dest in config["sites"] else (source, tuple(float(v) for v in dest.split(",")))


def grasp_yaw(config: dict, site: str, o: dict, entry: dict, offset) -> float:
    """Tool yaw (deg) for a closing-axis candidate. The jaws close along tool y = yaw + offset, and must close
    across the object (long axis + jaw_axis_deg_from_long); yaw and yaw + 180 are the same grasp, the one
    nearest the site's own yaw is taken. A square object is only squared up to the site yaw."""
    base = config["sites"][site]["yaw_deg"]
    if offset is None:
        return round(base + max(-10.0, min(10.0, wrap90(o["long_axis_deg"] - base))), 1)
    yaw = o["long_axis_deg"] + entry["grasp"].get("jaw_axis_deg_from_long", 90) - offset
    return round(base + (yaw - base + 90) % 180 - 90, 1)


def across(entry: dict) -> float:
    """The object's size between the jaws: its width when they close across the long axis (jaw_axis_deg_from_long 90),
    its length when they close along it (0): a 90 mm 3-cell held by its ends needs a 90 mm gap, not 30 (2026-11-04)."""
    return entry["width_mm"] if entry.get("grasp", {}).get("jaw_axis_deg_from_long", 90) % 180 == 90 else entry["length_mm"]


def jaw_open_for(width_mm: float, params=None, margin_mm: float | None = None) -> float:
    """The jaw value whose finger gap is the object width plus a margin each side. Measured 2026-10-29 from the wrist
    view: about 10.4 mm of gap per unit, 30 mm held at 52.3. Opening to 62 put the fingers ~40 mm out, onto the 2-cells
    standing next to the box; 56 put a finger on the board edge."""
    g = lambda name: prm.get(params, name)  # noqa: E731
    margin = g("auto.jaw_margin_mm") if margin_mm is None else margin_mm  # less where a neighbour is near (finger_room)
    value = g("gripper.held_30mm") + (width_mm + 2 * margin - 30.0) / g("gripper.gap_mm_per_unit")
    if value > g("gripper.open_max"):  # clamped, the fingers would come down on the object (2026-11-04)
        raise SystemExit(f"a {width_mm:.0f} mm object needs the jaws at {value:.1f}, past gripper.open_max {g('gripper.open_max')}")
    return round(max(value, g("gripper.held_30mm") + 0.5), 2)


def reachable_ends(o: dict, entry: dict, params=None) -> list:
    """Grasp points shifted along a long box's axis, toward the arm's base first: grasp.end_frac of the way from
    the middle to where the jaws would reach the box's end. A square box has none."""
    reach = prm.get(params, "grasp.end_frac") * (entry["length_mm"] - entry["width_mm"]) / 2000
    if reach <= 0 or "grasp_shift_mm" in o or across(entry) == entry["length_mm"]:
        return []  # an end is not shifted again; jaws holding a box by its ends must straddle it, centred (2026-11-04)
    u = math.radians(o["long_axis_deg"])
    ends = [dict(o, raw_m=[o["raw_m"][0] + k * reach * math.cos(u), o["raw_m"][1] + k * reach * math.sin(u)],
                 grasp_shift_mm=round(1000 * k * reach, 1)) for k in (1, -1)]
    return sorted(ends, key=lambda e: math.hypot(*e["raw_m"]))
