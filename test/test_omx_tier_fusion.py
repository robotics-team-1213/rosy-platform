import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "deploy" / "robot" / "omx"))
import cell_task_exec  # noqa: E402
from cell_tier_fusion import fuse  # noqa: E402

OBS = {"tier": 2, "age_s": 10, "epoch": 3, "expect_epoch": 3}


@pytest.mark.parametrize("args,below,hold,sources", [
    ((1, None, None, None, None), 0, False, ["manifest"]),
    ((2, None, None, None, None), 1, False, ["manifest"]),
    ((1, {"tier": 2}, None, None, None), 1, False, ["manifest", "parallax"]),  # any 2 wins, manifest present: no hold
    ((None, {"tier": 1}, None, None, None), 0, True, ["parallax"]),  # one source, no manifest
    ((None, {"tier": 1}, None, None, {"tier": 1}), 0, False, ["parallax", "wrist"]),
    ((None, {"tier": 1}, None, None, {"tier": 2}), 1, True, ["parallax", "wrist"]),  # disagree, no manifest
    ((None, None, None, None, None), 0, True, []),
    ((2, None, None, "1", None), 1, False, ["judge", "manifest"]),  # judge cannot lower
    ((1, None, OBS, None, None), 1, False, ["manifest", "observer"]),  # observer raises
    ((1, None, {**OBS, "age_s": 121}, None, None), 0, False, ["manifest"]),  # stale ignored
    ((1, None, {**OBS, "epoch": 4}, None, None), 0, False, ["manifest"]),  # other epoch ignored
    ((None, {"tier": 1}, {**OBS, "age_s": 500}, None, None), 0, True, ["parallax"]),
    ((None, None, None, "2", None), 1, True, ["judge"]),
])
def test_fuse_table(args, below, hold, sources):
    r = fuse(*args)
    assert (r["layers_below"], r["hold"], r["sources"]) == (below, hold, sources)
    assert r["top_first"] == (below == 1)


def test_cell_task_exec_passes_layers_below(tmp_path, monkeypatch):
    seen = []

    class P:
        returncode, stdout = 0, json.dumps({"result": "placed"})

    monkeypatch.setattr(cell_task_exec.subprocess, "run", lambda cmd, **k: seen.append(cmd) or P())
    monkeypatch.setattr(cell_task_exec, "check_arm_hold", lambda a: {"held": False})
    monkeypatch.setattr(cell_task_exec, "measured_fold", lambda a, p: {"folded": True, "state": None, "fresh": True})
    monkeypatch.setattr(cell_task_exec, "source_clearance", lambda *a, **k: {"objects": 0})
    for n in ("with-session-arm-s-live.sh", "cell-auto-arm-s-live.json"):
        (tmp_path / n).write_text("{}")
    for hint, want in (({"layers_below": 1}, True), (None, False), ({"layers_below": 0}, False)):
        seen.clear()
        task = {"arm_id": "arm_s", "task_id": "t", "handoff_lease_id": "l", **({"tier_hint": hint} if hint else {})}
        cell_task_exec.execute_guarded_cell_task(task, prep_dir=tmp_path)
        assert ("--layers-below" in seen[0]) is want
        if want:
            assert seen[0][seen[0].index("--layers-below") + 1] == "1"
