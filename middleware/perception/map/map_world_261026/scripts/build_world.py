#!/usr/bin/env python3
"""Build worlds/map_world_261026.world and meshes/road_lines_loop.stl.

The 261026 team track mat (2.44 x 1.22 m). Geometry follows the active graph v7
(Rosy/docs/research/map-world-261026/2026-11-01-world261026-graph-v7.json) and the
2026-10-31 ceiling-camera finding (bundle README): the CAD loop paint matches the
floor, the parking area does not — the real bays are pink tape. So the loop keeps
the measured CAD paint (triangles fully in y <= 0.20, the accepted registration
subset) and the parking area is pink planes plus collision bay guides from v7.

Usage: python build_world.py [--out BUNDLE_DIR]
Output is byte-deterministic; re-run and diff before committing.
"""

import argparse
import math
import struct
from pathlib import Path

HERE = Path(__file__).resolve().parent
BUNDLE = HERE.parent
SOURCE_STL = BUNDLE / "meshes" / "road_lines.stl"
LOOP_URI = "model://control/map/map_world_261026/meshes/road_lines_loop.stl"

#: Mat and wall ring (design values from the CAD; wall thickness like map_v2_fleet).
MAT_X, MAT_Y = 2.44, 1.22
WALL_T, WALL_H = 0.005, 0.155
WALL_MATERIAL = "<ambient>0.30 0.35 0.45 1</ambient><diffuse>0.30 0.35 0.45 1</diffuse>"
FLOOR_RGBA = "0.2 0.2 0.2 1"
WHITE_PAINT_RGBA = "1 1 1 1"

#: Graph v7. P_y is the pink guide bar in front of the bays (the 교차점 line),
#: C_y the charge pose; the bay lane paint runs between them.
P_Y = 0.022
C_Y = 0.47
BAY_XS = (-0.414, -0.19, 0.032)
#: Guide bar and entrance/exit curves (v7 edges park_in, bar_32+bar_21, park_out).
GUIDE_POLYLINE = (
    ((0.309, -0.130), (0.266, -0.045), (0.220, P_Y), (0.032, P_Y)),       # park_in
    ((0.021, P_Y), (-0.212, P_Y), (-0.434, P_Y)),                         # guide bar
    ((-0.414, P_Y), (-0.583, P_Y), (-0.637, -0.039), (-0.687, -0.126)),   # park_out
)
#: Pink tape width on the mat (unmeasured; v7 lanes are 0.15-0.18 wide).
TAPE_W = 0.025
PINK_Z = 0.0015
#: Diffuse chosen to pass floor_pink_mask (lane_keep_lines PINK_*): rendered
#: BGR ~ (217, 38, 242) -> H ~146, S ~215, V ~242 with margin on every gate.
PINK_RGBA = "0.95 0.15 0.85 1"
#: Bay 3D guides (design values, unmeasured): two low rails per bay plus a rear
#: stop bar, the only parking-area collision. 0.015 stays below the camera plane
#: so the pink line stays visible over them.
BAY_HALF_W = 0.09
RAIL_Y0, RAIL_Y1 = 0.40, 0.555
GUIDE_T, GUIDE_H = 0.008, 0.015
GUIDE_MATERIAL = "<ambient>0.85 0.55 0.15 1</ambient><diffuse>0.85 0.55 0.15 1</diffuse>"
#: Green bay border tape (visual only), outside the rails.
BORDER_RGBA = "0.15 0.75 0.25 1"
BORDER_Z = 0.0012


def read_triangles(path: Path):
    """Binary STL triangles as ((v0),(v1),(v2)) in metres, ROS frame."""
    data = path.read_bytes()
    count = struct.unpack_from("<I", data, 80)[0]
    tris = []
    for i in range(count):
        off = 84 + 50 * i
        vals = struct.unpack_from("<12f", data, off)
        tris.append((tuple(vals[3:6]), tuple(vals[6:9]), tuple(vals[9:12])))
    return tris


def write_mesh(triangles, path: Path, note: str) -> None:
    header = f"rosy map_world_261026 {note} (metres, Z-up)".encode()[:80].ljust(80, b" ")
    body = bytearray(header + struct.pack("<I", len(triangles)))
    for t in triangles:
        ux, uy, _ = (t[1][k] - t[0][k] for k in range(3))
        vx, vy, _ = (t[2][k] - t[0][k] for k in range(3))
        nx, ny, nz = uy * 0 - 0 * vy, 0 * vx - ux * 0, ux * vy - uy * vx
        length = math.sqrt(nx * nx + ny * ny + nz * nz) or 1.0
        body += struct.pack("<12fH", nx / length, ny / length, nz / length,
                            *t[0], *t[1], *t[2], 0)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(bytes(body))


def loop_triangles(triangles):
    """The ceiling-accepted loop subset: triangles entirely in y <= 0.20 m."""
    return [t for t in triangles if max(v[1] for v in t) <= 0.20]


def _plane_xml(name, x1, y1, x2, y2, width, rgba, z):
    dx, dy = x2 - x1, y2 - y1
    length = math.hypot(dx, dy)
    yaw = math.atan2(dy, dx)
    return f"""        <visual name="{name}">
          <pose>{(x1 + x2) / 2:.4f} {(y1 + y2) / 2:.4f} {z:.4f} 0 0 {yaw:.6f}</pose>
          <geometry><plane><normal>0 0 1</normal><size>{length:.4f} {width:.4f}</size></plane></geometry>
          <material><ambient>{rgba}</ambient><diffuse>{rgba}</diffuse></material>
        </visual>
"""


def _pink_guide_xml():
    parts, i = [], 0
    for polyline in GUIDE_POLYLINE:
        for (x1, y1), (x2, y2) in zip(polyline[:-1], polyline[1:]):
            parts.append(_plane_xml(f"guide_{i:02d}", x1, y1, x2, y2, TAPE_W, PINK_RGBA, PINK_Z))
            i += 1
    for k, bx in enumerate(BAY_XS):
        parts.append(_plane_xml(f"bay_{k + 1}_line", bx, P_Y, bx, C_Y, TAPE_W, PINK_RGBA, PINK_Z))
    return f"""    <model name="pink_guide">
      <static>true</static>
      <pose>0 0 0 0 0 0</pose>
      <link name="link">
{"".join(parts)}      </link>
    </model>

"""


def _bay_xml(idx, bx):
    """One charge bay: collision rails + rear bar, green border tape (visual)."""
    def box(name, cx, cy, sx, sy, collision):
        col = f"""        <collision name="{name}_col">
          <pose>{cx:.4f} {cy:.4f} {GUIDE_H / 2:.4f} 0 0 0</pose>
          <geometry><box><size>{sx:.4f} {sy:.4f} {GUIDE_H:.4f}</size></box></geometry>
          <surface><friction><ode><mu>0.3</mu><mu2>0.3</mu2></ode></friction></surface>
        </collision>
""" if collision else ""
        return f"""{col}        <visual name="{name}_vis">
          <pose>{cx:.4f} {cy:.4f} {GUIDE_H / 2:.4f} 0 0 0</pose>
          <geometry><box><size>{sx:.4f} {sy:.4f} {GUIDE_H:.4f}</size></box></geometry>
          <material>{GUIDE_MATERIAL}</material>
        </visual>
"""
    rail_len = RAIL_Y1 - RAIL_Y0
    rail_yc = (RAIL_Y0 + RAIL_Y1) / 2
    boxes = "".join((
        box("rail_left", -BAY_HALF_W, rail_yc, GUIDE_T, rail_len, True),
        box("rail_right", BAY_HALF_W, rail_yc, GUIDE_T, rail_len, True),
        box("stop_bar", 0.0, RAIL_Y1, 2 * BAY_HALF_W, GUIDE_T, True),
    ))
    borders = (_plane_xml("border_left", -BAY_HALF_W - 0.004, 0.24,
                          -BAY_HALF_W - 0.004, 0.55, 0.012, BORDER_RGBA, BORDER_Z)
               + _plane_xml("border_right", BAY_HALF_W + 0.004, 0.24,
                            BAY_HALF_W + 0.004, 0.55, 0.012, BORDER_RGBA, BORDER_Z))
    return f"""    <model name="bay_guide_{idx}">
      <static>true</static>
      <pose>{bx:.4f} 0 0 0 0 0</pose>
      <link name="link">
{boxes}{borders}      </link>
    </model>

"""


def _wall_xml(i, cx, cy, sx, sy):
    pose = f"{cx:.4f} {cy:.4f} {WALL_H / 2:.4f} 0 0 0"
    size = f"{sx:.4f} {sy:.4f} {WALL_H:.4f}"
    return f"""        <collision name="wall_{i:02d}_col">
          <pose>{pose}</pose>
          <geometry><box><size>{size}</size></box></geometry>
          <surface><friction><ode><mu>0.9</mu><mu2>0.9</mu2></ode></friction></surface>
        </collision>
        <visual name="wall_{i:02d}_vis">
          <pose>{pose}</pose>
          <geometry><box><size>{size}</size></box></geometry>
          <material>{WALL_MATERIAL}</material>
        </visual>
"""


def world_xml(loop_count: int) -> str:
    hx, hy = MAT_X / 2, MAT_Y / 2
    walls = "".join((
        _wall_xml(0, 0.0, hy + WALL_T / 2, MAT_X + 2 * WALL_T, WALL_T),
        _wall_xml(1, 0.0, -hy - WALL_T / 2, MAT_X + 2 * WALL_T, WALL_T),
        _wall_xml(2, hx + WALL_T / 2, 0.0, WALL_T, MAT_Y),
        _wall_xml(3, -hx - WALL_T / 2, 0.0, WALL_T, MAT_Y),
    ))
    bays = "".join(_bay_xml(i + 1, bx) for i, bx in enumerate(BAY_XS))
    return f"""<?xml version="1.0"?>
<!-- MAP world 261026 — generated by scripts/build_world.py. Do not edit.
  Mat 2.44 x 1.22 m. Loop paint: meshes/road_lines.stl triangles in y <= 0.20
  ({loop_count} of the measured CAD paint; the ceiling-accepted subset).
  Parking area: pink guide tape and bay lanes from graph v7 (visual only) plus
  per-bay collision rails and a rear stop bar (design values, unmeasured).
  Green bay borders visual only. The wall ring is the loop-side collision.
-->
<sdf version="1.6">
  <world name="map_world_261026">
    <plugin filename="gz-sim-physics-system" name="gz::sim::systems::Physics">
      <engine><filename>gz-physics-dartsim-plugin</filename></engine>
    </plugin>
    <plugin filename="gz-sim-user-commands-system" name="gz::sim::systems::UserCommands"/>
    <plugin filename="gz-sim-scene-broadcaster-system" name="gz::sim::systems::SceneBroadcaster"/>
    <plugin filename="gz-sim-sensors-system" name="gz::sim::systems::Sensors">
      <render_engine>ogre2</render_engine>
    </plugin>
    <plugin filename="gz-sim-imu-system" name="gz::sim::systems::Imu"/>

    <light type="directional" name="sun">
      <cast_shadows>false</cast_shadows>
      <pose>0 0 10 0 0 0</pose>
      <diffuse>0.9 0.9 0.9 1</diffuse>
      <specular>0.2 0.2 0.2 1</specular>
      <direction>-0.4 0.2 -0.9</direction>
    </light>

    <model name="ground_plane">
      <static>true</static>
      <link name="link">
        <collision name="collision">
          <geometry><plane><normal>0 0 1</normal><size>5 5</size></plane></geometry>
        </collision>
        <visual name="visual">
          <geometry><plane><normal>0 0 1</normal><size>5 5</size></plane></geometry>
          <material><ambient>{FLOOR_RGBA}</ambient><diffuse>{FLOOR_RGBA}</diffuse></material>
        </visual>
      </link>
    </model>

    <model name="road_lines_loop">
      <static>true</static>
      <pose>0 0 0.001 0 0 0</pose>
      <link name="link">
        <visual name="paint">
          <geometry><mesh><uri>{LOOP_URI}</uri></mesh></geometry>
          <material><ambient>{WHITE_PAINT_RGBA}</ambient><diffuse>{WHITE_PAINT_RGBA}</diffuse></material>
        </visual>
      </link>
    </model>

{_pink_guide_xml()}{bays}    <model name="track_261026">
      <static>true</static>
      <pose>0 0 0 0 0 0</pose>
      <link name="link">
{walls}      </link>
    </model>
  </world>
</sdf>
"""


def build(out: Path) -> None:
    tris = read_triangles(SOURCE_STL)
    loop = loop_triangles(tris)
    if not loop or len(loop) == len(tris):
        raise ValueError(f"loop subset unexpected: {len(loop)} of {len(tris)}")
    write_mesh(loop, out / "meshes" / "road_lines_loop.stl", "road_lines_loop")
    world = out / "worlds" / "map_world_261026.world"
    world.parent.mkdir(parents=True, exist_ok=True)
    world.write_text(world_xml(len(loop)), encoding="utf-8", newline="\n")


def main(argv=None) -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--out", type=Path, default=BUNDLE)
    args = p.parse_args(argv)
    build(args.out)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
