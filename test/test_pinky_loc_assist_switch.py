"""2026-11-14: a real Pinky never ran the D-395 loc_assist_node, so CORE's state.localization stayed null.

The navigation unit now passes ``enable_loc_assist`` from ``ROSY_ENABLE_LOC_ASSIST`` (default false, runtime.env
wins), and the launch argument it feeds exists with the same name.
"""
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
UNIT = ROOT / "deploy/robot/pinky_pro/native/rosy-navigation.service"
ENV = ROOT / "deploy/robot/pinky_pro/native/rosy-runtime.env"
LAUNCH = ROOT / "middleware/drive/planning/nav2/launch/hardware.launch.py"


def test_the_unit_passes_the_switch_with_a_false_default():
    unit = UNIT.read_text(encoding="utf-8")
    exec_start = next(line for line in unit.splitlines() if line.startswith("ExecStart="))
    assert "enable_loc_assist:=${ROSY_ENABLE_LOC_ASSIST}" in exec_start
    defaults = next(line for line in unit.splitlines() if line.startswith("Environment=ROSY_NAVIGATION_BACKEND="))
    assert "ROSY_ENABLE_LOC_ASSIST=false" in defaults.split()   # an unset value would be an empty launch argument
    # the default comes before runtime.env, so a robot's own value wins
    assert unit.index("ROSY_ENABLE_LOC_ASSIST=false") < unit.index("EnvironmentFile=/etc/rosy/runtime.env")


def test_the_template_names_the_switch_off():
    assert re.search(r"^ROSY_ENABLE_LOC_ASSIST=false$", ENV.read_text(encoding="utf-8"), re.M)


def test_the_launch_declares_the_argument_the_unit_sets():
    launch = LAUNCH.read_text(encoding="utf-8")
    assert 'DeclareLaunchArgument("enable_loc_assist"' in launch
    assert 'IfCondition(LaunchConfiguration("enable_loc_assist"))' in launch
