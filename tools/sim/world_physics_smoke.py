"""Headless MuJoCo physics smoke: step a deterministic rigid-body scene and verify finite state.

Prefers the real two-arm OMX cell when it loads (`omx_two_arm_world`); otherwise
steps a minimal box-on-plane scene. Prints one JSON summary line, writes it to
`--out` when given, exits 0 on pass, 3 when mujoco is missing, 4 when the scene
cannot load or the state goes non-finite. LOCAL evidence only (D-91).

    python tools/sim/world_physics_smoke.py --steps 200 --out smoke.json
    python tools/remote/remote_sim.py <host> cmd -- python3 tools/sim/world_physics_smoke.py --out "$OUT/physics-smoke.json"
"""
from __future__ import annotations

import argparse
import json
import math
from pathlib import Path
import sys

BOX_ON_PLANE_XML = """\
<mujoco model="rosy_physics_smoke">
  <option timestep="0.002"/>
  <worldbody>
    <geom name="floor" type="plane" size="1 1 0.1" friction="1 0.005 0.0001"/>
    <body name="box" pos="0 0 0.2">
      <freejoint/>
      <geom name="box" type="box" size="0.05 0.05 0.05" mass="0.2" friction="1 0.005 0.0001"/>
    </body>
  </worldbody>
</mujoco>
"""


def _finite(values) -> bool:
    flat = list(values.flat) if hasattr(values, "flat") else list(values)
    return len(flat) > 0 and all(math.isfinite(float(value)) for value in flat)


def _load_scene(mujoco):
    """Return (model, scene_name): the OMX two-arm cell when it loads, else the minimal box."""
    try:
        here = str(Path(__file__).resolve().parent)
        if here not in sys.path:
            sys.path.insert(0, here)
        import omx_two_arm_world

        return omx_two_arm_world.World().model, "omx_two_arm_world"
    except Exception:  # missing private cell values, assets or deps: fall back to the minimal scene
        return mujoco.MjModel.from_xml_string(BOX_ON_PLANE_XML), "minimal_box_on_plane"


def run(steps: int) -> tuple[dict, int]:
    try:
        import mujoco  # deferred so importing this module never needs mujoco
    except (ImportError, OSError) as error:  # a broken native install must not traceback
        return {"ok": False, "engine": "mujoco", "error": f"mujoco is not importable: {error}"}, 3
    try:
        model, scene = _load_scene(mujoco)
    except Exception as error:
        return {"ok": False, "engine": "mujoco", "error": f"scene load failed: {error}"}, 4
    data = mujoco.MjData(model)
    for _ in range(max(0, steps)):
        mujoco.mj_step(model, data)
        if not _finite(data.qpos) or not _finite(data.qvel):
            return {"ok": False, "engine": "mujoco", "scene": scene, "error": "non-finite qpos/qvel"}, 4
    if not (_finite(data.qfrc_constraint) and _finite(data.qfrc_actuator) and _finite(data.cfrc_ext)):
        return {"ok": False, "engine": "mujoco", "scene": scene, "error": "non-finite forces/contacts"}, 4
    if not math.isfinite(data.time):
        return {"ok": False, "engine": "mujoco", "scene": scene, "error": "non-finite sim time"}, 4
    return {
        "ok": True,
        "engine": "mujoco",
        "scene": scene,
        "steps": max(0, steps),
        "dt_s": float(model.opt.timestep),
        "sim_time_s": round(float(data.time), 6),
        "contacts": int(data.ncon),
    }, 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--steps", type=int, default=200, help="physics steps to run")
    parser.add_argument("--out", type=Path, help="optional path for the JSON summary")
    args = parser.parse_args(argv)
    summary, code = run(args.steps)
    line = json.dumps(summary, ensure_ascii=False, allow_nan=False)
    print(line)
    if args.out is not None:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(line + "\n", encoding="utf-8")
    return code


if __name__ == "__main__":
    raise SystemExit(main())
