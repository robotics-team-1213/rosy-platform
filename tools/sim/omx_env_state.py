#!/usr/bin/env python3
"""Write a belt-pose checkpoint's ENV_STATE.json (Panel L): the environment_state names and the belt_reference the cell's
deploy/robot/omx/cell_belt_pose.py reads, since the cell has no tools/sim.

  omx_env_state.py --info DATASET/meta/info.json --top-camera top_refit.json --preset v24-20261126-real-home \
      --out CHECKPOINT/pretrained_model/ENV_STATE.json

--info: the training dataset's meta/info.json (observation.environment_state names, ending belt_dx_cm, belt_dy_cm,
belt_yaw_x5). --top-camera: the camera the training views were rendered around (top_refit.json, {"ok": true, "camera": {..}},
or a bare camera dict). --preset: the sim layout the data was collected in; the belt site, belt top and container size come
from omx_two_arm_sites.Layout(preset), the footprint tolerances from omx_real2sim_helpers (lane_blobs' container rule).
Optional --range="dx_lo,dx_hi,dy_abs,yaw_abs_deg" (write it with "=": dx_lo is usually negative) (m, m, m, deg) declares belt_reference.range, the range the
cell's gate uses instead of its default (past a hard ceiling in cell_belt_pose it is refused here and on the cell).
Write it into the checkpoint folder before package_cell_bundle, which copies it unchanged; the bundle's policy_revision
(model.safetensors sha256) does not change, its checkpoint_sha256 and file list do."""
from __future__ import annotations

import argparse
import json
import math
from pathlib import Path
import sys

HERE = Path(__file__).resolve().parent
sys.path[:0] = [str(HERE), str(HERE.parents[1] / "deploy" / "robot" / "omx")]
from cell_belt_pose import BELT_NAMES, CAMERA_KEYS, _range  # noqa: E402

GOAL = "observation.environment_state"


def parse_range(text: str) -> dict:
    """"dx_lo,dx_hi,dy_abs,yaw_abs_deg" (m, m, m, deg) -> belt_reference.range; cell_belt_pose enforces its ceiling."""
    try:
        dx_lo, dx_hi, dy_abs, yaw_deg = (float(v) for v in text.split(","))
    except ValueError:
        raise ValueError('--range needs "dx_lo,dx_hi,dy_abs,yaw_abs_deg" (m, m, m, deg)') from None
    return {"dx_m": [dx_lo, dx_hi], "dy_m": [-dy_abs, dy_abs], "yaw_rad": [-math.radians(yaw_deg), math.radians(yaw_deg)]}


def build(info: dict, top: dict, preset: str, belt_range: str | None = None) -> dict:
    import omx_two_arm_sites as sites
    from omx_real2sim_helpers import PARTIAL_MIN, SIZE_TOL

    feature = (info.get("features") or {}).get(GOAL) or {}
    names, shape = feature.get("names"), feature.get("shape")
    if not isinstance(names, list) or shape != [len(names)] or tuple(names[-len(BELT_NAMES):]) != BELT_NAMES:
        raise ValueError(f"{GOAL} names must match its shape and end with {list(BELT_NAMES)}")
    if "camera" in top:
        if top.get("ok") is False:
            raise ValueError("top camera fit is not ok")
        top = top["camera"]
    if any(key not in top for key in CAMERA_KEYS):
        raise ValueError(f"top camera needs {', '.join(CAMERA_KEYS)}")
    layout = sites.Layout(preset=preset)
    site = layout.sites["belt"]
    length, width, height = sites.CONTAINER[layout.choices["ship_source"]]
    reference = {
        "preset": preset, "top_camera": {key: top[key] for key in CAMERA_KEYS},
        "belt_site": {"xy": [float(v) for v in site["xy"]], "yaw": float(site["yaw"])},
        "belt_top_m": float(layout.belt_top),
        "container": {"length_m": length, "width_m": width, "height_m": height},
        "footprint_tol_m": {"length": SIZE_TOL[0], "width": SIZE_TOL[1] + 0.004, "partial_min": PARTIAL_MIN}}
    if belt_range is not None:
        reference["range"] = parse_range(belt_range)
        _range(reference["range"])  # same ceiling and shape check the cell applies: refuse here, not on the cell
    return {"names": names, "belt_reference": reference}


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--info", type=Path, required=True)
    parser.add_argument("--top-camera", type=Path, required=True)
    parser.add_argument("--preset", required=True)
    parser.add_argument("--range", dest="belt_range", help='optional "dx_lo,dx_hi,dy_abs,yaw_abs_deg" (m, m, m, deg): '
                        "the trained range plus margin; omitted -> no range key (cell default)")
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args(argv)
    try:
        doc = build(json.loads(args.info.read_text(encoding="utf-8")), json.loads(args.top_camera.read_text(encoding="utf-8")),
                    args.preset, args.belt_range)
    except (ValueError, KeyError, OSError) as error:
        parser.error(str(error))
    args.out.write_text(json.dumps(doc, indent=2) + "\n", encoding="utf-8")
    print(args.out)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
