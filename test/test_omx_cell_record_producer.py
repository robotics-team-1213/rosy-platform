"""The OMX recording producer writes the Rosy Learning contract read only: the runner's live.json
state and sent targets, viewer camera frames, stale input leaving no event, and no command path."""
import ast
import hashlib
import json
from pathlib import Path
import sys

import pytest

np = pytest.importorskip("numpy")
cv2 = pytest.importorskip("cv2")

ROOT = Path(__file__).parents[1]
OMX = ROOT / "deploy" / "robot" / "omx"
sys.path.insert(0, str(OMX))
try:
    import arm_status_bridge
    import cell_record_producer as producer
finally:
    sys.path.remove(str(OMX))
sys.path.insert(0, str(ROOT / "learning" / "curation" / "omx"))
try:
    import passive_recording_helpers  # the workbench's own event validator
finally:
    sys.path.remove(str(ROOT / "learning" / "curation" / "omx"))

RULE = {"held_30mm": 46.0, "gap_mm_per_unit": 0.9}
STATE = [0.0, -12.5, 30.0, 4.0, -5.0, 50.0]
TARGET = [1.0, 2.0, 3.0, 4.0, 5.0, 60.0]
SOURCE = (OMX / "cell_record_producer.py").read_text(encoding="utf-8")


def arm(out, **kwargs):
    return producer.ArmProducer(out, "arm_a", rule=RULE, clock=lambda: "host-monotonic:test-boot", **kwargs)


def receipt(shape=(240, 320), seq=1):
    image = np.zeros((*shape, 3), np.uint8)
    ok, raw = cv2.imencode(".jpg", image)
    assert ok
    return {"image": image, "jpeg_bytes": raw.tobytes(), "source_seq": seq, "source_stamp": 1000.0,
            "camera": "top", "etag": f'"e{seq}"', "captured_at": 1000.1}


def _violations(source):
    """Every way this module could open a command path; empty means read only."""
    forbidden = {"mkfifo", "O_WRONLY", "O_RDWR"}
    hits = []
    for node in ast.walk(ast.parse(source)):
        if isinstance(node, ast.Name) and node.id in forbidden:
            hits.append(node.id)
        if isinstance(node, ast.Attribute) and node.attr in forbidden:
            hits.append(node.attr)
        if (isinstance(node, ast.Constant) and isinstance(node.value, str) and "chunk-cmd" in node.value):
            hits.append("chunk-cmd")
        if (isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute) and node.func.attr == "open"
                and isinstance(node.func.value, ast.Name) and node.func.value.id == "os"):
            hits.append("os.open")
    return hits


def test_fake_live_row_publishes_a_contract_event(tmp_path):
    live, out = tmp_path / "live.json", tmp_path / "arm_a"
    live.write_text(json.dumps({"t": 1000.0, "state": STATE, "target": TARGET}))
    made = arm(out)
    assert made.poll(live, monotonic=lambda: 5000.0, wall=lambda: 1000.2)["sequence"] == 0
    event = json.loads((out / "events" / "0.json").read_text())
    assert event == json.loads((out / "latest.json").read_text())
    assert event["schema"] == "rosy.passive-owner-sample/1"
    assert event["state"] == STATE and event["accepted_reference"] == TARGET  # follower units, unconverted
    assert event["state_timestamp"] == event["reference_timestamp"] == 5000.0
    assert event["reference_id"] == "arm_a-live-target@1000.0"
    config = {"producers": {"arms": {"arm_a": made.descriptor}}}
    passive_recording_helpers.validate_event(config, "arms", {**event, "arm_id": "arm_a"}, 5001.0)
    # a stale gap leaves no event; numbering resumes without overwrite or regression
    live.write_text(json.dumps({"t": 995.0, "state": STATE, "target": TARGET}))
    assert made.poll(live, monotonic=lambda: 5001.0, wall=lambda: 1002.5)["ok"] is False
    live.write_text(json.dumps({"t": 1002.4, "state": STATE, "target": TARGET}))
    assert made.poll(live, monotonic=lambda: 5002.0, wall=lambda: 1002.5)["sequence"] == 1
    assert json.loads((out / "events" / "1.json").read_text())["sequence"] == 1


@pytest.mark.parametrize("row,needle", [
    ({"t": 997.0, "state": STATE, "target": TARGET}, "s old"),  # wall 1000.2 - t > arm_status_bridge.STALE_S
    ({"t": 1000.1, "state": STATE}, "target"),
    ({"t": 1000.1, "state": STATE[:5], "target": TARGET}, "6 joints"),
    ({}, "t/state/target"),
])
def test_stale_or_broken_rows_leave_no_event_and_the_reason(tmp_path, row, needle):
    live, out = tmp_path / "live.json", tmp_path / "arm_a"
    live.write_text(json.dumps(row))
    result = arm(out).poll(live, monotonic=lambda: 5000.0, wall=lambda: 1000.2)
    assert result["ok"] is False and needle in result["reason"]
    assert not list((out / "events").glob("*.json")) and not (out / "latest.json").exists()
    assert needle in json.loads((out / "status.json").read_text())["reason"]


def test_missing_live_file_leaves_the_reason_only(tmp_path):
    result = arm(tmp_path / "arm_a").poll(tmp_path / "absent.json",
                                          monotonic=lambda: 5000.0, wall=lambda: 1000.2)
    assert result["ok"] is False and "FileNotFoundError" in result["reason"]


def test_descriptor_freezes_the_two_arm_input_contract(tmp_path):
    out = tmp_path / "arm_a"
    made = arm(out)
    descriptor = json.loads((out / "descriptor.json").read_text())
    assert descriptor == made.descriptor  # frozen at start; a restart rewrites it with a new epoch
    assert json.loads((out / "registration.json").read_text()) == {"kind": "arm", "label": "OMX arm_a follower"}
    assert descriptor["kind"] == "arm" and descriptor["joint_names"] == arm_status_bridge.JOINTS
    assert descriptor["reference_stage"] == "post_guard_accepted"
    assert descriptor["state_units"] == descriptor["action_units"] == producer.UNITS
    assert descriptor["rate_hz"] == producer.SIM_FPS  # the sim dataset's FPS is the grid this feeds
    assert descriptor["clock_domain"].startswith("host-monotonic:")
    assert descriptor["grip_rule"] == {"held_30mm": 46.0, "gap_mm_per_unit": 0.9}
    assert descriptor["owner_id"] == "arm_a:chunk_runner"
    assert descriptor["state_producer"] == "chunk_runner.live.json:state"
    assert descriptor["reference_producer"] == "chunk_runner.live.json:target"
    assert descriptor["calibration_revision"] and descriptor["profile_revision"]


def test_camera_frames_become_contract_events(tmp_path):
    out = tmp_path / "cam_top"
    made = producer.CameraProducer(out, "top", shape=(240, 320), clock=lambda: "host-monotonic:test-boot")
    assert made.poll(receipt(seq=1), monotonic=lambda: 5000.0)["sequence"] == 0
    assert made.poll(receipt(seq=2), monotonic=lambda: 5000.1)["sequence"] == 1
    event = json.loads((out / "events" / "1.json").read_text())
    raw = (out / "events" / "1.jpg").read_bytes()
    assert event == json.loads((out / "latest.json").read_text())
    assert event["schema"] == "rosy.passive-camera-sample/1" and event["shape"] == [3, 240, 320]
    assert event["timestamp_semantics"] == "host_receive" and event["timestamp"] == 5000.1
    assert event["jpeg_sha256"] == hashlib.sha256(raw).hexdigest()  # the frame hash and true resolution
    config = {"producers": {"cameras": {"cam_top": made.descriptor}}}
    checked = {**event, "camera_id": "cam_top"}  # what learning_recording_sources.poll hands the recorder
    checked.pop("jpeg_sha256")  # the workbench checks the hash itself and drops the field
    passive_recording_helpers.validate_event(config, "cameras", checked, 5001.0)


def test_camera_frame_of_another_shape_is_refused(tmp_path):
    made = producer.CameraProducer(tmp_path / "cam_top", "top", shape=(240, 320),
                                   clock=lambda: "host-monotonic:test-boot")
    result = made.poll(receipt(shape=(480, 640)), monotonic=lambda: 5000.0)
    assert result["ok"] is False and "differs from frozen shape" in result["reason"]
    assert not list((tmp_path / "cam_top" / "events").glob("*.json"))


def test_module_has_no_arm_command_path():
    assert _violations(SOURCE) == []


def test_the_no_command_guard_bites():
    for snippet in ("os.mkfifo(path)", "fd = os.open(path, os.O_WRONLY)", "write_command('chunk-cmd')"):
        assert _violations(snippet), snippet
