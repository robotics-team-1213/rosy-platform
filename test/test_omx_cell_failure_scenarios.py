"""The failure scenarios run in parallel, each on its own ledger; real failures become scenarios; the ledger only reorders the table."""
import json
import sys
from pathlib import Path

import pytest

pytest.importorskip("numpy")
pytest.importorskip("cv2")
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "deploy/robot/omx"))
import cell_choices  # noqa: E402
import cell_diagnose as dg  # noqa: E402
import cell_failure_scenarios as fs  # noqa: E402
import cell_recovery as rc  # noqa: E402


def test_every_scenario_passes_in_parallel():
    out = fs.run_all(fs.SCENARIOS)
    assert out["failed"] == [] and out["passed"] == len(fs.SCENARIOS)


def test_a_wrong_expectation_is_reported_not_hidden():
    wrong = dict(fs.SCENARIOS[1], actions=["observe_again", "done"])
    assert [r["name"] for r in fs.run_all([wrong])["failed"]] == [wrong["name"]]


def test_going_on_past_a_scenarios_end_is_a_failure_not_a_crash():
    short = dict(fs.SCENARIOS[1], rounds=fs.SCENARIOS[1]["rounds"][:1])
    assert fs.run_all([short])["failed"][0]["result"] == "tried again past the scenario's end"


def test_recovery_refuses_a_dry_run_rather_than_moving_the_arm():
    with pytest.raises(SystemExit):
        rc.main(["--config", "c", "--catalog", "k", "--roi", "0", "0", "1", "1", "--dest", "d", "--dry-run", "--commissioning", "--person-at-switch"])


def test_the_scenarios_cover_every_cause_in_the_table():
    causes = {dg.attempt_cause(r[0], r[1]) for s in fs.SCENARIOS for r in s["rounds"]}
    assert set(dg.RECOVERY) <= causes


def test_a_failed_action_loses_its_place_and_a_working_one_keeps_it(tmp_path):
    choices = cell_choices.Choices(tmp_path / "c.json")
    can = {"push_clear", "observe_again"}
    assert rc.options("misaligned", can, choices)[0] == "observe_again"  # untried: the table's order
    fs.replay([("stopped: misaligned", False, True), ("stopped: fault", False, True)], choices)
    assert rc.options("misaligned", can, choices) == ["push_clear", "observe_again", "ask_person"]
    fs.replay([("stopped: misaligned", False, True), ("placed", False, True)], choices)
    assert next(c for c in choices.data["values"]["recovery.misaligned"] if c["value"] == "push_clear")["ok"] == 1
    assert cell_choices.Choices(tmp_path / "c.json").data["values"]["recovery.misaligned"]  # saved


def test_what_the_trace_read_goes_before_the_record_but_stays_inside_the_table(tmp_path):
    choices = cell_choices.Choices(tmp_path / "c.json")
    fs.replay([(fs.STALL, False, True, "too_fast"), ("stopped: fault", False, True)], choices)  # slow_down has a bad record now
    can = {"push_clear", "observe_again", "slow_down"}
    assert rc.options("lift_stall", can, choices, "slow_down")[0] == "slow_down"
    assert rc.options("lift_stall", can, choices)[0] == "push_clear"
    assert rc.options("other", can, choices, "slow_down") == ["ask_person"]


def test_a_real_trace_and_the_table_agree_end_to_end(tmp_path):
    import cell_why as w
    trace = [{"t": 100 + i / 30, "chunk": "lift_pick", "sent": [0, 0, 0, 32.6 + 3 * i / 30, 0, 48.8], "present": [0, 0, 0, 32.1 + 1.5 * i / 30, 0, 53.8]} for i in range(44)]
    world = fs.World([(fs.STALL, False, True), ("placed", False, True)])
    out = rc.carry(world.frame, world.pick, world.push, expected_px=lambda a: [], emit=lambda *a: None, slow=lambda: True,
                   explain=lambda cause, o: w.explain(cause, o["result"], trace, [], None, tmp_path / "why.jsonl"))
    # A wrist that kept moving names no cause, so the table's own first action stands and the row says nobody knows.
    assert out["result"] == "placed" and out["rounds"][0]["action"] == "slow_down" and out["rounds"][0]["why"] == "unknown"


def test_the_ledger_never_turns_a_hard_stop_into_a_retry(tmp_path):
    choices = cell_choices.Choices(tmp_path / "c.json")
    for name in ("recovery.other", "recovery.held_stop"):
        choices.offer(name, "observe_again", "a bad row")
        choices.outcome(name, "observe_again", True)
    assert rc.options("other", {"push_clear", "observe_again"}, choices) == ["ask_person"]
    assert rc.options("held_stop", {"push_clear", "observe_again"}, choices) == ["ask_person"]


def test_what_only_a_person_could_answer_is_listed_with_the_raw_result(tmp_path):
    choices = cell_choices.Choices(tmp_path / "c.json")
    fs.replay([("stopped: fault", False, True)], choices)
    assert rc.unsolved(choices) == {"other": {"asked": 1, "last": "stopped: fault"}}


def test_real_failures_become_scenarios_and_a_new_kind_lands_on_the_list(tmp_path):
    rows = [{"stage": "recovery", "facts": {"result": fs.STALL, "pile_moved": []}},
            {"stage": "recovery", "facts": {"result": fs.STALL, "pile_moved": []}},  # the same failure once
            {"stage": "recovery", "facts": {"result": "placed", "pile_moved": []}},
            {"stage": "verify", "facts": {"result": "stopped: fault"}},
            {"stage": "recovery", "facts": {"result": "stopped: gripper melted", "pile_moved": []}}]
    path = tmp_path / "decisions.jsonl"
    path.write_text("\n".join(json.dumps(r) for r in rows))
    scenarios = fs.from_decisions(path)
    assert len(scenarios) == 2 and scenarios[0]["actions"] == ["slow_down", "done"]
    out = fs.run_all(scenarios)
    assert out["failed"] == [] and out["unsolved"] == {"other": {"asked": 1, "last": "stopped: gripper melted"}}
