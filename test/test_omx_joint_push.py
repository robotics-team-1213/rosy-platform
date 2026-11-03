"""joint_push on the arm_b elbow samples of 2026-11-03 13:27 (1 Hz, degrees) and on normal holds."""
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).parents[1] / "deploy/robot/omx"))
import joint_push as jp  # noqa: E402


def samples(elbow_target, elbow_present, elbow_pwm, grip=(48.8, 48.8, -40)):
    return [([0, -60, t, 45, 10, grip[0]], [0, -60, p, 45, 10, grip[1]], [0, 0, w, 0, 0, grip[2]])
            for t, p, w in zip(elbow_target, elbow_present, elbow_pwm)]


def test_the_elbow_wind_up_before_the_overload_is_seen_and_flat_holds_are_not():
    home, short = 3134 * 360 / 4096, 3123 * 360 / 4096
    wound = jp.pushing(samples([home] * 4, [short] * 4, [261, 278, 295, 312]), {"elbow_flex": 600})
    assert wound and wound[0] == "elbow_flex"
    assert jp.pushing(samples([home] * 4, [home] * 4, [30] * 4), {"elbow_flex": 600}) is None  # folded, at rest
    hover = samples([212.1] * 4, [212.9] * 4, [-110, -154, -178, -21])  # an extended hold swings, not climbs
    assert jp.pushing(hover, {"elbow_flex": 600}) is None
    assert jp.pushing(samples([home] * 4, [short] * 4, [100, 110, 120, 130]), {"elbow_flex": 600}) is None  # low


def test_jaws_stopped_short_at_load_count_only_in_a_park():
    caught = samples([90] * 2, [90] * 2, [30] * 2, grip=(43.9, 54.6, -290))
    assert jp.pushing(caught, {"gripper": 300}) is None
    assert jp.pushing(caught, {"gripper": 300}, jaws=True)[0] == "gripper"
    closing = [([90] * 5 + [48.8], [90] * 5 + [62.0], [0] * 5 + [-200]), ([90] * 5 + [48.8], [90] * 5 + [58.0], [0] * 5 + [-200])]
    assert jp.pushing(closing, {"gripper": 300}, jaws=True) is None  # still moving


def test_the_thresholds_are_cell_params():
    home, short = 3134 * 360 / 4096, 3123 * 360 / 4096
    wound = samples([home] * 4, [short] * 4, [261, 278, 295, 312])
    assert jp.pushing(wound, {"elbow_flex": 600}, params={"windup.rest_pwm": 0.9}) is None
    assert jp.pushing(wound, {"elbow_flex": 600}, params={"windup.rest_rise": 60}) is None


def test_push_replay_reports_the_catch_and_the_normal_envelope(tmp_path):
    import json
    import push_replay

    def motor(joint, cmd, pre, pwm):
        return {"joint": joint, "usb_port": "/dev/serial/by-id/usb-ROBOTIS_OpenRB-150_7F31D1FE5032FF061D2D-if00",
                "command_raw": cmd, "present_raw": pre, "pwm": pwm, "pwm_limit": 600 if joint == "elbow_flex" else 300}
    rows = []
    for k in range(10):  # a flat hold, then the elbow winds up 1 deg short of home
        pwm = 30 if k < 4 else 261 + 17 * (k - 4)
        rows.append({"event": "sample", "sample_time": 100.0 + k, "motors": [
            motor(j, 2048, 2048, 0) if j != "elbow_flex" else motor(j, 3134, 3123 if k >= 4 else 3134, pwm)
            for j in jp.MOTORS]})
    rows.append({"event": "fault", "fault": "Hardware_Error_Status id 13"})
    log = tmp_path / "motor-health-1.jsonl"
    log.write_text("\n".join(json.dumps(r) for r in rows) + "\n{cut")
    arms = push_replay.replay([log])
    arm = arms["FF061D2D"]
    assert len(arm["hits"]) == 1 and "elbow_flex" in arm["hits"][0]["reason"] and len(arm["faults"]) == 1
    assert arm["envelope"]["shoulder_pan"]["rise"] == 0
