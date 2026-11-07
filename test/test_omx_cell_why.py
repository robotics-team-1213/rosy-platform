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
    return lambda prompt, images, schema: {"hypothesis": hypothesis, "reason": "seen", "missing": list(missing)}


@pytest.mark.parametrize("sent, present", [(3.52, 1.71), (1.98, 1.25), (2.07, 1.14)])
def test_a_joint_that_kept_moving_is_not_called_too_fast(sent, present):
    """Recorded descents the work record calls real contact, 2026-11-06 and 07: the wrist kept moving at these speeds."""
    row = w.read_motion(lift(present, sent_speed=sent))
    assert row["verdict"] == "undetermined" and row["joint"] == "wrist_flex" and row["present_units_s"] == present


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
    moving = w.explain("lift_stall", "x at run lift_pick", lift(1.5), [], answers("snagged"), tmp_path / "why.jsonl")
    assert moving["hypothesis"] == "snagged" and moving["by"] == "model"  # recovery follows only by == measurement


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


def test_another_chunks_stop_is_no_repeat(tmp_path):
    path = tmp_path / "why.jsonl"
    w.explain("lift_stall", "stopped: released after a stop at run lift_place", [{**r, "chunk": "lift_place"} for r in FAST], [], None, path)
    assert w.explain("lift_stall", STALL, SLOW, [], None, path)["motion"]["verdict"] == "undetermined"


def test_a_stop_keeps_the_pwm_it_was_recorded_with():
    rows = [{**r, "pwm": {"wrist_flex": 212}} for r in FAST]
    assert w.read_motion(rows)["pwm_end"] == 212 and w.read_motion(FAST)["pwm_end"] is None
