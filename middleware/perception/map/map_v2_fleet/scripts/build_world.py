#!/usr/bin/env python3
"""Build worlds/map_v2_fleet.world, meshes/road_lines.stl and the parking
marker's textures/dock_tag_7.png from the 260919 STL, plus the real-profile
variant worlds/map_v2_fleet_real.world and its textures/carpet_grey.png.

Usage: python build_world.py [--out BUNDLE_DIR] [--line-colour bright|dark]
Output is byte-deterministic; re-run and diff before committing.
"""

import argparse
import importlib.util
import math
import struct
from dataclasses import replace
from pathlib import Path

import yaml

HERE = Path(__file__).resolve().parent
BUNDLE = HERE.parent
SOURCE = BUNDLE / "260919 MAP FILE.STL"
RULES = BUNDLE / "lane_rules.yaml"
MESH_URI = "model://control/map/map_v2_fleet/meshes/road_lines.stl"
COLOURS = {
    # (floor, paint): dark = black tape on white mat, bright = white tape on dark floor
    "dark": ("1 1 1 1", "0.05 0.05 0.05 1"),
    "bright": ("0.2 0.2 0.2 1", "1 1 1 1"),
}

#: Stage-3 parking marker (docs/plans/2026-09-23-lane-network-parking-design.md):
#: a low inclined ("wedge") ArUco tag, DICT_4X4_50 id 7, 50 mm, with a white
#: one-cell quiet zone, on a face inclined 25 deg whose bottom edge lies at
#: (-0.78, 0) facing -x into the bay. Its top rises 28 mm: the camera
#: (0.060 m high, 25 deg down) sees nothing above ~6 cm and only ~2 cm at
#: the spur entry's range. Visual only, like the paint. The face's diffuse
#: keeps the tag's white under line_observer's bright threshold (180), so
#: the paint pipeline never takes the marker for paint.
DOCK_TAG_ID = 7
DOCK_TAG_SIZE_M = 0.050
DOCK_TAG_QUIET_CELLS = 1
DOCK_TAG_FACE_M = DOCK_TAG_SIZE_M * (6 + 2 * DOCK_TAG_QUIET_CELLS) / 6
DOCK_TAG_TILT_RAD = math.radians(25.0)
DOCK_TAG_BOTTOM_X = -0.78
DOCK_TAG_DIFFUSE = "0.6 0.6 0.6 1"
DOCK_TAG_PX_PER_CELL = 40
TEXTURE_URI = "model://control/map/map_v2_fleet/textures/dock_tag_7.png"

#: D-395 rev. 1 floor reference squares (lane_rules.yaml `reference_squares`):
#: flat visual-only patches, red outline under a blue fill, just above the
#: lane paint (mesh at z 0.001). No collision, so the Nav2 map is unchanged.
SQUARE_COLOURS = {"red": "0.8 0.1 0.1 1", "blue": "0.1 0.2 0.8 1"}
SQUARE_OUTLINE_Z = 0.002
SQUARE_FILL_Z = 0.0025

WALL_MATERIAL = "<ambient>0.30 0.35 0.45 1</ambient><diffuse>0.30 0.35 0.45 1</diffuse>"

#: D-364 5 real profile: the 2026-09-19 track as the real robot camera sees it
#: (teleop_20260919_151213): grey textured carpet (~60-75 grey, speckle sd
#: ~8-10 in the 320x240 frame), white tape, white foam-board walls (~220
#: grey) taller than the camera's view near, blue tape on the board seams.
#: Grey levels are tuned against rendered Gazebo frames, not physics.
REAL_WALL_HEIGHT_M = 0.30
REAL_WALL_MATERIAL = (
    "<ambient>0.85 0.88 0.85 1</ambient><diffuse>0.85 0.88 0.85 1</diffuse>"
    "<emissive>0.55 0.57 0.55 1</emissive>")
REAL_FLOOR_RGBA = "0.13 0.14 0.13 1"
# Real tape reads ~186 grey against the sim's full-white 226.
REAL_PAINT_RGBA = "0.66 0.68 0.66 1"
CARPET_URI = "model://control/map/map_v2_fleet/textures/carpet_grey.png"
CARPET_PX = 256
CARPET_TILE_M = 0.5
CARPET_TILES = (6, 3)  # x, y: 3.0 x 1.5 m, past the 2.81 x 1.26 m wall ring
CARPET_DIFFUSE = "0.27 0.29 0.27 1"
CARPET_SEED = 260919
TAPE_RGBA = "0.05 0.15 0.75 1"
TAPE_SPACING_M = 0.60
TAPE_SIZE_M = (0.035, 0.12)  # width along the wall, height


def _scene_module():
    spec = importlib.util.spec_from_file_location("stl_scene", HERE / "stl_scene.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _normal(t):
    (ax, ay, az), (bx, by, bz), (cx, cy, cz) = t
    ux, uy, uz = bx - ax, by - ay, bz - az
    vx, vy, vz = cx - ax, cy - ay, cz - az
    nx, ny, nz = uy * vz - uz * vy, uz * vx - ux * vz, ux * vy - uy * vx
    length = (nx * nx + ny * ny + nz * nz) ** 0.5 or 1.0
    return nx / length, ny / length, nz / length


def write_mesh(lines, path: Path) -> None:
    header = b"rosy map_v2_fleet road_lines (metres, Z-up)".ljust(80, b" ")
    body = bytearray(header + struct.pack("<I", len(lines)))
    for t in lines:
        body += struct.pack("<12fH", *_normal(t), *t[0], *t[1], *t[2], 0)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(bytes(body))


def _wall_xml(i: int, w, height=None, material=WALL_MATERIAL) -> str:
    height = w.height if height is None else height
    pose = f"{w.cx:.5f} {w.cy:.5f} {height / 2:.5f} 0 0 0"
    size = f"{w.size_x:.5f} {w.size_y:.5f} {height:.5f}"
    return f"""        <collision name="wall_{i:02d}_col">
          <pose>{pose}</pose>
          <geometry><box><size>{size}</size></box></geometry>
          <surface><friction><ode><mu>0.9</mu><mu2>0.9</mu2></ode></friction></surface>
        </collision>
        <visual name="wall_{i:02d}_vis">
          <pose>{pose}</pose>
          <geometry><box><size>{size}</size></box></geometry>
          <material>{material}</material>
        </visual>
"""


def write_tag_texture(path: Path) -> None:
    """The marker plus its white quiet zone, row 0 at the top of the slope."""
    import cv2

    dictionary = cv2.aruco.getPredefinedDictionary(cv2.aruco.DICT_4X4_50)
    draw = getattr(cv2.aruco, "generateImageMarker", None) or cv2.aruco.drawMarker
    marker = draw(dictionary, DOCK_TAG_ID, 6 * DOCK_TAG_PX_PER_CELL)
    pad = DOCK_TAG_QUIET_CELLS * DOCK_TAG_PX_PER_CELL
    image = cv2.copyMakeBorder(marker, pad, pad, pad, pad, cv2.BORDER_CONSTANT, value=255)
    path.parent.mkdir(parents=True, exist_ok=True)
    ok, data = cv2.imencode(".png", image)
    if not ok:
        raise RuntimeError("could not encode the dock tag texture")
    path.write_bytes(data.tobytes())


def _dock_tag_xml() -> str:
    half = DOCK_TAG_FACE_M / 2.0
    cx = DOCK_TAG_BOTTOM_X + half * math.cos(DOCK_TAG_TILT_RAD)
    cz = half * math.sin(DOCK_TAG_TILT_RAD)
    # R_y(-tilt) takes the plane's +z normal to (-sin, 0, cos): facing -x, up.
    return f"""    <model name="dock_tag_{DOCK_TAG_ID}">
      <static>true</static>
      <link name="link">
        <visual name="face">
          <pose>{cx:.5f} 0 {cz:.5f} 0 {-DOCK_TAG_TILT_RAD:.6f} 0</pose>
          <geometry><plane><normal>0 0 1</normal><size>{DOCK_TAG_FACE_M:.5f} {DOCK_TAG_FACE_M:.5f}</size></plane></geometry>
          <material>
            <ambient>{DOCK_TAG_DIFFUSE}</ambient><diffuse>{DOCK_TAG_DIFFUSE}</diffuse>
            <pbr><metal><albedo_map>{TEXTURE_URI}</albedo_map></metal></pbr>
          </material>
        </visual>
      </link>
    </model>
"""


def write_carpet_texture(path: Path) -> None:
    """Grey carpet speckle: per-texel noise over a faint blotch layer."""
    import cv2
    import numpy as np

    rng = np.random.RandomState(CARPET_SEED)
    fine = rng.normal(0.0, 1.0, (CARPET_PX, CARPET_PX))
    blotch = cv2.GaussianBlur(rng.normal(0.0, 1.0, (CARPET_PX, CARPET_PX)), (0, 0), 6)
    blotch /= blotch.std() or 1.0
    image = np.clip(128.0 + 60.0 * fine + 22.0 * blotch, 0, 255).astype(np.uint8)
    path.parent.mkdir(parents=True, exist_ok=True)
    ok, data = cv2.imencode(".png", image)
    if not ok:
        raise RuntimeError("could not encode the carpet texture")
    path.write_bytes(data.tobytes())


def _reference_squares_xml() -> str:
    squares = yaml.safe_load(RULES.read_text(encoding="utf-8"))["reference_squares"]
    models = []
    for sq in squares:
        x, y = sq["centre"]
        parts = ((sq["size"], sq["outline_colour"], SQUARE_OUTLINE_Z, "outline"),
                 (sq["fill_size"], sq["fill_colour"], SQUARE_FILL_Z, "fill"))
        visuals = "".join(f"""        <visual name="{name}">
          <pose>0 0 {z} 0 0 0</pose>
          <geometry><plane><normal>0 0 1</normal><size>{size[0]:.3f} {size[1]:.3f}</size></plane></geometry>
          <material><ambient>{SQUARE_COLOURS[colour]}</ambient><diffuse>{SQUARE_COLOURS[colour]}</diffuse></material>
        </visual>
""" for size, colour, z, name in parts)
        models.append(f"""    <model name="reference_square_{sq["id"]}">
      <static>true</static>
      <pose>{x:.3f} {y:.3f} 0 0 0 0</pose>
      <link name="link">
{visuals}      </link>
    </model>

""")
    return "".join(models)


def _carpet_xml() -> str:
    nx, ny = CARPET_TILES
    tiles = []
    for ix in range(nx):
        for iy in range(ny):
            x = (ix - (nx - 1) / 2.0) * CARPET_TILE_M
            y = (iy - (ny - 1) / 2.0) * CARPET_TILE_M
            tiles.append(f"""        <visual name="tile_{ix}_{iy}">
          <pose>{x:.3f} {y:.3f} 0 0 0 0</pose>
          <geometry><plane><normal>0 0 1</normal><size>{CARPET_TILE_M} {CARPET_TILE_M}</size></plane></geometry>
          <material>
            <ambient>{CARPET_DIFFUSE}</ambient><diffuse>{CARPET_DIFFUSE}</diffuse>
            <pbr><metal><albedo_map>{CARPET_URI}</albedo_map></metal></pbr>
          </material>
        </visual>
""")
    return f"""    <model name="carpet">
      <static>true</static>
      <pose>0 0 0.0003 0 0 0</pose>
      <link name="link">
{"".join(tiles)}      </link>
    </model>

"""


def _tape_xml(walls) -> str:
    """Visual-only blue tape strips on each wall's inner face."""
    width, height = TAPE_SIZE_M
    strips = []
    for i, w in enumerate(walls):
        along_x = w.size_x >= w.size_y
        length = w.size_x if along_x else w.size_y
        count = max(1, int(length // TAPE_SPACING_M))
        for k in range(count):
            s = (k - (count - 1) / 2.0) * TAPE_SPACING_M
            if along_x:
                x, y = w.cx + s, w.cy - math.copysign(w.size_y / 2 + 0.001, w.cy)
                size = f"{width} 0.002 {height}"
            else:
                x, y = w.cx - math.copysign(w.size_x / 2 + 0.001, w.cx), w.cy + s
                size = f"0.002 {width} {height}"
            strips.append(f"""        <visual name="tape_{i:02d}_{k}">
          <pose>{x:.5f} {y:.5f} {0.02 + height / 2:.5f} 0 0 0</pose>
          <geometry><box><size>{size}</size></box></geometry>
          <material><ambient>{TAPE_RGBA}</ambient><diffuse>{TAPE_RGBA}</diffuse></material>
        </visual>
""")
    return f"""    <model name="wall_tape">
      <static>true</static>
      <link name="link">
{"".join(strips)}      </link>
    </model>

"""


def training_point(point):
    """Smoothly deepen the east S-bend, leaving outer paint and junctions fixed."""
    x, y, *rest = point
    if not 0.30 < x < 1.20 or abs(y) >= 0.40:
        return tuple(point)
    t = (x - 0.30) / 0.90
    fade = max(0.0, (abs(y) - 0.20) / 0.20)
    weight = 1.0 - fade * fade * (3.0 - 2.0 * fade)
    shift = -0.06 * math.sin(2.0 * math.pi * t) * math.sin(math.pi * t) ** 2
    return (x, y + weight * shift, *rest)


def _training_triangles(triangle):
    xs, ys = [p[0] for p in triangle], [p[1] for p in triangle]
    if max(xs) <= 0.30 or min(xs) >= 1.20 or min(ys) >= 0.40 or max(ys) <= -0.40:
        return [triangle]
    # Subdivide long CAD faces so the curved paint follows the graph between vertices.
    if max(math.dist(triangle[i], triangle[(i + 1) % 3]) for i in range(3)) <= 0.015:
        return [tuple(training_point(p) for p in triangle)]
    a, b, c = triangle
    ab, bc, ca = [tuple((u + v) / 2 for u, v in zip(p, q))
                  for p, q in ((a, b), (b, c), (c, a))]
    return [t for child in ((a, ab, ca), (ab, b, bc), (ca, bc, c), (ab, bc, ca))
            for t in _training_triangles(child)]


def training_scene(scene):
    lines = tuple(t for triangle in scene.lines for t in _training_triangles(triangle))
    return replace(scene, lines=lines, triangle_count=len(lines) + scene.wall_triangle_count,
                   walls=tuple(replace(w, height=REAL_WALL_HEIGHT_M) for w in scene.walls))


def world_xml(scene, line_colour: str, profile: str = "default") -> str:
    floor, paint = COLOURS[line_colour]
    mesh_uri = MESH_URI
    geometry_note = "STL Y-up mm -> ROS Z-up m by R_x(+90 deg); no reshaping."
    if profile in ("real", "training"):
        floor, paint = REAL_FLOOR_RGBA, REAL_PAINT_RGBA
        material = REAL_WALL_MATERIAL
        extra = _carpet_xml()
        if profile == "training":
            paint = "1 1 1 1"
            material = "<ambient>1 1 1 1</ambient><diffuse>1 1 1 1</diffuse>"
            mesh_uri = MESH_URI.replace("/meshes/", "/training-curved/meshes/")
            geometry_note = "Training derivative: stronger east S-bend; not the measured physical map."
        else:
            extra += _tape_xml(scene.walls)
        walls = "".join(_wall_xml(i, w, REAL_WALL_HEIGHT_M, material)
                        for i, w in enumerate(scene.walls))
        note = ("\n  Real profile (D-364 5): carpet texture, white 0.30 m walls, blue seam tape."
                if profile == "real" else
                "\n  Training: white 0.30 m walls and white paint; no artificial dark separation.")
        scene_xml = "    <scene><background>0.35 0.30 0.30 1</background></scene>\n\n"
    else:
        walls = "".join(_wall_xml(i, w) for i, w in enumerate(scene.walls))
        extra = note = scene_xml = ""
    return f"""<?xml version="1.0"?>
<!-- MAP v2 fleet / 260919 — generated by scripts/build_world.py. Do not edit.
  Source: 260919 MAP FILE.STL sha256 {scene.source_sha256}
  Envelope {scene.size_x:.3f} x {scene.size_y:.3f} m, centred at the origin.
  {geometry_note}
  Lane paint is visual-only; the perimeter ring is the only collision.
  dock_tag_7: the stage-3 parking marker (visual-only wedge face).
  reference_square_A/B: floor reference squares from lane_rules.yaml (visual-only).
  Line colour: {line_colour}. Orientation vs the physical mat: see README.md.{note}
-->
<sdf version="1.6">
  <world name="map_v2_fleet">
    <plugin filename="gz-sim-physics-system" name="gz::sim::systems::Physics">
      <engine><filename>gz-physics-dartsim-plugin</filename></engine>
    </plugin>
    <plugin filename="gz-sim-user-commands-system" name="gz::sim::systems::UserCommands"/>
    <plugin filename="gz-sim-scene-broadcaster-system" name="gz::sim::systems::SceneBroadcaster"/>
    <plugin filename="gz-sim-sensors-system" name="gz::sim::systems::Sensors">
      <render_engine>ogre2</render_engine>
    </plugin>
    <plugin filename="gz-sim-imu-system" name="gz::sim::systems::Imu"/>

{scene_xml}    <light type="directional" name="sun">
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
          <geometry><plane><normal>0 0 1</normal><size>100 100</size></plane></geometry>
        </collision>
        <visual name="visual">
          <geometry><plane><normal>0 0 1</normal><size>100 100</size></plane></geometry>
          <material><ambient>{floor}</ambient><diffuse>{floor}</diffuse></material>
        </visual>
      </link>
    </model>

{extra}{_reference_squares_xml()}    <model name="road_lines">
      <static>true</static>
      <pose>0 0 0.001 0 0 0</pose>
      <link name="link">
        <visual name="paint">
          <geometry><mesh><uri>{mesh_uri}</uri></mesh></geometry>
          <material><ambient>{paint}</ambient><diffuse>{paint}</diffuse></material>
        </visual>
      </link>
    </model>

    <model name="track_v2_fleet">
      <static>true</static>
      <pose>0 0 0 0 0 0</pose>
      <link name="link">
{walls}      </link>
    </model>

{_dock_tag_xml()}  </world>
</sdf>
"""


def build(source: Path, out: Path, line_colour: str = "bright") -> None:
    scene = _scene_module().load_scene(source)
    write_mesh(scene.lines, out / "meshes" / "road_lines.stl")
    write_tag_texture(out / "textures" / f"dock_tag_{DOCK_TAG_ID}.png")
    world = out / "worlds" / "map_v2_fleet.world"
    world.parent.mkdir(parents=True, exist_ok=True)
    world.write_text(world_xml(scene, line_colour), encoding="utf-8", newline="\n")
    write_carpet_texture(out / "textures" / "carpet_grey.png")
    (out / "worlds" / "map_v2_fleet_real.world").write_text(
        world_xml(scene, "bright", "real"), encoding="utf-8", newline="\n")
    training = out / "training-curved"
    write_mesh(training_scene(scene).lines, training / "meshes" / "road_lines.stl")
    (training / "worlds").mkdir(parents=True, exist_ok=True)
    (training / "worlds" / "map_v2_fleet_real.world").write_text(
        world_xml(scene, "bright", "training"), encoding="utf-8", newline="\n")
    graph = yaml.safe_load((BUNDLE / "lane_graph.yaml").read_text(encoding="utf-8"))
    east = graph["segments"]["east"]
    east["points"] = [[round(v, 4) for v in training_point(p)] for p in east["points"]]
    east["length_m"] = round(sum(math.dist(a, b) for a, b in zip(east["points"][:-1], east["points"][1:])), 4)
    (training / "lane_graph.yaml").write_text(
        "# Generated by scripts/build_world.py: curved training derivative, not the physical map.\n"
        + yaml.safe_dump(graph, sort_keys=True, default_flow_style=None, width=100),
        encoding="utf-8", newline="\n")


def main(argv=None) -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--out", type=Path, default=BUNDLE)
    p.add_argument("--line-colour", choices=sorted(COLOURS), default="bright")
    args = p.parse_args(argv)
    build(SOURCE, args.out, args.line_colour)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
