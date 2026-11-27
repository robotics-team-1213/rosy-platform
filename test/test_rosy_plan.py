"""Plan schema and validator: closed fields, no metres, targets only from the cited pack, no repeat after failure."""
from __future__ import annotations

import copy
import json
import sys
from pathlib import Path
from typing import Any

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools" / "remote"))

import rosy_cli as cli  # noqa: E402
import rosy_observe as obs  # noqa: E402
import rosy_plan as pl  # noqa: E402

CASES = ROOT / "test" / "fixtures" / "llm_loop"


def pack_of(name: str, **raw_patch: Any) -> dict[str, Any]:
    raw = json.loads((CASES / f"{name}.json").read_text(encoding="utf-8"))["raw"]
    raw.update(raw_patch)
    return obs.assemble(raw)


def plan(pack: dict[str, Any], verb: str = "pick", **step: Any) -> dict[str, Any]:
    base = {"verb": verb, "arm": pack["arm"], "reason": "test"}
    return {"observation_id": pack["observation_id"], "step": {**base, **step}}


def check(p: dict[str, Any], pack: dict[str, Any], **kw: Any) -> list[str]:
    kw.setdefault("history", [])
    res = pl.validate_plan(p, pack, now=pack["observed_at"] + 1, **kw)
    assert res["ok"] == (not res["errors"])
    return [e["code"] for e in res["errors"]]


def test_schema_properties_match_the_fields_the_validator_accepts():
    props = pl.PLAN_SCHEMA["properties"]["step"]["properties"]
    assert set(props) == {"verb", "arm", "target", "dest", "reason"}
    assert props["verb"]["enum"] == list(pl.VERBS) and pl.PLAN_SCHEMA["additionalProperties"] is False
    assert pl.PLAN_SCHEMA["properties"]["step"]["additionalProperties"] is False


def test_good_pick_of_a_planned_candidate_and_idle_pass():
    pack = pack_of("belt_middle_box")
    assert check(plan(pack, target="c1", dest="pallet"), pack) == []
    assert check(plan(pack, "idle"), pack) == [] and check(plan(pack, "ask_human"), pack) == []


@pytest.mark.parametrize("extra, code", [
    ({"x": 0.12}, "FORBIDDEN_FIELD"), ({"pick_x": 0.1}, "FORBIDDEN_FIELD"), ({"offset_mm": 5}, "FORBIDDEN_FIELD"),
    ({"operator": "someone"}, "FORBIDDEN_FIELD"), ({"proposer": "a"}, "FORBIDDEN_FIELD"), ({"reviewed_auto": True}, "FORBIDDEN_FIELD"),
    ({"person_at_switch": True}, "FORBIDDEN_FIELD"), ({"colour": "red"}, "UNKNOWN_FIELD"),
])
def test_metres_and_authority_fields_are_refused_by_name(extra, code):
    pack = pack_of("belt_middle_box")
    p = plan(pack, target="c1", dest="pallet")
    p["step"].update(extra)
    assert check(p, pack) == [code]
    q = plan(pack, target="c1", dest="pallet")
    q.update(extra)
    assert check(q, pack) == [code]


def test_targets_must_come_from_the_pack():
    pack = pack_of("belt_middle_box")
    assert check(plan(pack, target="c9", dest="pallet"), pack) == ["TARGET_NOT_IN_PACK"]
    assert check(plan(pack, target="temp_plate_b-l1", dest="pallet"), pack) == ["SITE_NOT_SUGGESTED"]
    assert check(plan(pack, target="mars", dest="pallet"), pack) == ["UNKNOWN_SITE"]
    assert check(plan(pack, target="c1", dest="mars"), pack) == ["UNKNOWN_DEST"]
    assert check(plan(pack, target={"anchor": "belt", "at_px": [0.18, 0.1]}, dest="pallet"), pack) == ["BAD_TARGET"]
    assert check(plan(pack, target={"anchor": "belt", "at_px": [300, 100]}, dest="pallet"), pack) == ["BAD_TARGET"]  # pick takes no pixel


def test_a_refused_candidate_only_allows_what_the_pack_suggested():
    edge = pack_of("belt_edge_box")
    assert check(plan(edge, target="c1", dest="pallet"), edge) == ["TARGET_REFUSED"]
    assert check(plan(edge, "push", target="c1"), edge) == []
    assert pl.validate_plan(plan(edge, "push", target="c1"), edge)["needs_human_approval"] is True
    assert check(plan(edge, "push", target="c1", dest="pallet"), edge) == ["BAD_DEST"]
    wb = pack_of("plate_b_workbench")
    assert check(plan(wb, target="c1", dest="pallet"), wb) == ["UNTRUSTED_SOURCE"]


def test_retier_site_is_allowed_only_when_the_pack_suggested_it():
    pack = pack_of("tier_hint_base_site")
    assert check(plan(pack, target="temp_plate_a-l1", dest="pallet"), pack) == []
    assert check(plan(pack, target="temp_plate_a-l2", dest="pallet"), pack) == ["SITE_NOT_SUGGESTED"]
    assert check(plan(pack, target="c1", dest="pallet"), pack) == ["TARGET_REFUSED"]


def test_free_pick_needs_a_pixel_inside_a_trusted_source_region_and_a_live_verb():
    pack = pack_of("belt_edge_box")
    ok = plan(pack, "free_pick", target={"anchor": "belt", "at_px": [330, 100]}, dest="pallet")
    assert check(ok, pack) == []
    assert check(plan(pack, "free_pick", target={"anchor": "belt", "at_px": [10, 10]}, dest="pallet"), pack) == ["PIXEL_NOT_IN_SITE"]
    assert check(plan(pack, "free_pick", target={"anchor": "plate_b", "at_px": [200, 300]}, dest="pallet"), pack) == ["PIXEL_NOT_IN_SITE"]
    assert check(plan(pack, "free_pick", target={"anchor": "pallet", "at_px": [300, 200]}, dest="pallet"), pack) == ["UNKNOWN_SITE"]
    assert check(plan(pack, "free_pick", target={"anchor": "belt", "at_px": [330, 100], "x": 1}, dest="pallet"), pack) == ["BAD_TARGET"]
    old = pack_of("belt_edge_box", probe={"at_px": {"status": 400, "text": "\"unknown params ['at_px']\""}, "push": {"status": 400, "text": "x"}})
    assert check(plan(old, "free_pick", target={"anchor": "belt", "at_px": [330, 100]}, dest="pallet"), old) == ["VERB_NOT_LIVE"]


def test_arm_s_has_no_free_pick_and_a_dark_pack_allows_only_idle_or_ask_human():
    s = pack_of("camera_moved")
    assert check(plan(s, "pick", target="c1", dest="belt"), s) == ["UNOBSERVABLE"]
    assert check(plan(s, "ask_human"), s) == [] and check(plan(s, "idle"), s) == []
    raw = json.loads((CASES / "belt_middle_box.json").read_text(encoding="utf-8"))["raw"]
    stamp = raw["frames"]["top"]
    raw.update(arm="arm_s", frames={"arm_s_top": stamp, "arm_s_wrist": stamp}, dry_runs=[])
    seen = obs.assemble(raw)
    assert seen["observable"] and seen["live_verbs"]["free_pick"] is False
    assert "VERB_NOT_LIVE" in check(plan(seen, "free_pick", target={"anchor": "belt", "at_px": [400, 150]}, dest="pinky"), seen)


def test_observation_id_age_arm_and_readiness_are_checked():
    pack = pack_of("belt_middle_box")
    good = plan(pack, target="c1", dest="pallet")
    assert pl.validate_plan({**good, "observation_id": "deadbeef"}, pack)["errors"][0]["code"] == "OBSERVATION_MISMATCH"
    assert [e["code"] for e in pl.validate_plan(good, pack, now=pack["observed_at"] + 31)["errors"]] == ["OBSERVATION_STALE"]
    assert check(plan(pack, target="c1", dest="pallet", arm="arm_a"), pack) == ["ARM_MISMATCH"]
    held = pack_of("incident_held_planned_box")
    assert check(plan(held, target="c1", dest="pallet"), held) == ["ARM_NOT_READY"]
    assert check(plan(held, "idle"), held) == []


def test_idle_and_ask_human_take_no_target_and_need_a_reason():
    pack = pack_of("belt_middle_box")
    assert check(plan(pack, "idle", target="c1"), pack) == ["BAD_TARGET"]
    p = plan(pack, "ask_human")
    p["step"]["reason"] = " "
    assert check(p, pack) == ["BAD_REASON"]
    assert check({"observation_id": "x"}, pack) == ["BAD_PLAN"] and check("pick c1", pack) == ["BAD_PLAN"]
    assert check(plan(pack, "teleport"), pack) == ["BAD_VERB"]


def test_second_identical_step_after_a_failure_is_refused():
    pack = pack_of("belt_middle_box")
    p = plan(pack, target="c1", dest="pallet")
    failed = [{"step": copy.deepcopy(p["step"]), "verdict": "NOT_MOVED"}]
    assert check(p, pack, history=failed) == ["REPEAT_AFTER_FAILURE"]
    assert check(p, pack, history=[{"step": p["step"], "verdict": "VERIFIED"}]) == []
    assert check(plan(pack, "ask_human"), pack, history=failed) == []


def test_repeat_rule_ignores_the_reason_and_pixel_jitter_and_needs_history():
    pack = pack_of("belt_middle_box")
    p = plan(pack, target="c1", dest="pallet")
    failed = [{"step": {**p["step"], "reason": "another wording"}, "verdict": "NOT_MOVED"}]
    assert check(p, pack, history=failed) == ["REPEAT_AFTER_FAILURE"]
    assert check(p, pack, history=[{"step": "garbage", "verdict": "NOT_MOVED"}]) == ["REPEAT_AFTER_FAILURE"]  # malformed row: fail closed
    assert check(p, pack, history=None) == ["HISTORY_REQUIRED"] and check(plan(pack, "idle"), pack, history=None) == []
    edge = pack_of("belt_edge_box")
    fp = lambda uv: plan(edge, "free_pick", target={"anchor": "belt", "at_px": uv}, dest="pallet")  # noqa: E731
    assert check(fp([331, 101]), edge, history=[{"step": fp([330, 100])["step"], "verdict": "NOT_MOVED"}]) == ["REPEAT_AFTER_FAILURE"]
    assert check(fp([360, 100]), edge, history=[{"step": fp([330, 100])["step"], "verdict": "NOT_MOVED"}]) == []


def test_untrusted_and_destination_sources_never_give_a_pick_whatever_the_suggestion_says():
    adv = pack_of("plate_b_workbench")
    assert check(plan(adv, target="plate_b-l1", dest="pallet"), adv) == ["SITE_NOT_SUGGESTED"]
    hinted = obs.assemble(json.loads((CASES / "adversarial" / "adv_retier_hint_on_untrusted_plate_b.json").read_text(encoding="utf-8"))["raw"])
    assert check(plan(hinted, target="plate_b-l1", dest="pallet"), hinted) == ["SITE_NOT_SUGGESTED"]
    assert check(plan(hinted, target="c1", dest="pallet"), hinted) == ["UNTRUSTED_SOURCE"]
    forged = copy.deepcopy(hinted)  # a hint smuggled in after the pack was built: the id no longer matches
    forged["candidates"][0]["suggestions"] = ["retier(plate_b-l1)"]
    assert check(plan(hinted, target="plate_b-l1", dest="pallet"), forged) == ["PACK_TAMPERED"]
    resealed = obs._seal(forged)  # even a resealed pack cannot make an untrusted site a pick source
    assert check(plan(resealed, target="plate_b-l1", dest="pallet"), resealed) == ["SITE_NOT_SUGGESTED"]
    assert check(plan(resealed, target="c1", dest="pallet"), resealed) == ["UNTRUSTED_SOURCE"]


def test_edited_pack_stale_clock_and_missing_arm_are_clean_refusals():
    pack = pack_of("belt_middle_box")
    good = plan(pack, target="c1", dest="pallet")
    forged = copy.deepcopy(pack)
    forged["candidates"].append({"id": "c9", "site": "belt", "suggestions": ["pick"]})
    assert check(plan(pack, target="c9", dest="pallet"), forged) == ["PACK_TAMPERED"]
    assert "OBSERVATION_STALE" in [e["code"] for e in pl.validate_plan(good, pack, history=[])["errors"]]  # now=None is the real clock
    noarm = {"observation_id": pack["observation_id"], "step": {"verb": "idle", "reason": "r"}}
    assert check(noarm, pack) == ["BAD_ARM"]


def test_cli_plan_check_exit_code(tmp_path, capsys):
    pack = pack_of("belt_middle_box")
    pack["observed_at"] = __import__("time").time()
    obs._seal(pack)
    (tmp_path / "pack.json").write_text(json.dumps(pack), encoding="utf-8")
    (tmp_path / "plan.json").write_text(json.dumps(plan(pack, target="c1", dest="pallet")), encoding="utf-8")
    (tmp_path / "plan.json").write_text(json.dumps(plan(pack, target="c1", dest="pallet")), encoding="utf-8")
    assert cli.main(["plan-check", "--pack", str(tmp_path / "pack.json"), "--plan", str(tmp_path / "plan.json")]) == 1  # no history: refused
    assert cli.main(["plan-check", "--pack", str(tmp_path / "pack.json"), "--plan", str(tmp_path / "plan.json"), "--first-step"]) == 0
    (tmp_path / "bad.json").write_text(json.dumps(plan(pack, target="c1", dest="pallet", x=1)), encoding="utf-8")
    assert cli.main(["plan-check", "--pack", str(tmp_path / "pack.json"), "--plan", str(tmp_path / "bad.json"), "--first-step"]) == 1
    assert "FORBIDDEN_FIELD" in capsys.readouterr().out
