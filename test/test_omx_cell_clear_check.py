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


def test_the_bird_view_blocks_a_clear_when_a_container_sits_out_of_its_lane_or_the_arm_leans():
    clean = {"obstruction": "none", "cable": "slack", "evidence": ""}
    scene = {"misplaced": "container across lanes R2/R3 on the left plate", "occupied_spots": "belt, tmp-a-1",
             "arm_leaning": "none", "evidence": ""}
    result = cc.check("arm_a", lambda view: b"jpg", model([clean, clean, scene]), scene_image=b"overhead")
    assert result["verdict"]["camera_clear"] is False and result["note"] == ""
    assert result["verdict"]["worries"] == ["scene: misplaced container across lanes R2/R3 on the left plate"]
    quiet = {"misplaced": "none", "occupied_spots": "belt", "arm_leaning": "none", "evidence": ""}
    ok = cc.check("arm_b", lambda view: b"jpg", model([clean, clean, quiet]), scene_image=b"overhead")
    assert ok["verdict"]["camera_clear"] is True  # an occupied spot is reported, placement measurement owns occupancy
