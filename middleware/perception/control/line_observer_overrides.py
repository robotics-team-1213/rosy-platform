"""Write or remove the operator override overlay of line_observer_node (D-344 §12 addendum 2026-10-03).

The bench switch used to edit the release's line_follow.yaml in place, so every
payload update (a new /opt/rosy/releases/<id>) silently dropped it. This tool
writes /etc/rosy/line_observer_overrides.yaml instead, which no release or
image-layer sync replaces, and camera_preview.launch.py layers it last. It
refuses anything the launch validator would skip, so a written file is a
loaded file. Run as root on the robot; it restarts only rosy-camera. sudo
drops PYTHONPATH, so source the ROS and release environments inside the root
shell and start it with ros2 run:

    sudo -n bash -c 'source /opt/ros/jazzy/setup.bash && source /opt/rosy/current/install/setup.bash && ros2 run control line_observer_overrides apply --profile <camera_nominal.yaml> [--pitch-deg 11.2] [--height-m 0.059]'

with ``clear`` (remove, restart) or ``show`` (print, would launch load it) in
place of ``apply ...``.

Pitch and height are the D-397 operator layer: omit them and the robot's
accepted camera_profile record, else the URDF nominal file, applies.
"""

from __future__ import annotations

import argparse
import math
import os
import subprocess
import sys
import tempfile

import yaml

from control.ir_overlay import LEARNED_PAINT_TARGETS, NODE_KEY, OPERATOR_OVERLAY, operator_overlay_problem

CAMERA_UNIT = "rosy-camera"


def overlay_for(args) -> dict:
    params = {"camera_lane_mode": args.mode, "camera_ground_source": args.ground,
              "debug_overlay": not args.no_debug_overlay}
    if args.ground == "NOMINAL":
        params.update(allow_nominal_ground=True, nominal_camera_profile_path=args.profile or "")
    if args.pitch_deg is not None:
        params["camera_pitch_rad_override"] = math.radians(args.pitch_deg)
    if args.height_m is not None:
        params["camera_height_m_override"] = float(args.height_m)
    if args.paint_source is not None:
        params["paint_source"] = args.paint_source
    if args.model_pointer is not None:
        params["learned_lane_pointer"] = args.model_pointer
    if args.paint_every_n is not None:
        params["learned_paint_every_n"] = args.paint_every_n
    if args.paint_motion_compensation:
        params["learned_paint_motion_compensation"] = True
    if args.paint_target is not None:
        params["learned_paint_target"] = args.paint_target
    return {NODE_KEY: {"ros__parameters": params}}


def write_overlay(path: str, data: dict) -> None:
    problem = operator_overlay_problem(data)
    if problem is not None:
        raise ValueError(problem)
    directory = os.path.dirname(path) or "."
    handle, temp = tempfile.mkstemp(prefix=".line_observer_overrides.", dir=directory)
    try:
        with os.fdopen(handle, "w", encoding="utf-8") as out:
            out.write("# Written by line_observer_overrides (D-344 §12 addendum); "
                      "remove with: line_observer_overrides clear\n")
            yaml.safe_dump(data, out, sort_keys=False)
            out.flush()
            os.fsync(out.fileno())
        os.chmod(temp, 0o644)
        os.replace(temp, path)
        _fsync_dir(directory)
    except BaseException:
        if os.path.exists(temp):
            os.unlink(temp)
        raise


def _fsync_dir(directory: str) -> None:
    """Make the rename survive a power cut (robots are switched off at the bench)."""
    if not hasattr(os, "O_DIRECTORY"):   # Windows hosts: no directory handles to sync
        return
    handle = os.open(directory, os.O_RDONLY | os.O_DIRECTORY)
    try:
        os.fsync(handle)
    finally:
        os.close(handle)


def main(argv=None, run=subprocess.run) -> int:
    parser = argparse.ArgumentParser(prog="line_observer_overrides", description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--path", default=OPERATOR_OVERLAY)
    sub = parser.add_subparsers(dest="command", required=True)
    apply = sub.add_parser("apply", help="write the overlay, then restart rosy-camera")
    apply.add_argument("--mode", default="keep")
    apply.add_argument("--ground", default="NOMINAL", choices=("NOMINAL", "PINKY"))
    apply.add_argument("--profile", help="nominal camera profile (required for NOMINAL ground)")
    apply.add_argument("--pitch-deg", type=float)
    apply.add_argument("--height-m", type=float)
    apply.add_argument("--paint-source", choices=("threshold", "denoise", "learned"),
                       help="keep-mode paint input; learned falls back to denoise per frame")
    apply.add_argument("--model-pointer", help="absolute model pointer, required for learned paint")
    apply.add_argument("--paint-every-n", type=int, choices=range(1, 5), metavar="1..4",
                       help="learned paint: submit inference every Nth keep frame (node default 2)")
    apply.add_argument("--paint-motion-compensation", action="store_true",
                       help="learned paint: warp older masks by odometry (D-570)")
    apply.add_argument("--paint-target", choices=LEARNED_PAINT_TARGETS,
                       help="learned paint: lane_marking classes (default) or the drivable way's boundaries (D-NNN)")
    apply.add_argument("--no-debug-overlay", action="store_true")
    clear = sub.add_parser("clear", help="remove the overlay, then restart rosy-camera")
    for command in (apply, clear):
        command.add_argument("--no-restart", action="store_true")
    sub.add_parser("show", help="print the overlay and whether launch would load it")
    args = parser.parse_args(argv)

    if args.command == "show":
        from control.ir_overlay import usable_operator_overlay
        if os.path.isfile(args.path):
            with open(args.path, encoding="utf-8") as handle:
                sys.stdout.write(handle.read())
        print(usable_operator_overlay(args.path)[1])
        return 0
    try:
        if args.command == "apply":
            if args.profile is not None and not os.path.isfile(args.profile):
                # The node would only log "unreadable" and keep NOMINAL ground off.
                raise ValueError(f"--profile {args.profile} is not an existing file")
            write_overlay(args.path, overlay_for(args))
            print(f"wrote {args.path}")
        elif os.path.exists(args.path):
            os.unlink(args.path)
            _fsync_dir(os.path.dirname(args.path) or ".")
            print(f"removed {args.path}; packaged camera lane settings apply")
        else:
            print(f"{args.path} absent; nothing to remove")
    except (OSError, ValueError) as exc:
        print(f"line_observer_overrides: {exc}", file=sys.stderr)
        return 1
    if args.no_restart:
        print(f"not restarted; run: systemctl restart {CAMERA_UNIT}")
        return 0
    return run(["systemctl", "restart", CAMERA_UNIT], check=False).returncode


if __name__ == "__main__":
    sys.exit(main())
