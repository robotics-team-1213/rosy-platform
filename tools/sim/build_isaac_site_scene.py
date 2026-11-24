"""Build the archived 261026 Isaac site scene from its Gazebo geometry and R08 CAD."""

import argparse
import gzip
from hashlib import sha256
import json
import math
from pathlib import Path
import re
import shutil
import struct
from xml.etree import ElementTree

MAP = Path(__file__).resolve().parents[2] / "middleware/perception/map/map_world_261026"
WORLD = MAP / "worlds/map_world_261026.world"
AB_CANDIDATE_SHA256 = "32377e7ba62a645eec56ef561f12bc529365e9cb4c7c4372ee401694e058e779"


def write_materials(output):
    output.write('def Scope "Materials" {\n')
    for material, friction in (("BayRail", 0.3), ("PerimeterWall", 0.9)):
        output.write(f'def Material "{material}" (prepend apiSchemas = ["PhysicsMaterialAPI"]) {{\n'
                     f" float physics:staticFriction = {friction}\n float physics:dynamicFriction = {friction}\n}}\n")
    output.write("}\n")


def digest(path):
    return sha256(path.read_bytes()).hexdigest()


def vector(values, length):
    values = tuple(float(value) for value in values)
    if len(values) != length or not all(map(math.isfinite, values)):
        raise ValueError("invalid geometry vector")
    return values


def numbers(element, key, default=""):
    return element.findtext(key, default).split()


def point(values):
    return "(" + ", ".join(f"{value:.8g}" for value in values) + ")"


def pose(element):
    return vector(numbers(element, "pose", "0 0 0 0 0 0"), 6)


def xform(transform, scale=None):
    locations = [
        f"double3 xformOp:translate = {point(transform[:3])}",
        f"float3 xformOp:rotateXYZ = {point(map(math.degrees, transform[3:]))}",
    ]
    order = ["xformOp:translate", "xformOp:rotateXYZ"]
    if scale is not None:
        locations.append(f"float3 xformOp:scale = {point(scale)}")
        order.append("xformOp:scale")
    locations.append("uniform token[] xformOpOrder = " + json.dumps(order))
    return "\n".join(locations)


def name(element):
    value = element.get("name", "")
    if not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", value):
        raise ValueError("invalid USD prim name")
    return value


def mesh(output, prim, points, color, transform=""):
    if len(points) % 3 or not points:
        raise ValueError("expected complete triangles")
    output.write(f'def Mesh "{prim}" {{\n{transform}\n uniform token subdivisionScheme = "none"\n')
    output.write("  point3f[] points = [" + ", ".join(point(triple) for triple in points) + "]\n")
    output.write("  int[] faceVertexCounts = [" + ", ".join("3" for _ in range(len(points) // 3)) + "]\n")
    output.write("  int[] faceVertexIndices = [" + ", ".join(map(str, range(len(points)))) + "]\n")
    output.write(f"  color3f[] primvars:displayColor = [{point(color)}]\n}}\n")


def paint_points(road):
    raw = road.read_bytes()
    count, = struct.unpack_from("<I", raw, 80)
    if len(raw) != 84 + count * 50:
        raise ValueError("road mesh must be binary STL")
    return [vector(triangle[offset:offset + 3], 3)
            for triangle in struct.iter_unpack("<12fH", raw[84:]) for offset in (3, 6, 9)]


def cube(output, prim, transform, dimensions, color, collider, material=None):
    apis = ["PhysicsCollisionAPI"] if collider else []
    if material:
        apis.append("MaterialBindingAPI")
    schema = f" (prepend apiSchemas = {json.dumps(apis)})" if apis else ""
    output.write(f'def Cube "{prim}"{schema} {{\n double size = 1\n{xform(transform, dimensions)}\n')
    if material:
        output.write(f' rel material:binding:physics = </World/Materials/{material}>\n')
    if color:
        output.write(f" color3f[] primvars:displayColor = [{point(color)}]\n")
    else:
        output.write(' uniform token purpose = "guide"\n uniform token visibility = "invisible"\n')
    output.write("}\n")


def write_site(output, road, world_path=WORLD):
    world = ElementTree.parse(world_path).find("world")
    colliders = 0
    for model in world.findall("model"):
        if model.findtext("static") != "true":
            raise ValueError("expected an all-static site world")
        output.write(f'def Xform "{name(model)}" {{\n{xform(pose(model))}\n')
        for link in model.findall("link"):
            output.write(f'def Xform "{name(link)}" {{\n{xform(pose(link))}\n')
            for element in link.findall("visual") + link.findall("collision"):
                collision = element.tag == "collision"
                transform = pose(element)
                color = None if collision else vector(numbers(element, "material/diffuse", ".25 .25 .25 1"), 4)[:3]
                box, plane = element.find("geometry/box"), element.find("geometry/plane")
                friction = element.find("surface/friction/ode")
                material = None
                if friction is not None:
                    mu = float(friction.findtext("mu"))
                    if mu != float(friction.findtext("mu2")) or mu not in (0.3, 0.9):
                        raise ValueError("unsupported archived SDF surface friction")
                    material = "BayRail" if mu == 0.3 else "PerimeterWall"
                if box is not None:
                    cube(output, name(element), transform, vector(numbers(box, "size"), 3), color, collision, material)
                elif plane is not None:
                    if vector(numbers(plane, "normal"), 3) != (0, 0, 1):
                        raise ValueError("expected horizontal planes")
                    base = 0.01 if collision else 0.0001
                    lowered = (*transform[:2], transform[2] - base / 2, *transform[3:])
                    cube(output, name(element), lowered, (*vector(numbers(plane, "size"), 2), base), color, collision)
                elif not collision and element.findtext("geometry/mesh/uri") == (
                    "model://control/map/map_world_261026/meshes/road_lines_loop.stl"
                ):
                    mesh(output, name(element), paint_points(road), color, xform(transform))
                else:
                    raise ValueError("unsupported archived SDF geometry")
                colliders += collision
            output.write("}\n")
        output.write("}\n")
    return colliders


def build(bundle, out, dynamic_cell=None, site_scene=None):
    registration = json.loads((bundle / "data/site-registration.json").read_bytes())
    site_cad_hash = json.loads((MAP / "meshes/road_lines.json").read_bytes())["source_sha256"]
    cell_path = bundle / "data/cell-equipment.json.gz"
    cell = json.loads(gzip.decompress(cell_path.read_bytes()))
    identity = registration["bundle"]
    road = MAP / "meshes/road_lines_loop.stl"
    world_path = WORLD
    field_map_version = None
    if site_scene is not None:
        generated = json.loads((site_scene / "manifest.json").read_bytes())
        world_name = "worlds/map_world_261026.world"
        map_path = site_scene / "site-map.json"
        world_path = site_scene / world_name
        if (generated.get("schema") != "rosy.world.gazebo-scene.v1"
                or generated["sha256"][world_name] != digest(world_path)
                or generated["sha256"]["site-map.json"] != digest(map_path)
                or generated["sha256"]["meshes/road_lines_loop.stl"] != digest(road)
                or generated["map_version"] != json.loads(map_path.read_bytes())["version"]):
            raise ValueError("generated Gazebo scene, loop mesh or map differs from its manifest")
        field_map_version = generated["map_version"]
    if (registration.get("schema") != "rosy.world.registration-check.v1"
            or registration.get("basis") != "archived-cad" or registration.get("status") != "candidate"
            or identity.get("site_cad_sha256") != site_cad_hash
            or identity.get("site_map_sha256") != digest(bundle / "data/site-map.json")
            or identity.get("cell_model_sha256") != digest(cell_path)
            or identity.get("cell_layout_sha256") != cell.get("layout_sha256")
            or cell.get("schema") != "rosy.world.meshes.v1"):
        raise ValueError("site CAD registration or R08 asset does not match this bundle")
    transform = registration["site_from_cell"]
    cell_pose = vector([*transform["translation_m"], 0, 0, transform["yaw_rad"]], 6)
    if dynamic_cell is not None and digest(dynamic_cell) != AB_CANDIDATE_SHA256:
        raise ValueError("only the audited R08 A/B cargo-pose candidate can share this placement")
    out.mkdir(parents=True, exist_ok=False)
    layer = out / "r08-visual.usda"
    with layer.open("x", encoding="utf-8", newline="\n") as output:
        output.write('#usda 1.0\n(defaultPrim = "R08"\n metersPerUnit = 1\n upAxis = "Z")\n def Xform "R08" {\n')
        for index, chunk in enumerate(cell["chunks"]):
            coords = chunk["positions"]
            points = [vector(coords[i:i + 3], 3) for i in range(0, len(coords), 3)]
            mesh(output, f"part_{index}", points, vector(chunk["color"], 3))
        output.write("}\n")
    scene = out / "world_261026.usda"
    with scene.open("x", encoding="utf-8", newline="\n") as output:
        output.write('#usda 1.0\n(defaultPrim = "World"\n metersPerUnit = 1\n upAxis = "Z")\ndef Xform "World" {\n')
        output.write('def PhysicsScene "Physics" {\n vector3f physics:gravityDirection = (0, 0, -1)\n float physics:gravityMagnitude = 9.81\n}\n')
        write_materials(output)
        output.write('def Xform "Site" {\n')
        colliders = write_site(output, road, world_path)
        output.write('}\ndef Xform "R08" (prepend references = @./r08-visual.usda@) {\n')
        output.write(xform(cell_pose) + "\n}\n}\n")
    report = {
        "scope": "archived site static colliders and R08 visual only",
        "source_site_cad_sha256": site_cad_hash, "source_gazebo_world_sha256": digest(world_path),
        "source_road_mesh_sha256": digest(road), "cell_layout_sha256": cell["layout_sha256"],
        "source_revision": registration["source"], "r08_site_from_cell": transform,
        "static_colliders": colliders, "outputs": {path.name: digest(path) for path in (scene, layer)},
    }
    if field_map_version is not None:
        report.update(scope="map-derived parking guide with archived site colliders and R08 registration",
                      parking_map_version=field_map_version,
                      parking_map_sha256=digest(site_scene / "site-map.json"))
    if dynamic_cell is not None:
        asset = out / "r08-ab-candidate.usdc"
        shutil.copyfile(dynamic_cell, asset)
        candidate = out / "world_261026_ab_candidate.usda"
        # Keep the cell's physics, articulation and observation paths at their original prims.
        x, y, z, _, _, yaw = cell_pose
        c, s = math.cos(yaw), math.sin(yaw)
        site_pose = (-c * x - s * y, s * x - c * y, -z, 0, 0, -yaw)
        with candidate.open("x", encoding="utf-8", newline="\n") as output:
            output.write('#usda 1.0\n(defaultPrim = "World"\n metersPerUnit = 1\n upAxis = "Z"\n'
                         ' subLayers = [@./r08-ab-candidate.usdc@])\nover "World" {\n')
            write_materials(output)
            output.write(f'def Xform "Site" {{\n{xform(site_pose)}\n')
            write_site(output, road, world_path)
            output.write("}\n}\n")
        report["dynamic_scope"] = "experimental R08 A/B cell with site in cell coordinates"
        report["outputs"].update({path.name: digest(path) for path in (asset, candidate)})
    (out / "manifest.json").write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--bundle", required=True, type=Path)
    parser.add_argument("--out", required=True, type=Path)
    parser.add_argument("--dynamic-cell", type=Path, help="the audited R08 A/B cargo-pose USDC candidate")
    parser.add_argument("--site-scene", type=Path, help="a generated Gazebo site bundle with map-derived parking tape")
    args = parser.parse_args()
    print(json.dumps(build(args.bundle, args.out, args.dynamic_cell, args.site_scene), indent=2))


if __name__ == "__main__":
    main()
