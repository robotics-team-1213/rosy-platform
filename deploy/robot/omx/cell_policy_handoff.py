"""Bind a job to its taught library and hand off from measured ACT lift to the folded carry."""
import json
import math
from pathlib import Path

import cell_params as prm
from cell_pick_geom import grasp_depth, surface_z
from cell_site_target import unmeasured_refusal
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
    result = transfer_folded(runner, library_path, sequence=sequence, strict_motion=True)
    log({"taught_carry": result})
    return result


def _carry_hold_reason(res, label: str) -> str | None:
    from cell_policy_timing import park_ack_ok

    if isinstance(res, dict) and res.get("result") == "placed":
        return None
    steps = res.get("steps") if isinstance(res, dict) else ()
    last_step = steps[-1] if isinstance(steps, list) and steps and isinstance(steps[-1], dict) else None
    last_park = last_step if last_step and last_step.get("command") == "park" else None
    has_overload = ("overload-hold" in str((res.get("error") if isinstance(res, dict) else "") or "")
                    or any(isinstance(s, dict) and ("overload-hold" in str(s.get("error") or "") or "overload-hold" in str(s.get("fault") or ""))
                           for s in (steps or ())))
    if (not isinstance(res, dict) or res.get("result") == "fault"
            or has_overload or not park_ack_ok(last_park, require_command=True)):
        return ((res.get("error") if isinstance(res, dict) else None)
                or f"{label} ended without settled park ({res.get('result') if isinstance(res, dict) else 'invalid'})")
    return None


class Authorization:
    """Use the existing supervised envelope and bind runner commands to the checked library."""
    supports_check_home = True

    def __init__(self, config):
        self.config = config
        self.calibration = json.loads(Path(config["calibration_path"]).expanduser().read_text(encoding="utf-8"))

    def __call__(self, library, state, sequence, *, check_home: bool = True):
        from cell_envelope import assess
        from cell_pipeline_io import limit_error

        limits = limit_error(dict(self.config, played_chunks=list(library["chunks"])), library)
        if limits:
            raise ValueError(limits)
        result = assess(self.config, self.calibration, library, state, sequence=sequence, check_home=check_home)
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
        from cell_policy_timing import ack_status, best_effort_hold, cmd_ack_ok, send_hold
        from grasp_planner import Planner, norm_to_rad
        from omx_adapter.chunk_library import GUARD_UNITS_PER_S
        from omx_adapter.motion_profile import retime

        try:
            current = cell.act("state")
            if not isinstance(current, dict) or current.get("holding") is not True or current.get("fault") or not current.get("ok"):
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
            if not isinstance(loaded, dict) or not loaded.get("ok"):
                raise ValueError((loaded.get("error") if isinstance(loaded, dict) else None) or "handoff lift load refused")
            lifted = cell.act(prefix + lift_cmd)
            log({"command": lift_cmd, **(lifted if isinstance(lifted, dict) else {"raw": lifted})})
            if not cmd_ack_ok(lifted, (lift_cmd, lift_name), require_command=True) or lifted.get("holding") is not True:
                raise ValueError((lifted.get("error") if isinstance(lifted, dict) else None) or "handoff lift did not settle with a measured hold")
            # Preserve the taught fold before going to the destination.
            res = _carry(cell, self.library_path, FOLDED[-len(RETURN_HELD) - 1:], authorize, log)
            if (why := _carry_hold_reason(res, "handoff carry")) is not None:
                raise ValueError(why)
            return res
        except (ValueError, OSError, KeyError, SystemExit) as exc:
            hold_reply = send_hold(cell, log=log)
            log({"command": "human-hold", **ack_status(hold_reply), "reason": str(exc)})
            return {"result": "refused", "reason": str(exc)}
        except BaseException:
            hold_row = best_effort_hold(cell, log=log)
            if hold_row is not None:
                log(hold_row)
            raise


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
    if unmeasured_refusal(sites, goal, source):
        raise ValueError("SITE_NOT_MEASURED: a registered slot needs XY and Z measurements before the arm goes there")
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
    from cell_policy_timing import ack_status, best_effort_hold, send_hold

    if dry_run:
        log({"dry_run": True, "taught_sequence": FOLDED})
        return {"result": "dry_run", "mode": "taught"}
    try:
        res = _carry(cell, library_path, FOLDED, authorize, log)
        if (why := _carry_hold_reason(res, "taught carry")) is not None:
            raise ValueError(why)
        return res
    except (ValueError, OSError, KeyError, SystemExit) as exc:
        hold_reply = send_hold(cell, log=log)
        log({"command": "human-hold", **ack_status(hold_reply), "reason": str(exc)})
        return {"result": "refused", "mode": "taught", "reason": str(exc), "parked": False}
    except BaseException:
        hold_row = best_effort_hold(cell, log=log)
        if hold_row is not None:
            log(hold_row)
        raise


from cell_policy_paced import run_paced_chunks  # noqa: E402,F401
