"""cell_why: the trace says blocked only when a joint stood still, the model adds what the trace cannot, and an unknown does not repeat quietly."""
import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "deploy/robot/omx"))
import cell_why as w  # noqa: E402


def lift(present_speed, sent_speed=3.0, seconds=1.45, droop=0.54):
    """The wrist_flex (joint 3) under a rising command, at 30 Hz. The 2026-11-07 stall: about 3 sent, about 1.5 present."""
    rows = []
    for i in range(int(seconds * 30)):
        t = i / 30
        rows.append({"t": 100 + t, "chunk": "lift_pick", "sent": [-35.6, 1.1, 16.3, 32.6 + sent_speed * t, 11.3, 48.8],
                     "present": [-35.1, 1.1, 16.3, 32.6 - droop + present_speed * t, 11.3, 53.8]})
    return rows


def answers(hypothesis="too_fast", missing=("frames at the stop",)):
    def ask(prompt, images, schema):
        assert list(schema["properties"])[0] == "seen"  # what is shown comes before the pick
        return {"seen": "arm folded", "hypothesis": hypothesis, "reason": "seen", "missing": list(missing)}
    return ask


@pytest.mark.parametrize("sent, present", [(3.52, 1.71), (1.98, 1.25), (2.07, 1.14)])
def test_a_joint_that_kept_moving_is_not_called_too_fast(sent, present):
    """Recorded descents the work record calls real contact, 2026-11-06 and 07: the wrist kept moving at these speeds."""
    row = w.read_motion(lift(present, sent_speed=sent))
    assert row["verdict"] == "undetermined" and row["joint"] == "wrist_flex" and row["present_units_s"] == present


def descent(present, sent_speed, chunk="descend_pick"):
    return [{**r, "chunk": chunk} for r in lift(present, sent_speed=sent_speed)]


@pytest.mark.parametrize("rows, verdict", [
    (descent(1.25, 1.98), "blocked"),  # 11-07 00:17: the bare-table descent at this speed lagged 0.64, this one reached 1.6
    (descent(1.71, 3.52), "undetermined"),  # 11-06 23:09: faster than any descent measured with nothing in the way
    (descent(1.25, 1.98, chunk="descend_place"), "undetermined"),  # no baseline for the place descent
    (descent(1.5, 1.98), "undetermined"),  # lag 1.2: under 1.8 times what a free descent lagged
])
def test_a_stop_is_read_against_the_same_chunk_with_nothing_in_the_way(rows, verdict):
    assert w.read_motion(rows)["verdict"] == verdict


HELD_LIFT = lift(2.3, sent_speed=3.58)  # 2026-11-07 02:15: a held lift stopped at 3.58 units/s, lag about 2.3
RAN_ON = {"lift_pick": {"wrist_flex": [[3.80, 2.10, 1.0], [3.70, 2.20, 2.0]]}}  # held lifts that ran to their end


@pytest.mark.parametrize("free, verdict", [
    (RAN_ON, "too_fast"),  # as fast and as laggy with nothing in the way: the command outran the joint
    ({"lift_pick": {"wrist_flex": [[3.80, 2.10, 1.0]]}}, "undetermined"),  # one run is not a baseline
    ({"lift_pick": {"wrist_flex": [[3.0, 2.10, 1.0], [3.1, 2.2, 2.0]]}}, "undetermined"),  # slower runs say nothing of this speed
    ({"lift_pick": {"wrist_flex": [[3.80, 1.0, 1.0], [3.70, 1.1, 2.0]]}}, "blocked"),  # free runs lag half as much
    ({"lift_pick": {"elbow_flex": [[3.80, 2.10, 1.0], [3.70, 2.20, 2.0]]}}, "undetermined"),  # another joint's runs
])
def test_a_stop_is_read_against_the_finished_runs_of_its_chunk(free, verdict):
    assert w.read_motion(HELD_LIFT, free)["verdict"] == verdict


def test_finished_runs_are_learned_once_and_stops_are_not(tmp_path):
    finished = lift(2.9, sent_speed=3.0)  # lag ends at 0.68: ran on
    stopped = [{**r, "t": r["t"] + 10} for r in HELD_LIFT]  # lag ends at 2.3: a stop
    rows = finished + [{"t": 102, "chunk": "park", "sent": [0] * 6, "present": [0] * 6}] + stopped
    path = tmp_path / "free_lag.json"
    free = w.learn(rows, path)
    runs = free["lift_pick"]["wrist_flex"]
    assert len(runs) == 1 and runs[0][0] == pytest.approx(3.0, abs=0.01) and runs[0][1] < 1.0
    assert w.learn(rows, path)["lift_pick"]["wrist_flex"] == runs  # the same trace again adds nothing
    assert free["descend_pick"]["wrist_flex"] == w.SEED["descend_pick"]["wrist_flex"]  # the seed stays


def test_a_joint_that_nearly_stands_was_blocked():
    assert w.read_motion(lift(0.42, sent_speed=2.09))["verdict"] == "blocked"  # the slowed descent of 2026-11-06 23:30


def test_a_still_command_or_a_steady_lag_tells_nothing():
    assert w.read_motion(lift(0.0, sent_speed=0.0))["verdict"] == "undetermined"
    assert w.read_motion(lift(3.0))["verdict"] == "undetermined"  # following at speed, the lag did not grow
    assert w.read_motion([])["verdict"] == "undetermined"


def test_the_last_stretch_of_the_named_chunk_is_read_and_the_result_names_it():
    assert w.chunk_of("stopped: released after a stop at run lift_pick") == "lift_pick"
    assert w.chunk_of("stopped: holding after a stop at goto above_place") == "goto above_place"
    assert w.chunk_of("stopped: fault") is None
    rows = [{"chunk": "lift_pick", "n": 1}, {"chunk": None}, {"chunk": "lift_pick", "n": 2}, {"chunk": "lift_pick", "n": 3}, {"chunk": "park"}]
    assert [r["n"] for r in w.last_run(rows, "lift_pick")] == [2, 3] and w.last_run(rows, "goto") == []


def test_the_model_cannot_overrule_the_measurement_and_a_disagreement_stays_open(tmp_path):
    path = tmp_path / "why.jsonl"
    row = w.explain("lift_stall", "stopped: released after a stop at run lift_pick", lift(0.1), [], answers("too_fast"), path)
    assert row["hypothesis"] == "blocked" and row["by"] == "measurement" and row["disagree"]
    assert w.open_questions(path)["lift_stall"]["missing"] == ["frames at the stop"]


def test_where_the_measurement_cannot_tell_the_model_may(tmp_path):
    row = w.explain("misaligned", "stopped: misaligned", [], ["img"], answers("wrong_position"), tmp_path / "why.jsonl")
    assert row["hypothesis"] == "wrong_position" and row["by"] == "model" and not row["repeat_unknown"]

@pytest.mark.parametrize("said", sorted(w.ARM_CAUSES))
def test_why_an_arm_stopped_is_the_measurements_and_a_models_guess_stays_advice(tmp_path, said):
    """11-07: no model told contact from speed or a snag in 13 recorded failures; each guessed differently."""
    moving = w.explain("lift_stall", "x at run lift_pick", lift(1.5), [], answers(said), tmp_path / "why.jsonl")
    assert (moving["hypothesis"], moving["by"], moving["model"]["hypothesis"]) == ("unknown", "nobody", said)
    assert w.open_questions(tmp_path / "why.jsonl")["lift_stall"]["missing"] == ["frames at the stop"]


def test_no_model_or_a_bad_answer_leaves_the_measurement_or_unknown(tmp_path):
    path = tmp_path / "why.jsonl"
    assert w.explain("lift_stall", "x at run lift_pick", lift(0.1), [], None, path)["hypothesis"] == "blocked"
    bad = w.explain("calibrate", "stopped: pivot", [], [], answers("a ghost"), path)
    assert bad["hypothesis"] == "unknown" and bad["by"] == "nobody" and "unavailable" in bad["model"]["reason"]
    def dead(*a):
        raise OSError("no route")
    assert w.explain("calibrate", "stopped: pivot", [], [], dead, path)["repeat_unknown"]


def test_an_unknown_kind_repeats_only_once_quietly_and_carries_what_is_missing(tmp_path):
    path = tmp_path / "why.jsonl"
    first = w.explain("other", "stopped: gripper melted", [], [], answers("unknown", ["a side frame"]), path)
    second = w.explain("other", "stopped: gripper melted", [], [], answers("unknown", ["a current trace"]), path)
    assert not first["repeat_unknown"] and second["repeat_unknown"]
    assert w.open_questions(path)["other"] == {"times": 2, "missing": ["a current trace", "a side frame"], "last": "stopped: gripper melted"}
    assert not w.explain("other", "stopped: other", [], [], answers("snagged"), tmp_path / "other.jsonl")["repeat_unknown"]


def test_an_unknown_of_an_earlier_carry_does_not_count_against_this_one(tmp_path):
    path = tmp_path / "why.jsonl"
    w.explain("calibrate", "stopped: pivot", [], [], None, path)
    assert not w.explain("calibrate", "stopped: pivot", [], [], None, path, since=9e12)["repeat_unknown"]
    assert w.explain("calibrate", "stopped: pivot", [], [], None, path)["repeat_unknown"]


def test_a_cut_last_line_and_a_tick_without_a_command_are_left_out(tmp_path):
    path = tmp_path / "trace.jsonl"
    path.write_text(json.dumps(lift(1.5)[0]) + "\n" + json.dumps({"t": 1, "chunk": "x", "sent": None, "present": [0] * 6}) + '\n{"t": 2, "chu')
    assert len(w.read_trace(path)) == 1


def test_the_row_is_kept_and_the_past_reaches_the_prompt(tmp_path):
    path, seen = tmp_path / "why.jsonl", []
    w.explain("calibrate", "stopped: pivot", [], [], answers("camera_or_map"), path)
    w.explain("calibrate", "stopped: pivot", [], [], lambda p, i, s: seen.append(p) or {"hypothesis": "unknown", "reason": "", "missing": []}, path)
    assert "camera_or_map" in seen[0] and json.loads(path.read_text().splitlines()[0])["kind"] == "calibrate"


def stop_of(sent_speed, present_speed, seconds, start=0.0):
    """A lift that ended at about the same joint position whatever its speed, when the seconds are chosen for it."""
    rows = lift(present_speed, sent_speed=sent_speed, seconds=seconds)
    for row in rows:
        row["sent"][1] += start
        row["present"][1] += start
    return rows


STALL = "stopped: released after a stop at run lift_pick"
FAST, SLOW = stop_of(3.0, 1.5, 1.45), stop_of(1.8, 1.2, 1.81)  # both end near wrist_flex 34.2


def test_a_slower_retry_that_stops_at_the_same_place_excludes_speed(tmp_path):
    path = tmp_path / "why.jsonl"
    first = w.explain("lift_stall", STALL, FAST, [], None, path)
    assert first["motion"]["verdict"] == "undetermined" and first["by"] == "nobody"
    second = w.explain("lift_stall", STALL, SLOW, [], None, path)
    assert second["hypothesis"] == "blocked" and second["by"] == "measurement" and "same place" in second["motion"]["why"]


@pytest.mark.parametrize("name,retry,since", [
    ("same speed: a stop repeats at the same place whatever its cause", FAST, 0.0),
    ("faster", None, 0.0),
    ("another plan", stop_of(1.8, 1.2, 1.81, start=5.0), 0.0),
    ("slower and went further", stop_of(1.8, 1.2, 4.5), 0.0),
    ("the earlier stop was another carry's", SLOW, 9e12),
])
def test_a_repeat_says_nothing_unless_it_really_is_slower_at_the_same_place(tmp_path, name, retry, since):
    path = tmp_path / "why.jsonl"
    if retry is None:  # the faster one second
        w.explain("lift_stall", STALL, SLOW, [], None, path)
        retry = FAST
    else:
        w.explain("lift_stall", STALL, FAST, [], None, path)
    assert w.explain("lift_stall", STALL, retry, [], None, path, since=since)["motion"]["verdict"] == "undetermined", name


def from_below(offset, seconds, sent_speed=3.0):
    """The same lift started `offset` lower on wrist_flex and run long enough to reach FAST's stop."""
    rows = lift(1.5, sent_speed=sent_speed, seconds=seconds)
    for row in rows:
        row["sent"][3] -= offset
        row["present"][3] -= offset
    return rows


@pytest.mark.parametrize("retry, verdict", [
    (from_below(3.0, 3.43), "blocked"),  # 11-07 00:17 -> 01:15: started 12 mm higher, stopped at the same FK z
    (from_below(3.0, 3.43, sent_speed=3.6), "undetermined"),  # faster: more lag in less time says nothing
    (from_below(3.0, 2.0), "undetermined"),  # stopped elsewhere
])
def test_a_stop_at_the_same_place_from_another_start_excludes_speed(tmp_path, retry, verdict):
    path = tmp_path / "why.jsonl"
    w.explain("lift_stall", STALL, FAST, [], None, path)
    assert w.explain("lift_stall", STALL, retry, [], None, path)["motion"]["verdict"] == verdict


def test_a_measured_block_at_the_same_place_settles_the_earlier_unknown(tmp_path):
    path = tmp_path / "why.jsonl"
    first = w.explain("lift_stall", STALL, FAST, [], None, path)
    assert w.open_questions(path)["lift_stall"]["times"] == 1
    later = w.explain("lift_stall", STALL, SLOW, [], None, path)
    assert later["hypothesis"] == "blocked" and later["settles"] == [first["t"]] and w.open_questions(path) == {}
    other, elsewhere = tmp_path / "other.jsonl", from_below(5.0, 1.45)
    for row in elsewhere:
        row["present"][3] = row["present"][3] - 1.4 * (row["t"] - 100)  # nearly still: blocked, 5 below FAST's stop
    w.explain("lift_stall", STALL, FAST, [], None, other)
    elsewhere_row = w.explain("lift_stall", STALL, elsewhere, [], None, other)
    assert elsewhere_row["hypothesis"] == "blocked" and elsewhere_row["settles"] == []


def test_another_chunks_stop_is_no_repeat(tmp_path):
    path = tmp_path / "why.jsonl"
    w.explain("lift_stall", "stopped: released after a stop at run lift_place", [{**r, "chunk": "lift_place"} for r in FAST], [], None, path)
    assert w.explain("lift_stall", STALL, SLOW, [], None, path)["motion"]["verdict"] == "undetermined"


def test_a_stop_keeps_the_pwm_it_was_recorded_with():
    rows = [{**r, "pwm": {"wrist_flex": 212}} for r in FAST]
    assert w.read_motion(rows)["pwm_end"] == 212 and w.read_motion(FAST)["pwm_end"] is None
