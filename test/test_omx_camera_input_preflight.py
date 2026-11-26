import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "deploy/robot/omx"))

from cell_camera_input_preflight import binding_status, collect


def test_three_roles_must_advance():
    def frame(role, *, previous, **_):
        seq = previous["source_seq"] + 1 if previous else 4
        return {"source_seq": seq, "source_stamp": float(seq), "camera": role}

    evidence = collect("arm_b", frame, sleep=lambda _: None)
    assert evidence["camera_source_ready"]
    assert set(evidence["cameras"]) == {"top", "side", "arm_b_wrist"}
    assert not evidence["motion_permission"]


def test_missing_wrist_is_reported_without_substitution():
    def frame(role, *, previous, **_):
        if role == "arm_a_wrist":
            raise ValueError("camera frame HTTP 503; no fresh JPEG")
        seq = previous["source_seq"] + 1 if previous else 4
        return {"source_seq": seq, "source_stamp": float(seq), "camera": role}

    evidence = collect("arm_a", frame, sleep=lambda _: None)
    assert not evidence["camera_source_ready"]
    assert evidence["cameras"]["top"]["ok"]
    assert "HTTP 503" in evidence["cameras"]["arm_a_wrist"]["error"]


def test_stale_sequence_or_source_stamp_blocks():
    def frame(role, *, previous, **_):
        if not previous:
            return {"source_seq": 4, "source_stamp": 2.0, "camera": role}
        return {"source_seq": 4 if role == "top" else 5, "source_stamp": 2.0, "camera": role}

    evidence = collect("arm_b", frame, sleep=lambda _: None)
    assert not evidence["camera_source_ready"]
    assert all(not camera["ok"] for camera in evidence["cameras"].values())


def test_a_live_side_role_can_still_have_the_wrong_camera():
    registry = {"cameras": [{"role": "side", "device": "camera", "usb_id": "4c4a:4a55", "topic": "/side"}]}
    producers = {"camera-side": {"ROSY_CAMERA_DEVICE": "camera", "ROSY_CAMERA_TOPIC": "/side"}}
    facts = {"camera": {"id": "8086:0b07"}}
    args = ("side",), registry, producers, facts, {"side": "/side"}
    assert binding_status(*args, realpath=lambda path: path) == {"side": "binding_mismatch"}
    facts["camera"]["id"] = "4c4a:4a55"
    assert binding_status(*args, realpath=lambda path: path) == {"side": "matched"}
    registry["cameras"].append({"role": "arm_s_top", "device": "camera"})
    assert binding_status(*args, realpath=lambda path: path) == {"side": "binding_mismatch"}
