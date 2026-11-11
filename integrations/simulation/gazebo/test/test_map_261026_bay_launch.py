"""map_261026_bay_lane launch contract: pink paint source, keep mode, S2 spawn."""

from pathlib import Path

LAUNCH = Path(__file__).resolve().parents[1] / "launch" / "map_261026_bay_lane.launch.py"


def test_launch_source_pins():
    src = LAUNCH.read_text(encoding="utf-8")
    assert 'map_world_261026", "worlds", "map_world_261026.world' in src
    # D-1013: magenta guide tape, consumed by keep mode's paint path.
    assert '"paint_source": "pink"' in src
    assert '"camera_lane_mode", default_value="keep"' in src
    # S2 (parking entrance) facing +y along the guide curve toward P3.
    assert '"spawn_x", default_value="0.309"' in src
    assert '"spawn_y", default_value="-0.13"' in src
    assert '"spawn_yaw", default_value="1.5708"' in src
    assert "map_261026_core.yaml" in src
    # D-601 front preview (CAMERA_LAUNCHES membership).
    assert "sim_jpeg_relay" in src
    # The bay pit-in docking approach (approach "line") is a later branch.
    assert "dock_observer" not in src
    assert "lane_graph_path" not in src
