"""D-397: geometry.yaml is the URDF evaluated, and every Pinky Pro default equals it.

The first test regenerates geometry.yaml from the xacro and fails on any
difference, so the URDF and the profile config cannot drift. The rest pin each
consumer's default to geometry.yaml (URDF nominal, refined per robot by an
accepted calibration record, D-47 addendum store).
"""
import ast
import importlib.util
import math
import re
import sys
from pathlib import Path

import pytest
import yaml

HERE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(HERE))

import urdf_nominal  # noqa: E402

REPO = urdf_nominal.REPO
GEOMETRY = yaml.safe_load(urdf_nominal.OUTPUT.read_text(encoding="utf-8"))


def test_checked_in_geometry_matches_the_urdf():
    checked_in = urdf_nominal.OUTPUT.read_text(encoding="utf-8").replace("\r\n", "\n")
    assert checked_in == urdf_nominal.render(), "run python tools/calibration/urdf_nominal.py"
    assert urdf_nominal.main(["--check"]) == 0


def test_header_names_the_urdf_source_without_hashes():
    text = urdf_nominal.OUTPUT.read_text(encoding="utf-8")
    assert "src/sim/description/urdf/rosy.urdf.xacro" in text
    assert not re.search(r"[0-9a-f]{40}", text), "no hashes: the secret scan rejects 40-hex strings"
    assert "upstream import 6455b1a9" in text


def test_extractor_reproduces_the_hand_derived_chain():
    """The numbers the 2026-10-01 decision was computed from, re-derived in code."""
    g = urdf_nominal.nominal()
    assert g["base_link_z_m"] == pytest.approx(0.028)
    assert g["lidar"]["x_m"] == pytest.approx(-0.017)
    assert g["lidar"]["height_m"] == pytest.approx(0.125)
    assert g["lidar"]["yaw_rad"] == pytest.approx(math.pi)
    assert g["lidar"]["forward_deg"] == pytest.approx(180.0)
    tilt = math.radians(8.0)
    assert g["camera"]["x_m"] == pytest.approx(0.020 + 0.015 * math.cos(tilt) - 0.0121 * math.sin(tilt))
    assert g["camera"]["x_m"] == pytest.approx(0.0332, abs=1e-4)
    assert g["camera"]["height_m"] == pytest.approx(0.0634, abs=1e-4)
    assert g["camera"]["pitch_rad"] == pytest.approx(tilt)
    assert g["wheels"]["radius_m"] == pytest.approx(0.028)
    assert g["wheels"]["joint_y_m"] == pytest.approx(0.04055)
    assert g["wheels"]["separation_m"] == pytest.approx(0.0971)
    for key, y in (("left", 0.020), ("mid", 0.0), ("right", -0.020)):
        assert g["ir"][key]["x_m"] == pytest.approx(0.0295)
        assert g["ir"][key]["y_m"] == pytest.approx(y)
        assert g["ir"][key]["height_m"] == pytest.approx(0.013)
    assert g["ultrasonic"]["x_m"] == pytest.approx(0.0267)
    assert (g["imu"]["x_m"], g["imu"]["y_m"], g["imu"]["z_base_link_m"]) == pytest.approx((-0.044, 0.0, 0.0525))
    assert g["footprint"]["rotation_radius_sim_box_m"] == pytest.approx(0.088, abs=5e-4)
    assert 0.080 < g["footprint"]["rotation_radius_m"] < g["footprint"]["rotation_radius_sim_box_m"]
    assert g["footprint"]["front_x_m"] == pytest.approx(0.04205, abs=1e-5)   # screen mount (D-422)


def test_camera_follows_the_tilt_arg():
    args = {**urdf_nominal.arg_defaults(), "cam_tilt_deg": 25}
    g = urdf_nominal.nominal(args)
    assert g["camera"]["pitch_deg"] == pytest.approx(25.0)
    # the Gazebo lane bench value (map_v2_fleet_lane.launch.py dock_observer)
    assert g["camera"]["x_m"] == pytest.approx(0.028481, abs=1e-6)
    assert g["camera"]["height_m"] == pytest.approx(0.060194, abs=1e-6)
    lane = (urdf_nominal.REPO / "src" / "sim" / "gz_sim" / "launch" / "map_v2_fleet_lane.launch.py").read_text(
        encoding="utf-8")
    assert '"cam_tilt_deg": "25"' in lane
    assert lane.count(f'"camera_x_offset_m": {round(g["camera"]["x_m"], 6)},') == 2
    assert lane.count(f'"camera_height_m": {round(g["camera"]["height_m"], 6)},') == 1


def test_unsupported_xacro_fails_loudly():
    with pytest.raises(ValueError):
        urdf_nominal._eval("__import__('os')", {"pi": math.pi})
    with pytest.raises(ValueError):
        urdf_nominal._eval("radius ** 2", {"radius": 1.0})


# --- every consumer's default equals geometry.yaml ----------------------------------

G = GEOMETRY
SRC = REPO / "src"
SENSING = SRC / "runtime" / "sensing"
BRINGUP = SRC / "products" / "pinky_pro" / "bringup"
PROFILE = SRC / "products" / "pinky_pro" / "profile" / "config"


def _yaml(path):
    return yaml.safe_load(Path(path).read_text(encoding="utf-8"))


def _text(path):
    return Path(path).read_text(encoding="utf-8")


def _number(path, pattern):
    """The one numeric literal captured by `pattern` in a source file."""
    found = re.findall(pattern, _text(path))
    assert len(found) == 1, f"{path}: expected one match of {pattern!r}, got {found}"
    return float(found[0])


def _module_constants(path, *names):
    """Module-level literal assignments (parsed, not imported: no ROS or numpy needed)."""
    out = {}
    for node in ast.parse(_text(path)).body:
        if not isinstance(node, ast.Assign):
            continue
        target = node.targets[0]
        if isinstance(target, ast.Name) and target.id in names:
            try:
                out[target.id] = ast.literal_eval(node.value)
            except ValueError:  # plain arithmetic such as 0.011 + 0.0065
                out[target.id] = urdf_nominal._eval(ast.unparse(node.value), {})
        elif isinstance(target, ast.Tuple) and isinstance(node.value, ast.Tuple):
            for name, value in zip(target.elts, node.value.elts):
                if isinstance(name, ast.Name) and name.id in names:
                    out[name.id] = ast.literal_eval(value)
    missing = set(names) - set(out)
    assert not missing, f"{path}: {missing} not found"
    return out


def _load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_lidar_mount_consumers():
    yaw, forward = G["lidar"]["yaw_rad"], G["lidar"]["forward_deg"]
    lidar = _module_constants(SENSING / "control" / "sensing" / "lidar.py", "MOUNT_YAW_DEG")
    assert lidar["MOUNT_YAW_DEG"] == 0.0                     # NOSE_YAW = pi + 0 = the URDF yaw
    assert yaw == pytest.approx(math.pi, abs=1e-6)
    params = _yaml(SENSING / "config" / "robot.yaml")["/**"]["ros__parameters"]
    assert params["lidar_yaw_offset"] == pytest.approx(yaw, abs=1e-6)
    assert params["scan_yaw_offset"] == pytest.approx(yaw, abs=1e-6)
    auto = _yaml(SENSING / "config" / "auto_calib.yaml")["/**/safety_node"]["ros__parameters"]
    assert auto["lidar_yaw_offset"] == pytest.approx(yaw, abs=1e-6)
    assert _yaml(PROFILE / "core.yaml")["line_follow"]["lidar_forward_deg"] == forward
    store = _module_constants(SRC / "contracts" / "foundation" / "core_common" / "calibration_store.py",
                              "LIDAR_NOMINAL_DEG")
    assert store["LIDAR_NOMINAL_DEG"] == forward
    assert _number(SENSING / "control" / "road_state_node.py",
                   r"declare_parameter\('lidar_yaw_offset_deg', ([0-9.]+)\)") == forward
    perception = _module_constants(REPO / "tools" / "perception" / "dataset" / "geometry.py",
                                   "LIDAR_FORWARD_DEG", "LIDAR_HEIGHT_M", "LIDAR_X_OFFSET_M")
    assert perception == {"LIDAR_FORWARD_DEG": forward, "LIDAR_HEIGHT_M": G["lidar"]["height_m"],
                          "LIDAR_X_OFFSET_M": G["lidar"]["x_m"]}
    world_to_map = _module_constants(SRC / "sim" / "gz_sim" / "scripts" / "world_to_map.py", "LIDAR_Z")
    assert world_to_map["LIDAR_Z"] == G["lidar"]["height_m"]


def test_camera_consumers():
    cam = G["camera"]
    nominal = _yaml(PROFILE / "camera_nominal.yaml")
    assert nominal["pitch_rad"] == pytest.approx(cam["pitch_rad"], abs=1e-6)
    assert nominal["height_m"] == pytest.approx(cam["height_m"], abs=1e-6)
    assert nominal["x_offset_m"] == pytest.approx(cam["x_m"], abs=1e-6)
    real = _module_constants(SRC / "sim" / "gz_sim" / "launch" / "map_v2_fleet_real.launch.py",
                             "REAL_TILT_DEG", "REAL_CAM_MOUNT_Z", "REAL_CAMERA_HEIGHT_M", "REAL_CAMERA_X_OFFSET_M")
    assert real["REAL_TILT_DEG"] == cam["tilt_arg_deg"]
    assert real["REAL_CAM_MOUNT_Z"] == cam["mount_z_arg_m"]
    assert real["REAL_CAMERA_HEIGHT_M"] == pytest.approx(cam["height_m"], abs=1e-6)
    assert real["REAL_CAMERA_X_OFFSET_M"] == pytest.approx(cam["x_m"], abs=1e-6)


def test_wheel_consumers():
    radius, separation = G["wheels"]["radius_m"], G["wheels"]["separation_m"]
    for name in ("rosy_params.yaml", "pinky_pro_adapter.yaml"):
        params = _yaml(BRINGUP / "config" / name)["bringup"]["ros__parameters"]
        assert (params["wheel_radius"], params["wheel_separation"]) == (radius, separation), name
    adapter = _module_constants(BRINGUP / "bringup" / "pinky_pro_adapter.py", "DEFAULTS")["DEFAULTS"]
    assert (adapter["wheel_radius"], adapter["wheel_separation"]) == (radius, separation)
    node = BRINGUP / "bringup" / "bringup.py"
    assert _number(node, r"declare_parameter\('wheel_radius', ([0-9.]+)\)") == radius
    assert _number(node, r"declare_parameter\('wheel_separation', ([0-9.]+)\)") == separation
    launch = _text(BRINGUP / "launch" / "bringup_robot.launch.py")
    # The launch arguments are operator overrides only; 0 leaves the URDF nominal above.
    assert "DeclareLaunchArgument('wheel_radius', default_value='0.0')" in launch
    assert "DeclareLaunchArgument('wheel_separation', default_value='0.0')" in launch
    store = _module_constants(SRC / "contracts" / "foundation" / "core_common" / "calibration_store.py",
                              "NOMINAL_WHEEL_RADIUS_M", "NOMINAL_WHEEL_SEPARATION_M", "WHEEL_TOLERANCE")
    assert (store["NOMINAL_WHEEL_RADIUS_M"], store["NOMINAL_WHEEL_SEPARATION_M"]) == (radius, separation)
    assert store["WHEEL_TOLERANCE"] == 0.10
    gz = _text(SRC / "sim" / "description" / "urdf" / "rosy_gz.urdf.xacro")
    assert f"<wheel_separation>{separation}</wheel_separation>" in gz
    assert f"<wheel_radius>{radius}</wheel_radius>" in gz
    isaac = _load("isaac_graph_contract", SRC / "sim" / "isaac_sim" / "graph_contract.py").robot_contract("rosy_01")
    assert (isaac["wheel_radius"], isaac["wheel_distance"]) == (radius, separation)


def test_line_follow_stuck_body_consumers():
    """D-407: the CORE back-off measures rear clearance from the URDF body rear."""
    line_follow = _yaml(PROFILE / "core.yaml")["line_follow"]
    assert line_follow["body_lidar_x_m"] == G["lidar"]["x_m"]
    assert line_follow["body_rear_x_m"] == G["caster"]["rear_x_m"]
    assert line_follow["body_rotation_radius_m"] == G["footprint"]["rotation_radius_m"]
    assert line_follow["body_half_width_m"] == G["footprint"]["half_width_m"]
    # D-422: the obstacle stop measures from the body front; the ultrasonic gap from its mount.
    assert line_follow["body_front_x_m"] == G["footprint"]["front_x_m"]
    assert line_follow["body_ultrasonic_x_m"] == G["ultrasonic"]["x_m"]
    assert G["ultrasonic"]["x_m"] < G["footprint"]["front_x_m"] < G["footprint"]["rotation_radius_m"]


def test_shared_robot_body_matches_geometry():
    """D-424: core_common.robot_body.PINKY_PRO is the one body every near/stop check uses."""
    foundation = str(SRC / "contracts" / "foundation")
    if foundation not in sys.path:
        sys.path.insert(0, foundation)
    from core_common import robot_body as body_module
    nominal = body_module.PINKY_PRO_GEOMETRY
    for section, values in nominal.items():
        for key, value in values.items():
            assert value == G[section][key], f"{section}.{key}"
    body = body_module.PINKY_PRO
    assert (body.front_x_m, body.rear_x_m, body.half_width_m, body.rotation_radius_m) == (
        G["footprint"]["front_x_m"], G["caster"]["rear_x_m"], G["footprint"]["half_width_m"],
        G["footprint"]["rotation_radius_m"])
    assert (body.lidar_x_m, body.lidar_y_m, body.lidar_forward_deg, body.ultrasonic_x_m) == (
        G["lidar"]["x_m"], G["lidar"]["y_m"], G["lidar"]["forward_deg"], G["ultrasonic"]["x_m"])
    # D-422 gap policy: the CORE defaults equal the shared module's.
    defaults = _yaml(SRC / "contracts" / "foundation" / "config" / "rosy_default.yaml")["line_follow"]
    assert (defaults["obstacle_body_margin_m"], defaults["obstacle_latency_s"], defaults["obstacle_decel_mps2"],
            defaults["obstacle_resume_hysteresis_m"]) == (
        body_module.MARGIN_M, body_module.LATENCY_S, body_module.DECEL_MPS2, body_module.HYSTERESIS_M)


def test_body_and_ir_consumers():
    body = _module_constants(SENSING / "control" / "sensing" / "body.py", "WHEEL_Y", "WHEEL_R", "CASTER_X",
                             "CASTER_EXTRA", "FRONT_X")
    assert body["WHEEL_Y"] == G["wheels"]["joint_y_m"]
    assert body["WHEEL_R"] == G["wheels"]["radius_m"]
    assert body["CASTER_X"] + body["CASTER_EXTRA"] == pytest.approx(-G["caster"]["rear_x_m"], abs=1e-9)
    assert body["FRONT_X"] == G["ir"]["mid"]["x_m"]
    # LIDAR_X and ROTATION_RADIUS come from the shared body (D-424); no literal left in body.py.
    text = _text(SENSING / "control" / "sensing" / "body.py")
    assert "LIDAR_X = BODY.lidar_x_m" in text and "ROTATION_RADIUS = BODY.rotation_radius_m" in text
    circumradius = max(body["WHEEL_Y"] + body["WHEEL_R"], body["CASTER_X"] + body["CASTER_EXTRA"], body["FRONT_X"])
    for config, block in (("robot.yaml", "/**"), ("auto_calib.yaml", "/**/safety_node")):
        radius = _yaml(SENSING / "config" / config)[block]["ros__parameters"]["robot_radius"]
        assert radius == pytest.approx(circumradius, abs=1e-9), config
    model = SENSING / "control" / "sensing" / "perception" / "road_state_model.py"
    assert _number(model, r"ir_x_m: float = ([0-9.]+)") == G["ir"]["mid"]["x_m"]
    node = SENSING / "control" / "road_state_node.py"
    assert _number(node, r"declare_parameter\('ir_half_span_m', ([0-9.]+)\)") == G["ir"]["half_span_m"]
    replay = _module_constants(REPO / "tools" / "perception" / "road_replay.py", "IR_HALF_SPAN_M")
    assert replay["IR_HALF_SPAN_M"] == G["ir"]["half_span_m"]


# --- the extractor fails closed -------------------------------------------------------

def _xacro(tmp_path, body, top=""):
    path = tmp_path / "robot.xacro"
    path.write_text(f"""<?xml version="1.0"?>
<robot xmlns:xacro="http://www.ros.org/wiki/xacro">{top}
  <xacro:macro name="insert_robot" params="namespace is_sim:=false">
    <link name="base_footprint"/>
    <link name="base_link"/>
    <joint name="j" type="fixed"><parent link="base_footprint"/><child link="base_link"/>
      <origin xyz="0 0 0.028" rpy="0 0 0"/></joint>
{body}
  </xacro:macro>
</robot>
""", encoding="utf-8")
    return path


def _expand(path):
    return urdf_nominal.expand(path, args={"namespace": ""})


def test_minimal_xacro_expands(tmp_path):
    links, joints = _expand(_xacro(tmp_path, ""))
    assert [j["xyz"] for j in joints] == [(0.0, 0.0, 0.028)]


@pytest.mark.parametrize("top,body", [
    ('<xacro:property name="r" value="0.03"/>', ""),
    ("", '<xacro:insert_block name="blk"/>'),
    ("", '<xacro:element xacro:name="link"/>'),
    ("", '<xacro:include filename="$(find other)/urdf/x.xacro"/>'),
    ("", '<xacro:not_a_macro/>'),
    ('<xacro:macro name="m" params="a"><link name="m_${a}"/></xacro:macro>', '<xacro:m a="1" b="2"/>'),
    ('<xacro:macro name="m" params="a"><link name="m_${a}"/></xacro:macro>', '<xacro:m/>'),
    ("", '<link name="x"><collision><geometry><mesh filename="package://description/meshes/collision/'
         'base_link.stl" scale="0.001 0.001 0.001"/></geometry></collision></link>'),
    ("", '<link name="x"><visual><xacro:property name="p" value="1"/></visual></link>'),
    ("", '<joint name="k" type="fixed"><parent link="base_link"/><child link="y"/>'
         '<xacro:property name="p" value="1"/></joint>'),
])
def test_unsupported_xacro_is_an_error_not_a_guess(tmp_path, top, body):
    path = _xacro(tmp_path, body, top)
    with pytest.raises(ValueError):
        links, joints = _expand(path)
        for link in links:
            for spec in link["collisions"]:
                urdf_nominal._shape_points(spec)


def test_joint_origin_inside_a_branch_is_honoured(tmp_path):
    body = ('<link name="y"/><joint name="k" type="fixed"><parent link="base_link"/><child link="y"/>'
            '<xacro:unless value="${is_sim}"><origin xyz="0.1 0 0" rpy="0 0 0"/></xacro:unless>'
            '<xacro:if value="${is_sim}"><origin xyz="0.2 0 0" rpy="0 0 0"/></xacro:if></joint>')
    _, joints = _expand(_xacro(tmp_path, body))
    assert joints[-1]["xyz"] == (0.1, 0.0, 0.0)


def test_a_comment_only_urdf_edit_keeps_the_values(tmp_path):
    copy = tmp_path / "rosy.urdf.xacro"
    text = urdf_nominal.URDF.read_text(encoding="utf-8")
    copy.write_text(text.replace("<link name=\"base_footprint\"/>",
                                 "<!-- a new comment -->\n        <link name=\"base_footprint\"/>"), encoding="utf-8")
    assert urdf_nominal.expand(copy) == urdf_nominal.expand()


def test_ascii_stl_with_a_long_name_and_garbage(tmp_path):
    ascii_stl = tmp_path / "a.stl"
    ascii_stl.write_text("solid " + "n" * 600 + "\n facet normal 0 0 1\n  outer loop\n"
                         "   vertex 0 0 0\n   vertex 1 0 0\n   vertex 0 1 0\n  endloop\n endfacet\nendsolid\n",
                         encoding="ascii")
    assert urdf_nominal._stl_points(ascii_stl) == [(0.0, 0.0, 0.0), (1.0, 0.0, 0.0), (0.0, 1.0, 0.0)]
    garbage = tmp_path / "b.stl"
    garbage.write_bytes(b"not an stl at all" * 10)
    with pytest.raises(ValueError, match="neither a binary nor an ASCII STL"):
        urdf_nominal._stl_points(garbage)
