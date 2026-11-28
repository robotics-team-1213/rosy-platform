"""Calibrated unit conversion and reviewed-envelope shaping for ACT chunks."""
import math
from pathlib import Path

import numpy as np

import cell_lerobot_shadow as lrs

MARGIN = 3.0  # units of sensor and settle noise outside the reviewed range
JOINTS = len(lrs.JOINT_NAMES)
SCALE = {name: 200.0 for name in lrs.JOINT_NAMES[:-1]} | {"gripper": 100.0}
SIM_POLICY_FPS = 15


def calibration_offset(model_cal: dict, cell_cal: dict) -> list[float]:
    """Model units minus cell units per joint: Present_Position carries the homing offset, so a different homing shifts
    every reading by (model_homing - cell_homing) ticks."""
    offset = []
    for name in lrs.JOINT_NAMES:
        m, c = model_cal[name], cell_cal[name]
        if (m["range_min"], m["range_max"], m["drive_mode"]) != (c["range_min"], c["range_max"], c["drive_mode"]):
            raise ValueError(f"{name}: range or drive mode differ, not a pure homing shift")
        span = float(m["range_max"] - m["range_min"])
        offset.append((float(m["homing_offset"]) - float(c["homing_offset"])) * SCALE[name] / span)
    return offset


def envelope(library: dict) -> tuple[list[float], list[float], float]:
    """(per-joint min, max, fastest step) over every frame of the reviewed library's chunks."""
    chunks = library.get("chunks")
    if not isinstance(chunks, dict) or any(not isinstance(c, (list, tuple, np.ndarray)) for c in chunks.values()):
        raise ValueError("reviewed library chunks must be frame lists")
    raw_fps = library.get("fps", 30)
    fps = finite_float(raw_fps)
    if fps is None or fps <= 0.0:
        raise ValueError("reviewed library fps must be finite and positive")
    frames = []
    for chunk in chunks.values():
        for f in chunk:
            if len(f) == JOINTS:
                vals = [finite_float(v) for v in f]
                if any(v is None for v in vals):
                    raise ValueError("reviewed library frames must contain finite numbers")
                frames.append(vals)
    if not frames:
        raise ValueError("reviewed library has no 6-joint frames")
    arr = np.asarray(frames, dtype=float)
    steps = [np.abs(np.diff(np.asarray(c, dtype=float)[:, :5], axis=0)).max()
             for c in chunks.values() if len(c) > 1]
    if steps:
        fastest = float(max(steps))
    else:
        from omx_adapter.chunk_library import GUARD_UNITS_PER_S

        fastest = float(GUARD_UNITS_PER_S / fps)
    return arr.min(axis=0).tolist(), arr.max(axis=0).tolist(), fastest


def demonstrated_range(policy_root: Path, offset) -> tuple[list[float], list[float]]:
    """Per-joint q01..q99 of the actions the model was trained on (recorded by a person on this arm), in cell units."""
    policy_root = Path(policy_root)
    if (policy_root / lrs.UNITS).is_file():
        raise ValueError("sim-unit checkpoint action quantiles are not cell-unit envelope limits")
    files = sorted(policy_root.glob("policy_preprocessor_step_*_normalizer_processor.safetensors"))
    if not files:
        raise ValueError("checkpoint has no normalizer statistics")
    from safetensors.numpy import load_file

    stats = load_file(str(files[0]))
    off = np.asarray(offset, dtype=float)
    return (np.asarray(stats["action.q01"], dtype=float) - off).tolist(), (np.asarray(stats["action.q99"], dtype=float) - off).tolist()


def widen(low, high, demo_low, demo_high) -> tuple[list[float], list[float]]:
    """Union of the reviewed IK range and the range a person demonstrated on this arm, per joint."""
    return np.minimum(low, demo_low).tolist(), np.maximum(high, demo_high).tolist()


def open_before_close(chunk, open_g: float, closed: float):
    """IK help for the jaws (11-19: in a new scene the model opened only to 52 = a 30 mm gap, then closed on nothing):
    before the model's close (jaws back at closed after having been open) the jaws are at least the reviewed library's
    widest opening, then the model closes as it chose. A chunk without such a close is left as the model gave it."""
    arr = np.array(chunk, dtype=float)
    g = arr[:, 5]
    was_open = np.maximum.accumulate(g) > closed + 2.0
    closing = np.flatnonzero((g <= closed + 1.0) & was_open)
    if len(closing):
        arr[:closing[0], 5] = np.maximum(g[:closing[0]], open_g)
    return arr


def converted_closed(closed: float, rule: dict) -> float:
    from cell_act_inputs import real_grippers, sim_gripper

    return float(real_grippers([sim_gripper(closed, rule)], rule)[0])


def resample_chunk(chunk, start, library_fps: float) -> np.ndarray:
    """Sample the measured start (t=0) to each predicted row (t=1/15, 2/15, ...)."""
    path = np.vstack([start, chunk])
    ticks = np.arange(1, math.ceil(len(chunk) * library_fps / SIM_POLICY_FPS) + 1)
    times = ticks * SIM_POLICY_FPS / library_fps
    return np.column_stack([np.interp(times, np.arange(len(path)), joint) for joint in path.T])


def finite_float(raw) -> float | None:
    if isinstance(raw, bool) or not isinstance(raw, (int, float)):
        return None
    try:
        val = float(raw)
    except OverflowError:
        return None
    return val if math.isfinite(val) else None


from cell_policy_entry import trained_grasp_mismatch, wrist_roll_warning  # noqa: E402,F401
from cell_policy_pre_home import EASE_MIN_ROWS, ease_start, refuse_outside, trim_backtrack_prefix  # noqa: E402,F401


def _params_rim_z(params) -> float | None:
    if not params or "policy.source_rim_z_m" not in params:
        return None
    val = finite_float(params["policy.source_rim_z_m"])
    if val is None or not 0.0 <= val <= 0.5:
        raise ValueError("invalid policy jaw_gate parameters")
    return val if val > 0.0 else None


def source_rim_z(config: dict | None, source: str | None, library: dict) -> float | None:
    """Configured rim height (m) from config['sites'][source] when surface_z is present, else None."""
    if not isinstance(config, dict) or not source:
        return None
    from cell_pick_geom import grasp_depth, surface_z

    site = (config.get("sites") or {}).get(source)
    if not isinstance(site, dict):
        return None
    raw_rim = site.get("rim_z")
    rim_val = None if raw_rim is None else finite_float(raw_rim)
    if "surface_z" not in site:
        if raw_rim is None:
            return None
        if rim_val is None:
            raise ValueError(f"site {source!r} rim_z must be finite, got {raw_rim!r}")
        return rim_val
    surface = surface_z(config, source)
    if raw_rim is not None:
        if rim_val is None or rim_val < surface:
            raise ValueError(f"site {source!r} rim_z must be finite >= surface_z ({surface}), got {raw_rim!r}")
        return rim_val
    _, pick_meta = _source_and_pick(library)
    if (pick_z := finite_float(pick_meta.get("z"))) is not None:
        return max(surface, pick_z + grasp_depth(config, source))
    return surface


def _source_and_pick(library: dict | None) -> tuple[dict, dict]:
    if not isinstance(library, dict):
        return {}, {}
    src = library.get("source")
    if src is None:
        return {}, {}
    if not isinstance(src, dict):
        raise ValueError(f"library source must be a dict, got {type(src).__name__}")
    pick = src.get("pick")
    if pick is None:
        return src, {}
    if not isinstance(pick, dict):
        raise ValueError(f"library source.pick must be a dict, got {type(pick).__name__}")
    return src, pick


def _declared_rim_z(spec: dict | None, library: dict | None, rim_z_m: float | None = None,
                    params=None, trusted_grasp=None) -> float | None:
    vals, sources = [], []
    if rim_z_m is not None:
        sources.append(rim_z_m)
    if (p_rim := _params_rim_z(params)) is not None:
        sources.append(p_rim)
    if isinstance(spec, dict) and "rim_z_m" in spec:
        sources.append(spec["rim_z_m"])
    for mapping in (*_source_and_pick(library), *_source_and_pick(trusted_grasp)):
        for key in ("rim_z_m", "rim_z"):
            if key in mapping and mapping[key] is not None:
                sources.append(mapping[key])
    for raw in sources:
        if (val := finite_float(raw)) is None:
            raise ValueError("invalid policy jaw_gate parameters")
        vals.append(val)
    return max(vals) if vals else None


def jaw_gate_spec(library: dict, kin, params=None, *, xy_radius_m: float = 0.08, max_tilt_rad: float = 0.45,
                  rim_z_m: float | None = None) -> dict | None:
    """Spatial source grasp cylinder and target tool yaw from the reviewed grasp_pick chunk."""
    import cell_params as prm
    from grasp_planner import norm_to_rad

    if rim_z_m is not None and finite_float(rim_z_m) is None:
        raise ValueError(f"rim_z_m must be finite, got {rim_z_m!r}")
    chunks = library.get("chunks")
    if chunks is not None and not isinstance(chunks, dict):
        raise ValueError("library chunks must be a dict")
    chunks = chunks or {}
    if "grasp_pick" not in chunks:
        return None
    grasp = chunks["grasp_pick"]
    grasp_vals = ([finite_float(v) for v in grasp[-1]]
                  if isinstance(grasp, list) and grasp and isinstance(grasp[-1], (list, tuple)) and len(grasp[-1]) == JOINTS
                  else None)
    if grasp_vals is None or any(v is None for v in grasp_vals):
        raise ValueError("library chunks.grasp_pick[-1] must be six finite joints")
    fk = kin.fk([norm_to_rad(v) for v in grasp_vals[:5]])
    _, pick_meta = _source_and_pick(library)
    raw_yaw = pick_meta.get("yaw_deg")
    yaw_val = None if raw_yaw is None else finite_float(raw_yaw)
    if raw_yaw is not None and (yaw_val is None or not -360.0 <= yaw_val <= 360.0):
        raise ValueError(f"library source.pick.yaw_deg must be a finite number, got {raw_yaw!r}")
    yaw_deg = yaw_val if yaw_val is not None else math.degrees(fk.yaw)
    raw_square = pick_meta.get("square")
    if raw_square is not None and type(raw_square) is not bool:
        raise ValueError(f"library source.pick.square must be a boolean, got {raw_square!r}")
    tol_lo, tol_hi = prm.DEFAULTS["policy.approach_yaw_tol_deg"][2:]
    r_val = finite_float(xy_radius_m)
    tilt_val = finite_float(max_tilt_rad)
    tol_val = finite_float(prm.get(params, "policy.approach_yaw_tol_deg"))
    square = raw_square is True
    if (r_val is None or not 0.02 <= r_val <= 0.25 or tilt_val is None or not 0.0 < tilt_val <= 0.45
            or tol_val is None or not (tol_lo <= tol_val <= tol_hi and (not square or tol_val < tol_hi))):
        raise ValueError("invalid policy jaw_gate parameters")
    rim_margin = prm.get(params, "policy.rim_margin_m")
    eff_rim = _declared_rim_z(None, library, rim_z_m, params=params)
    z_m = float(fk.z) + rim_margin + prm.get(params, "auto.approach_near_m")
    if eff_rim is not None:
        z_m = max(z_m, eff_rim + rim_margin)
    return {
        "x": float(fk.x), "y": float(fk.y), "z_m": z_m, "xy_radius_m": r_val,
        "yaw_deg": yaw_deg, "grasp_roll": grasp_vals[4], "tol_deg": tol_val, "max_tilt_rad": tilt_val,
        "square": square, **({"rim_z_m": eff_rim} if eff_rim is not None else {}),
    }


def resolve_gate_tcp(gate_tcp, lib_tcp, trusted_tcp=None):
    import os
    from omx_tcp import ENV, RANGE_M

    vals = []
    for raw in (gate_tcp, lib_tcp, trusted_tcp):
        if raw is None:
            continue
        try:
            v = float("nan" if isinstance(raw, bool) else raw)
        except (TypeError, ValueError, OverflowError):
            v = float("nan")
        if not (math.isfinite(v) and RANGE_M[0] <= v <= RANGE_M[1]):
            raise ValueError(f"invalid policy jaw_gate tcp_x_m: {raw!r}")
        vals.append(v)
    if len(vals) > 1 and any(abs(v - vals[0]) > 1e-6 for v in vals[1:]):
        raise ValueError(f"policy jaw_gate tcp_x_m {vals[0]} conflicts with library {vals[1]}")
    if vals:
        return vals[0]
    if not (env_raw := os.environ.get(ENV)):
        return None
    try:
        env_val = float(env_raw)
    except (TypeError, ValueError, OverflowError):
        env_val = float("nan")
    if not (math.isfinite(env_val) and RANGE_M[0] <= env_val <= RANGE_M[1]):
        raise ValueError(f"invalid {ENV}: {env_raw!r}")
    return env_val


def validate_jaw_gate_geometry(spec: dict, kin, library: dict | None = None, params=None,
                               rim_z_m: float | None = None, trusted_grasp: dict | None = None) -> None:
    """Reject unreachable grasp-zone centers/heights and zones weakened relative to library/rim config."""
    import cell_params as prm
    from cell_jaw_axis import wrap90

    x, y, z_m, yaw_deg = (finite_float(spec.get(k)) for k in ("x", "y", "z_m", "yaw_deg"))
    r_spec, tol_spec, tilt_spec = (finite_float(spec.get(k)) for k in ("xy_radius_m", "tol_deg", "max_tilt_rad"))
    if None in (x, y, z_m, yaw_deg, r_spec, tol_spec, tilt_spec) or not -360.0 <= yaw_deg <= 360.0:
        raise ValueError("invalid policy jaw_gate parameters")
    if hasattr(kin, "l1"):
        reach = abs(kin.shoulder_offset_m) + kin.l1 + kin.l2 + abs(kin.tool_length_m)
        r_xy = math.hypot(x - kin.base_xy[0], y - kin.base_xy[1])
        z_max = kin.shoulder_height_m + kin.l1 + kin.l2 + abs(kin.tool_length_m)
    else:
        reach, r_xy, z_max = 0.45, math.hypot(x, y), 0.50
    if not math.isfinite(r_xy) or r_xy > reach or not -0.05 <= z_m <= z_max:
        raise ValueError("invalid policy jaw_gate parameters")
    eff_rim = _declared_rim_z(spec, library, rim_z_m, params=params, trusted_grasp=trusted_grasp)
    min_z = eff_rim + float(prm.get(params, "policy.rim_margin_m")) if eff_rim is not None else None
    has_grasp = False
    if isinstance(library, dict):
        pb = library.get("policy_playback")
        if pb is not None and not isinstance(pb, dict):
            raise ValueError("policy_playback must be a dict")
        handoff = pb.get("handoff") if isinstance(pb, dict) else None
        if handoff is not None and not isinstance(handoff, dict):
            raise ValueError("invalid policy handoff parameters")
        if isinstance(handoff, dict) and handoff.get("min_z") is not None:
            if (hz := finite_float(handoff["min_z"])) is None:
                raise ValueError("invalid policy jaw_gate parameters")
            if min_z is not None and hz < min_z - 1e-6:
                raise ValueError("policy handoff min_z below source rim clearance")
            min_z = hz if min_z is None else max(min_z, hz)
        chunks = library.get("chunks")
        if chunks is not None and not isinstance(chunks, dict):
            raise ValueError("library chunks must be a dict")
        has_grasp = "grasp_pick" in (chunks or {})
    has_trusted = isinstance(trusted_grasp, dict) and "grasp_pick" in (trusted_grasp.get("chunks") or {})
    if eff_rim is not None and not (has_grasp or has_trusted):
        raise ValueError("policy jaw_gate requires reviewed grasp_pick geometry")
    if min_z is not None and z_m < min_z - 1e-6:
        raise ValueError("policy jaw_gate conflicts with library grasp_pick geometry" if (has_grasp or has_trusted)
                         else "invalid policy jaw_gate parameters")
    for ref_lib in [r for r in (trusted_grasp if has_trusted else None, library if has_grasp else None) if r is not None]:
        if ref_lib.get("tcp_x_m") is not None:
            ref_tcp = resolve_gate_tcp(spec.get("tcp_x_m"),
                                       library.get("tcp_x_m") if isinstance(library, dict) else None, ref_lib["tcp_x_m"])
            if getattr(kin, "tcp_offset", None) is not None and abs(float(kin.tcp_offset[0]) - ref_tcp) > 1e-6:
                raise ValueError(f"policy jaw_gate kinematics tcp_x_m {kin.tcp_offset[0]} conflicts with {ref_tcp}")
        ref = jaw_gate_spec(ref_lib, kin, params, rim_z_m=eff_rim)
        shift_xy = math.hypot(x - ref["x"], y - ref["y"])
        diff = yaw_deg - ref["yaw_deg"]
        yaw_shift = abs((diff + 45.0) % 90.0 - 45.0) if ref["square"] else abs(wrap90(diff))
        if (not math.isfinite(shift_xy) or shift_xy > 0.005
                or not r_spec >= ref["xy_radius_m"] + shift_xy - 1e-6 or not z_m >= ref["z_m"] - 1e-6
                or not tol_spec + yaw_shift <= ref["tol_deg"] + 1e-6 or not tilt_spec <= ref["max_tilt_rad"] + 1e-6
                or spec.get("square", False) is not ref["square"]):
            raise ValueError("policy jaw_gate conflicts with library grasp_pick geometry")


def closed_gripper(library: dict) -> float:
    """Empty-jaw stop when present and non-null, else reviewed gripper_closed."""
    raw = library.get("jaw_empty_stop")
    val = finite_float(library.get("gripper_closed") if raw is None else raw)
    if val is None:
        raise ValueError("invalid gripper_closed")
    return val


def _in_zone(pose, spec: dict) -> bool:
    return math.hypot(pose.x - spec["x"], pose.y - spec["y"]) <= spec["xy_radius_m"] and pose.z <= spec["z_m"]


def in_jaw_zone(frames, kin, spec: dict | None) -> bool:
    """True if any frame's TCP sits inside the source grasp cylinder."""
    if not spec:
        return False
    from grasp_planner import norm_to_rad

    return any(_in_zone(kin.fk([norm_to_rad(float(v)) for v in frame[:5]]), spec) for frame in frames)


def jaw_zone_error(frames, kin, spec: dict | None, *, force_all: bool = False) -> str | None:
    """Refuse crosswise jaw yaw or excessive tilt inside the source grasp cylinder before load/motion."""
    if not spec:
        return None
    from cell_jaw_axis import wrap90
    from grasp_planner import norm_to_rad

    for i, frame in enumerate(frames):
        pose = kin.fk([norm_to_rad(float(v)) for v in frame[:5]])
        if not force_all and not _in_zone(pose, spec):
            continue
        if pose.tool_down_error_rad > spec["max_tilt_rad"]:
            return (f"frame {i} jaw tilt {math.degrees(pose.tool_down_error_rad):.1f} deg "
                    f"exceeds {math.degrees(spec['max_tilt_rad']):.1f} deg in grasp zone")
        diff = math.degrees(pose.yaw) - spec["yaw_deg"]
        err = abs((diff + 45.0) % 90.0 - 45.0) if spec.get("square") else abs(wrap90(diff))
        if err > spec["tol_deg"]:
            return (f"frame {i} jaw yaw {math.degrees(pose.yaw):.1f} deg is {err:.1f} deg "
                    f"from target {spec['yaw_deg']:.1f} deg (tol {spec['tol_deg']:.1f} deg)")
    return None


def shape_chunk(chunk, start, low, high, fastest: float, *, trim_backtrack: bool = False,
                ease: bool = False, jaw_floor: float | None = None) -> list[list[float]]:
    """Cell-unit frames the runner may get: refused outside the envelope, stretched so no body step beats `fastest`.
    `ease` joins a policy chunk to `start` (see `ease_start`); reviewed waypoints keep their exact rows."""
    arr = np.asarray(chunk, dtype=float)
    if arr.ndim != 2 or arr.shape[1] != JOINTS or not np.isfinite(arr).all():
        raise ValueError("policy chunk is not finite (n, 6)")
    if jaw_floor is not None:  # below the empty stop the jaw stalls on nothing and reads as HOLDING; library close_target is floor+1, so unaffected
        arr = np.column_stack([arr[:, :5], np.maximum(arr[:, 5], jaw_floor)])  # policy callers only
    lo, hi = np.asarray(low) - MARGIN, np.asarray(high) + MARGIN
    refuse_outside(arr, lo, hi, lrs.JOINT_NAMES)
    if trim_backtrack:
        arr = trim_backtrack_prefix(arr, start, tol=MARGIN, joints=JOINTS)
    if ease:
        arr = ease_start(arr, start)
        refuse_outside(arr, lo, hi, lrs.JOINT_NAMES)
    path = np.vstack([np.asarray(start, dtype=float)[None, :], arr])
    out = []
    for a, b in zip(path[:-1], path[1:]):
        n = max(1, math.ceil(float(np.abs(b - a).max()) / fastest - 1e-9))  # all six joints, as the runner checks
        out.extend((a + (b - a) * k / n).tolist() for k in range(1, n + 1))
    return out
