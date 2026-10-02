"""Pinky Pro NOMINAL geometry from the URDF, without ROS (D-397).

Evaluates the fixed-joint chain of src/sim/description/urdf/rosy.urdf.xacro
(Pinky Pro upstream import 6455b1a9, D-16) with the arg defaults of
robot.urdf.xacro, and writes src/products/pinky_pro/profile/config/geometry.yaml.
Every Pinky Pro geometric default in the repo is that file's value: URDF
nominal, refined per robot by an accepted calibration record (D-47 addendum
store). test_urdf_nominal.py regenerates the file and fails on any drift.

The xacro subset handled here is the one the file uses: macro params and
their defaults, xacro:arg defaults, ${...} with pi and + - * /, ==,
xacro:if/unless, the two known includes, calls to macros they define, the
inertia helpers inside links, and fixed/continuous joint origins. Anything else
(xacro:property, insert_block, element, an unknown include, macro or param, a
mesh scale other than 1 1 1) raises instead of being guessed. Stdlib only: Windows CI
has no ROS xacro.

    python tools/calibration/urdf_nominal.py            # rewrite geometry.yaml
    python tools/calibration/urdf_nominal.py --check    # exit 1 on drift
"""
from __future__ import annotations

import argparse
import ast
import math
import operator
import re
import struct
import sys
import xml.etree.ElementTree as ET
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
DESCRIPTION = REPO / "src" / "sim" / "description"
URDF = DESCRIPTION / "urdf" / "rosy.urdf.xacro"
ROBOT_URDF = DESCRIPTION / "urdf" / "robot.urdf.xacro"
OUTPUT = REPO / "src" / "products" / "pinky_pro" / "profile" / "config" / "geometry.yaml"
XACRO = "{http://www.ros.org/wiki/xacro}"
XACRO_ALT = "{http://ros.org/wiki/xacro}"
UPSTREAM_IMPORT = "6455b1a9"
ADR = "D-397"
_OPS = {ast.Add: operator.add, ast.Sub: operator.sub, ast.Mult: operator.mul,
        ast.Div: operator.truediv, ast.USub: operator.neg, ast.UAdd: operator.pos}
_EXPR = re.compile(r"\$\{([^}]*)\}")
# The only includes the extractor follows; anything else fails.
INCLUDES = {f"$(find description)/urdf/{name}": DESCRIPTION / "urdf" / name
            for name in ("common/insert_inertia.urdf.xacro", "rosy_gz.urdf.xacro")}
# xacro tags allowed inside a <link>: branches plus the inertia helpers (not geometry).
LINK_XACRO = ("if", "unless", "box_inertia", "sphere_inertia", "cylinder_inertia")


def _tag(element):
    return element.tag.replace(XACRO_ALT, XACRO)


def _eval(expr, env):
    def walk(node):
        if isinstance(node, ast.Expression):
            return walk(node.body)
        if isinstance(node, ast.Constant) and isinstance(node.value, (int, float, str)):
            return node.value
        if isinstance(node, ast.Name):
            if node.id in env:
                return env[node.id]
            raise ValueError(f"unknown xacro name {node.id!r}")
        if isinstance(node, ast.BinOp) and type(node.op) in _OPS:
            return _OPS[type(node.op)](walk(node.left), walk(node.right))
        if isinstance(node, ast.UnaryOp) and type(node.op) in _OPS:
            return _OPS[type(node.op)](walk(node.operand))
        if (isinstance(node, ast.Compare) and len(node.ops) == 1
                and isinstance(node.ops[0], (ast.Eq, ast.NotEq))):
            same = walk(node.left) == walk(node.comparators[0])
            return same if isinstance(node.ops[0], ast.Eq) else not same
        raise ValueError(f"unsupported xacro expression {expr!r}")
    return walk(ast.parse(expr.strip(), mode="eval"))


def _literal(text):
    for cast in (int, float):
        try:
            return cast(text)
        except ValueError:
            pass
    return {"true": True, "false": False}.get(text, text)


def _substitute(text, env):
    """A whole-string ${...} keeps its type; mixed text is string-joined."""
    match = _EXPR.fullmatch(text.strip())
    if match:
        return _eval(match.group(1), env)
    return _EXPR.sub(lambda m: str(_eval(m.group(1), env)), text)


def _truthy(value):
    if isinstance(value, str):
        return value.strip().lower() in ("true", "1")
    return bool(value)


def _params(spec):
    """'a b:=1 c' -> ordered [(name, default or None)]."""
    out = []
    for token in spec.split():
        name, _, default = token.partition(":=")
        out.append((name, _literal(default) if default else None))
    return out


def arg_defaults(path=ROBOT_URDF):
    """xacro:arg defaults of the top-level robot.urdf.xacro."""
    root = ET.parse(path).getroot()
    return {el.get("name"): _literal(el.get("default", ""))
            for el in root.iter() if _tag(el) == XACRO + "arg"}


def expand(path=URDF, *, args=None, is_sim=False):
    """Expanded links and joints of insert_robot as ([links], [joints]) of plain dicts."""
    args = dict(arg_defaults() if args is None else args)
    root = ET.parse(path).getroot()
    macros = {}
    _register(root, macros)
    top = macros["insert_robot"]
    env = {"pi": math.pi}
    for name, default in _params(top.get("params")):
        value = args.get(name, default)
        if name == "is_sim":
            value = is_sim
        if value is None:
            if name == "namespace":
                value = ""
            else:
                raise ValueError(f"insert_robot param {name!r} has no default and no arg")
        env[name] = value
    links, joints = [], []
    _walk(top, env, macros, links, joints)
    return links, joints


def _register(root, macros):
    for el in root:
        tag = _tag(el)
        if not isinstance(tag, str):
            continue
        if tag == XACRO + "macro":
            macros[el.get("name")] = el
        elif tag == XACRO + "include":
            _include(el, macros)
        elif tag.startswith(XACRO) and tag != XACRO + "arg":
            raise ValueError(f"unsupported top-level xacro tag {tag[len(XACRO):]!r}")


def _include(el, macros):
    filename = el.get("filename", "")
    if filename not in INCLUDES:
        raise ValueError(f"unknown xacro include {filename!r}")
    _register(ET.parse(INCLUDES[filename]).getroot(), macros)


def _check_xacro(element, allowed):
    """Fail closed: any xacro tag below `element` outside `allowed` is an error."""
    for el in element.iter():
        tag = _tag(el)
        if isinstance(tag, str) and tag.startswith(XACRO) and tag[len(XACRO):] not in allowed:
            raise ValueError(f"unsupported xacro tag {tag[len(XACRO):]!r} inside <{element.tag}>")


def _walk(parent, env, macros, links, joints):
    for el in parent:
        tag = _tag(el)
        if not isinstance(tag, str):
            continue  # comments
        if tag == XACRO + "macro":
            macros[el.get("name")] = el
        elif tag in (XACRO + "if", XACRO + "unless"):
            if _truthy(_substitute(el.get("value"), env)) == (tag == XACRO + "if"):
                _walk(el, env, macros, links, joints)
        elif tag == XACRO + "include":
            _include(el, macros)
        elif tag == XACRO + "arg":
            continue
        elif tag.startswith(XACRO):
            name = tag[len(XACRO):]
            if name not in macros:
                raise ValueError(f"unknown xacro macro or tag {name!r}")
            spec = _params(macros[name].get("params"))
            extra = set(el.attrib) - {pname for pname, _ in spec}
            if extra:
                raise ValueError(f"xacro:{name} called with unknown params {sorted(extra)}")
            inner = dict(env)
            for pname, default in spec:
                raw = el.get(pname)
                if raw is None and default is None:
                    raise ValueError(f"xacro:{name} missing param {pname!r}")
                value = _substitute(raw, env) if raw is not None else default
                inner[pname] = _literal(value) if isinstance(value, str) else value
            _walk(macros[name], inner, macros, links, joints)
        elif tag == "link":
            _check_xacro(el, LINK_XACRO)
            links.append(_link(el, env))
        elif tag == "joint":
            _check_xacro(el, ("if", "unless"))
            flat = ET.Element("joint")
            _flatten(el, env, flat)
            joints.append({"name": _substitute(el.get("name"), env), "type": el.get("type"),
                           "parent": _substitute(flat.find("parent").get("link"), env),
                           "child": _substitute(flat.find("child").get("link"), env),
                           **_origin(flat.find("origin"), env)})


def _origin(el, env):
    if el is None:
        return {"xyz": (0.0, 0.0, 0.0), "rpy": (0.0, 0.0, 0.0)}
    out = {}
    for key in ("xyz", "rpy"):
        parts = el.get(key, "0 0 0").split()
        out[key] = tuple(float(_substitute(p, env)) for p in parts)
    return out


def _link(el, env):
    collisions = []
    for col in _collision_elements(el, env):
        geometry = col.find("geometry")
        shape = geometry[0]
        spec = {"shape": shape.tag, **_origin(col.find("origin"), env)}
        for key in ("size", "radius", "length", "filename"):
            if shape.get(key) is not None:
                raw = shape.get(key)
                spec[key] = (raw if key == "filename" else
                             tuple(float(v) for v in raw.split()) if key == "size" else float(raw))
        if shape.tag == "mesh" and shape.get("scale", "1 1 1").split() != ["1", "1", "1"]:
            raise ValueError(f"mesh scale {shape.get('scale')!r} unsupported (link {el.get('name')})")
        collisions.append(spec)
    return {"name": _substitute(el.get("name"), env), "collisions": collisions}


def _collision_elements(link, env):
    for col in link.findall("collision"):
        holder = ET.Element("collision")
        _flatten(col, env, holder)
        if holder.find("geometry") is not None:
            yield holder


def _flatten(parent, env, holder):
    for child in parent:
        tag = _tag(child)
        if tag in (XACRO + "if", XACRO + "unless"):
            if _truthy(_substitute(child.get("value"), env)) == (tag == XACRO + "if"):
                _flatten(child, env, holder)
        elif isinstance(tag, str):
            holder.append(child)


# --- rigid transforms (4x4 row-major lists) ------------------------------------------

def _matrix(xyz, rpy):
    r, p, y = rpy
    cr, sr, cp, sp, cy, sy = math.cos(r), math.sin(r), math.cos(p), math.sin(p), math.cos(y), math.sin(y)
    return [[cy * cp, cy * sp * sr - sy * cr, cy * sp * cr + sy * sr, xyz[0]],
            [sy * cp, sy * sp * sr + cy * cr, sy * sp * cr - cy * sr, xyz[1]],
            [-sp, cp * sr, cp * cr, xyz[2]],
            [0.0, 0.0, 0.0, 1.0]]


def _mul(a, b):
    return [[sum(a[i][k] * b[k][j] for k in range(4)) for j in range(4)] for i in range(4)]


def _apply(m, point):
    return tuple(sum(m[i][k] * v for k, v in enumerate((*point, 1.0))) for i in range(3))


def frames(joints, root="base_footprint"):
    """Pose of every link in `root` (all joints at zero)."""
    poses = {root: _matrix((0, 0, 0), (0, 0, 0))}
    pending = list(joints)
    while pending:
        progressed = False
        for joint in list(pending):
            if joint["parent"] in poses:
                poses[joint["child"]] = _mul(poses[joint["parent"]], _matrix(joint["xyz"], joint["rpy"]))
                pending.remove(joint)
                progressed = True
        if not progressed:
            raise ValueError(f"joints not connected to {root}: {[j['name'] for j in pending]}")
    return poses


def _yaw(m):
    return math.atan2(m[1][0], m[0][0])


def _pitch(m):
    return math.asin(-m[2][0])


# --- collision outline in the base_link xy plane ----------------------------------

def _stl_points(path):
    data = Path(path).read_bytes()
    count = struct.unpack("<I", data[80:84])[0] if len(data) >= 84 else -1
    if len(data) != 84 + 50 * count:  # not binary by size: must be ASCII STL, whatever its name length
        if not data.lstrip().startswith(b"solid"):
            raise ValueError(f"{path}: neither a binary nor an ASCII STL")
        points = [tuple(float(v) for v in line.split()[1:4])
                  for line in data.decode("ascii", "replace").splitlines() if line.strip().startswith("vertex")]
        if not points:
            raise ValueError(f"{path}: ASCII STL without vertices")
        return points
    points = []
    for i in range(count):
        values = struct.unpack("<12f", data[84 + 50 * i: 84 + 50 * i + 48])
        points.extend((values[3:6], values[6:9], values[9:12]))
    return points


def _shape_points(spec):
    shape = spec["shape"]
    if shape == "box":
        sx, sy, sz = spec["size"]
        return [(x, y, z) for x in (-sx / 2, sx / 2) for y in (-sy / 2, sy / 2) for z in (-sz / 2, sz / 2)]
    if shape == "cylinder":
        r, h = spec["radius"], spec["length"]
        return [(r * math.cos(a), r * math.sin(a), z) for a in (i * math.pi / 180 for i in range(360))
                for z in (-h / 2, h / 2)]
    if shape == "sphere":
        r = spec["radius"]
        return [(r * math.cos(a) * math.cos(e), r * math.sin(a) * math.cos(e), r * math.sin(e))
                for a in (i * math.pi / 36 for i in range(72)) for e in (j * math.pi / 12 for j in range(-6, 7))]
    if shape == "mesh":
        name = spec["filename"].split("package://description/", 1)[-1]
        return _stl_points(DESCRIPTION / name)
    raise ValueError(f"unsupported collision shape {shape!r}")


def rotation_radius(links, poses):
    """Largest xy distance from base_link's z axis of any collision point, every
    joint at zero (a wheel cylinder is symmetric, so its spin does not matter)."""
    base_inv = _invert(poses["base_link"])
    best = 0.0
    for link in links:
        for spec in link["collisions"]:
            m = _mul(base_inv, _mul(poses[link["name"]], _matrix(spec["xyz"], spec["rpy"])))
            for point in _shape_points(spec):
                x, y, _ = _apply(m, point)
                best = max(best, math.hypot(x, y))
    return best


def half_width(links, poses):
    """Largest |y| from base_link of any collision point, every joint at zero: the body's
    lateral half-width (D-407 rear band; wider bands count side walls as behind)."""
    base_inv = _invert(poses["base_link"])
    best = 0.0
    for link in links:
        for spec in link["collisions"]:
            m = _mul(base_inv, _mul(poses[link["name"]], _matrix(spec["xyz"], spec["rpy"])))
            for point in _shape_points(spec):
                best = max(best, abs(_apply(m, point)[1]))
    return best


def _invert(m):
    rot = [[m[j][i] for j in range(3)] for i in range(3)]
    t = [-sum(rot[i][k] * m[k][3] for k in range(3)) for i in range(3)]
    return [[*rot[0], t[0]], [*rot[1], t[1]], [*rot[2], t[2]], [0.0, 0.0, 0.0, 1.0]]


# --- the nominal table -------------------------------------------------------------

def nominal(args=None):
    """The NOMINAL geometry as a nested dict of floats (metres, radians, degrees)."""
    args = dict(arg_defaults() if args is None else args)
    links, joints = expand(args=args, is_sim=False)
    sim_links, _ = expand(args=args, is_sim=True)
    poses = frames(joints)
    base = poses["base_link"]

    def pos(link):
        return _apply(poses[link], (0.0, 0.0, 0.0))

    lidar = poses["rplidar_link"]
    lidar_xyz = pos("rplidar_link")
    camera = poses["front_camera_link"]
    camera_xyz = pos("front_camera_link")
    wheels = {}
    by_name = {link["name"]: link for link in links}
    for side in ("l", "r"):
        spec = by_name[f"{side}_wheel"]["collisions"][0]
        if spec["shape"] != "cylinder":
            raise ValueError(f"{side}_wheel collision is not a cylinder")
        contact = _mul(poses[f"{side}_wheel"], _matrix(spec["xyz"], spec["rpy"]))
        wheels[side] = (spec["radius"], _apply(contact, (0.0, 0.0, 0.0)))
    if wheels["l"][0] != wheels["r"][0]:
        raise ValueError("left and right wheel radii differ")
    joint_y = {side: _apply(poses[f"{side}_wheel"], (0.0, 0.0, 0.0))[1] for side in ("l", "r")}
    caster = by_name["caster_wheel"]["collisions"][0]
    caster_x = _apply(poses["caster_wheel"], (0.0, 0.0, 0.0))[0] - caster["radius"]
    ir = {key: pos(f"ir_{link}_link") for key, link in (("left", "l"), ("mid", "mid"), ("right", "r"))}
    imu = pos("imu_link")
    imu_base = _apply(_invert(base), imu)
    return {
        "base_link_z_m": base[2][3],
        "lidar": {"frame": "rplidar_link", "x_m": lidar_xyz[0], "y_m": lidar_xyz[1], "height_m": lidar_xyz[2],
                  "yaw_rad": _yaw(lidar) % (2 * math.pi), "forward_deg": math.degrees(-_yaw(lidar)) % 360.0},
        "camera": {"frame": "front_camera_link", "x_m": camera_xyz[0], "y_m": camera_xyz[1],
                   "height_m": camera_xyz[2], "pitch_rad": _pitch(camera), "pitch_deg": math.degrees(_pitch(camera)),
                   "tilt_arg_deg": float(args["cam_tilt_deg"]), "mount_z_arg_m": float(args["cam_mount_z"])},
        "wheels": {"radius_m": wheels["l"][0], "joint_y_m": (joint_y["l"] - joint_y["r"]) / 2.0,
                   "separation_m": wheels["l"][1][1] - wheels["r"][1][1]},
        "caster": {"rear_x_m": caster_x},
        "ir": {**{key: {"x_m": p[0], "y_m": p[1], "height_m": p[2]} for key, p in ir.items()},
               "half_span_m": (ir["left"][1] - ir["right"][1]) / 2.0},
        "ultrasonic": {"x_m": pos("ultrasonic_link")[0], "height_m": pos("ultrasonic_link")[2]},
        "imu": {"x_m": imu_base[0], "y_m": imu_base[1], "z_base_link_m": imu_base[2], "height_m": imu[2]},
        "footprint": {"rotation_radius_m": rotation_radius(links, poses),
                      "half_width_m": half_width(links, poses),
                      "rotation_radius_sim_box_m": rotation_radius(sim_links, poses)},
    }


def _fmt(value):
    if isinstance(value, str):
        return value
    text = f"{round(value, 6) + 0.0:.6f}".rstrip("0")
    return text + "0" if text.endswith(".") else text


def _dump(mapping, indent=0):
    lines = []
    for key, value in mapping.items():
        if isinstance(value, dict):
            lines.append(" " * indent + f"{key}:")
            lines.extend(_dump(value, indent + 2))
        else:
            lines.append(" " * indent + f"{key}: {_fmt(value)}")
    return lines


def render(table=None):
    table = nominal() if table is None else table
    rel = lambda p: p.relative_to(REPO).as_posix()  # noqa: E731
    header = [
        "# GENERATED by tools/calibration/urdf_nominal.py - do not edit; regenerate with",
        "#   python tools/calibration/urdf_nominal.py",
        f"# Pinky Pro NOMINAL geometry ({ADR}): the fixed-joint chain of",
        f"#   {rel(URDF)}",
        f"#   (Pinky Pro upstream import {UPSTREAM_IMPORT}, D-16) with the arg defaults of",
        f"#   {rel(ROBOT_URDF)}. Only the values matter: test_urdf_nominal.py",
        "#   regenerates this file and fails if any value differs.",
        "# URDF nominal (upstream CAD, not measured); refined per robot by an accepted",
        "# calibration record (D-47 addendum store); an operator overlay wins over both.",
        "# Frame: base_footprint on the floor, x forward, y left; height_m is above the floor.",
        "# lidar.forward_deg is the scan angle of the robot's forward (rplidar_link yaw pi).",
        "# footprint.rotation_radius_m uses the collision meshes the device URDF loads",
        "# (is_sim false); rotation_radius_sim_box_m the Gazebo collision boxes.",
    ]
    return "\n".join(header + _dump(table)) + "\n"


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--check", action="store_true", help="exit 1 if geometry.yaml differs")
    args = parser.parse_args(argv)
    text = render()
    current = OUTPUT.read_text(encoding="utf-8").replace("\r\n", "\n") if OUTPUT.exists() else None
    if args.check:
        if current != text:
            print(f"{OUTPUT} is stale: run python tools/calibration/urdf_nominal.py", file=sys.stderr)
            return 1
        return 0
    OUTPUT.write_text(text, encoding="utf-8", newline="\n")
    print(f"wrote {OUTPUT.relative_to(REPO).as_posix()}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
