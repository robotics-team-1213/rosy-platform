"""map_v2_fleet lane launch keeps CORE the only final cmd_vel publisher."""

from pathlib import Path

LAUNCH = Path(__file__).resolve().parents[1] / "launch" / "map_v2_fleet_lane.launch.py"


def test_launch_uses_the_catalogued_world_and_spawn():
    source = LAUNCH.read_text(encoding="utf-8")
    assert '"map_v2_fleet", "worlds", "map_v2_fleet.world"' in source
    assert '"spawn_x": "-1.26955"' in source
    assert '"spawn_y": "0.24255"' in source
    assert '"bridge_image": "true"' in source


def test_line_observer_uses_the_bright_line_threshold():
    source = LAUNCH.read_text(encoding="utf-8")
    assert '"camera_bright_threshold": 180' in source


def test_only_core_can_command_motion():
    source = LAUNCH.read_text(encoding="utf-8")
    assert 'executable="core"' in source
    assert "cmd_vel" not in source
    assert "road_observer_node" not in source  # needs a map_v2_fleet road scene first
