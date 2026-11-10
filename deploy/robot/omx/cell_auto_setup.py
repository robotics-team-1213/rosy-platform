"""Command-line setup shared by cell_auto_pick (one carry) and cell_auto_carry (carries until the source is empty):
the config with its camera profiles, plan and parameters, the common options, and the cell with its logs started."""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import cell_attempts  # noqa: E402
import cell_decisions as cd  # noqa: E402
import cell_params as prm  # noqa: E402
import cell_pipeline as cp  # noqa: E402


def load_config(path: Path) -> dict:
    import cell_perception

    config = json.loads(path.read_text())
    config["profiles"] = {camera: cell_perception.load_profile(Path(spec.get("profile_path", config["profile_path"])).expanduser())
                          for camera, spec in config["cameras"].items()}
    config["plan"] = json.loads(Path(config["plan_path"]).expanduser().read_text())
    config["params"] = prm.load(config.get("params_path"))["values"]  # cell-params.example.json form
    return config


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
    return ap


def open_cell(args, commissioning=False):
    """-> (config, cell, calibration path, work dir), with the attempts (and unless dry, decisions) logs started."""
    config = load_config(args.config)
    if getattr(args, "want_object", None) or getattr(args, "want_colour", None):
        config["want"] = {**config.get("want", {}),
                          **({"object": args.want_object} if getattr(args, "want_object", None) else {}),
                          **({"colour": args.want_colour} if getattr(args, "want_colour", None) else {})}
    if commissioning:
        config["_commissioning"] = {"person_at_switch": True}
    work = Path(config["work_dir"]).expanduser()
    cp.KEEP["dir"] = work / "frames"
    cell_attempts.start(work / "attempts.jsonl", knowledge=config.get("knowledge"), params=config.get("params_path"),
                        arm_id=config.get("arm_id", "arm_s"))
    if not args.dry_run:
        cd.start(work / "decisions.jsonl", knowledge=config.get("knowledge"))
    cell = cp.FifoCell(Path(config["io"]).expanduser(), config["cameras"])
    return config, cell, Path(config["calibration_path"]).expanduser(), work
