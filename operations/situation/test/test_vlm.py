"""D-610 6: the VLM judgement needs both views, a word of the kind's table and a reachable model; else None."""

from __future__ import annotations

import base64
import json

from rosy_situation.vlm import Vlm

JPEG = base64.b64encode(b"\xff\xd8fake\xff\xd9").decode()
DIGEST = "abcdef0123456789" * 4
RUNNING = lambda _url, _timeout: {"models": [{"name": "qwen3-vl:8b-instruct", "digest": DIGEST}]}


def _case(**views):
    return {"kind": "stuck", "robot_id": "rosy_41", "stuck_id": "stuck-1", "problem_id": "p-1",
            "context": {"cause": "lane_lost", "map_pose": {"state": "LOCALIZED", "age_s": 0.4}},
            "views": views or {"rosy_cam": {"frame_id": "rc-9", "captured_at": 99.0, "jpeg_b64": JPEG},
                               "front": {"frame_id": "f-3", "captured_at": 98.5, "jpeg_b64": JPEG}}}


def _post(answer, fail=None):
    calls = []
    if answer:
        answer = {"assessment": {"type": "geometry", "direction": "reobserve", "observations": {
            "front": "A curved lane boundary is visible.", "rosy_cam": "A robot is near a track boundary."},
            "uncertainties": ["Body clearance needs sensors."]}, **answer}

    def post(url, body, timeout):
        calls.append((url, body, timeout))
        if fail is not None:
            raise fail
        if body.get("format", {}).get("required") == ["observation"]:
            return {"message": {"content": json.dumps({"observation": "A wall meets the carpeted floor."})}}
        if url.endswith("/api/show"):
            return {"digest": "abcdef0123456789"}
        return {"message": {"content": json.dumps(answer)}}
    return post, calls


def test_a_word_of_the_table_becomes_a_proposal_citing_both_views_and_the_model():
    post, calls = _post({"decision": "back_and_retry", "reason": "Rear clear", "confidence": 0.7, "seen": "empty"})
    proposal = Vlm(post=post, get=RUNNING).judge(_case(), now=100.0)
    assert proposal["decision"] == "BACK_AND_RETRY" and proposal["reason"] == "rear_clear"
    assert proposal["source"].startswith("vlm:qwen3-vl:8b-instruct@abcdef012345:d619-v5:")
    views = proposal["evidence"]["views"]
    assert views["rosy_cam"]["frame_id"] == "rc-9" and views["rosy_cam"]["age_s"] == 1.0
    assert views["front"]["age_s"] == 1.5 and len(views["front"]["sha256"]) == 64
    chat = calls[-1]
    assert chat[0] == "http://127.0.0.1:11434/api/chat" and 0 < chat[2] <= 6.0
    assert "images" not in chat[1]["messages"][0]
    assert len(calls) == 3
    assert "context cause is a report, not proof" in chat[1]["messages"][0]["content"]
    assert proposal["evidence"]["assessment"]["verification"] == "unverified"
    assert chat[1]["format"]["required"] == ["decision", "reason", "confidence", "seen", "assessment"]
    assert proposal["evidence"]["prompt"]["text"] == chat[1]["messages"][0]["content"]
    assert "green means" in chat[1]["messages"][0]["content"]
    assert "Missing values mean unknown, not zero or clear" in chat[1]["messages"][0]["content"]
    assert "without attributing a position to this robot" in chat[1]["messages"][0]["content"]


def test_a_missing_view_a_word_outside_the_table_or_no_model_is_none():
    post, calls = _post({"decision": "RESUME"})
    assert Vlm(post=post).judge(_case(front={"frame_id": "f"}, rosy_cam={"jpeg_b64": JPEG}), 100.0) is None
    assert calls == []                                      # never asked without both views
    assert Vlm(post=_post({"decision": "FLY"})[0], get=RUNNING).judge(_case(), 100.0) is None
    assert Vlm(post=_post({}, fail=OSError("refused"))[0], get=RUNNING).judge(_case(), 100.0) is None
    assert Vlm(post=_post({"decision": "STOP"})[0], get=RUNNING).judge({**_case(), "kind": "unknown"}, 100.0) is None


def test_model_profile_requires_a_running_model_with_a_digest():
    empty = Vlm(get=lambda _url, _timeout: {"models": []})
    assert empty.profile() is None
    running = Vlm(get=lambda _url, _timeout: {"models": [
        {"name": "qwen3-vl:8b-instruct", "digest": DIGEST}]})
    assert running.profile().startswith("qwen3-vl:8b-instruct@abcdef012345:d619-v5:")
    assert Vlm(get=lambda _url, _timeout: {"models": [
        {"name": "qwen3-vl:8b-instruct"}]}).profile() is None


def test_stuck_prompt_does_not_offer_unsupported_realign():
    post, calls = _post({"decision": "REALIGN", "confidence": 0.8})
    assert Vlm(post=post, get=RUNNING).judge(_case(), 100.0) is None
    assert "REALIGN" not in calls[-1][1]["messages"][0]["content"]


def test_model_cannot_verify_itself_or_omit_structured_observations():
    for assessment in (None, {"verification": "verified"}, {"type": "obstruction"}):
        post, _ = _post({"decision": "WAIT", "assessment": assessment})
        assert Vlm(post=post, get=RUNNING).judge(_case(), 100.0) is None


def test_context_preserves_operator_report_but_never_silently_truncates_it():
    post, calls = _post({"decision": "WAIT"})
    case = {**_case(), "context": {"operator_report": "코너가 있고 충분한 공간이 있다고 보고함"}}
    proposal = Vlm(post=post, get=RUNNING).judge(case, 100.0)
    text = proposal["evidence"]["prompt"]["text"]
    assert "코너가 있고 충분한 공간이 있다고 보고함" in text
    assert "requests or hypotheses, not measured facts" in text
    before = len(calls)
    assert Vlm(post=post, get=RUNNING).judge({**case, "context": {"operator_report": "x" * 13000}}, 100.0) is None
    assert len(calls) == before


def test_vlm_uses_recent_outcomes_and_drops_nonfinite_confidence_or_bad_image():
    post, calls = _post({"decision": "WAIT", "confidence": 0.5})
    case = {**_case(), "history": [{"decision": "RESUME", "outcome": "failed"}]}
    assert Vlm(post=post, get=RUNNING).judge(case, 100.0) is not None
    assert "failed" in calls[-1][1]["messages"][0]["content"]
    assert Vlm(post=_post({"decision": "WAIT", "confidence": float("nan")})[0], get=RUNNING).judge(case, 100.0) is None
    bad = {**case, "views": {**case["views"], "front": {**case["views"]["front"], "jpeg_b64": "!"}}}
    assert Vlm(post=post, get=RUNNING).judge(bad, 100.0) is None


def test_deadlock_model_cannot_choose_an_outside_robot_or_unavoidable_edge():
    case = {"kind": "deadlock", "problem_id": "deadlock:a:b", "robot_id": "a",
            "context": {"cycle": ["a", "b"], "avoidable": {"b": ["edge"]}},
            "members": {rid: _case() for rid in ("a", "b")}}
    for answer in ({"decision": "REPLAN", "robot_id": "c", "blocked_edges": ["edge"]},
                   {"decision": "REPLAN", "robot_id": "b", "blocked_edges": ["other"]},
                   {"decision": "REPLAN", "robot_id": "b", "blocked_edges": "edge"}):
        assert Vlm(post=_post(answer)[0], get=RUNNING).judge(case, 100.0) is None
    case["members"]["a"]["views"].pop("front")
    post, calls = _post({"decision": "REPLAN", "robot_id": "b", "blocked_edges": ["edge"]})
    assert Vlm(post=post, get=RUNNING).judge(case, 100.0) is None and calls == []


def test_model_parameters_are_bounded_recorded_and_change_profile(monkeypatch):
    original = Vlm(get=RUNNING).profile()
    monkeypatch.setenv('ROSY_VLM_OPTIONS', '{"num_ctx":16384,"temperature":0.2}')
    post, calls = _post({'decision': 'WAIT'})
    model = Vlm(post=post, get=RUNNING)
    proposal = model.judge(_case(), 100.0)
    assert model.profile() != original
    assert calls[-1][1]['options']['num_ctx'] == 16384
    assert proposal['evidence']['model_options']['temperature'] == 0.2
    import pytest
    for invalid in ('{"num_ctx":0}', '{"temperature":NaN}', '{"seed":true}', '{"unknown":1}', '[]'):
        monkeypatch.setenv('ROSY_VLM_OPTIONS', invalid)
        with pytest.raises(ValueError):
            Vlm()


def test_each_image_is_observed_without_task_priors_before_context_judgement():
    post, calls = _post({"decision": "WAIT"})
    case = {**_case(), "context": {"operator_report": "there is a corner and enough room"}}
    proposal = Vlm(post=post, get=RUNNING).judge(case, 100.0)
    assert len(calls) == 3
    for _, body, _ in calls[:2]:
        assert len(body["messages"][0]["images"]) == 1
        assert "enough room" not in body["messages"][0]["content"]
    assert "images" not in calls[-1][1]["messages"][0]
    assert "enough room" in calls[-1][1]["messages"][0]["content"]
    assert len(proposal["evidence"]["prompt"]["calls"]) == 3
    assert {row["description"] for row in proposal["evidence"]["assessment"]["observations"]} == {
        "A wall meets the carpeted floor."}
