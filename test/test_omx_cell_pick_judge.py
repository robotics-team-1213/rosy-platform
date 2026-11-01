"""cell_pick_judge: the model orders only the candidates the measurement kept, may veto all of them, and when it cannot
answer the rule's order stands."""
import sys
from pathlib import Path

import pytest

np = pytest.importorskip("numpy")
pytest.importorskip("cv2")
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "deploy/robot/omx"))
import cell_pick_judge as pj  # noqa: E402

IMG = np.full((120, 160, 3), 150, np.uint8)
USABLE = [{"object": {"object": "container-1", "length_mm": 30, "width_mm": 30, "hull_px": [[10, 10], [40, 10], [40, 40], [10, 40]]}},
          {"object": {"object": "container-2", "length_mm": 60, "width_mm": 30, "hull_px": [[60, 20], [120, 20], [120, 50], [60, 50]],
                      "split_from": "touching"}}]


def test_the_models_pick_goes_first_and_sees_only_measured_candidates():
    seen = {}

    def backend(prompt, images, schema):
        seen["prompt"], seen["images"] = prompt, images
        return {"choice": 1, "reason": "the 2-cell lies flat"}

    out = pj.ask(backend, IMG, USABLE)
    assert out["order"] == [1, 0] and out["by"] == "model" and len(seen["images"]) == 1
    assert "container-2" in seen["prompt"] and "touching" in seen["prompt"]


def test_a_veto_empties_the_list_and_a_failure_keeps_the_rule():
    assert pj.ask(lambda *a: {"choice": -1, "reason": "both lean on each other"}, IMG, USABLE)["order"] == []
    assert pj.ask(lambda *a: {"choice": 7, "reason": "?"}, IMG, USABLE)["order"] == [0, 1]

    def down(*a):
        raise OSError("connection refused")

    out = pj.ask(down, IMG, USABLE)
    assert out["order"] == [0, 1] and out["by"] == "rule" and "unavailable" in out["reason"]
    assert pj.ask(None, IMG, USABLE)["order"] == [0, 1]
