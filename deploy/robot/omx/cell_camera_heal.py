"""Before a camera job runs: every camera its cell config names answers, or the upkeep camera recovery runs.

No arm motion. Recovery is `cell_upkeep_checks.check_cameras(fix=True)`: restart the camera unit, then
`cell_upkeep.usb_recover` (a port shared with an OpenRB board only gets its camera leaf re-authorised).
It is skipped while that arm's bus is owned, exactly as the 30-min upkeep does.

  cell_camera_heal.py --target ARM=CONFIG [--target ...] -- <job argv...>
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path


# The API's own tree, not $OMX: the job API and the $OMX tools tree switch releases separately.
CAMERA_HEAL = 'exec ~/rosy-omx/current-env/bin/python "$0" "$@"'
CAMERA_HEAL_SCRIPT = str(Path(__file__).resolve())


def with_camera_heal(argv: list[str], job: dict, params: dict) -> list[str]:
    """Camera jobs first check their cell config's cameras and run the upkeep camera recovery (no motion)."""
    from cell_job_spec import ENV, job_arms

    if not job.get("camera"):
        return argv
    arms = job_arms(job, params)
    keyed = (("config", arms[0] if len(arms) == 1 else None), ("config_a", "arm_a"), ("config_b", "arm_b"))
    targets = [f"{arm or '-'}={params[key]}" for key, arm in keyed if params.get(key)]
    if not targets:
        return argv
    return ["bash", "-c", ENV + CAMERA_HEAL, CAMERA_HEAL_SCRIPT,
            *[x for t in targets for x in ("--target", t)], "--", *argv]


def heal(targets, io=None) -> list[dict]:
    """targets: [(arm or None, cell config path)]. Returns the upkeep rows, one per config."""
    from cell_upkeep import Io
    from cell_upkeep_checks import bus_owner, check_cameras

    io = io or Io()
    rows = []
    for arm, config in targets:
        cameras = json.loads(Path(config).read_text(encoding="utf-8")).get("cameras") or {}
        owner = bus_owner(arm, io) if arm else None
        found, _top = check_cameras(arm or "cell", cameras, io, fix=True, bus_free=owner is None)
        rows += [{**r, "arm": arm, "config": str(config)} for r in found]
    return rows


def _target(text: str):
    arm, sep, config = text.partition("=")
    if not sep or not config:
        raise argparse.ArgumentTypeError("--target is ARM=CONFIG (ARM may be '-')")
    return (None if arm in ("", "-") else arm), config


def main(argv=None, *, heal_fn=heal, exec_fn=os.execvp) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    if "--" not in argv:
        print("REFUSED: cell_camera_heal needs '-- <job argv>'")
        return 2
    cut = argv.index("--")
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--target", type=_target, action="append", required=True)
    args, command = ap.parse_args(argv[:cut]), argv[cut + 1:]
    if not command:
        print("REFUSED: no job command after '--'")
        return 2
    rows = heal_fn(args.target)
    print(json.dumps({"camera_preflight": rows}), flush=True)
    failed = [r for r in rows if r.get("status") == "fail"]
    if failed:
        print("REFUSED: cameras not ready after automatic recovery: " + "; ".join(r["detail"] for r in failed), flush=True)
        return 3
    exec_fn(command[0], command)
    return 0  # exec_fn replaced the process; reached only with a test seam


if __name__ == "__main__":
    raise SystemExit(main())
