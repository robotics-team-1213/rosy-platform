"""Shared ACT entry-bridge, ack/idle verification, wrist-roll guards, and CLI shadow helpers."""
from __future__ import annotations

import argparse
import copy
import inspect
import json
import math
from pathlib import Path
import time
from typing import Any, Mapping
from urllib.parse import urlsplit, urlunsplit

ENTRY_START_TOL, PRE_SETTLE_TOL, STILL_TOL, STILL_WAIT_S = 2.0, 2.0, 0.15, 0.08
FAULT_KEYS = ("fault", "contact", "hold", "human_hold_latched")


def ack_status(status: dict) -> dict:
    out = {k: status.get(k) for k in ("ok", "error", "fault", "contact", "holding", "settled", "state")}
    for k in ("t", "human_hold_latched", "torque_hold_commanded"):
        if k in status:
            out[k] = status[k]
    return out


def finite_stamp(val) -> float | None:
    if not isinstance(val, (int, float)) or isinstance(val, bool):
        return None
    try:
        num = float(val)
    except (TypeError, ValueError, OverflowError):
        return None
    return num if math.isfinite(num) else None


def pose6(raw) -> list[float] | None:
    return vals if isinstance(raw, (list, tuple)) and len(raw) == 6 and None not in (vals := [finite_stamp(v) for v in raw]) else None


def max_diff(a: list[float], b: list[float], n: int | None = None) -> float:
    return max(abs(x - y) for x, y in zip(a[:n] if n else a, b[:n] if n else b))


def valid_state(status: dict) -> tuple[bool, bool, str | None]:
    hold_or_fault = bool(isinstance(status, dict) and any(status.get(k) for k in FAULT_KEYS))
    if not isinstance(status, dict) or not status.get("ok") or hold_or_fault or pose6(status.get("state")) is None:
        msg = ((status.get("error") or status.get("fault")) if isinstance(status, dict) else None) or "policy start state unavailable"
        return False, hold_or_fault, str(msg)
    return True, False, None


def empty_gripper_ok(status: dict, current_limit_ma: float = 140.0, *, max_health_age_s: float = 1.0, now: float | None = None) -> bool:
    if not isinstance(status, dict) or status.get("holding") is not False:
        return False
    hw = isinstance(status.get("operating_context"), dict) and status["operating_context"].get("scope") == "hardware"
    health = status.get("health")
    if hw:
        ht, ref_t = finite_stamp(status.get("health_t")), finite_stamp(status.get("t"))
        if (not isinstance(health, dict) or "current_ma" not in health or ht is None or ref_t is None
                or not (-0.05 <= ref_t - ht <= max_health_age_s)
                or (now is not None and not (-1.0 <= now - ht <= max_health_age_s))):
            return False
    if isinstance(health, dict) and "current_ma" in health:
        cur = health.get("current_ma")
        if not isinstance(cur, (list, tuple)) or len(cur) < 6 or (c5 := finite_stamp(cur[5])) is None or abs(c5) >= current_limit_ma:
            return False
    return True


def cmd_ack_ok(reply, expected: tuple[str, ...], *, require_command: bool = False) -> bool:
    if (not isinstance(reply, dict) or reply.get("ok") is not True
            or any(reply.get(k) for k in ("fault", "hold", "human_hold_latched")) or reply.get("settled") is not True):
        return False
    if "command" not in reply:
        return not require_command
    cmd = str(reply["command"])
    return (cmd.split(" ", 3)[-1] if cmd.startswith("checked ") else cmd) in expected


def park_ack_ok(reply, *, require_command: bool = False) -> bool:
    """True only on a settled, fault-free park ack, never on a preempting human-hold or timeout row."""
    return cmd_ack_ok(reply, ("park", "run park"), require_command=require_command)


def retreat_ack_ok(reply) -> bool:
    """True only on an explicitly labeled, settled, fault-free retreat ack."""
    return cmd_ack_ok(reply, ("retreat", "run retreat"), require_command=True)


def hold_ack_ok(reply) -> bool:
    """True only when the owner confirms HOLD execution (`command`, `ok`, `human_hold_latched`, `torque_hold_commanded`, not `released`)."""
    return (isinstance(reply, dict) and reply.get("command") == "human-hold" and reply.get("ok") is True
            and not reply.get("released") and reply.get("human_hold_latched") is True
            and reply.get("torque_hold_commanded") is True)


def validate_entry_chunk(library: dict, kin=None, jaw_spec: dict | None = None) -> list[list[float]] | None:
    """Validate optional `entry` bridge chunk (idle home -> canonical start)."""
    chunks = library.get("chunks") if isinstance(library, dict) else None
    if not isinstance(chunks, dict) or "entry" not in chunks:
        return None
    raw_entry = chunks["entry"]
    if not isinstance(raw_entry, (list, tuple)) or not raw_entry:
        raise ValueError("library chunks.entry must be a non-empty list of 6-joint finite frames")
    entry: list[list[float]] = []
    for frame in raw_entry:
        if (parsed := pose6(frame)) is None or any(v < -100.0 or v > 100.0 for v in parsed):
            raise ValueError("library chunks.entry must contain 6-joint finite frames in [-100, 100]")
        entry.append(parsed)
    home = chunks.get("home")
    home_pose = pose6(home[-1]) if isinstance(home, (list, tuple)) and home else None
    if home_pose is None or max_diff(entry[0], home_pose, 5) > ENTRY_START_TOL:
        raise ValueError("library chunks.entry must start at home")
    if jaw_spec is not None:
        from cell_policy_shape import jaw_zone_error

        if err := jaw_zone_error(entry, kin, jaw_spec):
            raise ValueError(err)
    return entry


def entry_ready(status: dict, entry_pose: list[float]) -> bool:
    ok, _, _ = valid_state(status)
    if (not ok or status.get("holding") is True or status.get("chunk") is not None
            or (status.get("jitter") or {}).get("shaking")
            or not empty_gripper_ok(status, now=time.time())):
        return False
    target = pose6(status["target"]) if status.get("target") is not None else status["state"]
    return (max_diff(status["state"], entry_pose, 5) <= ENTRY_START_TOL
            and target is not None and max_diff(target, entry_pose, 5) <= ENTRY_START_TOL)


def run_entry_chunk(
    cell, library: dict, work: Path, status: dict, authorize, log, *, jaw_gate: dict | None = None,
) -> tuple[dict | None, str, dict | None]:
    """Execute the reviewed `entry` bridge chunk from home before chunk 0 inference."""
    from cell_policy_timing import send_hold

    entry_lib = {**library, "jaw_gate": jaw_gate} if jaw_gate is not None else library
    prefix = ""
    if authorize is not None:
        try:
            a = authorize(entry_lib, status, ("run entry", "park"))
        except ValueError as exc:
            msg = str(exc)
            log({"command": "run entry", "refused": msg})
            return None, "", {"result": "refused", "at": 0, "reason": msg, "parked": False}
        prefix = f"checked {a['session_id']} {a['library_sha256']} "
    path = work / f"policy-entry-{time.time_ns()}.json"
    path.write_text(json.dumps(entry_lib), encoding="utf-8")
    loaded = cell.act(f"{prefix}load {path}")
    load_lost = isinstance(loaded, dict) and str(loaded.get("error") or "").startswith("no status within")
    load_fault = not isinstance(loaded, dict) or load_lost or any(loaded.get(k) for k in FAULT_KEYS)
    if load_fault or loaded.get("ok") is not True:
        reason = ((loaded.get("error") or loaded.get("fault")) if isinstance(loaded, dict) else None) or "entry load failed"
        log({"command": "load", "target": "entry", "refused": reason, **(ack_status(loaded) if isinstance(loaded, dict) else {})})
        if load_fault:
            log({"command": "human-hold", **ack_status(send_hold(cell, log=log))})
        return None, "", {"result": "fault" if load_fault else "refused", "at": 0, "reason": reason, "parked": False}
    ran = cell.act(f"{prefix}run entry")
    log({"command": "run entry", **(ack_status(ran) if isinstance(ran, dict) else {})})
    if not cmd_ack_ok(ran, ("run entry", "entry"), require_command=True) or ran.get("holding") is True:
        reason = (
            ((ran.get("error") or ran.get("fault")) if isinstance(ran, dict) else None)
            or ("unexpected holding state during entry" if isinstance(ran, dict) and ran.get("holding") is True else "entry chunk did not settle")
        )
        log({"command": "human-hold", **ack_status(send_hold(cell, log=log))})
        fault = isinstance(ran, dict) and bool(ran.get("fault"))
        return None, prefix, {"result": "fault" if fault else "refused", "at": 0, "reason": reason, "parked": False}
    return ran, prefix, None


def moved_snapshot(state, ran: dict, top_before, cell, work: Path, n: int) -> dict:
    """Did the arm move: joint travel the encoders measured and how much the top view changed (mean |diff|, 0-255)."""
    import numpy as np
    out = {"joint_travel": float(np.abs(np.asarray(ran.get("state") or state, dtype=float) - state).max())}
    try:
        import cv2
        top_after = cell.frame("top")
        out["top_change"] = round(float(np.abs(top_before.astype(np.int16) - top_after.astype(np.int16)).mean()), 2)
        shots = work / "policy-frames"
        shots.mkdir(exist_ok=True)
        cv2.imwrite(str(shots / f"{int(time.time())}-{n}-before.jpg"), top_before)
        cv2.imwrite(str(shots / f"{int(time.time())}-{n}-after.jpg"), top_after)
    except Exception as exc:  # camera evidence never stops the episode
        out["top_change_error"] = str(exc)[:120]
    return out


def check_idle_sample(status: dict, home: list[float], *, check_home_target: bool, target_tol: float) -> tuple[list[float], list[float] | None] | None:
    ok, _, _ = valid_state(status)
    if (not ok or status.get("holding") is True or status.get("chunk") is not None
            or (status.get("jitter") or {}).get("shaking")
            or (status.get("command") is not None and status.get("command") != "state")):
        return None
    pose = [float(v) for v in status["state"]]
    tgt = pose6(status["target"]) if status.get("target") is not None else None
    if status.get("target") is not None and (tgt is None or max_diff(pose, tgt, 5) > PRE_SETTLE_TOL
                                             or (check_home_target and max_diff(tgt, home, 5) > target_tol)):
        return None
    return pose, tgt


def live_idle_ok(cell, pose: list[float], home: list[float], *, check_home_target: bool, target_tol: float) -> bool:
    if not hasattr(cell, "policy_state"):
        return True
    try:
        live = cell.policy_state()
    except Exception:
        return False
    lp, lt = (pose6(live.get("state")), finite_stamp(live.get("t"))) if isinstance(live, dict) else (None, None)
    if (not isinstance(live, dict) or live.get("chunk") is not None or any(live.get(k) for k in FAULT_KEYS)
            or (live.get("jitter") or {}).get("shaking") or lp is None or lt is None
            or abs(time.time() - lt) > 1.0 or max_diff(pose, lp) > STILL_TOL
            or (live.get("lag") is not None and ((lag := finite_stamp(live.get("lag"))) is None or lag > PRE_SETTLE_TOL))):
        return False
    tg = pose6(live.get("target")) if live.get("target") is not None else None
    return not (live.get("target") is not None and (tg is None or max_diff(lp, tg, 5) > PRE_SETTLE_TOL
                or (check_home_target and max_diff(tg, home, 5) > target_tol)))


def stationary_idle(cell, status: dict, home: list[float], *, check_home_target: bool,
                    max_off_home: float, sleep=time.sleep) -> tuple[dict, list[float] | None]:
    p1, t1 = check_idle_sample(status, home, check_home_target=check_home_target, target_tol=max_off_home) or (None, None)
    if p1 is None or max_diff(p1, home, 5) > max_off_home or not live_idle_ok(cell, p1, home, check_home_target=check_home_target, target_tol=max_off_home):
        return status, None
    sleep(STILL_WAIT_S)
    s2 = cell.act("state")
    p2, t2 = check_idle_sample(s2, home, check_home_target=check_home_target, target_tol=max_off_home) or (None, None)
    if (p2 is None or max_diff(p2, home, 5) > max_off_home or max_diff(p2, p1) > STILL_TOL
            or (t1 is not None and t2 is not None and max_diff(t2, t1) > STILL_TOL)
            or not live_idle_ok(cell, p2, home, check_home_target=check_home_target, target_tol=max_off_home)):
        return s2, None
    return s2, p2


def dry_no_runner_fallback(status: dict, dry_run: bool, dry_seed_state, library: dict) -> list[float] | None:
    if not (dry_run and isinstance(status, dict) and status.get("fault") == "no runner"):
        return None
    if dry_seed_state is not None:
        return list(dry_seed_state)
    home_frames = (library.get("chunks") or {}).get("home") if isinstance(library, dict) else None
    return pose6(home_frames[-1]) if isinstance(home_frames, (list, tuple)) and home_frames else None


def infer_chunk(shadow, obs, state, sim_units: bool):
    import numpy as np
    sig = inspect.signature(shadow.infer).parameters
    kw = {"state": state.tolist()} if (sim_units and ("state" in sig or any(p.kind == inspect.Parameter.VAR_KEYWORD for p in sig.values()))) else {}
    return np.asarray(shadow.infer(obs, **kw).chunk, dtype=float)


def wrist_roll_warning(chunk, home_roll: float, *, roll_range: tuple[float, float] | None = None) -> str | None:
    import numpy as np
    from arm_status_bridge import TICKS
    from cell_policy_shape import SCALE, finite_float
    home_val = finite_float(home_roll)
    if home_val is None:
        raise ValueError("home_roll must be a finite number")
    arr = np.asarray(chunk, dtype=float)
    if arr.ndim != 2 or arr.shape[1] < 5 or not np.isfinite(arr).all():
        raise ValueError("wrist_roll_warning chunk must be finite (n, >=5)")
    # The two trained orientations are a half-turn apart. Accept within 45 degrees of either.
    half_turn = SCALE["wrist_roll"] * TICKS / (TICKS - 1) / 2
    distance = np.abs((arr[:, 4] - home_val + half_turn / 2) % half_turn - half_turn / 2)
    flagged = distance > half_turn / 4
    if roll_range is not None:
        if not isinstance(roll_range, (list, tuple)) or len(roll_range) != 2:
            raise ValueError("roll_range must be a pair of finite numbers")
        lo, hi = finite_float(roll_range[0]), finite_float(roll_range[1])
        if lo is None or hi is None or lo > hi:
            raise ValueError("roll_range bounds must be finite with lo <= hi")
        folded = (arr[:, 1] <= -50.0) | (arr[:, 2] >= 45.0)
        outside_lib = (arr[:, 4] < lo) | (arr[:, 4] > hi)
        flagged = flagged & (folded | outside_lib)
    between = np.flatnonzero(flagged)
    if len(between):
        i = between[0]
        return f"arm_b frame {i} wrist_roll={arr[i, 4]:.2f} lies between trained branches (home={home_val:.2f})"
    return None


def trained_grasp_mismatch(demo_low, demo_high, grasp_roll: float, *, margin: float | None = None, square: bool = False) -> str | None:
    """Refuse when no symmetric branch of the library grasp_roll falls inside the trained q01..q99 wrist_roll interval."""
    from arm_status_bridge import TICKS
    from cell_policy_shape import MARGIN, SCALE

    eff_margin = MARGIN if margin is None else margin
    step = SCALE["wrist_roll"] * TICKS / (TICKS - 1) / (4 if square else 2)
    lo, hi = float(demo_low[4]) - eff_margin, float(demo_high[4]) + eff_margin
    if any(lo <= grasp_roll + k * step <= hi for k in (range(-4, 5) if square else range(-2, 3))):
        return None
    return (
        f"trained wrist_roll {demo_low[4]:.1f}..{demo_high[4]:.1f} misses reviewed grasp_pick "
        f"({grasp_roll:.1f} mod {step:.1f} +- {eff_margin:.1f})"
    )


def two_arm_roll_bounds(arm: str, lib: Mapping[str, Any], demo_rng, sim_units: bool) -> tuple[float, tuple[float, float] | None]:
    from cell_policy_shape import envelope, widen

    home_rows = (lib.get("chunks") or {}).get("home") or []
    home_roll = float(home_rows[0][4]) if home_rows else 0.0
    roll_range: tuple[float, float] | None = None
    if arm == "b" and isinstance(lib.get("chunks"), dict) and any(len(f) == 6 for c in lib["chunks"].values() for f in c):
        lib_lo, lib_hi, _ = envelope(dict(lib))
        if demo_rng is not None and not sim_units:
            lib_lo, lib_hi = widen(lib_lo, lib_hi, demo_rng[0], demo_rng[1])
        roll_range = (lib_lo[4], lib_hi[4])
    return home_roll, roll_range


def check_obs_stamp(stamp: Any, now_wall: float, max_age_s: float, label: str) -> float:
    if isinstance(stamp, bool) or not isinstance(stamp, (int, float)) or not math.isfinite(float(stamp)):
        raise ValueError(f"invalid {label} stamp {stamp!r}")
    val = float(stamp)
    if val - now_wall > 0.5:
        raise ValueError(f"future {label} stamp {val:.3f} > {now_wall:.3f}")
    if now_wall - val > max_age_s:
        raise ValueError(f"stale {label} stamp (age {now_wall - val:.3f}s > {max_age_s:.3f}s)")
    return val


def build_two_arm_chunk_library(
    lib: Mapping[str, Any], shaped: list[list[float]], obs_mono: float, max_obs_age_s: float, fastest: float, jaw_spec: Mapping[str, Any] | None,
) -> dict[str, Any]:
    # Budget 2 runner ticks (cell_policy_timing) for authorize + FIFO load/run latency before frame 0 is due.
    fps = max(1.0, float(lib.get("fps", 30.0)))
    start_mono = max(obs_mono, time.monotonic()) + 2.0 / fps
    chunk_lib = copy.deepcopy(dict(lib))
    chunk_lib.setdefault("chunks", {})["policy"] = shaped
    playback: dict[str, Any] = {"observed": obs_mono, "start": start_mono, "max_age": max_obs_age_s, "max_step": float(fastest)}
    if jaw_spec is not None:
        playback["jaw_gate"] = dict(jaw_spec)
        if jaw_spec.get("rim_z_m") is not None:
            chunk_lib["source"] = {**(chunk_lib.get("source") or {}), "rim_z_m": float(jaw_spec["rim_z_m"])}
    chunk_lib["policy_playback"] = playback
    return chunk_lib


def configured_arm_id(config: dict, parser: argparse.ArgumentParser) -> str | None:
    cfg_id = str(config["arm_id"]) if config.get("arm_id") else None
    prof_id = None
    if prof_path := config.get("operating_profile_path"):
        import cell_robot_profile

        try:
            prof_id = cell_robot_profile.load(Path(str(prof_path)).expanduser())["binding"]["device_id"]
        except (OSError, ValueError, KeyError) as error:
            parser.error(f"cannot resolve remote arm_id from operating_profile_path: {error}")
    if cfg_id and prof_id and cfg_id != prof_id:
        parser.error(f"config arm_id {cfg_id!r} disagrees with operating profile {prof_id!r}")
    return prof_id or cfg_id


def resolve_arm_id(arm_id: str | None, config: dict, parser: argparse.ArgumentParser) -> str:
    physical = configured_arm_id(config, parser)
    if arm_id and physical and arm_id != physical:
        parser.error(f"--arm-id {arm_id!r} disagrees with configured arm {physical!r}")
    resolved = physical or arm_id
    if resolved:
        return resolved
    parser.error("--endpoint-url requires --arm-id, config.arm_id, or operating_profile_path")


def safe_log_url(url: str | None) -> str | None:
    if not url:
        return None
    parts = urlsplit(url)
    host = f"[{parts.hostname}]" if parts.hostname and ":" in parts.hostname else (parts.hostname or "")
    netloc = f"{host}:{parts.port}" if host and parts.port else host
    return urlunsplit((parts.scheme, netloc, parts.path, "", ""))


def open_policy_shadow(args, config: dict, parser: argparse.ArgumentParser, lrs_mod):
    shadow = None
    physical_arm = configured_arm_id(config, parser)
    if args.arm_id and physical_arm and args.arm_id != physical_arm:
        parser.error(f"--arm-id {args.arm_id!r} disagrees with configured arm {physical_arm!r}")
    if args.mode != "taught":
        if args.endpoint_url:
            from cell_job_guards import read_token_file
            from cell_remote_policy import RemotePolicyError, RemotePolicyShadow

            arm_id = resolve_arm_id(args.arm_id, config, parser)
            try:
                token = read_token_file(args.token_file) if args.token_file is not None else None
                shadow = RemotePolicyShadow(
                    args.endpoint_url, arm_id, args.policy_revision, token=token,
                    timeout_s=args.timeout_s, policy_root=args.policy_root, config=config,
                )
                shadow.full_chunk = not getattr(args, "paced_chunks", False)  # timed playback drops late rows itself
            except (ValueError, RemotePolicyError, OSError, SystemExit) as error:
                parser.error(str(error))
        else:
            shadow = lrs_mod.LeRobotShadow(args.policy_root, args.policy_revision, cell_config=config)
        if args.endpoint_url and physical_arm and (s_arm := getattr(shadow, "arm_id", None)) and s_arm != physical_arm:
            parser.error(f"policy arm_id {s_arm!r} disagrees with configured arm {physical_arm!r}")
    return shadow
