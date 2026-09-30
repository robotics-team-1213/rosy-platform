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
            value = kw["default_value"]
            if isinstance(value, ast.Call) and getattr(value.func, "id", "") == "_env_switch":
                out[name] = ("env", ast.literal_eval(value.args[0]))
            else:
                out[name] = ast.literal_eval(value)
    return out


def test_switches_default_from_the_unit_environment():
    """rosy-camera.service EnvironmentFile=-/etc/rosy/learned-perception.env (D-373)."""
    d = _declared_defaults()
    assert d["learned_shadow"] == ("env", "ROSY_LEARNED_SHADOW")
    assert d["capture"] == ("env", "ROSY_CAPTURE")
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


SWITCH_ENV = ("ROSY_LEARNED_SHADOW", "ROSY_CAPTURE")


@pytest.fixture
def no_switch_env(monkeypatch):
    for name in SWITCH_ENV:
        monkeypatch.delenv(name, raising=False)
    return monkeypatch


def test_introspection_both_off_starts_nothing_new(no_switch_env):
    assert _started({}) == BASE


def test_env_true_turns_both_switches_on(no_switch_env):
    no_switch_env.setenv("ROSY_LEARNED_SHADOW", "true")
    no_switch_env.setenv("ROSY_CAPTURE", "true")
    assert _started({}) == BASE + ["learned_lane_node", "capture_trigger_node",
                                   "record_session --snapshot"]


def test_env_false_keeps_them_off(no_switch_env):
    no_switch_env.setenv("ROSY_LEARNED_SHADOW", "false")
    no_switch_env.setenv("ROSY_CAPTURE", "false")
    assert _started({}) == BASE


@pytest.fixture
def launch_warnings():
    """Records of the launch file's logger (launch's own handlers do not propagate)."""
    import logging
    records = []
    handler = logging.Handler(logging.WARNING)
    handler.emit = records.append
    logger = logging.getLogger("camera_preview.launch")
    logger.addHandler(handler)
    yield records
    logger.removeHandler(handler)


@pytest.mark.parametrize("garbage", ["1", "yes", "TRUE", "True", " true", "", "on"])
def test_env_garbage_is_off_and_says_so(no_switch_env, launch_warnings, garbage):
    no_switch_env.setenv("ROSY_LEARNED_SHADOW", garbage)
    no_switch_env.setenv("ROSY_CAPTURE", garbage)
    assert _started({}) == BASE
    text = " ".join(r.getMessage() for r in launch_warnings)
    assert "ROSY_LEARNED_SHADOW" in text and "ROSY_CAPTURE" in text


def test_env_unset_or_valid_warns_nothing(no_switch_env, launch_warnings):
    no_switch_env.setenv("ROSY_CAPTURE", "false")
    _started({})
    assert launch_warnings == []


def test_explicit_launch_argument_still_wins_over_env(no_switch_env):
    no_switch_env.setenv("ROSY_CAPTURE", "true")
    assert _started({"capture": "false"}) == BASE


def test_introspection_learned_shadow_only():
    assert _started({"learned_shadow": "true"}) == BASE + ["learned_lane_node"]


def test_introspection_capture_only():
    assert _started({"capture": "true"}) == BASE + ["capture_trigger_node",
                                                     "record_session --snapshot"]
