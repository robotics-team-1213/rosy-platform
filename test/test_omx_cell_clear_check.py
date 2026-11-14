"""cell_clear_check: camera views per arm, a clear note only when every view is clean, never a hand-check claim."""
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "deploy/robot/omx"))

import cell_clear_check as cc  # noqa: E402


def model(answers):
    def ask(prompt, images, schema):
        ask.calls.append(prompt)
        return answers.pop(0)
    ask.calls = []
    return ask


def test_arm_b_clean_in_both_views_gives_an_honest_camera_note():
    seen = []
    ask = model([{"obstruction": "none", "cable": "slack", "evidence": "free"}] * 2)
    result = cc.check("arm_b", lambda view: seen.append(view) or b"jpg", ask, now=lambda: 1.0)
    assert seen == ["top", "side"] and "RIGHT arm" in ask.calls[0]
    assert result["verdict"] == {"camera_clear": True, "worries": []}
    assert "not a hand check" in result["note"] and "joint friction" in result["note"]


def test_any_view_with_an_obstruction_or_a_taut_cable_needs_a_person():
    ask = model([{"obstruction": "none", "cable": "slack", "evidence": ""},
                 {"obstruction": "container leaning on the base", "cable": "slack", "evidence": ""}])
    result = cc.check("arm_a", lambda view: b"jpg", ask)
    assert result["verdict"]["camera_clear"] is False and result["note"] == ""
    taut = cc.check("arm_s", lambda view: b"jpg", model([{"obstruction": "none", "cable": "taut", "evidence": ""}]))
    assert taut["verdict"]["camera_clear"] is False and list(taut["answers"]) == ["arm_s_top"]
