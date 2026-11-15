"""Sim-ranked carry offers (`carry.tier{N}`, tools/sim/omx_carry_sweep.py offers --merge) applied to one attempt (D-872, D-947).

The best offer for the destination tier overrides three values only: the grip depth (params auto.grasp_depth_m), the release height
over the seat (the destination site's place_dz) and the jaw margin (params auto.jaw_margin_mm). Every value is clamped to the narrower
of cell_params and the sweep's BOUNDS, never wider; a missing or malformed offer leaves the defaults. The outcome of the attempt goes
back to the same candidate (`outcome`), so the choice learns from real tries. A sim win is a candidate, not real evidence.

  offer value: {"candidate", "tier", "auto.grasp_depth_m", "place_dz", "auto.jaw_margin_mm"} (the sweep file's "site.place_dz_m" is read as place_dz)
"""
from __future__ import annotations

import math
import re

import cell_params as prm

SWEEP_TO_REAL = {"site.place_dz_m": "place_dz"}  # the one place the sweep's key and the plan's key differ
BOUNDS = {"auto.grasp_depth_m": (0.008, 0.024), "place_dz": (0.0, 0.010), "auto.jaw_margin_mm": (2.0, 6.5)}  # = omx_carry_sweep.BOUNDS


def tier_name(dest: str) -> str:
    m = re.search(r"-l(\d+)$", dest or "")
    return f"carry.tier{int(m.group(1)) + 1 if m else 1}"


def _limits(key: str, params) -> tuple[float, float]:
    lo, hi = BOUNDS[key]
    if key in prm.DEFAULTS:
        lo, hi = max(lo, prm.DEFAULTS[key][2]), min(hi, prm.DEFAULTS[key][3])
    if key == "auto.jaw_margin_mm":
        lo = max(lo, float(prm.get(params, "auto.min_jaw_margin_mm")))
    if lo > hi:  # the cell's own floor is above the sweep's ceiling: no safe value, never widen
        raise ValueError(f"{key}: floor {lo} is above ceiling {hi}")
    return lo, hi


def apply(config: dict, choices, dest: str, dest_site: str, log=print, source: str | None = None):
    """(config with the offer applied, (name, value) applied or None, shadow or None). The input config is not changed.

    A site that states its own grasp_depth_m (the source) or place_dz (the destination) is a measured value: it wins, the whole offer
    is left unapplied (its candidate was not what ran), and `shadow` names it so the attempt row says so and nobody credits the offer."""
    name = tier_name(dest)
    try:
        value = choices.best(name)
        if value is None:
            return config, None, None
        if not isinstance(value, dict):
            raise ValueError("value is not an object")
        found = {SWEEP_TO_REAL.get(k, k): v for k, v in value.items() if SWEEP_TO_REAL.get(k, k) in BOUNDS}
        if not found:
            raise ValueError("no carry key in the value")
        if any(isinstance(v, bool) or not isinstance(v, (int, float)) or not math.isfinite(v) for v in found.values()):
            raise ValueError("a carry value is not a finite number")
        params = dict(config.get("params") or {})
        site_keys = {"auto.grasp_depth_m": (source, "grasp_depth_m"), "place_dz": (dest_site, "place_dz")}
        held = sorted(k for k in found if k in site_keys and site_keys[k][0] and site_keys[k][1] in (config["sites"].get(site_keys[k][0]) or {}))
        if held:
            log(f"{name}: offer shadowed by the site's own {held}, not applied")
            return config, None, {"offer": name, "candidate": value.get("candidate"), "keys": held}
        got = {}
        for key, v in found.items():
            lo, hi = _limits(key, params)
            got[key] = round(min(max(float(v), lo), hi), 5)
            if got[key] != v:
                log(f"{name}: {key} {v} clamped to {got[key]} ({lo}..{hi})")
        site = dict(config["sites"][dest_site])
        if "place_dz" in got:
            site["place_dz"] = got.pop("place_dz")
        out = dict(config, params=params | got, sites=dict(config["sites"], **{dest_site: site}))
    except (KeyError, TypeError, ValueError, AttributeError, OverflowError) as exc:  # OverflowError: a huge int in the store
        log(f"{name}: offer not applied, defaults kept ({type(exc).__name__}: {exc})")
        return config, None, None
    log(f"{name}: applied {value.get('candidate')} {found}")
    return out, (name, value), None


def outcome(choices, applied, ok: bool):
    """The attempt's real result for the offer that was applied (nothing when none was)."""
    if applied is not None:
        try:
            choices.outcome(*applied, ok, "carry applied")
            choices.save()
        except (KeyError, OSError) as exc:  # the real attempt happened; a store problem must not abort the run
            print(f"{applied[0]}: outcome not recorded ({type(exc).__name__}: {exc})")
