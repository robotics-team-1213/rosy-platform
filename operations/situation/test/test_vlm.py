"""D-610 6: the VLM judgement needs both views, a word of the kind's table and a reachable model; else None."""

from __future__ import annotations

import base64
import json

from rosy_situation.vlm import Vlm

JPEG = base64.b64encode(b"\xff\xd8fake\xff\xd9").decode()


def _case(**views):
    return {"kind": "stuck", "robot_id": "rosy_41", "stuck_id": "stuck-1", "problem_id": "p-1",
            "context": {"cause": "lane_lost", "map_pose": {"state": "LOCALIZED", "age_s": 0.4}},
            "views": views or {"rosy_cam": {"frame_id": "rc-9", "captured_at": 99.0, "jpeg_b64": JPEG},
                               "front": {"frame_id": "f-3", "captured_at": 98.5, "jpeg_b64": JPEG}}}


def _post(answer, fail=None):
    calls = []

    def post(url, body, timeout):
        calls.append((url, body, timeout))
        if fail is not None:
            raise fail
        if url.endswith("/api/show"):
            return {"digest": "abcdef0123456789"}
        return {"message": {"content": json.dumps(answer)}}
    return post, calls


def test_a_word_of_the_table_becomes_a_proposal_citing_both_views_and_the_model():
    post, calls = _post({"decision": "back_and_retry", "reason": "Rear clear", "confidence": 0.7, "seen": "empty"})
    proposal = Vlm(post=post).judge(_case(), now=100.0)
    assert proposal["decision"] == "BACK_AND_RETRY" and proposal["reason"] == "rear_clear"
    assert proposal["source"] == "vlm:qwen3-vl:8b-instruct@abcdef012345:d610-v1"
    views = proposal["evidence"]["views"]
    assert views["rosy_cam"]["frame_id"] == "rc-9" and views["rosy_cam"]["age_s"] == 1.0
    assert views["front"]["age_s"] == 1.5 and len(views["front"]["sha256"]) == 64
    chat = calls[-1]
    assert chat[0] == "http://127.0.0.1:11434/api/chat" and chat[2] == 6.0
    assert len(chat[1]["messages"][0]["images"]) == 2


def test_a_missing_view_a_word_outside_the_table_or_no_model_is_none():
    post, calls = _post({"decision": "RESUME"})
    assert Vlm(post=post).judge(_case(front={"frame_id": "f"}, rosy_cam={"jpeg_b64": JPEG}), 100.0) is None
    assert calls == []                                      # never asked without both views
    assert Vlm(post=_post({"decision": "FLY"})[0]).judge(_case(), 100.0) is None
    assert Vlm(post=_post({}, fail=OSError("refused"))[0]).judge(_case(), 100.0) is None
    assert Vlm(post=_post({"decision": "STOP"})[0]).judge({**_case(), "kind": "unknown"}, 100.0) is None
