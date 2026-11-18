#!/usr/bin/env python3
"""OMX joint-zero capture tool for a supervised session: plans poses and fits from captured files. Moves no arm.

  plan  (--calibration CAL.json | --intrinsics I.json --base-markers M.json) --slot N --camera NAME [--camera ...]
        --marker-offset-mm X Y Z [--config CELL.json] [-n 14] --out plan.json
  fit   ... --capture DIR [--touch-z-mm H] [--camera-prior NAME:HEIGHT_MM,TILT_DEG] [--report r.json]

The poses go to the existing supervised capture (person at the switch, D-911); nothing here sends a command or
relaxes a guard. `fit` writes only the report (also on PASS: applying the zeros stays a human step). Every
`--camera NAME` must exist in the calibration's `cameras`; a multi-camera capture folder holds one subfolder per
camera name (a single camera keeps the flat layout). Without a calibration record, `--intrinsics` (K, dist, size)
plus `--base-markers` (ruler-measured arm coordinates per marker id) start the session: the camera is then seeded by
base-marker PnP, and `--base-sigma-mm` puts that ruler error into the residuals.
Marker: --marker-id (default: slot's gripper id), --marker-size-mm, --marker-offset-mm (centre in the link5 frame,
MEASURE), --marker-normal (which link5 face), --marker-yaw-deg. Frame: --origin-mm (arm frame minus link0), --tcp-x-mm.
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
    ap.add_argument("--calibration", type=Path, help="rosy.omx-cell-calibration.v1 with cameras.<NAME> per --camera")
    ap.add_argument("--slot", type=int, required=True, help="arm slot for the gripper marker id (arm_b = 2: UNVERIFIED)")
    ap.add_argument("--camera", action="append", required=True, metavar="NAME",
                    help="camera name in the calibration; repeat for each camera of the session")
    ap.add_argument("--intrinsics", type=Path, help="K/dist/size json; with --base-markers, replaces --calibration")
    ap.add_argument("--base-markers", type=Path,
                    help='json {"<id>": {"centre_mm": [x,y,z], "size_mm": s, "normal": "+z", "yaw_deg": 0}}, ruler-measured')
    ap.add_argument("--base-sigma-mm", type=float, default=0.3, help="ruler error of those base coordinates")
    ap.add_argument("--camera-prior", action="append", default=[], metavar="NAME:HEIGHT_MM,TILT_DEG",
                    help="stated mounting; a fitted camera further off than 20 mm / 2 deg fails the gate")
    ap.add_argument("--marker-id", type=int)
    ap.add_argument("--marker-size-mm", type=float, default=20.0)
    ap.add_argument("--marker-offset-mm", type=float, nargs=3, required=True)
    ap.add_argument("--marker-normal", default="+z", choices=["+z", "-z", "+x", "-x", "+y", "-y"])
    ap.add_argument("--marker-yaw-deg", type=float, default=0.0)
    ap.add_argument("--origin-mm", type=float, nargs=3, default=[0.0, 0.0, 0.0])
    ap.add_argument("--tcp-x-mm", type=float, default=74.1)


def marker_corners_mm(spec):
    return Marker(0, float(spec["size_mm"]), tuple(float(v) for v in spec["centre_mm"]),
                  spec.get("normal", "+z"), float(spec.get("yaw_deg", 0.0))).local_corners()


def parse_priors(items, records):
    priors = {}
    for it in items:
        name, vals = it.split(":", 1)
        if name not in records:
            raise SystemExit(f"--camera-prior names {name}, which is not a --camera of this session ({sorted(records)})")
        h, t = (float(v) for v in vals.split(","))
        priors[name] = (h, t)
    return priors


def setup(a):
    if a.calibration and (a.intrinsics or a.base_markers):
        raise SystemExit("--intrinsics/--base-markers replace --calibration; pass one of the two")
    if a.calibration:
        data = json.loads(a.calibration.read_text())["cameras"]
        missing = [nm for nm in a.camera if nm not in data]
        if missing:
            raise SystemExit(f"calibration has no camera {missing} (it has {sorted(data)})")
        records = {nm: data[nm] for nm in a.camera}
    elif a.intrinsics and a.base_markers:
        if len(a.camera) != 1:
            raise SystemExit("the --intrinsics + --base-markers path serves one camera (its base markers seed it)")
        intr, bm = json.loads(a.intrinsics.read_text()), json.loads(a.base_markers.read_text())
        if not bm:
            raise SystemExit("--base-markers is empty: the camera seed needs at least one base marker")
        records = {a.camera[0]: {"K": intr["K"], "dist": intr["dist"], "size": intr["size"],
                                 "markers": {i: (marker_corners_mm(s) / 1000.0).tolist() for i, s in bm.items()},
                                 "base": sorted(int(i) for i in bm)}}
    else:
        raise SystemExit("pass --calibration, or --intrinsics and --base-markers together")
    marker = Marker(a.marker_id if a.marker_id is not None else cf.slot_ids(a.slot)["gripper"], a.marker_size_mm,
                    tuple(a.marker_offset_mm), a.marker_normal, a.marker_yaw_deg)
    return records, marker, parse_priors(a.camera_prior, records)


def _camera_folder(folder, name, n_cameras):
    sub = Path(folder) / name
    if sub.is_dir():
        return sub
    if n_cameras == 1:
        return Path(folder)
    raise SystemExit(f"capture folder lacks a '{name}' subfolder per camera (it has "
                     f"{sorted(p.name for p in Path(folder).iterdir())})")


def run_fit(records, marker, folder, origin_mm=(0, 0, 0), touch_z_mm=None, tcp_x_mm=74.1, min_frames=5,
            free_camera=True, base_sigma_mm=0.3, priors=None):
    cam_poses, skipped, pooled, cam_rms, cam_std = {}, [], {}, {}, {}
    for nm, record in records.items():
        poses_nm = []
        for key, group in read_groups(_camera_folder(folder, nm, len(records))).items():
            s, why = summarise(group, record, marker.id, min_frames)
            (poses_nm.append(s) if s else skipped.append({"camera": nm, "pose": key, "why": why}))
        if not poses_nm:
            raise SystemExit(f"camera {nm}: no usable pose in its capture folder")
        cam, rms, pooled_nm = session_camera(record, poses_nm)
        if cam is None:
            raise SystemExit(f"camera {nm}: no base marker seen in any kept frame, the camera cannot be seeded")
        cam_poses[nm] = [dict(p, camera=cam) for p in poses_nm]
        pooled[nm], cam_rms[nm] = pooled_nm, float(rms)
        cam_std[nm] = float(np.median([p["camera_t_std_mm"] for p in poses_nm]))
    touch = None
    if touch_z_mm is not None:
        q = read_touch(folder)
        if q is None:
            raise SystemExit("--touch-z-mm needs touch.json (the jaw-tip-on-ruler joints) in the capture folder")
        touch = {"q_deg": q, "z_mm": touch_z_mm}
    report = solve(cam_poses, marker, records, origin_mm, touch, tcp_x_mm, base=pooled if free_camera else None,
                   base_sigma_mm=base_sigma_mm, priors=priors)
    noise = [p["std_px"] for ps in cam_poses.values() for p in ps if p["std_px"] is not None]
    report.update(skipped=skipped,
                  marker_noise_px={"median_per_pose_std": round(float(np.median(noise)), 2) if noise else None,
                                   "frames_per_pose": {nm: [p["n"] for p in ps] for nm, ps in cam_poses.items()}},
                  camera_rms_px={nm: round(v, 2) for nm, v in cam_rms.items()},
                  camera_t_std_mm_median={nm: round(v, 3) for nm, v in cam_std.items()})
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
    records, marker, priors = setup(a)
    if a.verb == "plan":
        config = json.loads(a.config.read_text()) if a.config else None
        out = plan(records, marker, config, a.n, a.origin_mm, a.seed, priors=priors or None)
        rc = 0 if out["gate"] == "PASS" else 2
    else:
        out = run_fit(records, marker, a.capture, a.origin_mm, a.touch_z_mm, a.tcp_x_mm, a.min_frames,
                      not a.fixed_camera, a.base_sigma_mm, priors or None)
        rc = 0 if out["verdict"] == "PASS" else 2
    text = json.dumps(out, indent=1)
    path = a.out if a.verb == "plan" else a.report
    (path.write_text(text) if path else print(text))
    if a.verb == "plan" and rc:
        print(f"gate FAIL: {'; '.join(out['gate_reasons'])}", file=sys.stderr)
    elif a.verb == "fit":
        print(f"{out['verdict']}: {'; '.join(out['reasons']) or 'gate met'}", file=sys.stderr)
    return rc


if __name__ == "__main__":
    sys.exit(main())
