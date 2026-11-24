#!/usr/bin/env python3
"""Replay trajectory reversal, pick-place task override, and live recording progress helpers."""
from __future__ import annotations

import json, math, re
from pathlib import Path

REPLAY_MODES = ("none", "swap_ab", "reverse_motion")
_SLOT_RE = re.compile(r"^[a-zA-Z0-9_-]{1,64}$")
_SLUG_RE = re.compile(r"[^a-z0-9-]+")


def validate_replay_payload(data: dict) -> list[list[float]]:
    """Validate rosy.omx-replay-trajectory.v1 schema, 6-DOF finite bounds, and segments."""
    if not isinstance(data, dict) or data.get("schema") != "rosy.omx-replay-trajectory.v1":
        raise ValueError("replay schema는 rosy.omx-replay-trajectory.v1이어야 합니다")
    raw_frames = data.get("frames")
    if not isinstance(raw_frames, list) or not raw_frames:
        raise ValueError("유효한 replay 궤적(frames)이 아닙니다")
    frames: list[list[float]] = []
    for idx, fr in enumerate(raw_frames):
        if not isinstance(fr, (list, tuple)) or len(fr) != 6:
            raise ValueError(f"replay frame[{idx}]는 6축 값이어야 합니다")
        row = []
        for v in fr:
            if isinstance(v, bool):
                raise ValueError(f"replay frame[{idx}] 값이 숫자가 아닙니다")
            fv = float(v)
            if not math.isfinite(fv) or not (-100.0 <= fv <= 100.0):
                raise ValueError(f"replay frame[{idx}] 값이 허용 범위(-100..100)를 벗어났습니다")
            row.append(fv)
        frames.append(row)
    segs = data.get("segments")
    if isinstance(segs, dict) and ("A" in segs or "B" in segs):
        for k in ("A", "B"):
            if k not in segs or not isinstance(segs[k], (list, tuple)) or len(segs[k]) != 2:
                raise ValueError(f"replay segments[{k}] 형식이 올바르지 않습니다")
            s0, s1 = int(segs[k][0]), int(segs[k][1])
            if not (0 <= s0 < s1 <= len(frames)):
                raise ValueError(f"replay segments[{k}] 범위가 유효하지 않습니다")
    return frames


def _flip_grip(frames: list[list[float]]) -> list[list[float]]:
    vals = [fr[5] for fr in frames]
    lo, hi = min(vals), max(vals)
    return [[*fr[:5], round(lo + hi - fr[5], 4)] for fr in frames]


def transform_replay(raw_bytes: bytes, mode: str = "none", invert_gripper: bool = False) -> bytes:
    """Validate and transform a rosy.omx-replay-trajectory.v1 JSON payload safely."""
    if mode not in REPLAY_MODES:
        raise ValueError(f"replay_mode는 {', '.join(REPLAY_MODES)} 중 하나여야 합니다")
    if mode == "none" and not invert_gripper:
        return raw_bytes
    data = json.loads(raw_bytes.decode("utf-8"))
    frames = validate_replay_payload(data)
    segs = data.get("segments") if isinstance(data.get("segments"), dict) else None
    if mode != "none":
        if segs and "A" in segs and "B" in segs:
            a0, a1 = int(segs["A"][0]), int(segs["A"][1])
            b0, b1 = int(segs["B"][0]), int(segs["B"][1])
            r0, r1 = (int(segs["reset"][0]), int(segs["reset"][1])) if "reset" in segs else (a1, b0)
            if not (0 <= r0 <= r1 <= len(frames)):
                raise ValueError("replay segments[reset] 범위가 유효하지 않습니다")
            seg_a, seg_b = frames[a0:a1], frames[b0:b1]
            reset_len = max(0, r1 - r0)
            first, second = (seg_b, seg_a) if mode == "swap_ab" else (list(reversed(seg_a)), list(reversed(seg_b)))
            hold = [list(first[-1])] * reset_len if reset_len else []
            frames = first + hold + second
            data["segments"] = {
                "A": [0, len(first)],
                "reset": [len(first), len(first) + len(hold)],
                "B": [len(first) + len(hold), len(first) + len(hold) + len(second)],
            }
        else:
            frames = list(reversed(frames))
    if invert_gripper:
        frames = _flip_grip(frames)
    data["frames"] = frames
    data["reverse_mode"] = mode
    data["invert_gripper"] = bool(invert_gripper)
    return json.dumps(data, ensure_ascii=False).encode("utf-8")


def _swap_tokens(text: str, old_a: str, old_b: str) -> str:
    if not text or not old_a or not old_b or old_a == old_b:
        return text
    if old_a in text and old_b in text:
        ph = "__OMX_SWAP_PH__"
        return text.replace(old_a, ph).replace(old_b, old_a).replace(ph, old_b)
    return f"{text} ({old_b} -> {old_a})"


def apply_task_override(tc_data: dict, override: dict) -> dict:
    """Apply pick/place swap or target override to a parsed task card dict."""
    if not isinstance(override, dict) or not override:
        return tc_data
    out = json.loads(json.dumps(tc_data))
    layout = out.setdefault("layout", {}) if isinstance(out.get("layout"), dict) else out.setdefault("layout", {})
    shot = out.get("shot") if isinstance(out.get("shot"), dict) else None
    old_orig = str(layout.get("origin") or (shot.get("source") if shot else "") or "")
    old_tgt = str(layout.get("target_slot") or (shot.get("target") if shot else "") or "")
    new_orig, new_tgt = old_orig, old_tgt
    if override.get("swap_pick_place"):
        new_orig, new_tgt = old_tgt, old_orig
    for key, cur in (("origin", new_orig), ("target_slot", new_tgt)):
        if override.get(key):
            v = str(override[key]).strip()
            if not _SLOT_RE.fullmatch(v):
                raise ValueError(f"{key} 형식이 올바르지 않습니다")
            if key == "origin":
                new_orig = v
            else:
                new_tgt = v
    if new_orig and new_tgt and new_orig == new_tgt:
        raise ValueError("집을 곳(origin)과 놓을 곳(target_slot)은 같을 수 없습니다")
    if new_orig:
        layout["origin"] = new_orig
        if shot is not None:
            shot["source"] = new_orig
    if new_tgt:
        layout["target_slot"] = new_tgt
        if shot is not None:
            shot["target"] = new_tgt
    if override.get("target_layer"):
        v = str(override["target_layer"]).strip()
        if not _SLOT_RE.fullmatch(v):
            raise ValueError("target_layer 형식이 올바르지 않습니다")
        layout["target_layer"] = v
    rec = out.get("record") if isinstance(out.get("record"), dict) else {}
    cur_task = str(out.get("single_task") or rec.get("single_task") or "")
    new_task = cur_task
    if override.get("single_task"):
        new_task = str(override["single_task"]).strip()
    elif (new_orig, new_tgt) != (old_orig, old_tgt):
        if override.get("swap_pick_place") and old_orig and old_tgt:
            new_task = _swap_tokens(cur_task, old_orig, old_tgt)
        elif cur_task and new_orig and new_tgt:
            new_task = f"Pick container from belt to {new_tgt}." if new_orig == "belt" else f"Move container from {new_orig} to {new_tgt}."
    if new_task:
        out["single_task"] = new_task
        if isinstance(out.get("record"), dict) and "single_task" in out["record"]:
            out["record"]["single_task"] = new_task
    if (new_orig, new_tgt) != (old_orig, old_tgt):
        base_id = str(out.get("task_id") or "task")
        slug = _SLUG_RE.sub("-", f"{base_id}-{new_orig}-to-{new_tgt}".lower()).strip("-")[:64].strip("-")
        out["task_id"] = slug or base_id
    return out


def recording_progress(state: dict, clock) -> dict:
    """Compute live recording elapsed seconds, last episode duration, and episode quota."""
    st = state.get("status")
    rec_start, rec_end = state.get("recording_started"), state.get("recording_ended")
    elapsed = None
    if st == "recording" and isinstance(rec_start, (int, float)):
        elapsed = round(max(0.0, clock() - rec_start), 1)
    elif isinstance(rec_start, (int, float)) and isinstance(rec_end, (int, float)):
        elapsed = round(max(0.0, rec_end - rec_start), 1)
    target = state.get("target_episodes")
    done, last_ep_s = None, None
    ds_root, task_id, started = state.get("dataset_root_prefix"), state.get("task_id"), state.get("started")
    if ds_root and Path(ds_root).is_dir():
        root_p = Path(ds_root)
        if not task_id and (root_p / "meta" / "info.json").is_file():
            ds_dir = root_p
        else:
            cands = sorted(root_p.glob(f"{task_id}-r*-*" if task_id else "*"), key=lambda p: p.stat().st_mtime, reverse=True)
            ds_dir = next((p for p in cands if p.is_dir() and (not started or p.stat().st_mtime >= started - 2.0)), None)
        if ds_dir is not None:
            info_p = ds_dir / "meta" / "info.json"
            if info_p.is_file():
                try:
                    done = int(json.loads(info_p.read_text(encoding="utf-8")).get("total_episodes", 0))
                except (OSError, ValueError, TypeError):
                    done = None
            parquets = sorted(ds_dir.glob("data/**/*.parquet"), key=lambda p: p.stat().st_mtime)
            if done is None:
                done = len(parquets)
            if len(parquets) >= 2:
                last_ep_s = round(max(0.0, parquets[-1].stat().st_mtime - parquets[-2].stat().st_mtime), 1)
            elif len(parquets) == 1 and isinstance(rec_start, (int, float)):
                last_ep_s = round(max(0.0, parquets[0].stat().st_mtime - rec_start), 1)
    rem = max(0, target - (done or 0)) if isinstance(target, int) else None
    return {
        "recording_elapsed_s": elapsed,
        "last_episode_s": last_ep_s,
        "episodes_done": done,
        "target_episodes": target,
        "episodes_remaining": rem,
    }


def _interp_waypoints(waypoints: list[list[float]], max_step: float = 0.15) -> list[list[float]]:
    """Interpolate 6-DOF waypoints so every per-frame joint delta stays <= max_step."""
    out = [list(waypoints[0])]
    for tgt in waypoints[1:]:
        prev = out[-1]
        n = max(1, math.ceil(max(abs(a - b) for a, b in zip(tgt, prev)) / max_step - 1e-9))
        for k in range(1, n + 1):
            out.append([round(p + (t - p) * k / n, 3) for p, t in zip(prev, tgt)])
    return out


def _read_live_norm_pose(prep: Path, arm: str, python_exe: str | None, hold=None) -> list[float] | None:
    """Read follower current ticks via leader_home.py (torque OFF) and convert to LeRobot norm units.
    hold() -> (lock handles, why not): the read writes torque OFF, so it runs only while this arm's session lock is held."""
    if not python_exe or hold is None:
        return None
    import bench_record_guard
    manual = Path(prep) / ".bench-manual-check.json"
    if bench_record_guard.arm_free(arm, manual):  # held lease, incident hold or person-check marker: no read that torque-OFFs the Follower
        return None
    handles, busy = hold()
    if busy:
        return None
    try:
        if bench_record_guard.arm_free(arm, manual):  # again with the lock held: a hold recorded by the session that just released it
            return None
        return _read_live_norm_pose_held(prep, arm, python_exe)
    finally:
        for handle in handles:
            handle.close()


def _read_live_norm_pose_held(prep: Path, arm: str, python_exe: str) -> list[float] | None:
    letter = arm.split("_")[-1] if "_" in arm else arm
    cfgs = sorted(prep.glob(f"record-config-arm-{letter}*.json"))
    lh = Path(__file__).resolve().parent / "leader_home.py"
    if not cfgs or not lh.is_file():
        return None
    import subprocess
    import bench_record_guard
    try:
        out = subprocess.run(
            [python_exe, str(lh), "--config", str(cfgs[0]), "--arm", arm, "--read-follower-pose"],
            capture_output=True, text=True, timeout=8,
        )
        if out.returncode != 0:
            if bench_record_guard.follower_torque_on(out.stdout):  # it wrote nothing: a person supports the arm first, also after a restart
                (prep / ".bench-manual-check.json").write_text(json.dumps({"reason": bench_record_guard.FOLLOWER_TORQUE_ON}), encoding="utf-8")
            return None
        ticks = json.loads(out.stdout.strip().splitlines()[-1]).get("state")
        if not isinstance(ticks, list) or len(ticks) != 6:
            return None
        cal_p = Path.home() / ".cache/huggingface/lerobot/calibration/robots/omx_follower"
        robot_id = json.loads(cfgs[0].read_text(encoding="utf-8-sig")).get("robot", {}).get("id", "omx_follower_arm")
        cal = json.loads((cal_p / f"{robot_id}.json").read_text(encoding="utf-8")) if (cal_p / f"{robot_id}.json").is_file() else {}
        names = ("shoulder_pan", "shoulder_lift", "elbow_flex", "wrist_flex", "wrist_roll", "gripper")
        norm = []
        for i, n in enumerate(names):
            c = cal.get(n, {})
            lo, hi = float(c.get("range_min", 0)), float(c.get("range_max", 4095))
            span = max(1.0, hi - lo)
            v = ((float(ticks[i]) - lo) / span * 100.0) if i == 5 else ((float(ticks[i]) - lo) / span * 200.0 - 100.0)
            norm.append(round(max(-100.0, min(100.0, v)), 3))
        return norm
    except subprocess.TimeoutExpired:  # killed with the Follower torque-OFF write possibly half done: a person checks, also after a restart
        (prep / ".bench-manual-check.json").write_text(json.dumps({"reason": f"{arm} 팔로워 위치 읽기를 강제 종료했습니다 — 팔로워 토크 상태를 확인하세요"}), encoding="utf-8")
        return None
    except Exception:
        return None


_REQ_CHUNKS = ("above_pick", "descend_pick", "grasp_pick", "lift_pick", "above_place", "descend_place", "release_place", "lift_place", "home")

def _has_req_chunks(path: Path) -> bool:
    try:
        d = json.loads(path.read_text(encoding="utf-8"))
        chunks = d.get("chunks") if isinstance(d, dict) else None
        return isinstance(chunks, dict) and all(isinstance(chunks.get(k), list) and chunks[k] and isinstance(chunks[k][0], (list, tuple)) and len(chunks[k][0]) >= 6 for k in _REQ_CHUNKS)
    except (OSError, ValueError, TypeError, AttributeError):
        return False


def _pick_chunk_library(prep: Path, arm: str, origin: str, target_slot: str) -> Path | None:
    cdir = Path(prep) / f"cell-arm-{arm.split('_')[-1] if '_' in arm else arm}"
    files = [p for p in (sorted(cdir.glob("auto-*.json"), key=lambda p: p.stat().st_mtime, reverse=True) if cdir.is_dir() else []) if _has_req_chunks(p)]
    hints = f"{origin} {target_slot}".lower()
    extra = [tok for key, tok in (("belt", "beltend"), ("temp", "temp_plate")) if key in hints] + (["pallet"] if ("ship" in hints or "pallet" in hints) else [])
    tokens = extra + [t for t in re.split(r"[^a-z0-9]+", hints) if len(t) >= 3]
    return next((p for tok in tokens for p in files if tok in p.name.lower()), files[0] if files else None)


def _clamp_wp(wp: list[float], jmin: dict, jmax: dict, g_min: float) -> list[float]:
    names = ("shoulder_pan", "shoulder_lift", "elbow_flex", "wrist_flex", "wrist_roll")
    out = [round(max(float(jmin.get(f"{n}.pos", -100.0)), min(float(jmax.get(f"{n}.pos", 100.0)), float(v))), 3) for n, v in zip(names, wp[:5])]
    return [*out, round(max(float(g_min), float(wp[5])), 3)]


def _build_arm_chunk_replay(prep: Path, arm: str, origin: str, target_slot: str, python_exe: str | None, hold) -> dict | None:
    lib_p = _pick_chunk_library(prep, arm, origin, target_slot)
    if lib_p is None:
        return None
    chunks = (lib := json.loads(lib_p.read_text(encoding="utf-8"))).get("chunks") or {}
    if any(not chunks.get(k) for k in _REQ_CHUNKS):
        raise ValueError(f"chunk 파일({lib_p.name})에 필수 동작 단계가 없습니다")
    stack_p = Path(prep) / f"cell-arm-{arm.split('_')[-1] if '_' in arm else arm}-stack.json"
    stack = json.loads(stack_p.read_text(encoding="utf-8")) if stack_p.is_file() else {}
    jmin, jmax, tr = stack.get("joint_min") or {}, stack.get("joint_max") or {}, lib.get("transit") or {}
    tsl, tef, twf = float(tr.get("shoulder_lift.pos", -27.0)), float(tr.get("elbow_flex.pos", 18.0)), float(tr.get("wrist_flex.pos", 46.0))
    g_c = float(lib.get("gripper_closed") or 49.0)
    g_o = max(g_c + 3.0, float(chunks["above_pick"][0][5]))
    home = list(_read_live_norm_pose(prep, arm, python_exe, hold) or chunks["home"][-1])
    rise = [home[0], tsl, tef, twf, home[4], g_o]
    tp, tpl = [chunks["above_pick"][0][0], tsl, tef, twf, chunks["above_pick"][0][4]], [chunks["above_place"][0][0], tsl, tef, twf, chunks["above_place"][0][4]]
    raw_wps = [
        home, rise, [*tp, g_o], [*chunks["above_pick"][0][:5], g_o], [*chunks["descend_pick"][-1][:5], g_o],
        [*chunks["grasp_pick"][-1][:5], g_c], [*chunks["lift_pick"][-1][:5], g_c], [*tp, g_c], [*tpl, g_c],
        [*chunks["above_place"][0][:5], g_c], [*chunks["descend_place"][-1][:5], g_c],
        [*chunks["release_place"][-1][:5], g_o], [*chunks["lift_place"][-1][:5], g_o], [*tpl, g_o], rise, [*home[:5], g_o],
    ]
    a_wps = [home, *[_clamp_wp(w, jmin, jmax, g_c) for w in raw_wps[1:]]]
    motion_a = _interp_waypoints(a_wps, max_step=0.14)
    seg_a, reset_n, seg_b = [list(motion_a[0])] * 30 + motion_a, 30, [list(motion_a[-1])] * 30 + list(reversed(motion_a))
    traj = {
        "schema": "rosy.omx-replay-trajectory.v1", "fps": 30, "frames": seg_a + [list(seg_a[-1])] * reset_n + seg_b,
        "names": ["shoulder_pan.pos", "shoulder_lift.pos", "elbow_flex.pos", "wrist_flex.pos", "wrist_roll.pos", "gripper.pos"],
        "segments": {"A": [0, len(seg_a)], "reset": [len(seg_a), len(seg_a) + reset_n], "B": [len(seg_a) + reset_n, 2 * len(seg_a) + reset_n]},
        "source": {"kind": "ik_planner", "origin": origin, "target": target_slot, "library": lib_p.name},
        "ik_origin": origin, "ik_target": target_slot,
    }
    validate_replay_payload(traj)
    return traj


def build_ik_replay(prep: Path, arm: str, origin: str = "belt-in", target_slot: str = "pinky", python_exe: str | None = None, hold=None) -> dict:
    """Build a speed-bounded rosy.omx-replay-trajectory.v1 from calibrated IK surfaces/chunks."""
    if origin and target_slot and origin == target_slot:
        raise ValueError("IK 집을 곳(origin)과 놓을 곳(target_slot)은 같을 수 없습니다")
    letter = arm.split("_")[-1] if "_" in arm else arm
    prof_p = prep / f"arm-{letter}-robot-profile.json"
    work_dir = prep / "cell-auto-1028"
    if prof_p.is_file():
        try:
            wd = json.loads(prof_p.read_text(encoding="utf-8")).get("work_dir")
            if wd:
                work_dir = Path(wd)
        except (OSError, ValueError):
            pass

    def _surface_poses(site: str):
        sp = work_dir / f"surface-{site}.json"
        if not sp.is_file():
            return None
        steps = json.loads(sp.read_text(encoding="utf-8")).get("steps", [])
        above = next((s.get("state") for s in steps if s.get("command") == "goto above_probe" and s.get("state")), None)
        touch = next((s.get("state") for s in steps if s.get("command") == "run descend_probe" and s.get("state")), None)
        home = next((s.get("state") for s in steps if str(s.get("command", "")).startswith("load ") and s.get("state")), None)
        return (home, above, touch) if (above and touch) else None

    belt_p, pinky_p = _surface_poses("belt"), _surface_poses("pinky")
    if belt_p and pinky_p:
        live_home = _read_live_norm_pose(prep, arm, python_exe, hold)
        home = live_home or belt_p[0] or pinky_p[0] or [0.85, -62.3, 53.0, 51.5, 45.0, 48.9]
        pick_p = pinky_p if "pinky" in origin.lower() else belt_p
        place_p = belt_p if "pinky" in origin.lower() else pinky_p
        g_open, g_close = 48.0, 38.0
        transit_pick = [pick_p[1][0], -27.0, 18.0, 46.0, pick_p[1][4]]
        transit_place = [place_p[1][0], -27.0, 18.0, 46.0, place_p[1][4]]
        a_wps = [
            list(home),
            [*home[:5], g_open],
            [*pick_p[1][:5], g_open],
            [*pick_p[2][:5], g_open],
            [*pick_p[2][:5], g_close],
            [*pick_p[1][:5], g_close],
            [*transit_pick, g_close],
            [*transit_place, g_close],
            [*place_p[1][:5], g_close],
            [*place_p[2][:5], g_close],
            [*place_p[2][:5], g_open],
            [*place_p[1][:5], g_open],
            [*transit_place, g_open],
            [*transit_pick, g_open],
            [*home[:5], g_open],
        ]
        # Keep arm_s wrist_roll above -5.0 norm (~1990 ticks) to avoid wrist camera cable stall at ~1946 ticks.
        for wp in a_wps[1:]:
            wp[4] = max(-5.0, wp[4])
        motion_a = _interp_waypoints(a_wps, max_step=0.14)
        seg_a = [list(motion_a[0])] * 30 + motion_a
        reset_n = 30
        seg_b = [list(motion_a[-1])] * 30 + list(reversed(motion_a))
        frames = seg_a + [list(seg_a[-1])] * reset_n + seg_b
        return {
            "schema": "rosy.omx-replay-trajectory.v1",
            "fps": 30,
            "names": ["shoulder_pan.pos", "shoulder_lift.pos", "elbow_flex.pos", "wrist_flex.pos", "wrist_roll.pos", "gripper.pos"],
            "frames": frames,
            "segments": {"A": [0, len(seg_a)], "reset": [len(seg_a), len(seg_a) + reset_n], "B": [len(seg_a) + reset_n, len(frames)]},
            "source": {"kind": "ik_planner", "origin": origin, "target": target_slot},
            "ik_origin": origin,
            "ik_target": target_slot,
        }
    if (traj := _build_arm_chunk_replay(prep, arm, origin, target_slot, python_exe, hold)) is not None:
        return traj
    raise ValueError(f"IK 표면 캘리브레이션(surface-belt/pinky.json)을 찾을 수 없습니다: {work_dir}")
