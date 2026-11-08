"""cell_why on arm_b's real stops of 2026-11-06/07, replayed in time order as the cell met them.

test/fixtures/omx_arm_b_stops_20261107.jsonl holds the chunk runs cut from the control PC's traces: the last stop of each
failed carry and four runs that met nothing (the bare-table descent, two finished pick descents, a finished held lift).
`record` is what the work record says: contact (the side view or a slower retry at the same place), free, or open (the
cause was never settled). Each run that met nothing joins the baseline before what comes after it is read, as
cell_recovery learns a carry's trace before reading its stop.
"""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "deploy/robot/omx"))
import cell_why as w  # noqa: E402

RUNS = [json.loads(line) for line in (Path(__file__).parent / "fixtures/omx_arm_b_stops_20261107.jsonl").read_text().splitlines()]


def replay(tmp_path):
    why, base, read = tmp_path / "why.jsonl", tmp_path / "free_lag.json", {}
    free = w.learn([], base)
    for run in RUNS:
        chunk = run["rows"][-1]["chunk"]
        if run["record"] == "free":
            read[run["name"]] = w.read_motion(run["rows"], free)  # read as if it had stopped there
            free = w.learn(run["rows"], base)
        else:
            read[run["name"]] = w.explain("contact", f"stopped: contact at run {chunk}", run["rows"], [], None, why, chunk, free=free)
    return read, why


def test_every_recorded_contact_ends_blocked_and_nothing_free_reads_as_a_cause(tmp_path):
    read, why = replay(tmp_path)
    settled = {t for row in read.values() for t in row.get("settles", [])}
    for run in RUNS:
        row = read[run["name"]]
        if run["record"] == "contact":  # blocked when it happened; 23:09, faster than any free descent, once 23:27 is
            assert row["hypothesis"] == "blocked" or ("leg-sky-11" in run["name"] and row["t"] in settled), run["name"]
        elif run["record"] == "free":
            assert row["verdict"] not in ("blocked", "too_fast"), run["name"]
        else:
            assert row["hypothesis"] == "unknown", run["name"]
    assert not any((r.get("motion") or r).get("verdict") == "too_fast" for r in read.values())  # contacts read too_fast: the 11-07 bug


def test_only_the_stops_whose_cause_is_still_open_go_to_a_person(tmp_path):
    read, why = replay(tmp_path)
    assert w.open_questions(why)["contact"]["times"] == sum(run["record"] == "open" for run in RUNS)
