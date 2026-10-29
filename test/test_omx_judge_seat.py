"""Measurement decides before the decision model; the model only picks among what the measurement allows."""
import importlib.util
import sys
from pathlib import Path

import pytest

OMX = Path(__file__).parents[1] / "deploy/robot/omx"
sys.path.insert(0, str(OMX))
spec = importlib.util.spec_from_file_location("judge_seat", OMX / "judge_seat.py")
m = importlib.util.module_from_spec(spec)
spec.loader.exec_module(m)


class Model:
    def __init__(self, decision):
        self.decision, self.asked = decision, []

    def __call__(self, prompt, images, schema):
        self.asked.append(schema["properties"]["decision"]["enum"])
        return {"decision": self.decision, "reason": "looks fine"}


@pytest.mark.parametrize("facts, decision", [
    ({"box_found": False, "next": "grasp"}, "abort"),               # 2026-10-25: the model chose grasp with no box
    ({"box_found": True, "fault": "stall", "next": "lift"}, "park"),
])
def test_measurement_decides_without_asking_the_model(facts, decision):
    model = Model("proceed")
    row = m.Seat(model).decide(facts)
    assert row["decision"] == decision and row["by"] == "measurement" and not model.asked


@pytest.mark.parametrize("facts", [
    {"box_found": True, "next": "grasp", "aligned": False},
    {"box_found": True, "next": "lift", "holding": False},
])
def test_proceed_is_not_offered_when_the_next_chunk_is_not_ready(facts):
    model = Model("retry")
    assert m.Seat(model).decide(facts)["decision"] == "retry"
    assert "proceed" not in model.asked[0]


def test_a_reply_outside_the_allowed_choices_is_vetoed_to_abort():
    rows = []
    row = m.Seat(Model("proceed"), log=rows.append).decide({"box_found": True, "next": "grasp", "aligned": False})
    assert row["decision"] == "abort" and row["by"] == "veto" and rows == [row]


def _broken_json(prompt, images, schema):
    return m.json.loads("{\"decision\": \"proceed\"")


def _timeout(prompt, images, schema):
    raise TimeoutError


@pytest.mark.parametrize("backend", [_broken_json, _timeout, lambda *a: ["proceed"]])
def test_no_parseable_object_reply_is_vetoed_to_abort(backend):
    rows = []
    row = m.Seat(backend, log=rows.append).decide({"box_found": True, "next": "grasp", "aligned": True})
    assert row["decision"] == "abort" and row["by"] == "veto" and rows == [row]


def test_the_model_chooses_when_the_measurement_allows_it():
    row = m.Seat(Model("proceed")).decide({"box_found": True, "next": "grasp", "aligned": True})
    assert row["decision"] == "proceed" and row["by"] == "model"


def test_knowledge_ids_in_row_and_prompt_but_unverified_never(tmp_path):
    import json
    seen = []
    path = tmp_path / "k.json"

    def entry(i, st, w):
        return {"id": i, "topic": "arm", "statement": f"s-{i}", "status": st, "evidence": [], "date": "d", "applies_when": w}

    path.write_text(json.dumps({"schema": "rosy.omx-cell-knowledge.v1", "entries": [
        entry("a", "verified", ["lift"]), entry("b", "unverified", ["lift"]), entry("c", "partial", ["map"])]}))
    model = Model("proceed")
    row = m.Seat(lambda p, i, s: seen.append(p) or model(p, i, s), knowledge=str(path)).decide(
        {"box_found": True, "next": "lift", "holding": True})
    assert row["knowledge_ids"] == ["a"] and row["knowledge_sha"] and "s-a" in seen[0]
    assert "s-b" not in seen[0] and "s-c" not in seen[0] and row["decision"] == "proceed"


def test_no_knowledge_keeps_old_row():
    row = m.Seat(Model("proceed")).decide({"box_found": True, "next": "lift", "holding": True})
    assert "knowledge_ids" not in row and "Cell knowledge" not in m.prompt({}, ["proceed"])
