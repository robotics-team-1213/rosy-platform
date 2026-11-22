"""Bind a job to its taught library and hand off from measured ACT lift to the folded carry."""
import json
import math
from pathlib import Path

import cell_params as prm
from cell_pick_geom import grasp_depth, surface_z
from cell_transfer import FOLDED, RETURN_HELD, Gate, transfer_folded


def _carry(cell, library_path, sequence, authorize, log):
    library = json.loads(library_path.read_text(encoding="utf-8"))
    runner = cell
    if authorize is not None:
        state = cell.act("state")
        if sequence == FOLDED and state.get("holding") is not False:
            raise ValueError("taught pick requires a measured empty gripper")
        runner = Gate(cell, authorize.config, authorize.calibration, sequence=sequence)
        runner.assessment = authorize(library, state, sequence)
        from cell_envelope import digest

        runner.scope_sha = digest([runner.config, runner.calibration, sequence])
    result = transfer_folded(runner, library_path, sequence=sequence)
    log({"taught_carry": result})
    return result


class Authorization:
    """Use the existing supervised envelope and bind runner commands to the checked library."""
    def __init__(self, config):
        self.config = config
        self.calibration = json.loads(Path(config["calibration_path"]).expanduser().read_text(encoding="utf-8"))

    def __call__(self, library, state, sequence):
        from cell_envelope import assess
        from cell_pipeline_io import limit_error

        limits = limit_error(dict(self.config, played_chunks=list(library["chunks"])), library)
        if limits:
            raise ValueError(limits)
        result = assess(self.config, self.calibration, library, state, sequence=sequence)
        if not result["allowed"]:
            raise ValueError(f"operating envelope refused: {result['reason']}")
        return result


class CellHandoff:
    def __init__(self, config, source, library_path, library, close_target, work):
        import omx_tcp

        params = config.get("params")
        pick = library["source"]["pick"]
        site = config["sites"][source]
        surface = surface_z(config, source)
        try:
            raw_rim = site.get("rim_z")
            if raw_rim is None:
                raw_z = pick["z"]
                pz = float("nan") if isinstance(raw_z, bool) else float(raw_z)
                rim = max(surface, pz + grasp_depth(config, source))
            else:
                rim = float("nan") if isinstance(raw_rim, bool) else float(raw_rim)
        except (TypeError, ValueError, OverflowError):
            rim = float("nan")
        if not math.isfinite(rim) or rim < surface:
            raise ValueError("source rim_z must be finite and at or above surface_z")
        self.config, self.work, self.library_path, self.library = config, work, library_path, library
        self.rise = prm.get(params, "policy.handoff_rise_m")
        self.spec = dict(hold_frames=prm.get(params, "policy.hold_frames"), x=pick["x"], y=pick["y"],
                         yaw_deg=pick["yaw_deg"], min_z=rim + prm.get(params, "policy.rim_margin_m"),
                         xy_tol=prm.get(params, "policy.pose_xy_tol_m"),
                         angle_tol_deg=prm.get(params, "policy.pose_angle_tol_deg"), close_target=close_target,
                         empty_stop=float(library["gripper_closed"] if library.get("jaw_empty_stop") is None else library["jaw_empty_stop"]),
                         hold_current_ma=library.get("hold_current_ma"), tcp_x_m=omx_tcp.config_tcp(config))

    def carry(self, cell, status, authorize, log):
        from grasp_planner import Planner, norm_to_rad
        from omx_adapter.chunk_library import GUARD_UNITS_PER_S
        from omx_adapter.motion_profile import retime

        try:
            current = cell.act("state")
            if current.get("holding") is not True or current.get("fault") or not current.get("ok"):
                raise ValueError("runner lost measured hold before handoff lift")
            state, target = current["state"], current["target"]
            # Recheck the handoff conditions after the FIFO round trip.
            from chunk_policy_playback import Handoff

            planner = Planner(dict(self.config["plan"], fps=self.library["fps"], tcp_x_m=self.spec["tcp_x_m"]))
            check = Handoff(self.spec, planner.kin)
            check.count = status["handoff"]["holding_frames"] - 1
            check.last_jaw = status["handoff"]["jaw"]
            facts = check.sample(state, target, health=current.get("health"))
            log({"handoff_recheck": facts})
            if not facts["triggered"]:
                raise ValueError("measured handoff pose or hold changed before lift")
            joints = [norm_to_rad(v) for v in state[:5]]
            pose = planner.kin.fk(joints)
            xyz = (pose.x, pose.y, pose.z)
            frames, _ = planner.line(xyz, (pose.x, pose.y, pose.z + self.rise), 0.010,
                                     math.degrees(pose.yaw), target[5], joints[4])
            # Start at the held target and retain the runner's guarded acceleration and rate.
            frames = retime([list(target), *frames], self.library["fps"], GUARD_UNITS_PER_S)
            lift_name = "lift_pick_policy_handoff"
            lift_lib = {**self.library, "chunks": {**self.library["chunks"], lift_name: frames}}
            path = self.work / "policy-handoff-lift.json"
            path.write_text(json.dumps(lift_lib), encoding="utf-8")
            lift_cmd = f"run {lift_name}"
            prefix = ""
            if authorize is not None:
                a = authorize(lift_lib, current, (lift_cmd,))
                prefix = f"checked {a['session_id']} {a['library_sha256']} "
            loaded = cell.act(f"{prefix}load {path}")
            if not loaded.get("ok"):
                raise ValueError(loaded.get("error") or "handoff lift load refused")
            lifted = cell.act(prefix + lift_cmd)
            log({"command": lift_cmd, **lifted})
            if lifted.get("holding") is not True or lifted.get("settled") is not True or not lifted.get("ok"):
                raise ValueError(lifted.get("error") or "handoff lift did not settle with a measured hold")
            # Preserve the taught fold before going to the destination.
            return _carry(cell, self.library_path, FOLDED[-len(RETURN_HELD) - 1:], authorize, log)
        except (ValueError, OSError, KeyError, SystemExit) as exc:
            log({"command": "human-hold", **cell.act("human-hold"), "reason": str(exc)})
            return {"result": "refused", "reason": str(exc)}


def validate_taught_goal(config, source, goal_site, destination, library):
    """Check the supplied library's taught endpoints against this job's calibrated sites."""
    from cell_place_fit import with_tiers
    from grasp_planner import load_kinematics, norm_to_rad
    import omx_tcp

    sites = with_tiers(config)[0]["sites"]
    names = (goal_site, destination, "vehicle_tray") if destination == "tray" else (goal_site, destination)
    goal = next((name for name in names if name in sites), None)
    if goal is None or source not in sites:
        raise ValueError("source and destination must exist in the arm's configured sites")
    effective = {**config, "sites": sites}
    pick, place = (library["source"][k] for k in ("pick", "place"))
    # Check xy and relative elevation so a taught lower-tier library cannot serve a higher-tier job.
    tol = prm.get(config.get("params"), "reach.tol_mm") / 1000
    height_delta = surface_z(effective, goal) - surface_z(effective, source)
    if (math.dist((place["x"], place["y"]), sites[goal]["place"]) > tol
            or abs((place["z"] - pick["z"]) - height_delta - sites[goal].get("place_dz", 0)) > tol):
        raise ValueError("taught library does not match the job destination pose and tier")
    if math.dist((pick["x"], pick["y"]), sites[source]["pick"]) > prm.get(config.get("params"), "policy.pose_xy_tol_m"):
        raise ValueError("taught library does not match the job source")
    if any(name not in library["chunks"] for name in (cmd.split()[-1] for cmd in FOLDED if cmd != "park")):
        raise ValueError("taught library is missing a folded carry chunk")
    kin, _, _ = load_kinematics(None, omx_tcp.config_tcp(config))
    for stage, reference in (("descend_pick", pick), ("descend_place", place)):
        joints = [norm_to_rad(v) for v in library["chunks"][stage][-1][:5]]
        fk = kin.fk(joints)
        if math.dist((fk.x, fk.y, fk.z), tuple(reference[k] for k in ("x", "y", "z"))) > tol:
            raise ValueError(f"taught {stage} endpoint does not match its declared pose")


def run_taught(cell, library_path, *, dry_run, authorize, log):
    if dry_run:
        log({"dry_run": True, "taught_sequence": FOLDED})
        return {"result": "dry_run", "mode": "taught"}
    return _carry(cell, library_path, FOLDED, authorize, log)


def _moved_snapshot(state, ran: dict, top_before, cell, work: Path, n: int) -> dict:
    """Did the arm move: joint travel the encoders measured and how much the top view changed (mean |diff|, 0-255)."""
    import numpy as np

    out = {"joint_travel": float(np.abs(np.asarray(ran.get("state") or state, dtype=float) - state).max())}
    try:
        import cv2
        import time

        top_after = cell.frame("top")
        out["top_change"] = round(float(np.abs(top_before.astype(np.int16) - top_after.astype(np.int16)).mean()), 2)
        shots = work / "policy-frames"
        shots.mkdir(exist_ok=True)
        cv2.imwrite(str(shots / f"{int(time.time())}-{n}-before.jpg"), top_before)
        cv2.imwrite(str(shots / f"{int(time.time())}-{n}-after.jpg"), top_after)
    except Exception as exc:  # camera evidence never stops the episode
        out["top_change_error"] = str(exc)[:120]
    return out


def _ack_status(status: dict) -> dict:
    keys = ("ok", "error", "fault", "contact", "holding", "settled", "state")
    return {**{k: status.get(k) for k in keys}, **({"t": status["t"]} if "t" in status else {})}


def run_paced_chunks(cell, shadow, library: dict, work: Path, *, off, max_chunks: int, dry_run: bool, log, goal: dict,
                     sim_units: bool, open_g: float, model_closed: float, closed: float, low, high, fastest: float,
                     kin, jaw_spec, resolved_tcp, authorize, max_obs_age_s: float = 0.6) -> dict:
    """Guarded step-rate-stretched chunk loop for full-chunk ACT checkpoints (e.g. arm_s)."""
    import time
    import numpy as np
    from cell_policy_shape import in_jaw_zone, jaw_zone_error, open_before_close, shape_chunk
    from cell_policy_timing import park_ack_ok

    def _safe_park_or_hold(cmd_prefix: str = "", *, fault: bool = False) -> tuple[bool, dict | None]:
        if dry_run:
            return False, None
        if fault:
            log({"command": "human-hold", **_ack_status(cell.act("human-hold"))})
            return False, None
        park_reply = cell.act(cmd_prefix + "park")
        log({"command": "park", **_ack_status(park_reply)})
        if park_ack_ok(park_reply):
            return True, park_reply
        log({"command": "human-hold", **_ack_status(cell.act("human-hold"))})
        return False, park_reply

    def _fail(res: str, at: int, reason, cmd_prefix: str = "", *, fault: bool = False, extra: dict | None = None) -> dict:
        parked_ok, park_reply = _safe_park_or_hold(cmd_prefix, fault=fault)
        return {"result": res, "at": at, "reason": reason, **(extra or {}), "parked": parked_ok,
                **({"park": _ack_status(park_reply)} if park_reply is not None else {})}

    def _legacy_jaw_hold(row, n: int, jaw_warn: str) -> dict:
        held_reply = cell.act("human-hold")
        log({**row, "refused": jaw_warn})
        log({"command": "human-hold", **_ack_status(held_reply)})
        return {"result": "refused", "at": n, "reason": jaw_warn, "parked": False}

    held, released, prefix = False, False, ""
    for n in range(max_chunks):
        row = {"chunk": n, "dry_run": dry_run}
        try:
            status = cell.act("state")
            if not status.get("ok") or status.get("fault") or not isinstance(status.get("state"), list):
                reason = status.get("error") or "policy start state unavailable"
                log({**row, "refused": reason, **_ack_status(status)})
                return _fail("fault" if status.get("fault") else "refused", n, reason, fault=bool(status.get("fault")))
            state = np.asarray(status["state"], dtype=float)
            frames, oldest_stamp = {}, None
            if hasattr(cell, "frame_receipt"):
                for view in shadow.image_views:
                    rec = cell.frame_receipt(view, max_age_s=max_obs_age_s, timeout_s=max_obs_age_s)
                    frames[view] = rec["image"]
                    stamp = rec.get("source_stamp")
                    if isinstance(stamp, (int, float)) and not isinstance(stamp, bool) and math.isfinite(stamp):
                        oldest_stamp = stamp if oldest_stamp is None else min(oldest_stamp, stamp)
            else:
                frames = {view: cell.frame(view) for view in shadow.image_views}
            obs, meta = shadow.inputs(state.tolist() if sim_units else (state + off).tolist(), frames, **goal)
            converted = np.asarray(shadow.infer(obs).chunk, dtype=float) - off
            proposed = converted if held else open_before_close(converted, open_g, model_closed)
            row = {**row, "state": state.tolist(), "meta": meta, "proposed_first": proposed[0].tolist(),
                   "proposed_last": proposed[-1].tolist()}
            if dry_run:
                row["converted_chunk"] = converted.tolist()
            live_poses = [state.tolist(), *([status["target"]] if status.get("target") is not None else [])]
            if jaw_spec is not None and (jaw_warn := jaw_zone_error(live_poses, kin, jaw_spec)):
                row["jaw_warning"] = jaw_warn
                if not dry_run:
                    return _legacy_jaw_hold(row, n, jaw_warn)
            force_all = jaw_spec is not None and in_jaw_zone(live_poses, kin, jaw_spec)
            try:
                frames_cell = shape_chunk(proposed, state, low, high, fastest)
            except ValueError as error:
                if dry_run:
                    row["envelope"] = {"ok": False, "reason": str(error)}
                log({**row, "refused": str(error)})
                return _fail("refused", n, str(error))
            if jaw_spec is not None and (jaw_warn := jaw_zone_error(frames_cell, kin, jaw_spec, force_all=force_all)):
                row["jaw_warning"] = jaw_warn
                if not dry_run:
                    return _legacy_jaw_hold(row, n, jaw_warn)
            row["frames"] = len(frames_cell)
            if dry_run:
                log({**row, "envelope": {"ok": True}})
                continue
            lib = {**library, "chunks": {**library["chunks"], "policy": frames_cell},
                   **({"jaw_gate": {**jaw_spec, "tcp_x_m": resolved_tcp}} if jaw_spec is not None else {})}
            path = work / f"policy-lib-{time.time_ns()}-{n}.json"
            path.write_text(json.dumps(lib), encoding="utf-8")
            prefix = ""
            if authorize is not None:
                try:
                    assessment = authorize(lib, status, ("run policy", "park"))
                except ValueError as error:
                    log({**row, "refused": str(error)})
                    return _fail("refused", n, str(error))
                prefix = f"checked {assessment['session_id']} {assessment['library_sha256']} "
        except Exception as error:  # fail closed on camera, inference, shaping, or file errors after chunk 0
            msg = str(error)[:200] or type(error).__name__
            log({**row, "refused": msg})
            return _fail("refused", n, msg)
        loaded = cell.act(f"{prefix}load {path}")
        log({**row, "command": "load", **_ack_status(loaded)})
        if not loaded.get("ok"):
            return _fail("refused", n, loaded.get("error"))
        if oldest_stamp is not None and time.time() - oldest_stamp > max_obs_age_s:
            log({**row, "refused": "stale policy observation"})
            return _fail("refused", n, "stale policy observation", prefix)
        ran = cell.act(prefix + "run policy")
        log({"command": "run policy", **_ack_status(ran), **_moved_snapshot(state, ran, frames.get("top"), cell, work, n)})
        if ran.get("contact"):
            if "overload-hold" not in (ran.get("error") or ""):
                log({"command": "retreat", **_ack_status(cell.act(prefix + "retreat"))})
            return _fail("contact", n, ran.get("error"), prefix, extra={"error": ran.get("error")})
        if not ran.get("ok"):
            is_fault = bool(ran.get("fault"))
            return _fail("fault" if is_fault else "refused", n, ran.get("error"), prefix,
                         fault=is_fault, extra={"error": ran.get("error")})
        held = held or bool(ran.get("holding"))
        released = held and [f[5] for f in frames_cell][-1] > closed + 10.0  # held something, then opened (OMX_RUN_STOP_ON_PLACE)
        if released:
            break
    if dry_run:
        return {"result": "dry_run", "chunks": max_chunks}
    parked_ok, park_reply = _safe_park_or_hold(prefix)
    return {"result": "released" if released else "chunks_done", "held": held, "parked": parked_ok,
            **({"park": _ack_status(park_reply)} if park_reply is not None else {})}
