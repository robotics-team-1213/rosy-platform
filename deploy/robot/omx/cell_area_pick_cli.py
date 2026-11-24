#!/usr/bin/env python3
"""Closed-loop AreaXYZ pick-and-place CLI using `cell_area_xyz.execute_directive` for fallback or direct visual control."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

HERE = Path(__file__).resolve().parent
if str(HERE) not in sys.path:
    sys.path.insert(0, str(HERE))

import cell_area_xyz  # noqa: E402
import cell_auto_setup  # noqa: E402
import cell_bundle_emit  # noqa: E402
import cell_control_core  # noqa: E402
import cell_pipeline as cp  # noqa: E402
import cell_preflight  # noqa: E402


def _parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(description="Run AreaXYZ visual closed-loop pick/place via cell_area_xyz")
    ap.add_argument("--arm", required=True, choices=("arm_s", "arm_a", "arm_b"))
    ap.add_argument("--config", required=True, type=Path)
    ap.add_argument("--pick-area", required=True)
    ap.add_argument("--pick-x", required=True, type=float)
    ap.add_argument("--pick-y", required=True, type=float)
    ap.add_argument("--pick-z", required=True, type=float)
    ap.add_argument("--place-area", required=True)
    ap.add_argument("--place-x", required=True, type=float)
    ap.add_argument("--place-y", required=True, type=float)
    ap.add_argument("--place-z", required=True, type=float)
    ap.add_argument("--pick-yaw-deg", type=float, default=-90.0)
    ap.add_argument("--place-yaw-deg", type=float, default=-90.0)
    ap.add_argument("--max-attempts", type=int, default=2)
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--stay-in-hover", action="store_true")
    ap.add_argument("--no-vision-refine", action="store_true")
    ap.add_argument("--commissioning", action="store_true")
    ap.add_argument("--person-at-switch", action="store_true")
    ap.add_argument("--operator", default=None)
    ap.add_argument("--proposer", default=None)
    return ap


def _resolve_tcp_x_m(config: dict) -> float | None:
    plan = config.get("plan") if isinstance(config.get("plan"), dict) else {}
    for cand in (config.get("tcp_x_m"), plan.get("tcp_x_m")):
        if cand is not None:
            return float(cand)
    return None


def _resolve_finger_color(arm: str, config: dict, raw_config: dict | None = None) -> str | None:
    """Resolve jaw color for wrist vision (`white` when v2.1 jaws are mounted via `tcp_x_m >= 0.073`)."""
    raw_wrist = raw_config.get("wrist") if isinstance(raw_config, dict) and isinstance(raw_config.get("wrist"), dict) else {}
    explicit = (
        raw_config.get("finger_color") if isinstance(raw_config, dict) else None,
        raw_wrist.get("finger_color"),
        config.get("finger_color"),
    )
    for cand in explicit:
        if cand in ("dark", "white", "auto"):
            return str(cand)
    tcp = _resolve_tcp_x_m(config)
    if arm == "arm_s" and tcp is not None and tcp >= 0.073:
        return "white"
    wrist = config.get("wrist") if isinstance(config.get("wrist"), dict) else {}
    if wrist.get("finger_color") in ("dark", "white", "auto"):
        return str(wrist["finger_color"])
    return None


def _build_directive(args: argparse.Namespace, config: dict, raw_config: dict | None = None) -> dict:
    cameras = config.get("cameras") or {}
    pick_xyz = [float(args.pick_x), float(args.pick_y), float(args.pick_z)]
    place_xyz = [float(args.place_x), float(args.place_y), float(args.place_z)]
    execution = {
        "vision_refine": not bool(args.no_vision_refine),
        "side_zone_snap": "side" in cameras,
        "stay_in_hover": bool(args.stay_in_hover),
        "grasp_deliberation": True,
        "live_perceived": True,
        "wrist_passes": 2,
    }
    if fc := _resolve_finger_color(args.arm, config, raw_config):
        execution["finger_color"] = fc
    if (tcp := _resolve_tcp_x_m(config)) is not None:
        execution["tcp_x_m"] = tcp
    return {
        "schema": cell_area_xyz.DIRECTIVE_SCHEMA,
        "directive_id": f"area-{args.arm}-{args.pick_area}-to-{args.place_area}",
        "arm_id": args.arm,
        "pick": {
            "area": args.pick_area,
            "x": pick_xyz[0],
            "y": pick_xyz[1],
            "z": pick_xyz[2],
            "effective_xyz_m": pick_xyz,
            "yaw_deg": float(args.pick_yaw_deg),
        },
        "place": {
            "area": args.place_area,
            "x": place_xyz[0],
            "y": place_xyz[1],
            "z": place_xyz[2],
            "effective_xyz_m": place_xyz,
            "yaw_deg": float(args.place_yaw_deg),
        },
        "execution": execution,
    }


def _check_workspace(args: argparse.Namespace) -> str | None:
    x_lo, x_hi, y_lim = cell_control_core.arm_workspace_xy_bounds(args.arm)
    for label, x_m, y_m in (("pick", args.pick_x, args.pick_y), ("place", args.place_x, args.place_y)):
        if not (x_lo <= float(x_m) <= x_hi and abs(float(y_m)) <= y_lim):
            return (
                f"{label} ({x_m}, {y_m}) outside {args.arm} workspace bounds "
                f"x=[{x_lo}, {x_hi}], |y|<={y_lim}"
            )
    return None


def _check_config_arm(arm: str, config: dict) -> str | None:
    import re

    seen: list[tuple[str, str]] = []
    if cfg_arm := config.get("arm_id"):
        seen.append(("arm_id", str(cfg_arm)))
    if prof_path := config.get("operating_profile_path"):
        import cell_robot_profile

        try:
            prof_arm = cell_robot_profile.load(Path(str(prof_path)).expanduser())["binding"]["device_id"]
        except (OSError, ValueError, KeyError) as exc:
            return f"cannot resolve operating_profile_path arm: {exc}"
        seen.append(("operating_profile_path", str(prof_arm)))
    if io_path := config.get("io"):
        if m := re.fullmatch(r"chunk-io-([abs])", Path(str(io_path)).name):
            seen.append(("io", f"arm_{m.group(1)}"))
    if not seen:
        return f"cannot verify config arm matches {arm!r}"
    for src, resolved in seen:
        if resolved != arm:
            return f"config {src} {resolved!r} disagrees with --arm {arm!r}"
    return None


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    if args.commissioning != args.person_at_switch:
        print(json.dumps({"result": "refused", "error": "--commissioning and --person-at-switch require each other"}))
        return 1
    if not args.dry_run and not (args.commissioning and args.person_at_switch):
        print(json.dumps({"result": "refused", "error": "real execution requires --commissioning --person-at-switch"}))
        return 1
    if err := _check_workspace(args):
        print(json.dumps({"result": "refused", "error": err}))
        return 1

    raw_config = json.loads(args.config.read_text(encoding="utf-8")) if args.config.is_file() else {}
    config = cell_auto_setup.load_config(args.config)
    if err := _check_config_arm(args.arm, config):
        print(json.dumps({"result": "refused", "error": err}))
        return 1
    work_dir = Path(config["work_dir"]).expanduser()
    cp.KEEP["dir"] = work_dir / "frames"
    cameras = config.get("cameras") or {}
    cell = cp.FifoCell(Path(config["io"]).expanduser(), cameras)
    dark = cell_preflight.ready(cell.frame, config)
    if dark:
        print(json.dumps({"result": "refused", "error": "; ".join(dark)}))
        return 1

    directive = _build_directive(args, config, raw_config=raw_config)
    frame_fn = lambda view: None if view not in cameras else cell.frame(view)

    if args.dry_run:
        try:
            lib, plan, cal = cell_area_xyz.plan_library_from_directive(directive, config["plan"], work_dir=work_dir)
        except Exception as exc:
            print(json.dumps({"result": "refused", "dry_run": True, "error": str(exc)}, default=str))
            return 1
        print(json.dumps({
            "result": "planned",
            "dry_run": True,
            "arm_id": args.arm,
            "pick": directive["pick"],
            "place": directive["place"],
            "plan_pick": plan["pick"],
            "plan_place": plan["place"],
            "chunks": sorted((lib.get("chunks") or {}).keys()),
            "finger_color": cal.get("finger_color"),
            "vision_refine": directive["execution"]["vision_refine"],
            "side_zone_snap": directive["execution"]["side_zone_snap"],
        }, indent=1, default=str))
        return 0

    if not cell.act("state").get("ok"):
        print(json.dumps({"result": "refused", "error": "chunk_runner session not active"}))
        return 1

    max_attempts = max(1, min(3, int(args.max_attempts)))
    try:
        res = cell_area_xyz.execute_directive(
            directive,
            base_plan=config["plan"],
            work_dir=work_dir,
            act_fn=cell.act,
            frame_fn=frame_fn,
            max_attempts=max_attempts,
        )
    except ValueError as exc:
        print(json.dumps({"result": "refused", "error": str(exc)}))
        return 1
    if res.get("result") not in ("placed", "hover"):
        bid = cell_bundle_emit.emit_pick_failure(
            cell,
            {**config, "arm_id": args.arm},
            res.get("calibration") or {},
            args.pick_area,
            args.place_area,
            work_dir,
            res,
            {"transfer": res, "fail": {"stage": res.get("at") or "area_xyz_pick", "class": res.get("result") or "unknown"}},
        )
        if bid:
            res["failure_bundle_id"] = bid
    if args.operator:
        res["operator"] = args.operator
    if args.proposer:
        res["proposer"] = args.proposer
    print(json.dumps(res, indent=1, default=str))
    return 0 if res.get("result") in ("placed", "hover") else 1


if __name__ == "__main__":
    raise SystemExit(main())
