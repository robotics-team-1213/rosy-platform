#!/usr/bin/env python3
"""OMX joint-zero capture tool for a supervised session: plans poses and fits from captured files. Moves no arm.

  plan  --calibration CAL.json --marker-offset-mm X Y Z [--config CELL.json] [-n 14] --out plan.json
  fit   --calibration CAL.json --marker-offset-mm X Y Z --capture DIR [--touch-z-mm H] [--report r.json]

The poses go to the existing supervised capture (person at the switch, D-911); nothing here sends a command or
relaxes a guard. `fit` writes only the report (also on PASS: applying the zeros stays a human step).
Marker: --marker-id (default: slot's gripper id), --marker-size-mm, --marker-offset-mm (centre in the link5 frame, MEASURE),
--marker-normal (which link5 face), --marker-yaw-deg. Frame: --origin-mm (arm frame minus link0, default 0), --tcp-x-mm.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import numpy as np

from omx_zero_model import Marker, cf
from omx_zero_frames import read_groups, read_touch, session_camera, summarise
from omx_zero_plan import plan
from omx_zero_solve import solve


def common(ap):
    ap.add_argument("--calibration", required=True, type=Path, help="rosy.omx-cell-calibration.v1 with cameras.top")
    ap.add_argument("--slot", type=int, default=2, help="arm slot for the gripper marker id (arm_b = 2: UNVERIFIED)")
    ap.add_argument("--marker-id", type=int)
    ap.add_argument("--marker-size-mm", type=float, default=20.0)
    ap.add_argument("--marker-offset-mm", type=float, nargs=3, required=True)
    ap.add_argument("--marker-normal", default="+z", choices=["+z", "-z", "+x", "-x", "+y", "-y"])
    ap.add_argument("--marker-yaw-deg", type=float, default=0.0)
    ap.add_argument("--origin-mm", type=float, nargs=3, default=[0.0, 0.0, 0.0])
    ap.add_argument("--tcp-x-mm", type=float, default=74.1)


def setup(a):
    record = json.loads(a.calibration.read_text())["cameras"]["top"]
    marker = Marker(a.marker_id if a.marker_id is not None else cf.slot_ids(a.slot)["gripper"], a.marker_size_mm,
                    tuple(a.marker_offset_mm), a.marker_normal, a.marker_yaw_deg)
    return record, marker


def run_fit(record, marker, folder, origin_mm=(0, 0, 0), touch_z_mm=None, tcp_x_mm=74.1, min_frames=5, free_camera=True):
    poses, skipped = [], []
    for key, group in read_groups(folder).items():
        s, why = summarise(group, record, marker.id, min_frames)
        (poses.append(s) if s else skipped.append({"pose": key, "why": why}))
    pooled = cam_rms = None
    if poses:
        cam, cam_rms, pooled = session_camera(record, poses)
        if cam is None:
            raise SystemExit("no base marker of the slot seen in any kept frame: the camera cannot be solved")
        poses = [dict(p, camera=cam) for p in poses]
    touch = None
    if touch_z_mm is not None:
        q = read_touch(folder)
        if q is None:
            raise SystemExit("--touch-z-mm needs touch.json (the jaw-tip-on-ruler joints) in the capture folder")
        touch = {"q_deg": q, "z_mm": touch_z_mm}
    report = solve(poses, marker, record, origin_mm, touch, tcp_x_mm, base=pooled if free_camera and poses else None)
    noise = [p["std_px"] for p in poses if p["std_px"] is not None]
    report.update(skipped=skipped, marker_noise_px={"median_per_pose_std": round(float(np.median(noise)), 2) if noise else None,
                                                    "frames_per_pose": [p["n"] for p in poses]},
                  camera_rms_px=None if not poses else round(float(cam_rms), 2),
                  camera_t_std_mm_median=round(float(np.median([p["camera_t_std_mm"] for p in poses])), 3) if poses else None)
    return report


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="verb", required=True)
    p = sub.add_parser("plan")
    common(p)
    p.add_argument("--config", type=Path, help="arm's cell config (joint_min/joint_max in .pos units)")
    p.add_argument("-n", type=int, default=14)
    p.add_argument("--seed", type=int, default=0)
    p.add_argument("--out", type=Path)
    f = sub.add_parser("fit")
    common(f)
    f.add_argument("--capture", required=True, type=Path)
    f.add_argument("--touch-z-mm", type=float, help="ruled jaw-tip height above the table at touch.json's pose")
    f.add_argument("--fixed-camera", action="store_true", help="keep the base-marker camera (the sim's assumption) instead of fitting it")
    f.add_argument("--min-frames", type=int, default=5)
    f.add_argument("--report", type=Path)
    a = ap.parse_args(argv)
    record, marker = setup(a)
    if a.verb == "plan":
        config = json.loads(a.config.read_text()) if a.config else None
        out = plan(record, marker, config, a.n, a.origin_mm, a.seed)
    else:
        out = run_fit(record, marker, a.capture, a.origin_mm, a.touch_z_mm, a.tcp_x_mm, a.min_frames, not a.fixed_camera)
    text = json.dumps(out, indent=1)
    path = a.out if a.verb == "plan" else a.report
    (path.write_text(text) if path else print(text))
    if a.verb == "fit":
        print(f"{out['verdict']}: {'; '.join(out['reasons']) or 'gate met'}", file=sys.stderr)
    return 0 if a.verb == "plan" or out["verdict"] == "PASS" else 2


if __name__ == "__main__":
    sys.exit(main())
