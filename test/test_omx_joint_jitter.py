"""joint_jitter and jitter_replay on synthetic traces (30 Hz) and health samples (4 Hz)."""
import json
import math
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).parents[1] / "deploy/robot/omx"))
import joint_jitter as jj  # noqa: E402
import jitter_replay  # noqa: E402


def trace(seconds, shake_hz=0.0, amp=0.0, joint=2, move=False):
    rows = []
    for k in range(int(seconds * 30)):
        t = k / 30
        sent = [10.0] * 6
        if move:
            sent[joint] = 10 + 5 * t
        present = list(sent)
        present[joint] += amp * math.sin(2 * math.pi * shake_hz * t)
        rows.append({"t": 100 + t, "chunk": "hold" if not move else "goto", "target": sent, "sent": sent, "present": present})
    return rows


def hits(rows, **kw):
    return jj.shaking(trace=jj.trace_windows(rows), **kw)


def test_a_4hz_tremor_at_a_hold_is_flagged_and_a_flat_hold_or_a_lag_is_not():
    assert [j for j, _ in hits(trace(4, 4.0, 0.6))] == ["elbow_flex"] * 2
    assert hits(trace(4)) == []
    slow = trace(4, 0.5, 0.6)  # a slow swing (someone handling the arm) crosses too rarely
    assert hits(slow) == []
    lagging = trace(4, move=True)
    for r in lagging:
        r["present"][2] -= 2.0  # constant following error is not shaking
    assert hits(lagging) == []


def test_moving_windows_use_their_own_thresholds_and_tremor_rides_on_the_move():
    shaky = trace(4, 5.0, 0.5, move=True)
    assert hits(shaky) and "move" in hits(shaky)[0][1]
    assert hits(shaky, params={"jitter.move_std": 1.0}) == []


def test_missing_sent_falls_back_to_target_and_short_or_gapped_windows_are_skipped():
    rows = trace(2, 4.0, 0.6)
    for r in rows:
        r["sent"] = None
    assert hits(rows)
    assert jj.trace_windows(trace(0.5)) == []
    gapped = trace(2)
    for r in gapped[30:]:
        r["t"] += 5
    assert len(jj.trace_windows(gapped)) == 12  # the 1 s before the pause and the 1 s after: 30 ticks each


def health(n, pwm):
    return [{"sample_time": 50 + k / 4, "motors": [{"command_raw": 2048, "present_raw": 2048, "pwm": pwm(k, i)}
                                                  for i in range(6)]} for k in range(n)]


def test_health_pwm_flips_at_a_standstill_but_not_the_gripper_or_a_moving_joint():
    ripple = lambda k, i: 60 * (-1) ** k if i in (1, 5) else 5  # noqa: E731
    found = jj.shaking(health=jj.health_windows(health(16, ripple)))
    assert [j for j, _ in found] == ["shoulder_lift"]  # the gripper dithers by design
    assert jj.shaking(health=jj.health_windows(health(16, lambda k, i: 30))) == []
    moving = health(16, ripple)
    for k, s in enumerate(moving):
        s["motors"][1]["present_raw"] += 5 * k
    assert jj.shaking(health=jj.health_windows(moving)) == []


def test_replay_pairs_a_trace_with_its_health_log_and_reports_flagged_and_envelope(tmp_path):
    def motor(joint, pwm):
        return {"joint": joint, "usb_port": "/dev/serial/by-id/usb-ROBOTIS_OpenRB-150_7F31D1FE5032FF06202D-if00",
                "command_raw": 2048, "present_raw": 2048, "pwm": pwm, "pwm_limit": 300}
    rows = [{"event": "sample", "sample_time": 50 + k / 4,
             "motors": [motor(j, 60 * (-1) ** k if j == "elbow_flex" else 0) for j in jj.MOTORS]} for k in range(16)]
    rows.append({"event": "fault", "fault": "stale"})
    (tmp_path / "motor-health-1.jsonl").write_text("\n".join(json.dumps(r) for r in rows) + "\n{cut")
    (tmp_path / "trace-arm_a-1.jsonl").write_text("\n".join(json.dumps(r) for r in trace(4, 4.0, 0.6)))
    arms = jitter_replay.replay([tmp_path / "trace-arm_a-1.jsonl"], [tmp_path / "motor-health-1.jsonl"])
    arm = arms["arm_a"]
    assert arm["trace_h"] > 0 and len(arm["faults"]) == 1
    assert {f["joint"] for f in arm["flagged"]} == {"elbow_flex"} and len(arm["flagged"]) == 3
    assert arm["joints"]["elbow_flex"]["hold"]["flips_hz"][-1] >= 3
    assert arm["joints"]["shoulder_pan"]["hold"]["std"][-1] < 0.01
    assert jitter_replay.main(["--trace", str(tmp_path / "trace-*.jsonl"), "--json", str(tmp_path / "o.json")]) == 0


def test_live_window_and_active_chunk_damping_and_arm_s_replay(tmp_path):
    from omx_adapter.motion_profile import TemporalChunkEnsembler

    assert jitter_replay.ARMS.get("FF070726") == "arm_s" and jitter_replay.ARMS.get("00FB51A1") == "arm_s"
    assert jj.live_window(trace(0.5, 4.0, 0.6))["shaking"] is False  # under MIN_TICKS
    shaky = jj.live_window(trace(1.5, 5.0, 0.6, move=True))
    assert shaky["shaking"] is True and shaky["max_std"] >= 0.3 and shaky["flagged"][0]["joint"] == "elbow_flex"
    calm = jj.live_window(trace(1.5, 0.0, 0.0, move=True))
    assert calm["shaking"] is False and calm["flagged"] == []

    ens = TemporalChunkEnsembler(coeff=0.08, vmax=5.0, fps=30)
    current = [0.0, -30.0, 20.0, 45.0, 0.0, 55.0]
    next_target = [0.0, -29.8, 20.0, 45.0, 0.0, 55.0]
    lookahead = [[0.0, -29.6, 20.0, 45.0, 0.0, 55.0], [0.0, -29.4, 20.0, 45.0, 0.0, 55.0]]
    damped = jj.damp_step(ens, current, next_target, lookahead)
    assert -30.0 <= damped[1] <= -29.6 and damped[5] == 55.0
    final = jj.damp_step(ens, damped, [0.0, -29.0, 20.0, 45.0, 0.0, 55.0], [])
    assert final[1] == -29.0
