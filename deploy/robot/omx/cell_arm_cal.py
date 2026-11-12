#!/usr/bin/env python3
"""Per-arm automatic calibration and profile persistence (`arm-cal-<arm_id>.json`).

Single Responsibility:
  - Loads, applies, updates via EMA, and persists per-arm calibration profiles (`profile_path`,
    `default_profile`, `load`, `save`, `apply_to_config`, `record_wrist_observation`,
    `record_grasp_measurement`).
  - Calculus & trend-based grasp/slip dynamics analysis (`evaluate_grasp_dynamics`, `infer_holding`)
    lives in `cell_grasp_dynamics.py` and is re-exported here for backward compatibility.
"""
from __future__ import annotations

import json
from pathlib import Path
import time
from typing import Any

from cell_grasp_dynamics import (  # noqa: F401  (re-exported)
    _extract_arm_load_ma,
    _extract_jaw_and_current,
    evaluate_grasp_dynamics,
    infer_holding,
)
import cell_params as prm

SCHEMA = "rosy.omx-arm-calibration.v1"
MAX_HISTORY = 20
_CAL_CACHE: dict[str, tuple[int, int, dict[str, Any]]] = {}


def _copy_profile(prof: dict[str, Any]) -> dict[str, Any]:
    out = dict(prof)
    if isinstance(out.get("finger_sign"), dict):
        out["finger_sign"] = dict(out["finger_sign"])
    if isinstance(out.get("history"), list):
        out["history"] = [dict(h) if isinstance(h, dict) else h for h in out["history"]]
    return out

ARM_DEFAULTS: dict[str, dict[str, Any]] = {
    "arm_s": {
        "finger_color": "dark",
        "parallax_px": 0.0,
        "finger_sign": {"along": 1.0, "across": 1.0},
        "held_30mm": 52.3,
        "grip_closed": 48.8,
        "hold_current_ma": 95,
        "jaw_margin_mm": 6.0,
        "gap_mm_per_unit": 5.0,
    },
    "arm_a": {
        "finger_color": "white",
        "parallax_px": 0.0,
        "finger_sign": {"along": -1.0, "across": 1.0},
        "held_30mm": 54.3,
        "grip_closed": 48.8,
        "hold_current_ma": 80,
        "jaw_margin_mm": 9.5,
        "gap_mm_per_unit": 5.0,
    },
    "arm_b": {
        "finger_color": "white",
        "parallax_px": 0.0,
        "finger_sign": {"along": -1.0, "across": 1.0},
        "held_30mm": 54.3,
        "grip_closed": 48.8,
        "hold_current_ma": 80,
        "jaw_margin_mm": 9.8,
        "gap_mm_per_unit": 5.0,
    },
}


def profile_path(config_or_work: dict | Path, arm_id: str | None = None) -> Path:
    """Resolve the persistent `arm-cal-<arm_id>.json` path for an arm."""
    if isinstance(config_or_work, dict):
        arm = arm_id or config_or_work.get("arm_id", "arm_s")
        if config_or_work.get("arm_calibration_path"):
            return Path(config_or_work["arm_calibration_path"]).expanduser()
        work = Path(config_or_work.get("work_dir", ".")).expanduser()
        return work / f"arm-cal-{arm}.json"
    arm = arm_id or "arm_s"
    return Path(config_or_work).expanduser() / f"arm-cal-{arm}.json"


def default_profile(arm_id: str = "arm_s") -> dict[str, Any]:
    base = dict(ARM_DEFAULTS.get(arm_id, ARM_DEFAULTS["arm_s"]))
    base["finger_sign"] = dict(base["finger_sign"])
    held = float(base["held_30mm"])
    margin = float(base["jaw_margin_mm"])
    slope = float(base["gap_mm_per_unit"])
    open_30 = round(held + (2.0 * margin) / slope, 2)
    return {
        "schema": SCHEMA,
        "arm_id": arm_id,
        **base,
        "grip_open_30mm": open_30,
        "grip_release_30mm": round(max(held + 1.8, open_30 - 0.6), 2),
        "samples": 0,
        "updated_at": None,
        "history": [],
    }


def load(config_or_work: dict | Path, arm_id: str | None = None) -> dict[str, Any]:
    """Load the per-arm calibration profile, merging with per-arm defaults if missing or partial."""
    arm = arm_id or (config_or_work.get("arm_id", "arm_s") if isinstance(config_or_work, dict) else "arm_s")
    path = profile_path(config_or_work, arm)
    try:
        st = path.stat()
    except OSError:
        return default_profile(arm)
    key = f"{path}:{arm}"
    cached = _CAL_CACHE.get(key)
    if cached is not None and cached[0] == st.st_mtime_ns and cached[1] == st.st_size:
        return _copy_profile(cached[2])
    prof = default_profile(arm)
    try:
        saved = json.loads(path.read_text(encoding="utf-8"))
        if isinstance(saved, dict) and saved.get("schema") == SCHEMA:
            for k, v in saved.items():
                if v is not None:
                    prof[k] = v
            _CAL_CACHE[key] = (st.st_mtime_ns, st.st_size, _copy_profile(prof))
    except (OSError, ValueError):
        pass
    return prof


def save(config_or_work: dict | Path, profile: dict[str, Any], arm_id: str | None = None) -> Path:
    """Persist the per-arm calibration profile atomically."""
    arm = (
        arm_id
        or profile.get("arm_id")
        or (config_or_work.get("arm_id", "arm_s") if isinstance(config_or_work, dict) else "arm_s")
    )
    profile = dict(profile, schema=SCHEMA, arm_id=arm, updated_at=time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()))
    path = profile_path(config_or_work, arm)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(profile, indent=2), encoding="utf-8")
    _CAL_CACHE.pop(f"{path}:{arm}", None)
    return path


def apply_to_config(config: dict[str, Any]) -> dict[str, Any]:
    """Apply the loaded per-arm calibration profile into `config['params']`, `config['plan']`, and `config['wrist']`."""
    arm = config.get("arm_id", "arm_s")
    cal = load(config, arm)
    config["_arm_calibration"] = cal
    params = dict(config.get("params") or {})
    color_code = 1 if cal.get("finger_color") == "dark" else (2 if cal.get("finger_color") == "white" else 0)
    if prm.get(params, "wrist.finger_color", 0) == 0 and color_code:
        params["wrist.finger_color"] = color_code
    if cal.get("samples", 0) > 0:
        params["gripper.held_30mm"] = round(float(cal["held_30mm"]), 2)
        params["auto.jaw_margin_mm"] = round(float(cal["jaw_margin_mm"]), 2)
        params["auto.jaw_margin_max_mm"] = round(
            max(float(params.get("auto.jaw_margin_max_mm", 8.0)), float(cal["jaw_margin_mm"]) + 0.5), 2
        )
    config["params"] = params

    plan = dict(config.get("plan") or {})
    if cal.get("samples", 0) > 0 or plan.get("hold_current_ma", 0) > 125:
        plan["hold_current_ma"] = int(cal["hold_current_ma"])
    if cal.get("samples", 0) > 0:
        plan["grip_open"] = float(cal["grip_open_30mm"])
        plan["grip_release"] = float(cal["grip_release_30mm"])
    config["plan"] = plan

    wrist = dict(config.get("wrist") or {})
    wrist.setdefault("finger_color", cal.get("finger_color", "auto"))
    wrist.setdefault("parallax_px", float(cal.get("parallax_px", 0.0)))
    wrist.setdefault("finger_sign", dict(cal.get("finger_sign") or {"along": 1.0, "across": 1.0}))
    config["wrist"] = wrist
    return config


def record_wrist_observation(
    config_or_work: dict | Path,
    *,
    arm_id: str | None = None,
    finger_color: str | None = None,
    finger_sign: dict[str, float] | None = None,
    parallax_px: float | None = None,
) -> dict[str, Any]:
    """Persist learned wrist-camera finger polarity, servo axis sign, and optical parallax."""
    prof = load(config_or_work, arm_id)
    changed = False
    if finger_color in ("dark", "white") and prof.get("finger_color") != finger_color:
        prof["finger_color"] = finger_color
        changed = True
    if isinstance(finger_sign, dict):
        cur = dict(prof.get("finger_sign") or {"along": 1.0, "across": 1.0})
        for k in ("along", "across"):
            if k in finger_sign and float(finger_sign[k]) in (-1.0, 1.0) and cur.get(k) != float(finger_sign[k]):
                cur[k] = float(finger_sign[k])
                changed = True
        prof["finger_sign"] = cur
    if parallax_px is not None:
        old_p = float(prof.get("parallax_px", 0.0))
        new_p = (
            round(0.7 * old_p + 0.3 * float(parallax_px), 1)
            if prof.get("samples", 0) > 0
            else round(float(parallax_px), 1)
        )
        if abs(new_p - old_p) >= 0.2:
            prof["parallax_px"] = new_p
            changed = True
    if changed or not profile_path(config_or_work, arm_id).exists():
        save(config_or_work, prof, arm_id)
    return prof


def record_grasp_measurement(
    config_or_work: dict | Path,
    *,
    arm_id: str | None = None,
    gripper_pos: float | None,
    gripper_current_ma: float | None,
    width_mm: float = 30.0,
    skew_mm: float | None = None,
    mm_per_px: float | None = None,
    finger_color: str | None = None,
) -> dict[str, Any]:
    """Update and persist the per-arm gripper and wrist calibration from a verified stable grasp."""
    prof = load(config_or_work, arm_id)
    closed = float(prof.get("grip_closed", 48.8))
    if gripper_pos is None or float(gripper_pos) <= closed + 2.0:
        return prof

    n = int(prof.get("samples", 0))
    alpha = 0.35 if n > 0 else 1.0
    slope = float(prof.get("gap_mm_per_unit", 5.0))
    implied_30mm = float(gripper_pos) - (float(width_mm) - 30.0) / max(slope, 1.0)
    held = round((1.0 - alpha) * float(prof.get("held_30mm", implied_30mm)) + alpha * implied_30mm, 2)
    prof["held_30mm"] = held

    if gripper_current_ma is not None and abs(float(gripper_current_ma)) >= 50.0:
        target_curr = max(65, min(120, round(0.68 * abs(float(gripper_current_ma)))))
        old_curr = int(prof.get("hold_current_ma", target_curr))
        prof["hold_current_ma"] = int(round((1.0 - alpha) * old_curr + alpha * target_curr))

    if finger_color in ("dark", "white"):
        prof["finger_color"] = finger_color
    is_white = prof.get("finger_color") == "white"
    margin = float(prof.get("jaw_margin_mm", 9.8 if is_white else 6.0))
    if is_white and margin < 8.5:
        margin = 9.8
    prof["jaw_margin_mm"] = round(margin, 2)
    open_30 = round(held + (2.0 * margin) / max(slope, 1.0), 2)
    prof["grip_open_30mm"] = open_30
    prof["grip_release_30mm"] = round(max(held + 1.8, open_30 - 0.6), 2)

    if skew_mm is not None and mm_per_px and float(mm_per_px) > 0.02 and abs(float(skew_mm)) <= 6.0:
        delta_px = float(skew_mm) / float(mm_per_px)
        prof["parallax_px"] = round(float(prof.get("parallax_px", 0.0)) + 0.25 * delta_px, 1)

    prof["samples"] = n + 1
    hist = list(prof.get("history") or [])
    hist.append(
        {
            "t": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            "gripper_pos": round(float(gripper_pos), 2),
            "gripper_current_ma": round(float(gripper_current_ma), 1) if gripper_current_ma is not None else None,
            "held_30mm": held,
            "hold_current_ma": prof["hold_current_ma"],
            "skew_mm": round(float(skew_mm), 2) if skew_mm is not None else None,
        }
    )
    prof["history"] = hist[-MAX_HISTORY:]
    save(config_or_work, prof, arm_id)
    return prof
