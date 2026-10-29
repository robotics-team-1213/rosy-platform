#!/usr/bin/env python3
"""The arm S cell's decided thresholds as one managed file (rosy.omx-cell-params.v1, D-904), stdlib only.

Each value: {"value", "unit", "source": measured|taught|theory|tuned|default, "evidence": "<date, what showed it>"}.
DEFAULTS below equal the constants the modules shipped with, so no file (or a file naming a few values) behaves
exactly as before; a module reads a value with get(values, name, fallback). Changing a threshold is a data edit.
  python cell_params.py cell-params.example.json      # validate, print the digest of the effective values
"""
from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path

SCHEMA = "rosy.omx-cell-params.v1"
SOURCES = ("measured", "taught", "theory", "tuned", "default")
# name: (default, unit, lowest, highest); counts are ints, the rest numbers
DEFAULTS = {
    "objects.chroma": (25.0, "lab", 1, 100), "objects.light": (60.0, "lab", 1, 255),
    "objects.min_px": (150, "px", 1, 100000), "objects.split_fill": (0.8, "ratio", 0.1, 1.0),
    "objects.split_axis_deg": (12.0, "deg", 0, 45), "objects.open_px": (3, "px", 1, 15),
    "objects.close_px": (5, "px", 1, 31), "objects.surface_min_px": (12000, "px", 500, 300000),
    "pivot.still_px": (40, "px", 1, 100000), "pivot.diff_px": (30, "gray", 1, 255),
    "pivot.min_blob": (300, "px", 1, 100000), "pivot.max_blob": (90, "px", 1, 1000),
    "pivot.follow_px": (60, "px", 1, 1000), "pivot.agree_px": (3.0, "px", 0.1, 50),
    "pivot.bias_reach_mm": (80.0, "mm", 1, 500), "pivot.settle_limit_s": (5.0, "s", 0.5, 60),
    "pivot.settle_step_s": (0.4, "s", 0.05, 5), "pivot.grip_closed": (50.5, "gripper", 0, 100),
    "pivot.max_rms_mm": (5.0, "mm", 0.5, 30), "pivot.radius_lo_mm": (12.0, "mm", 1, 100), "pivot.radius_hi_mm": (40.0, "mm", 5, 200),
    "auto.temp_stop_c": (55, "C", 30, 80), "auto.pwm_fraction": (0.8, "ratio", 0.1, 1.0),
    "auto.pwm_window_s": (1.5, "s", 0.1, 30), "auto.pwm_move_units": (0.3, "joint_unit", 0.0, 5), "auto.approach_near_m": (0.020, "m", 0.005, 0.2),
    "auto.grasp_depth_m": (0.015, "m", 0.0, 0.05), "auto.clear_mm": (55.0, "mm", 1, 500),
    "auto.finger_mm": (8.0, "mm", 0, 100), "auto.closing_theory_deg": (90, "deg", -180, 180),
    "auto.closing_alt_deg": (0, "deg", -180, 180),
    "auto.fold_before_transport": (1, "flag", 0, 1), "auto.bias_from_place": (1, "flag", 0, 1),
    "auto.bias_learn_max_mm": (15.0, "mm", 1, 50),
    "calibrate.max_shift_px": (6.0, "px", 1, 50), "calibrate.bias_near_mm": (30.0, "mm", 5, 120), "auto.attempts": (3, "count", 1, 6), "diagnose.top_band_mm": (4.0, "mm", 1, 30), "diagnose.surface_band_mm": (3.0, "mm", 0.5, 15),
    "auto.jaw_margin_mm": (8.0, "mm", 2, 25), "gripper.gap_mm_per_unit": (10.4, "mm", 3, 30),
    "gripper.held_30mm": (52.3, "gripper", 45, 60), "gripper.open_max": (56.0, "gripper", 50, 70),
    "reach.enabled": (1, "flag", 0, 1), "reach.tol_mm": (2.0, "mm", 0.5, 10), "reach.max_iter": (2, "count", 0, 5),
    "reach.max_mm": (20.0, "mm", 2, 50),
    "wrist.enabled": (0, "flag", 0, 1), "wrist.finger_servo": (0, "flag", 0, 1), "wrist.neutral_ring_chroma": (20.0, "lab", 2, 60),
    "wrist.min_blob_px": (3000, "px", 100, 200000), "wrist.servo_gain": (0.5, "ratio", 0.1, 1.0), "wrist.servo_across": (0, "flag", 0, 1), "wrist.ref_servo": (1, "flag", 0, 1),
    "wrist.probe_mm": (6.0, "mm", 2, 15), "wrist.ref_tol_px": (12.0, "px", 3, 60), "wrist.ref_estimate": (1, "flag", 0, 1),
    "wrist.z_probe_mm": (10.0, "mm", 3, 30), "wrist.tip_to_top_mm": (25.0, "mm", 0, 80),
    "wrist.servo_iter": (4, "count", 1, 8), "wrist.servo_total_mm": (60.0, "mm", 5, 100), "wrist.tol_mm": (3.0, "mm", 0.5, 20), "wrist.max_step_mm": (25.0, "mm", 1, 60),
    "wrist.max_total_mm": (30.0, "mm", 1, 80), "wrist.max_iter": (2, "count", 0, 5),
    "wrist.topmap_disagree_mm": (35.0, "mm", 1, 100), "wrist.edge_margin_px": (12, "px", 0, 100),
    "wrist.area_lo": (0.6, "ratio", 0.1, 1.0), "wrist.area_hi": (1.6, "ratio", 1.0, 5.0),
    "wrist.fill_min": (0.7, "ratio", 0.1, 1.0), "wrist.axis_tol_deg": (15.0, "deg", 1, 90),
    "wrist.fit_rms_max_px": (4.0, "px", 0.5, 50), "wrist.cal_offset_mm": (8.0, "mm", 2, 30),
    "pinch.enabled": (1, "flag", 0, 1), "pinch.band_px": (40, "px", 5, 200), "pinch.min_gap_mm": (2.0, "mm", 0, 20),
    "pinch.width_tol": (0.35, "ratio", 0.05, 1.0), "pinch.max_iter": (3, "count", 0, 5), "pinch.max_step_mm": (20.0, "mm", 1, 40),
    "pinch.mount_tol_px": (40.0, "px", 5, 200),
    "look.enabled": (0, "flag", 0, 1), "look.tol_mm": (3.0, "mm", 0.5, 20), "look.max_iter": (4, "count", 0, 6),
    "look.max_total_mm": (30.0, "mm", 5, 80), "push.look_tol_mm": (6.0, "mm", 1, 15),
    "objects.split_touching": (1, "flag", 0, 1), "objects.split_peak_frac": (0.6, "ratio", 0.3, 0.9),
    "pivot.over_target": (0, "flag", 0, 1), "pivot.over_top_mm": (30.0, "mm", 5, 120), "pivot.over_clear_mm": (30.0, "mm", 10, 100),
    "feel.enabled": (1, "flag", 0, 1), "feel.step_mm": (12.0, "mm", 3, 30), "feel.tries": (4, "count", 0, 6),
    "push.height_m": (0.012, "m", 0.005, 0.03), "push.speed_m_s": (0.010, "m/s", 0.003, 0.03),
    "push.gap_mm": (10.0, "mm", 3, 40),
    "runner.pace_lag": (1.6, "joint_unit", 0.1, 5), "runner.pace_rise": (0.3, "joint_unit", 0, 5),
    "runner.pace_max_s": (3.0, "s", 0.1, 30), "runner.idle_park_s": (180.0, "s", 5, 7200),
    "runner.idle_stop_s": (180.0, "s", 5, 7200), "runner.contact_lag": (1.5, "joint_unit", 0.1, 5),
    "runner.contact_ticks": (2, "count", 1, 30), "runner.contact_rise": (0.6, "joint_unit", 0.1, 1.5),
    "runner.contact_loaded_max": (2.2, "joint_unit", 1.5, 2.3),
}


def default(name: str):
    return DEFAULTS[name][0]


def get(values, name: str, fallback=None):
    """The file's value, else `fallback` (a module's own constant), else the shipped default."""
    if values and name in values:
        return values[name]
    return default(name) if fallback is None else fallback


def digest(values: dict) -> str:
    return hashlib.sha256(json.dumps(values, sort_keys=True).encode()).hexdigest()[:12]


def validate(data: dict) -> dict:
    if not isinstance(data, dict) or data.get("schema") != SCHEMA or not isinstance(data.get("params"), dict):
        raise ValueError(f"not a {SCHEMA} file")
    values = {}
    for name, p in data["params"].items():
        if name not in DEFAULTS:
            raise ValueError(f"{name}: unknown parameter")
        dflt, unit, lo, hi = DEFAULTS[name]
        if not isinstance(p, dict) or any(k not in p for k in ("value", "unit", "source", "evidence")):
            raise ValueError(f"{name}: needs value, unit, source, evidence")
        v = p["value"]
        if isinstance(v, bool) or not isinstance(v, (int, float)) or (isinstance(dflt, int) and not isinstance(v, int)):
            raise ValueError(f"{name}: value {v!r} must be {'an integer' if isinstance(dflt, int) else 'a number'}")
        if p["unit"] != unit:
            raise ValueError(f"{name}: unit {p['unit']!r}, expected {unit!r}")
        if p["source"] not in SOURCES:
            raise ValueError(f"{name}: source {p['source']!r} not in {SOURCES}")
        if not isinstance(p["evidence"], str) or not p["evidence"].strip():
            raise ValueError(f"{name}: empty evidence")
        if not lo <= v <= hi:
            raise ValueError(f"{name}: {v} outside {lo}..{hi} {unit}")
        values[name] = v
    return values


def load(path=None) -> dict:
    """{"values": every parameter (the file's, else the default), "sha": digest of those effective values}."""
    chosen = validate(json.loads(Path(path).read_text(encoding="utf-8-sig"))) if path else {}
    values = {name: chosen.get(name, spec[0]) for name, spec in DEFAULTS.items()}
    return {"values": values, "sha": digest(values)}


if __name__ == "__main__":
    loaded = load(sys.argv[1])
    print(len(loaded["values"]), "parameters ok, sha", loaded["sha"])
