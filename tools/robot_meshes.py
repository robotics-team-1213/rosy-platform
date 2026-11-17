"""Web robot models for the shared 3D view (shared/web/robot-3d.js): decimated meshes and small URDFs.

    python tools/robot_meshes.py            # write shared/web/meshes/
    python tools/robot_meshes.py --check    # exit 1 when the checked-in files differ from what this script builds

Sources (the repo's own models, never copied by hand):
  OMX-F    learning/envs/isaac/assets/open_manipulator_description  (URDF + 8 STL, mm, 5.8 MB)
  Pinky    middleware/devices/pinky/description                     (xacro + DAE visual meshes, 28 MB)
Output (binary STL in metres, one URDF per kind). Standard library only, so the result is the same on every host:
vertex clustering on a grid (the finest grid that stays under a per-part triangle target), vertex = cluster mean,
degenerate and duplicate triangles dropped. `BUDGET_BYTES` caps the whole folder; the test regenerates in memory and
compares bytes. Pinky joint origins below are copied from rosy.urdf.xacro (cam_tilt 8 deg, screen_tilt -25 deg, defaults
of robot.urdf.xacro); the static parts (board, lidar, camera, screen, lamp, caster) merge into one body mesh because
nothing reports their state, the two wheels stay one mesh drawn twice. Colour is not baked: the view paints by token.
"""
from __future__ import annotations

import math
from pathlib import Path
import re
import struct
import sys
import xml.etree.ElementTree as ET

REPO = Path(__file__).resolve().parents[1]
OUT = REPO / "shared" / "web" / "meshes"
OMX = REPO / "learning/envs/isaac/assets/open_manipulator_description"
PINKY = REPO / "middleware/devices/pinky/description"
BUDGET_BYTES = 400_000
HEADER = b"rosy web robot mesh (tools/robot_meshes.py)".ljust(80, b" ")
# triangle target per OMX link (visual mesh in the URDF); Pinky targets are per DAE part
OMX_TARGETS = {"link0": 900, "link1": 320, "link2": 380, "link3": 650, "link4": 260, "link5": 420, "link6": 160, "link7": 110}
RP = math.pi / 180
# (dae file, translation, (roll, pitch, yaw), target) in base_footprint; base_link sits 0.028 above it
PINKY_BODY = [
    ("base_link", (0, 0, 0.028), (0, 0, 0), 1500),
    ("rplidar_c1", (-0.017, 0, 0.028 + 0.067), (0, 0, 0), 420),
    ("camera_assy", (0.020, 0, 0.028 + 0.0495), (0, 8 * RP, 0), 320),
    ("screen_assy", (0.0165, 0, 0.028 + 0.071), (0, -25 * RP, 0), 260),
    ("robot_lamp", (0, 0, 0.028), (0, 0, 0), 150),
    ("caster_mount", (-0.0585, 0, 0.028 - 0.007), (0, 0, 0), 120),
    ("caster_rotate", (-0.0585, 0, 0.028 - 0.007 - 0.0035), (0, 0, 0), 100),
    ("caster_wheel", (-0.0585 - 0.011, 0, 0.028 - 0.007 - 0.0035 - 0.011), (0, 0, 0), 160),
]
WHEEL_TARGET, WHEEL_Y, WHEEL_Z = 520, 0.04055, 0.028
Tri = tuple  # (ax, ay, az, bx, by, bz, cx, cy, cz)


# --- transforms (row-major 4x4 as 16 floats) -----------------------------------------------------------------------
def rpy_matrix(xyz, rpy):
    roll, pitch, yaw = rpy
    cr, sr, cp, sp, cy, sy = math.cos(roll), math.sin(roll), math.cos(pitch), math.sin(pitch), math.cos(yaw), math.sin(yaw)
    return [cy * cp, cy * sp * sr - sy * cr, cy * sp * cr + sy * sr, xyz[0],
            sy * cp, sy * sp * sr + cy * cr, sy * sp * cr - cy * sr, xyz[1],
            -sp, cp * sr, cp * cr, xyz[2], 0.0, 0.0, 0.0, 1.0]


def mat_mul(a, b):
    return [sum(a[r * 4 + k] * b[k * 4 + c] for k in range(4)) for r in range(4) for c in range(4)]


def apply(m, v):
    return tuple(m[r * 4] * v[0] + m[r * 4 + 1] * v[1] + m[r * 4 + 2] * v[2] + m[r * 4 + 3] for r in range(3))


def transform(tris, m):
    return [sum((apply(m, t[i:i + 3]) for i in (0, 3, 6)), ()) for t in tris]


# --- readers -------------------------------------------------------------------------------------------------------
def read_stl(path: Path, scale: float) -> list[Tri]:
    data = path.read_bytes()
    count = struct.unpack_from("<I", data, 80)[0]
    if len(data) != 84 + 50 * count:
        raise ValueError(f"{path.name}: not a binary STL")
    return [tuple(v * scale for v in struct.unpack_from("<9f", data, 84 + 50 * i + 12)) for i in range(count)]


def read_dae(path: Path) -> list[Tri]:
    """Every <triangles> of every instanced geometry, node matrices applied (up axis Z, unit metre; asserted)."""
    root = ET.parse(path).getroot()
    ns = {"c": "http://www.collada.org/2005/11/COLLADASchema"}
    tag = lambda name: "{%s}%s" % (ns["c"], name)
    if root.findtext("c:asset/c:up_axis", namespaces=ns) != "Z_UP" or root.find("c:asset/c:unit", ns).get("meter") != "1":
        raise ValueError(f"{path.name}: expected Z_UP metres")
    geometries = {g.get("id"): g.find("c:mesh", ns) for g in root.iterfind("c:library_geometries/c:geometry", ns)}
    nodes = {n.get("id"): n for n in root.iterfind("c:library_nodes/c:node", ns)}

    def triangles(mesh):
        sources = {s.get("id"): s for s in mesh.iterfind("c:source", ns)}
        vertices = mesh.find("c:vertices", ns)
        position = next(i for i in vertices.iterfind("c:input", ns) if i.get("semantic") == "POSITION").get("source")[1:]
        flat = [float(x) for x in sources[position].find("c:float_array", ns).text.split()]
        points = [tuple(flat[i:i + 3]) for i in range(0, len(flat), 3)]
        out = []
        for part in mesh:
            if part.tag != tag("triangles"):
                if part.tag in (tag("polylist"), tag("polygons")):
                    raise ValueError(f"{path.name}: only <triangles> is supported")
                continue
            inputs = part.findall("c:input", ns)
            stride = 1 + max(int(i.get("offset")) for i in inputs)
            offset = int(next(i for i in inputs if i.get("semantic") == "VERTEX").get("offset"))
            index = [int(x) for x in part.find("c:p", ns).text.split()][offset::stride]
            out += [sum((points[k] for k in index[i:i + 3]), ()) for i in range(0, len(index) - 2, 3)]
        return out

    def walk(node, parent):
        matrix = node.find("c:matrix", ns)
        here = mat_mul(parent, [float(x) for x in matrix.text.split()]) if matrix is not None else parent
        found = []
        for child in node:
            if child.tag == tag("instance_geometry"):
                found += transform(triangles(geometries[child.get("url")[1:]]), here)
            elif child.tag == tag("instance_node"):
                found += walk(nodes[child.get("url")[1:]], here)
            elif child.tag == tag("node"):
                found += walk(child, here)
        return found

    identity = [1.0, 0, 0, 0, 0, 1.0, 0, 0, 0, 0, 1.0, 0, 0, 0, 0, 1.0]
    return sum((walk(n, identity) for n in root.iterfind("c:library_visual_scenes/c:visual_scene/c:node", ns)), [])


# --- decimation ----------------------------------------------------------------------------------------------------
def cluster(tris: list[Tri], cell: float) -> list[Tri]:
    sums: dict[tuple, list] = {}
    keyed = []
    for t in tris:
        keys = []
        for i in (0, 3, 6):
            key = (math.floor(t[i] / cell), math.floor(t[i + 1] / cell), math.floor(t[i + 2] / cell))
            slot = sums.setdefault(key, [0.0, 0.0, 0.0, 0])
            slot[0] += t[i]; slot[1] += t[i + 1]; slot[2] += t[i + 2]; slot[3] += 1
            keys.append(key)
        if len(set(keys)) == 3:
            keyed.append(keys)
    seen, out = set(), []
    for keys in keyed:
        ident = tuple(sorted(keys))
        if ident in seen:
            continue
        seen.add(ident)
        out.append(sum(((sums[k][0] / sums[k][3], sums[k][1] / sums[k][3], sums[k][2] / sums[k][3]) for k in keys), ()))
    return out


def decimate(tris: list[Tri], target: int) -> list[Tri]:
    """Finest grid (cell shrinks 12% per step from a coarse start) that stays at or under `target` triangles."""
    if len(tris) <= target:
        return tris
    lows = [min(t[i] for t in tris) for i in range(3)]
    highs = [max(t[i] for t in tris) for i in range(3)]
    cell, best = math.dist(lows, highs) / 4, []
    while cell > 1e-5:
        trial = cluster(tris, cell)
        if len(trial) > target:
            break
        best, cell = trial, cell / 1.12
    if not best:
        raise SystemExit(f"cannot reach {target} triangles: even the coarsest grid gives more")
    return best


# --- writers -------------------------------------------------------------------------------------------------------
def stl_bytes(tris: list[Tri]) -> bytes:
    body = bytearray(HEADER + struct.pack("<I", len(tris)))
    for t in tris:
        ux, uy, uz, vx, vy, vz = t[3] - t[0], t[4] - t[1], t[5] - t[2], t[6] - t[0], t[7] - t[1], t[8] - t[2]
        n = (uy * vz - uz * vy, uz * vx - ux * vz, ux * vy - uy * vx)
        length = math.sqrt(sum(c * c for c in n)) or 1.0
        body += struct.pack("<12fH", n[0] / length, n[1] / length, n[2] / length, *t, 0)
    return bytes(body)


def num(value: float) -> str:
    return f"{round(value, 6):g}".replace("-0", "0") if abs(value) < 5e-7 else f"{round(value, 6):g}"


def omx_files() -> dict[str, bytes]:
    root = ET.parse(OMX / "urdf/omx_f/omx_f.urdf").getroot()
    files, lines = {}, ['<robot name="omx_f">']
    for link in root.iterfind("link"):
        mesh = link.find("visual/geometry/mesh")
        if mesh is None:
            lines.append(f'  <link name="{link.get("name")}"/>')
            continue
        name, scale = link.get("name"), float(mesh.get("scale").split()[0])
        tris = decimate(read_stl(OMX / "meshes/omx_f" / Path(mesh.get("filename")).name, scale), OMX_TARGETS[name])
        files[f"omx-{name}.stl"] = stl_bytes(tris)
        lines.append(f'  <link name="{name}"><visual><geometry><mesh filename="omx-{name}.stl"/></geometry></visual></link>')
    for joint in root.iterfind("joint"):
        origin, axis, limit, mimic = joint.find("origin"), joint.find("axis"), joint.find("limit"), joint.find("mimic")
        inner = f'<parent link="{joint.find("parent").get("link")}"/><child link="{joint.find("child").get("link")}"/>'
        inner += f'<origin xyz="{origin.get("xyz")}" rpy="{origin.get("rpy", "0 0 0")}"/>'
        if axis is not None:
            inner += f'<axis xyz="{axis.get("xyz")}"/>'
        if limit is not None:
            inner += f'<limit lower="{limit.get("lower")}" upper="{limit.get("upper")}"/>'
        if mimic is not None:
            inner += f'<mimic joint="{mimic.get("joint")}" multiplier="{mimic.get("multiplier")}"/>'
        lines.append(f'  <joint name="{joint.get("name")}" type="{joint.get("type")}">{inner}</joint>')
    files["omx-f.urdf"] = ("\n".join(lines) + "\n</robot>\n").encode()
    return files


def pinky_files() -> dict[str, bytes]:
    visual = PINKY / "meshes/visual"
    body: list[Tri] = []
    for name, xyz, rpy, target in PINKY_BODY:
        body += transform(decimate(read_dae(visual / f"{name}.dae"), target), rpy_matrix(xyz, rpy))
    wheel = decimate(read_dae(visual / "main_wheel.dae"), WHEEL_TARGET)  # drawn mirrored: the left wheel's yaw (+90) is in the URDF
    lines = ['<robot name="pinky_pro">', '  <link name="base_footprint"/>',
             '  <link name="body"><visual><geometry><mesh filename="pinky-body.stl"/></geometry></visual></link>']
    for side, direction in (("l", 1), ("r", -1)):
        lines.append(f'  <link name="{side}_wheel"><visual><origin xyz="0 0 0" rpy="0 0 {num(direction * math.pi / 2)}"/>'
                     '<geometry><mesh filename="pinky-wheel.stl"/></geometry></visual></link>')
    lines.append('  <joint name="body_fixed" type="fixed"><parent link="base_footprint"/><child link="body"/><origin xyz="0 0 0" rpy="0 0 0"/></joint>')
    for side, direction in (("l", 1), ("r", -1)):
        lines.append(f'  <joint name="{side}_wheel_joint" type="continuous"><parent link="base_footprint"/><child link="{side}_wheel"/>'
                     f'<origin xyz="0 {num(direction * WHEEL_Y)} {num(WHEEL_Z)}" rpy="0 0 0"/><axis xyz="0 1 0"/></joint>')
    return {"pinky-body.stl": stl_bytes(body), "pinky-wheel.stl": stl_bytes(wheel),
            "pinky-pro.urdf": ("\n".join(lines) + "\n</robot>\n").encode()}


def build() -> dict[str, bytes]:
    files = {**omx_files(), **pinky_files()}
    total = sum(map(len, files.values()))
    if total > BUDGET_BYTES:
        raise SystemExit(f"mesh budget exceeded: {total} > {BUDGET_BYTES} bytes")
    return files


def main(argv: list[str]) -> int:
    files = build()
    if "--check" in argv:
        stale = sorted(n for n, data in files.items() if not (OUT / n).is_file() or (OUT / n).read_bytes() != data)
        stale += sorted(p.name for p in OUT.glob("*") if p.name not in files and p.is_file())
        print("stale: " + ", ".join(stale) if stale else "robot meshes are current")
        return 1 if stale else 0
    OUT.mkdir(parents=True, exist_ok=True)
    for name, data in files.items():
        (OUT / name).write_bytes(data)
    print(f"{len(files)} files, {sum(map(len, files.values()))} bytes")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
