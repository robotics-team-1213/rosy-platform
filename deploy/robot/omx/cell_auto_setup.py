"""Command-line setup shared by cell_auto_pick (one carry) and cell_auto_carry (carries until the source is empty):
the config with its camera profiles, plan and parameters, the common options, and the cell with its logs started."""
from __future__ import annotations

import argparse
import json
import math
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import cell_attempts  # noqa: E402
import cell_decisions as cd  # noqa: E402
import cell_params as prm  # noqa: E402
import cell_pipeline as cp  # noqa: E402


def load_config(path: Path) -> dict:
    import cell_arm_cal
    import cell_perception

    config = json.loads(path.read_text())
    config["profiles"] = {camera: cell_perception.load_profile(Path(spec.get("profile_path", config["profile_path"])).expanduser())
                          for camera, spec in config["cameras"].items()}
    config["plan"] = json.loads(Path(config["plan_path"]).expanduser().read_text())
    config["params"] = prm.load(config.get("params_path"))["values"]  # cell-params.example.json form
    return cell_arm_cal.apply_to_config(config)


def parser(doc: str) -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(description=doc, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--config", required=True, type=Path)
    ap.add_argument("--catalog", required=True)
    ap.add_argument("--roi", type=int, nargs=4, required=True, metavar=("X0", "Y0", "X1", "Y1"))
    ap.add_argument("--dest", required=True, help="a site name from the config, or x,y metres on the source surface")
    ap.add_argument("--from", dest="source", default="pinky")
    ap.add_argument("--object", dest="want_object", help="only pick catalogue object ID(s), e.g. container-2 or container-1,container-3")
    ap.add_argument("--colour", "--color", dest="want_colour", help="only pick object colour(s), e.g. yellow or orange,green")
    ap.add_argument("--dry-run", action="store_true", help="observe, choose and plan only; print JSON")
    ap.add_argument("--layers-below", type=int, help="tier hint: layers under the source stack top; raises, never lowers, the site value")
    ap.add_argument("--verify-zones", action="store_true", help="record destination zone_verification even without --task-id")
    ap.add_argument("--neighbour-clear-mm", type=float, help="this run's auto.neighbour_clear_mm, 10..30 (never below the 8 mm finger); recorded")
    return ap


def pick_parser(doc: str) -> argparse.ArgumentParser:
    """Shared argument parser for `cell_auto_pick.py`."""
    ap = parser(doc)
    ap.add_argument("--commissioning", action="store_true", help="a supervised trial of this one carry (D-911)")
    ap.add_argument("--person-at-switch", action="store_true", help="with --commissioning: a person is at the power switch")
    ap.add_argument("--task-id", help="correlate this one carry with a Fleet task; does not authorize completion")
    ap.add_argument("--handoff-lease-id", help="Fleet lease paired with --task-id")
    ap.add_argument("--scenario-id", help="scenario identifier from the cell task")
    ap.add_argument("--goal", help="operator goal sentence; shadow only: the model's reading is logged, the carry order is unchanged")
    ap.add_argument("--return-held", action="store_true", help="arm already holds an object at home: place it at --dest without picking")
    ap.add_argument("--map-only", action="store_true", help="pick on the measured site map without a pivot bias region near the object (recorded)")
    ap.add_argument("--stop-proof", action="store_true", help="D-1077/D-1078: prove arm stop capability at start without --person-at-switch")
    ap.add_argument("--one-shot", action="store_true", help="execute at most one attempt for the bound target object")
    ap.add_argument("--target-object-ref", help="cell-local catalog detection ref bound at click time")
    ap.add_argument("--target-catalog-id", help="expected matched catalog_id for single-target execution")
    ap.add_argument("--target-centroid-mm", help="bound centroid 'x,y' in arm mm")
    ap.add_argument("--target-source-seq", type=int, help="source frame sequence captured at click time")
    ap.add_argument("--target-observed-at", type=float, help="observation epoch timestamp captured at click time")
    ap.add_argument("--target-ttl-s", type=float, help="bound observation TTL in seconds")
    ap.add_argument("--target-tolerance-mm", type=float, help="requested centroid matching tolerance in mm")
    return ap


def validate_pick_args(args) -> None:
    if args.commissioning != args.person_at_switch:
        raise SystemExit("--commissioning needs --person-at-switch (and the other way round)")
    if getattr(args, "stop_proof", False) and (args.commissioning or args.person_at_switch):
        raise SystemExit("--stop-proof cannot be combined with --commissioning/--person-at-switch")
    if bool(args.task_id) != bool(args.handoff_lease_id) or (args.task_id and args.dry_run):
        raise SystemExit("--task-id and --handoff-lease-id require each other and a real single carry")
    t_vals = (getattr(args, "target_catalog_id", None), getattr(args, "target_centroid_mm", None), getattr(args, "target_observed_at", None))
    any_t = any(v is not None for v in (*t_vals, getattr(args, "target_object_ref", None), getattr(args, "target_source_seq", None), getattr(args, "target_ttl_s", None), getattr(args, "target_tolerance_mm", None)))
    if any_t and not all(v is not None for v in t_vals):
        raise SystemExit("--target-catalog-id, --target-centroid-mm, and --target-observed-at are all required together")
    for name, val in (("--target-observed-at", getattr(args, "target_observed_at", None)),
                      ("--target-ttl-s", getattr(args, "target_ttl_s", None)),
                      ("--target-tolerance-mm", getattr(args, "target_tolerance_mm", None))):
        if val is not None and not math.isfinite(val):
            raise SystemExit(f"{name} must be finite")


def fifo_cell(config: dict, cameras: dict) -> tuple[dict, cp.FifoCell]:
    """Bind operating_profile when configured and construct FifoCell with checked-command support."""
    config = dict(config)
    config.pop("_operating_profile_binding", None)
    if config.get("operating_profile_path"):
        import cell_robot_profile

        config = cell_robot_profile.bind_pipeline(config)
    binding = config.get("_operating_profile_binding")
    kwargs = {"operating_profile": binding} if binding is not None else {}
    return config, cp.FifoCell(Path(config["io"]).expanduser(), cameras, **kwargs)


def refresh_stop_proof(cell, config: dict) -> dict:
    """Measure a fresh D-1077 stop-capability proof right before motion or gate open."""
    import cell_stop_proof

    job_id = str(config.get("_stop_proof_job_id") or "auto-pick")
    proof = cell_stop_proof.session_proof(cell, job_id, str(config.get("arm_id") or "arm"))
    if not proof.get("ok"):
        raise SystemExit(f"no stop-capability proof ({proof.get('code')}): {proof.get('reason')}")
    config["_commissioning"] = {"stop_proof": proof}
    return config


def open_cell(args, commissioning=False):
    """-> (config, cell, calibration path, work dir), with the attempts (and unless dry, decisions) logs started."""
    config = load_config(args.config)
    if getattr(args, "want_object", None) or getattr(args, "want_colour", None):
        config["want"] = {**config.get("want", {}),
                          **({"object": args.want_object} if getattr(args, "want_object", None) else {}),
                          **({"colour": args.want_colour} if getattr(args, "want_colour", None) else {})}
    if getattr(args, "layers_below", None) is not None:
        base_src = args.source if args.source in config["sites"] else args.source.rsplit("-l", 1)[0]
        site = config["sites"][base_src]  # the planner reads sites[src].layers_below
        site["layers_below"] = max(int(site.get("layers_below", 0)), args.layers_below)
    config["_fleet_task"] = getattr(args, "task_id", None) or False  # D-1057: the placement zone check runs only for a Fleet task
    config["_verify_zones"] = bool(getattr(args, "verify_zones", False))
    config["_map_only"] = bool(getattr(args, "map_only", False))
    config["_one_shot"] = bool(getattr(args, "one_shot", False))
    if getattr(args, "target_catalog_id", None) is not None:
        from cell_job_validators import _catalog_id, _centroid_mm, _object_ref

        config["_target_binding"] = {
            "catalog_id": _catalog_id(args.target_catalog_id),
            "centroid_mm": _centroid_mm(args.target_centroid_mm),
            "observed_at": float(args.target_observed_at),
            **({"object_ref": _object_ref(args.target_object_ref)} if getattr(args, "target_object_ref", None) else {}),
            **({"source_seq": int(args.target_source_seq)} if getattr(args, "target_source_seq", None) is not None else {}),
            **({"ttl_s": float(args.target_ttl_s)} if getattr(args, "target_ttl_s", None) is not None else {}),
            **({"tolerance_mm": float(args.target_tolerance_mm)} if getattr(args, "target_tolerance_mm", None) is not None else {}),
        }
        config["_one_shot"] = True
    if (clear := getattr(args, "neighbour_clear_mm", None)) is not None:
        if not 10.0 <= clear <= 30.0:
            raise SystemExit("--neighbour-clear-mm must be 10..30")
        config["params"], config["_neighbour_clear_mm"] = {**config["params"], "auto.neighbour_clear_mm": float(clear)}, float(clear)
    if config.pop("_commissioning", None) is not None:  # a stored file cannot attest that a person is at the switch (D-911)
        print("warning: _commissioning in the config file is ignored; only --commissioning --person-at-switch sets it", file=sys.stderr)
    if commissioning:
        config["_commissioning"] = {"person_at_switch": True}
    config, cell = fifo_cell(config, config["cameras"])
    if getattr(args, "stop_proof", False) and not getattr(args, "dry_run", False):
        config["_stop_proof_job_id"] = getattr(args, "task_id", None) or "auto-pick"
        refresh_stop_proof(cell, config)
    work = Path(config["work_dir"]).expanduser()
    cp.KEEP["dir"] = work / "frames"
    cell_attempts.start(work / "attempts.jsonl", knowledge=config.get("knowledge"), params=config.get("params_path"),
                        arm_id=config.get("arm_id", "arm_s"), task_id=getattr(args, "task_id", None),
                        handoff_lease_id=getattr(args, "handoff_lease_id", None))
    if not args.dry_run:
        cd.start(work / "decisions.jsonl", knowledge=config.get("knowledge"))
    return config, cell, Path(config["calibration_path"]).expanduser(), work


def pick_main(argv=None, *, doc: str = "", run_auto_fn=None, run_held_fn=None):
    import cell_choices
    import cell_objects
    import cell_pivot
    import cell_preflight
    import cell_calibration as cal

    args = pick_parser(doc).parse_args(argv)
    validate_pick_args(args)
    config, cell, calibration_path, work = open_cell(args, args.commissioning)
    dark = cell_preflight.ready(cell.frame, config)
    if dark:
        print(json.dumps({"from": args.source, "to": args.dest, "result": "refused", "error": "; ".join(dark)}, indent=1))
        return 1
    cal_data = cell_pivot.with_site_maps(config, cal.load(calibration_path))
    cat = cell_objects.load_catalog(args.catalog)
    result = (
        run_held_fn(cell, config, cal_data, calibration_path, cat, args.roi, args.dest, work, args.dry_run)
        if args.return_held else
        run_auto_fn(cell, config, cal_data, calibration_path, cat, args.roi, args.source, args.dest, work,
                    cell_choices.Choices(work / "choices.json"), args.dry_run, scenario_id=args.scenario_id, goal=args.goal)
    )
    print(json.dumps(result, indent=1, default=str))
    return 0 if result["result"] in ("placed", "planned") else 1
