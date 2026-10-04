"""D-411 A: pilot_recorder_node stays thin; the camera publishes JPEG only while recording."""

from pathlib import Path
import ast
import json
import types

import pytest

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


@pytest.mark.parametrize('mode, expected', [(0, 'raw'), (1, 'annotated'), (2, None), (True, None)])
def test_typed_start_options_are_closed_and_read_back_the_recorder(mode, expected):
    tree = ast.parse(_src('pilot_recorder_node.py'))
    cls = next(n for n in tree.body if isinstance(n, ast.ClassDef))
    fn = next(n for n in cls.body if isinstance(n, ast.FunctionDef) and n.name == '_on_start')
    scope = {'json': json}
    exec(compile(ast.Module(body=[fn], type_ignores=[]), '<recorder-start>', 'exec'), scope)
    calls = []
    def start(**kwargs):
        calls.append(kwargs)
        return True, 'session-id'
    node = types.SimpleNamespace(_recorder=types.SimpleNamespace(start=start, status=lambda: {'state': 'starting'}),
                                 _publish=lambda: None)
    response = scope['_on_start'](node, types.SimpleNamespace(preview_mode=mode), types.SimpleNamespace())
    assert response.success is (expected is not None)
    assert calls == ([{'preview_mode': expected}] if expected is not None else [])
    assert json.loads(response.message)['status'] == {'state': 'starting'}


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


def test_node_falls_back_to_the_default_reserve_when_it_does_not_fit_the_quota():
    src = _src("pilot_recorder_node.py")
    assert "except ValueError as exc:" in src
    assert "DEFAULT_RESERVE_BYTES" in src.split("except ValueError as exc:", 1)[1]


def test_node_names_sessions_after_the_robot_not_the_host():
    # session.device must match CORE's robot id: explicit `device`, else the namespace.
    src = _src("pilot_recorder_node.py")
    assert "self.declare_parameter('device', '')" in src
    flat = "".join(src.split())
    assert ("recording_device(self.get_parameter('device').value,self.get_namespace(),"
            "socket.gethostname())") in flat


def test_node_turns_the_camera_copy_on_from_starting_and_notices_the_writer_quickly():
    src = _src("pilot_recorder_node.py")
    assert "status['state'] in ACTIVE_STATES" in src
    assert "ACTIVE_STATES" in src.split("from core_common.protocol.recording import", 1)[1].split(")", 1)[0]
    assert "create_timer(START_POLL_S, self._poll_start)" in src
    assert "self._recorder.poll_start()" in src


def test_executor_choice_warns_that_threads_break_the_recorder_pdeathsig():
    src = _src("executor_choice.py")
    assert "MultiThreadedExecutor" in src and "pdeathsig" in src and "pilot_recording" in src


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
