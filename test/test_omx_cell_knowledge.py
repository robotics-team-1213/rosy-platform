"""Cell knowledge: validated file, selection by step, unverified never selected."""
import copy
import importlib.util
import json
from pathlib import Path

import pytest

OMX = Path(__file__).parents[1] / "deploy/robot/omx"
spec = importlib.util.spec_from_file_location("cell_knowledge", OMX / "cell_knowledge.py")
k = importlib.util.module_from_spec(spec)
spec.loader.exec_module(k)
EXAMPLE = OMX / "cell-knowledge.example.json"


def test_example_loads_and_has_policy_entries():
    data = k.load(EXAMPLE)
    assert len(data["sha"]) == 12
    assert {e["id"] for e in data["entries"]} >= {"policy-measure-first", "policy-safety", "policy-self-resolve"}


@pytest.mark.parametrize("change", [
    lambda e: e.update(status="maybe"), lambda e: e.update(topic="cooking"), lambda e: e.update(statement=" "),
    lambda e: e.update(applies_when=[]), lambda e: e.pop("evidence"), lambda e: e.update(evidence="a log"),
])
def test_bad_entries_are_rejected(change):
    data = json.loads(EXAMPLE.read_text(encoding="utf8"))
    change(data["entries"][0])
    with pytest.raises(ValueError):
        k.validate(data)


def test_duplicate_id_and_wrong_schema_rejected():
    data = json.loads(EXAMPLE.read_text(encoding="utf8"))
    data["entries"].append(copy.deepcopy(data["entries"][0]))
    with pytest.raises(ValueError):
        k.validate(data)
    with pytest.raises(ValueError):
        k.validate({"schema": "other", "entries": []})


def test_selection_by_step_never_unverified_and_capped():
    data = k.load(EXAMPLE)

    def ids(step):
        return {e["id"] for e in k.select(data, {"next": step}, limit=99)}

    assert "wrist-sag-extended" in ids("lift") and "wrist-sag-extended" not in ids("idle")
    assert "container-size" in ids("grasp")  # grasp pulls approach entries
    assert "policy-safety" in ids("idle") and "container-true-centre" not in ids("grasp")
    assert len(k.select(data, {"next": "grasp"})) <= 6
    assert all(len(e["statement"]) <= 100 for e in k.select(data, {"next": "grasp"}, chars=100))
    assert k.select(None, {"next": "grasp"}) == []
