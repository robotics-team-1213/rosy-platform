"""cell_surface: a touch probe's contact hold is the surface; no contact or a refusal never gives a height."""
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "deploy/robot/omx"))
import cell_surface as cs  # noqa: E402
import chunk_runner  # noqa: E402

PLAN = json.loads((ROOT / "deploy/robot/omx/grasp-plan.example.json").read_text())


class Scripted:
    def __init__(self, answers=None):
        self.answers, self.sent = answers or {}, []

    def act(self, command):
        self.sent.append(command)
        return self.answers.get(command, {"ok": True})


def test_contact_hold_is_the_surface_then_it_backs_out_and_folds():
    cell = Scripted({"run descend_probe": {"ok": False, "contact": True, "state": [1, 2, 3, 4, 5, 46.6]}})
    out = cs.touch(cell, Path("lib.json"), fk=lambda state: 0.0412)
    assert out["result"] == "touched" and out["surface_z"] == 0.0412
    assert cell.sent[-2:] == ["retreat", "park"]


def test_no_contact_or_refusal_gives_no_height_and_parks():
    out = cs.touch(Scripted(), Path("lib.json"), fk=lambda s: 1 / 0)
    assert out["result"] == "no contact" and "surface_z" not in out
    cell = Scripted({"goto above_probe": {"ok": False, "error": "unknown chunk"}})
    out = cs.touch(cell, Path("lib.json"), fk=lambda s: 1 / 0)
    assert out["result"] == "refused" and cell.sent[-1] == "park"


def test_probe_library_loads_in_the_runner_and_only_descends(tmp_path):
    lib = cs.probe_library(PLAN, 0.15, 0.0, -14.4, 0.10, 0.01)
    path = tmp_path / "probe.json"
    path.write_text(json.dumps(lib))
    loaded = chunk_runner.load_library(path)
    down = loaded["chunks"]["descend_probe"]
    assert len(down) > 30 and all(f[5] == PLAN["grip_closed"] for f in down)  # jaws closed all the way
    assert cs.fk_z(down[-1]) < cs.fk_z(down[0]) - 0.08  # straight down by the full range
