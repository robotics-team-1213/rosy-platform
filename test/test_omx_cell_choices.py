"""Competing values keep their records; the best record is used, the others stay as fallbacks."""
import importlib.util
from pathlib import Path

OMX = Path(__file__).parents[1] / "deploy/robot/omx"
spec = importlib.util.spec_from_file_location("cell_choices", OMX / "cell_choices.py")
m = importlib.util.module_from_spec(spec)
spec.loader.exec_module(m)


def test_the_value_that_worked_is_chosen_and_the_others_are_kept(tmp_path):
    c = m.Choices(tmp_path / "choices.json")
    c.offer("grip", 46.6, "taught")
    c.offer("grip", 48.5, "measured")
    assert c.best("grip") == 46.6  # untried alike: the first offered
    c.outcome("grip", 46.6, False, "jaws stopped short")
    c.outcome("grip", 48.5, True)
    assert c.best("grip") == 48.5
    c.save()
    again = m.Choices(tmp_path / "choices.json")
    again.offer("grip", 46.6, "taught")  # offering again keeps the record
    assert again.best("grip") == 48.5 and len(again.data["values"]["grip"]) == 2


def test_a_taught_value_that_keeps_working_beats_a_newer_one_that_failed(tmp_path):
    c = m.Choices(tmp_path / "choices.json")
    c.offer("approach", 0.04, "taught")
    c.offer("approach", 0.03, "sim")
    for _ in range(3):
        c.outcome("approach", 0.04, True)
    c.outcome("approach", 0.03, True)
    c.outcome("approach", 0.03, False)
    assert c.best("approach") == 0.04
