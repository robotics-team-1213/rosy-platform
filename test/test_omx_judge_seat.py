"""Measurement decides before the decision model; the model only picks among what the measurement allows."""
import importlib.util
from pathlib import Path

import pytest

OMX = Path(__file__).parents[1] / "deploy/robot/omx"
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


def test_remap_is_offered_only_when_the_measurement_blames_the_map():
    model = Model("remap")
    row = m.Seat(model).decide({"box_found": True, "next": "grasp", "aligned": True})
    assert row["decision"] == "abort" and row["by"] == "veto" and "remap" not in model.asked[0]
    row = m.Seat(model).decide({"box_found": True, "next": "grasp", "aligned": False, "remap": True})
    assert row["decision"] == "remap" and "proceed" not in model.asked[1]
    row = m.Seat(model).decide({"box_found": False, "next": "grasp", "remap": True})  # no map: nothing to grasp yet
    assert row["decision"] == "remap" and set(model.asked[2]) == {"remap", "park", "abort"}


def test_without_a_model_the_rules_take_the_remap_when_offered_else_retry():
    off_map = {"box_found": True, "next": "grasp", "aligned": False}
    assert m.Seat(m.rules).decide(dict(off_map, remap=True))["decision"] == "remap"
    assert m.Seat(m.rules).decide(off_map)["decision"] == "retry"
