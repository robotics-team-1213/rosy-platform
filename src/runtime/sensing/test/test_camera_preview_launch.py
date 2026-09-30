"""D-373 decisions 2-4: camera_preview.launch.py payload switches, both off by default."""

import ast
import importlib.util
import sys
import types
from pathlib import Path

import pytest

LAUNCH = Path(__file__).resolve().parents[1] / "launch" / "camera_preview.launch.py"
SRC = LAUNCH.read_text(encoding="utf-8")


def _declared_defaults():
    tree = ast.parse(SRC)
    out = {}
    for node in ast.walk(tree):
        if isinstance(node, ast.Call) and getattr(node.func, "id", "") == "DeclareLaunchArgument":
            name = ast.literal_eval(node.args[0])
            kw = {k.arg: k.value for k in node.keywords}
            out[name] = ast.literal_eval(kw["default_value"])
    return out


def test_switches_default_off():
    d = _declared_defaults()
    assert d["learned_shadow"] == "false"
    assert d["capture"] == "false"
    assert d["shadow_pointer"] == "/var/lib/rosy/models/shadow"
    assert d["recording_root"] == "/var/lib/rosy/camera/recordings"


def test_new_actions_are_gated_by_their_switch():
    assert "condition=IfCondition(learned_shadow)" in SRC
    assert SRC.count("condition=IfCondition(capture)") == 2  # trigger node + recorder
    assert "'publish_compressed': ParameterValue(capture, value_type=bool)" in SRC
    assert "'--snapshot'" in SRC
    assert "cmd_vel" not in SRC  # camera unit never touches motion (test_camera_image_stack)


def test_recorder_name_is_left_to_the_namespace():
    """record_session and capture_trigger_node both derive it from the namespace."""
    assert "--node-name" not in SRC and "snapshot_service" not in SRC


def test_recording_root_matches_recording_default():
    from control.recording import DEFAULT_ROOT
    assert _declared_defaults()["recording_root"] == DEFAULT_ROOT


def _load():
    fake = types.ModuleType("ament_index_python.packages")
    fake.get_package_share_directory = lambda pkg: "/opt/share/" + pkg
    saved = sys.modules.get("ament_index_python.packages")
    sys.modules["ament_index_python.packages"] = fake
    try:
        spec = importlib.util.spec_from_file_location("camera_preview_launch", LAUNCH)
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
    finally:
        if saved is not None:
            sys.modules["ament_index_python.packages"] = saved
        else:
            del sys.modules["ament_index_python.packages"]
    return mod


def _started(args):
    # Not "launch": this package's own launch/ folder imports as a namespace package.
    pytest.importorskip("launch.launch_context")
    pytest.importorskip("launch_ros.actions")
    from launch import LaunchContext
    from launch.actions import DeclareLaunchArgument, ExecuteProcess
    from launch.substitutions import TextSubstitution
    from launch.utilities import perform_substitutions

    ld = _load().generate_launch_description()
    ctx = LaunchContext()
    ctx.launch_configurations.update(args)
    started = []
    for e in ld.entities:
        if isinstance(e, DeclareLaunchArgument):
            ctx.launch_configurations.setdefault(
                e.name, perform_substitutions(ctx, e.default_value))
            continue
        if e.condition is not None and not e.condition.evaluate(ctx):
            continue
        if isinstance(e, ExecuteProcess) and not hasattr(e, "node_executable"):
            texts = [s.text for part in e.cmd for s in part if isinstance(s, TextSubstitution)]
            started.append("record_session" + (" --snapshot" if "--snapshot" in texts else ""))
        else:
            started.append(e.node_executable)
    return started


BASE = ["camera_detect_node", "line_observer_node", "road_observer_node"]


def test_introspection_both_off_starts_nothing_new():
    assert _started({}) == BASE


def test_introspection_learned_shadow_only():
    assert _started({"learned_shadow": "true"}) == BASE + ["learned_lane_node"]


def test_introspection_capture_only():
    assert _started({"capture": "true"}) == BASE + ["capture_trigger_node",
                                                     "record_session --snapshot"]
