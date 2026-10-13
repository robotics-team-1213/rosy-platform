"""Camera and lane evidence have a separate holder from sensor geometry."""

from pathlib import Path

SENSING = Path(__file__).resolve().parents[1] / "sensors" / "sensing"
PERCEPTION = Path(__file__).resolve().parents[1] / "vision" / "perception"


def test_image_modules_moved_and_geometry_stayed():
    for name in ("lane.py", "camera.py", "road.py", "scene_context.py", "v4l2_controls.py"):
        assert (PERCEPTION / name).is_file()
        assert not (SENSING / name).exists()
    for name in ("lidar.py", "body.py", "dock_tag.py", "battery.py", "wall_tracker.py"):
        assert (SENSING / name).is_file()
        assert not (PERCEPTION / name).exists()


def test_perception_modules_do_not_import_ros_or_velocity():
    source = "\n".join(path.read_text(encoding="utf-8") for path in PERCEPTION.glob("*.py"))
    assert "rclpy" not in source
    assert "cmd_vel" not in source
