"""An operator goal sentence is only read in shadow: the carry runs the rule's target and the reading is one row."""
from test_omx_cell_auto_pick import (  # reuse the simulated cell and its operating profile
    CATALOG, CONFIG, CONT2, ROI, Cell, auto, calibrated_map, cal, cell_attempts, cell_choices, cell_decisions,
    judge_seat, no_sleep, simulated_operating_profile,
)


def goal_run(tmp_path, monkeypatch, veto):
    prompts = []

    def model(prompt, images, schema):
        prompts.append(prompt)
        if "operator's goal" in prompt:
            return {"choice": -1, "reason": "none fits"}  # the shadow tries to stop the carry; it must not
        return {"choice": -1 if veto else 0, "reason": "lies flat"}

    monkeypatch.setitem(CONFIG, "decision_model", "ollama:fake-judge")  # the config is serialised: a spec, not a callable
    monkeypatch.setattr(judge_seat, "from_config", lambda spec: model)
    monkeypatch.setattr(cell_attempts, "RUN", dict(cell_attempts.RUN))
    monkeypatch.setattr(cell_decisions, "RUN", dict(cell_decisions.RUN))
    cell_attempts.start(tmp_path / "attempts.jsonl", "r1")
    cell_decisions.start(tmp_path / "decisions.jsonl", None)
    cell = Cell([CONT2])
    path = calibrated_map(tmp_path, cell)
    result = auto.run_auto(cell, CONFIG, cal.load(path), path, CATALOG, ROI, "pinky", "0.060,0.090", tmp_path,
                           cell_choices.Choices(tmp_path / "choices.json"), sleep=no_sleep, log=lambda row: None,
                           goal="the container nearest the ship")
    return result, cell_decisions.read(tmp_path / "decisions.jsonl"), prompts


def test_a_goal_reading_of_minus_one_is_logged_and_the_carry_still_places(tmp_path, monkeypatch):
    result, rows, prompts = goal_run(tmp_path, monkeypatch, veto=False)
    shadow = [r for r in rows if r["stage"] == "target_goal_shadow"]
    assert result["result"] == "placed"
    assert shadow and all(r["chosen"] == -1 and r["by"] == "shadow" for r in shadow)
    assert shadow[0]["facts"]["goal"] == "the container nearest the ship"
    assert any("operator's goal" in p for p in prompts)


def test_a_veto_that_empties_the_candidates_skips_the_goal_reading(tmp_path, monkeypatch):
    result, rows, prompts = goal_run(tmp_path, monkeypatch, veto=True)
    assert result["result"] != "placed"
    assert not [r for r in rows if r["stage"] == "target_goal_shadow"]
    assert not any("operator's goal" in p for p in prompts)
