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


def test_reinsert_is_offered_and_proceed_forbidden_when_grasp_is_unstable():
    unstable = {"box_found": True, "next": "transport", "holding": True, "stable": False}
    model = Model("reinsert")
    row = m.Seat(model).decide(unstable)
    assert row["schema_version"] == 2
    assert row["decision"] == "reinsert" and row["by"] == "model"
    assert "reinsert" in model.asked[0] and "proceed" not in model.asked[0]
    # Without a model, rules chooses reinsert over retry when reinsert is offered
    assert m.Seat(m.rules).decide(unstable)["decision"] == "reinsert"


def test_cooperate_and_from_config_support_multi_model_deliberation_and_arbiter():
    seen_prompts = []

    def proposer(prompt, images, schema):
        seen_prompts.append(prompt)
        return {"decision": "retry", "reason": "proposer suggests retry"}

    def critic_agree(prompt, images, schema):
        seen_prompts.append(prompt)
        return {"decision": "retry", "reason": "critic agrees on retry"}

    panel = m.from_config([proposer, critic_agree])
    row = m.Seat(panel).decide({"box_found": True, "next": "grasp", "aligned": False})
    assert row["decision"] == "retry" and row["consensus"] is True
    assert len(row["deliberation"]) == 2 and "Deliberation v2" in seen_prompts[1]

    # Disagreement resolved by arbiter
    def critic_disagree(prompt, images, schema):
        return {"decision": "park", "reason": "critic prefers park"}

    def arbiter(prompt, images, schema):
        return {"decision": "reinsert", "reason": "arbiter chooses reinsert to put container back"}

    panel_with_arb = m.from_config({"models": [proposer, critic_disagree], "arbiter": arbiter})
    row2 = m.Seat(panel_with_arb).decide({"box_found": True, "next": "transport", "holding": True, "stable": False})
    assert row2["decision"] == "reinsert" and row2["consensus"] is False
    assert row2["deliberation"][-1]["role"] == "arbiter"


def test_from_config_builds_heterogeneous_provider_backends():
    zai_fn = m.from_config({"provider": "zai"})
    assert zai_fn.__name__ == "zai:glm-5.3"
    ollama_fn = m.from_config({"provider": "ollama", "model": "qwen3-vl:8b-instruct"})
    assert ollama_fn.__name__ == "ollama:qwen3-vl:8b-instruct"
    cli_fn = m.from_config({"provider": "opencode"})
    assert cli_fn.__name__ == "opencode:zai-coding-plan/glm-5.3-flash"

