"""D-411 A: pilot_recorder_node stays thin; the camera publishes JPEG only while recording."""

from pathlib import Path

from core_common.protocol import recording as rec

CONTROL = Path(__file__).resolve().parents[1] / "control"
LAUNCH = Path(__file__).resolve().parents[1] / "launch" / "camera_preview.launch.py"
SETUP = Path(__file__).resolve().parents[1] / "setup.py"


def _src(name):
    return (CONTROL / name).read_text(encoding="utf-8")


def test_node_wraps_the_ros_free_recorder_and_never_drives():
    src = _src("pilot_recorder_node.py")
    assert "from .pilot_recording import DEFAULT_QUOTA_BYTES, DEFAULT_RESERVE_BYTES, PilotRecorder" in src
    assert "create_service(SetBool, SET_ACTIVE_SERVICE, self._on_set_active)" in src
    assert "create_subscription(String, FETCHED_TOPIC, self._on_fetched, 5)" in src
    assert "create_publisher(String, STATUS_TOPIC, _LATCHED)" in src
    assert "create_publisher(Bool, ACTIVE_TOPIC, _LATCHED)" in src
    assert "create_timer(1.0, self._tick)" in src
    assert "self._recorder.recover()" in src
    assert "cmd_vel" not in src and "Twist" not in src
    assert "subprocess" not in src  # the process belongs to PilotRecorder


def test_node_main_matches_the_capture_trigger_shape():
    src = _src("pilot_recorder_node.py")
    assert "executor_choice.spin(node, rclpy)" in src
    assert "node.destroy_node()" in src and "rclpy.shutdown()" in src
    # 'events' raises this when the context shuts down from another thread (executor_choice).
    assert "except (KeyboardInterrupt, ExternalShutdownException):" in src


def test_node_survives_a_recover_failure_and_logs_through_ros():
    src = _src("pilot_recorder_node.py")
    assert "log=self.get_logger().warn" in src
    assert "except OSError as exc:" in src
    assert "reserve_gib" in src


def test_camera_publishes_compressed_only_while_the_recorder_is_active():
    src = _src("camera_detect_node.py")
    assert "create_subscription(Bool, ACTIVE_TOPIC, self._on_recorder_active, _RECORDER_QOS)" in src
    assert "self._recorder_active" in src
    assert "def _compressed_publisher(self)" in src
    assert "destroy_publisher" not in src


def test_camera_drops_the_jpeg_copy_when_the_recorder_is_gone():
    src = _src("camera_detect_node.py")
    assert "create_timer(1.0, self._check_recorder_alive)" in src
    assert "self.count_publishers(ACTIVE_TOPIC) == 0" in src


def test_launch_starts_the_recorder_with_the_d411_root_and_respawns_it():
    src = LAUNCH.read_text(encoding="utf-8")
    assert "executable='pilot_recorder_node'" in src
    assert f"'{rec.PILOT_RECORDING_ROOT}'" in src
    assert "'recording_root': pilot_recording_root" in src
    block = src[src.index("executable='pilot_recorder_node'"):]
    block = block[:block.index("),")]
    assert "respawn=True, respawn_delay=2.0" in block


def test_entry_point_is_installed():
    assert "pilot_recorder_node = control.pilot_recorder_node:main" in SETUP.read_text(encoding="utf-8")
