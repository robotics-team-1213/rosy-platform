"""cell_task_runner: a task becomes carries (a swap is three through a free buffer), stops at the first carry that is
not placed, and is refused when the cell check fails."""
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "deploy/robot/omx"))
import cell_task_runner as tr  # noqa: E402

SITES = {s: {"auto_roi": [0, 0, 10, 10]} for s in ("pinky", "belt", "floor")}


def task(**kw):
    return {"schema": tr.SCHEMA, "task_id": "t1", "source": "vla", **kw}


def test_move_and_swap_plans_and_bad_tasks_are_rejected():
    assert tr.carries(task(kind="move", **{"from": "pinky", "to": "belt"}), SITES) == [("pinky", "belt")]
    assert tr.carries(task(kind="swap", a="pinky", b="belt", buffer="floor"), SITES) == [
        ("pinky", "floor"), ("belt", "pinky"), ("floor", "belt")]
    for bad in (task(kind="swap", a="pinky", b="belt", buffer="belt"), task(kind="move", **{"from": "pinky", "to": "moon"}),
                task(kind="fly"), {"kind": "move"}):
        try:
            tr.carries(bad, SITES)
        except (ValueError, KeyError):
            continue
        raise AssertionError(f"accepted {bad}")


def config_file(tmp_path):
    path = tmp_path / "cell.json"
    path.write_text(json.dumps({"sites": SITES}))
    return path


def test_a_swap_stops_at_the_first_carry_that_is_not_placed(tmp_path):
    done = []

    def carry(config_path, catalog, sites, src, dst, log_dir):
        done.append((src, dst))
        return {"from": src, "to": dst, "result": "placed" if len(done) < 2 else "stopped: no usable object"}

    out = tr.run_task(task(kind="swap", a="pinky", b="belt", buffer="floor"), config_file(tmp_path), tmp_path / "c.json",
                      tmp_path, carry=carry)
    assert out["status"] == "stopped" and done == [("pinky", "floor"), ("belt", "pinky")] and "belt -> pinky" in out["why"]


def test_a_failed_cell_check_refuses_before_any_motion(tmp_path):
    out = tr.run_task(task(kind="move", **{"from": "pinky", "to": "belt"}), config_file(tmp_path), tmp_path / "c.json", tmp_path,
                      preflight=lambda c: [("top camera pose", False, "moved 30 px")],
                      carry=lambda *a: (_ for _ in ()).throw(AssertionError("moved")))
    assert out["status"] == "refused" and "top camera pose" in out["why"][0]
