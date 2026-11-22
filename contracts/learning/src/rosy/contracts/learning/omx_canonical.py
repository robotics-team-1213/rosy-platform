"""Shared OMX Design 2 canonical start-pose spec, 2-phase bridge metadata, and pure envelope checks.

Single source of truth consumed by Learning Center curation (`data_gate.py`), training pipelines
(`canonical_pipeline.py`, `canonical_workers.py`), and HTTP API serialization (`canonical_web.py`).
Stdlib only; never grants real-robot control, Fleet ledger writes, or cell policy approval (D-911, D-1024).
"""
from __future__ import annotations

import copy
from dataclasses import dataclass
import hashlib
import json
import math
from pathlib import Path
import stat

SPEC_SCHEMA = "rosy.omx-canonical-start.v1"
LIVE_CHECK_SCHEMA = "rosy.omx-cell-live-check.v1"
JOINT_NAMES = ("shoulder_pan", "shoulder_lift", "elbow_flex", "wrist_flex", "wrist_roll", "gripper")
ARM_IDS = ("arm_a", "arm_b")
ENVELOPE_MARGIN = 3.0
FOLDED_TOL_NORM = 10.0
DATA_GATE_HOME_LIMIT_RAD = 0.35
HALF_TURN_NORM = 200.0 * 4096.0 / 4095.0 / 2.0
WRIST_ROLL_BRANCH_LIMIT_NORM = HALF_TURN_NORM / 4.0

AUTHORITY_STAMP = {
    "real_evidence": False,
    "physical_learning_verified": False,
    "policy_activation": False,
    "approval_owner": "fleet_policy_approval_and_cell_gate",
}

CANONICAL_START_V1 = {
    "schema": SPEC_SCHEMA,
    "design": "design2_idle_home_active_canonical",
    "sim_jaw_open": 0.5907,
    "sim_jaw_closed": 0.137,
    "open_gap_m": 0.042,
    "start_jitter_rad": 0.035,
    "idle_park": {
        "arm_a": {
            "norm": [0.8, -62.2, 53.1, 51.6, 45.2],
            "gripper_units": 48.8,
            "sim_rad": [0.02513, -1.95407, 1.66819, 1.62106, 1.42, 0.137],
        },
        "arm_b": {
            "norm": [0.8, -62.2, 53.1, 51.6, 45.2],
            "gripper_units": 48.8,
            "sim_rad": [0.02513, -1.95407, 1.66819, 1.62106, 1.42, 0.137],
        },
    },
    "canonical_start": {
        "arm_a": {
            "norm": [4.0, -55.0, 46.5, 49.0, 40.0],
            "gripper_units": 56.23,
            "sim_rad": [0.12566, -1.72788, 1.46084, 1.53938, 1.25664, 0.5907],
            "raw_ticks": [2130, 922, 3000, 3052, 2867, 2303],
        },
        "arm_b": {
            "norm": [6.0, -55.0, 46.5, 49.0, 40.0],
            "gripper_units": 55.78,
            "sim_rad": [0.1885, -1.72788, 1.46084, 1.53938, 1.25664, 0.5907],
            "raw_ticks": [2171, 922, 3000, 3052, 2867, 2285],
        },
    },
    "real_entry_bridge": {
        "folded_tol_norm": FOLDED_TOL_NORM,
        "pre_entry": "Gate.open -> cell_unwedge.rehome_before_work (lifts elbow_flex -10 before any large roll turn)",
        "phases": [
            {
                "phase": 1,
                "name": "unfold_clear",
                "joints": ["shoulder_lift", "elbow_flex", "wrist_flex"],
                "from_home_norm": [-62.2, 53.1, 51.6],
                "to_canonical_norm": [-55.0, 46.5, 49.0],
                "note": "Unfold/clear shoulder & elbow first to avoid arm_a wrist-camera-to-body contact",
            },
            {
                "phase": 2,
                "name": "align_pan_roll_and_preopen_jaw",
                "joints": ["shoulder_pan", "wrist_roll", "gripper"],
                "from_home_norm": {"arm_a": [0.8, 45.2, 48.8], "arm_b": [0.8, 45.2, 48.8]},
                "to_canonical_norm": {"arm_a": [4.0, 40.0, 56.23], "arm_b": [6.0, 40.0, 55.78]},
                "note": "Runs inside reviewed chunk library (D-911, never raw SSH arm motion)",
            },
        ],
    },
    "envelope_margins": {
        "arm_a_reviewed_note": "pan 4.0 (>=0.8+3.2), lift -55.0 (>=-62.2+7.2), elbow 46.5 (<=53.1-6.6), wrist_flex 49.0 in [45,55], wrist_roll 40.0 in [36,62]",
        "arm_b_reviewed_lib": {
            "source": "armb-slow-lib.json",
            "low_norm": [0.33, -62.2, 2.927, 43.142, -33.32, 48.8],
            "high_norm": [29.029, -10.148, 53.1, 57.307, 45.2, 56.58],
            "canonical_margins": {
                "shoulder_pan": {"val": 6.0, "low_margin": 5.67, "high_margin": 23.03},
                "shoulder_lift": {"val": -55.0, "low_margin": 7.2, "high_margin": 44.85},
                "elbow_flex": {"val": 46.5, "low_margin": 43.57, "high_margin": 6.6},
                "wrist_flex": {"val": 49.0, "low_margin": 5.86, "high_margin": 6.3, "holder_safe_band": [45.0, 55.0]},
                "wrist_roll": {"val": 40.0, "low_margin": 73.32, "high_margin": 5.2, "holder_safe_band": [36.0, 63.0]},
                "gripper_units": {"val": 55.78, "low_margin": 6.98, "high_margin": 0.8},
            },
            "data_gate_home_max_j234_rad": 0.239,
            "data_gate_with_2deg_jitter_max_rad": 0.274,
            "data_gate_limit_rad": DATA_GATE_HOME_LIMIT_RAD,
        },
    },
}


def _finite_number(value) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError("finite non-boolean number required")
    number = float(value)
    if not math.isfinite(number):
        raise ValueError("finite number required")
    return number


def _vector(raw, length: int, label: str) -> list[float]:
    if not isinstance(raw, list) or len(raw) != length:
        raise ValueError(f"{label} must have length {length}")
    return [_finite_number(item) for item in raw]


def _validate_arm_pose(pose: dict, label: str) -> None:
    if not isinstance(pose, dict):
        raise ValueError(f"{label} must be a mapping")
    _vector(pose.get("norm"), 5, f"{label}.norm")
    _finite_number(pose.get("gripper_units"))
    _vector(pose.get("sim_rad"), 6, f"{label}.sim_rad")
    if "raw_ticks" in pose:
        ticks = pose["raw_ticks"]
        if not isinstance(ticks, list) or len(ticks) != 6 or any(type(v) is not int or not 0 <= v <= 4096 for v in ticks):
            raise ValueError(f"{label}.raw_ticks must hold 6 ints in 0..4096")


def validate_canonical_spec(doc: dict) -> dict:
    """Validate Design 2 canonical start specification, disjoint 2-phase bridge, and data_gate margin."""
    if not isinstance(doc, dict) or doc.get("schema") != SPEC_SCHEMA:
        raise ValueError(f"canonical spec requires schema {SPEC_SCHEMA}")
    design = doc.get("design")
    if not isinstance(design, str) or not design.strip():
        raise ValueError("canonical spec design name required")
    for scalar_key in ("sim_jaw_open", "sim_jaw_closed", "open_gap_m"):
        _finite_number(doc.get(scalar_key))
    jitter = _finite_number(doc.get("start_jitter_rad"))
    if not 0.0 <= jitter <= 0.2:
        raise ValueError("start_jitter_rad must lie in 0.0..0.2 rad")

    for section in ("idle_park", "canonical_start"):
        block = doc.get(section)
        if not isinstance(block, dict) or set(block) != set(ARM_IDS):
            raise ValueError(f"{section} must declare arm_a and arm_b")
        for arm in ARM_IDS:
            _validate_arm_pose(block[arm], f"{section}.{arm}")

    for arm in ARM_IDS:
        idle_j234 = doc["idle_park"][arm]["sim_rad"][1:4]
        canon_j234 = doc["canonical_start"][arm]["sim_rad"][1:4]
        j234_dist = max(abs(a - b) for a, b in zip(canon_j234, idle_j234))
        if j234_dist + jitter >= DATA_GATE_HOME_LIMIT_RAD:
            raise ValueError(
                f"{arm} canonical start plus jitter ({j234_dist + jitter:.3f} rad) exceeds data_gate limit {DATA_GATE_HOME_LIMIT_RAD}"
            )

    bridge = doc.get("real_entry_bridge")
    if not isinstance(bridge, dict):
        raise ValueError("real_entry_bridge required")
    if _finite_number(bridge.get("folded_tol_norm")) != FOLDED_TOL_NORM:
        raise ValueError(f"real_entry_bridge.folded_tol_norm must be {FOLDED_TOL_NORM}")
    phases = bridge.get("phases")
    if not isinstance(phases, list) or len(phases) != 2 or not all(isinstance(p, dict) for p in phases):
        raise ValueError("real_entry_bridge must define exactly 2 phase mappings")
    p1, p2 = phases[0].get("joints"), phases[1].get("joints")
    if p1 != ["shoulder_lift", "elbow_flex", "wrist_flex"]:
        raise ValueError("phase 1 must unfold/clear shoulder_lift, elbow_flex, wrist_flex first")
    if p2 != ["shoulder_pan", "wrist_roll", "gripper"]:
        raise ValueError("phase 2 must align shoulder_pan, wrist_roll, gripper second")
    if set(p1) & set(p2) or sorted([*p1, *p2]) != sorted(JOINT_NAMES):
        raise ValueError("2-phase bridge joints must partition all 6 joints")
    return doc


def canonical_spec_sha256(doc: dict) -> str:
    validate_canonical_spec(doc)
    payload = json.dumps(doc, sort_keys=True, ensure_ascii=False, separators=(",", ":"), allow_nan=False).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def default_canonical_spec() -> dict:
    return validate_canonical_spec(copy.deepcopy(CANONICAL_START_V1))


def load_canonical_spec(path: Path | str | None = None) -> tuple[dict, str, str]:
    """Return (spec_dict, sha256, source_tag) from built-in default or verified regular JSON file."""
    if path is None:
        spec = default_canonical_spec()
        return spec, canonical_spec_sha256(spec), "builtin"
    target = Path(path)
    info = target.lstat()
    if target.is_symlink() or not stat.S_ISREG(info.st_mode) or info.st_size > 262144:
        raise ValueError("canonical spec file must be a bounded regular non-symlink JSON file")
    doc = json.loads(target.read_text(encoding="utf-8"))
    validate_canonical_spec(doc)
    return doc, canonical_spec_sha256(doc), "configured"


@dataclass(frozen=True)
class CanonicalEnvelope:
    low: tuple[float, ...]
    high: tuple[float, ...]
    home_roll: float


def canonical_envelope_from_library(library_doc: dict) -> CanonicalEnvelope:
    """Extract per-joint (min, max) bounds and home wrist_roll across a reviewed chunk library."""
    if not isinstance(library_doc, dict) or not isinstance(library_doc.get("chunks"), dict):
        raise ValueError("chunk library requires chunks mapping")
    chunks = library_doc["chunks"]
    mins = [math.inf] * 6
    maxs = [-math.inf] * 6
    count = 0
    for rows in chunks.values():
        if not isinstance(rows, (list, tuple)):
            raise ValueError("chunk library entries must be frame sequences")
        for frame in rows:
            vals = _vector(list(frame), 6, "chunk frame")
            for idx, val in enumerate(vals):
                if val < mins[idx]:
                    mins[idx] = val
                if val > maxs[idx]:
                    maxs[idx] = val
            count += 1
    if count == 0:
        raise ValueError("chunk library has no valid 6-axis frames")
    home_rows = chunks.get("home")
    if not isinstance(home_rows, (list, tuple)) or not home_rows:
        raise ValueError("chunk library requires non-empty home chunk for wrist_roll branch check")
    home_last = _vector(list(home_rows[-1]), 6, "home[-1]")
    return CanonicalEnvelope(low=tuple(mins), high=tuple(maxs), home_roll=home_last[4])


def evaluate_chunk_envelope(chunk_rows, env: CanonicalEnvelope, *, margin: float = ENVELOPE_MARGIN) -> dict:
    """Check one 6-axis action chunk against strict & margined envelopes plus wrist_roll branch safety."""
    if not isinstance(chunk_rows, (list, tuple)) or not chunk_rows:
        raise ValueError("non-empty 6-axis chunk required")
    rows = [_vector(list(row), 6, "chunk row") for row in chunk_rows]
    margin_val = _finite_number(margin)
    strict_oor = []
    margin_oor = []
    for joint_idx, name in enumerate(JOINT_NAMES):
        vals = [row[joint_idx] for row in rows]
        mn, mx = min(vals), max(vals)
        lo, hi = env.low[joint_idx], env.high[joint_idx]
        if mn < lo or mx > hi:
            strict_oor.append({
                "joint": joint_idx, "name": name,
                "min": round(mn, 3), "max": round(mx, 3),
                "low": round(lo, 3), "high": round(hi, 3),
            })
        mlo, mhi = lo - margin_val, hi + margin_val
        if mn < mlo or mx > mhi:
            margin_oor.append({
                "joint": joint_idx, "name": name,
                "min": round(mn, 3), "max": round(mx, 3),
                "low": round(mlo, 3), "high": round(mhi, 3),
            })

    warning = None
    for idx, row in enumerate(rows):
        wrapped = ((row[4] - env.home_roll + HALF_TURN_NORM / 2.0) % HALF_TURN_NORM) - HALF_TURN_NORM / 2.0
        if abs(wrapped) > WRIST_ROLL_BRANCH_LIMIT_NORM:
            warning = f"frame {idx} wrist_roll={row[4]:.2f} lies between trained branches (home={env.home_roll:.2f})"
            break

    grip_vals = [row[5] for row in rows]
    return {
        "chunk0": [round(v, 3) for v in rows[0]],
        "chunk_last": [round(v, 3) for v in rows[-1]],
        "wrist_roll_warning": warning,
        "strict_ok": not strict_oor,
        "margin_ok": not margin_oor,
        "strict_oor": strict_oor,
        "margin_oor": margin_oor,
        "gripper_min": round(min(grip_vals), 3),
        "gripper_max": round(max(grip_vals), 3),
    }
