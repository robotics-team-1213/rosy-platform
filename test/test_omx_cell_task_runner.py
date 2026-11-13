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
    tiered = {s: {"auto_roi": [0, 0, 10, 10], "surface_z": 0.0} for s in ("pinky", "belt", "floor")}
    assert tr.carries(task(kind="stack", **{"from": "pinky", "to": "belt"}), tiered) == [
        ("pinky", "belt-l0"), ("pinky", "belt-l1"), ("pinky", "belt-l2")]
    assert tr.carries(task(kind="stack", **{"from": "pinky", "to": "belt"}, tier=2), tiered) == [("pinky", "belt-l1")]
    assert tr.carries(task(kind="unstack", **{"from": "belt", "to": "pinky"}), tiered) == [
        ("belt-l2", "pinky"), ("belt-l1", "pinky"), ("belt-l0", "pinky")]
    assert tr.carries(task(kind="move", **{"from": "pinky", "to": "belt"}, from_tier=2, to_tier=3), tiered) == [
        ("pinky-l1", "belt-l2")]
    for bad in (task(kind="swap", a="pinky", b="belt", buffer="belt"), task(kind="move", **{"from": "pinky", "to": "moon"}),
                task(kind="stack", **{"from": "pinky", "to": "belt"}, tier=4), task(kind="fly"), {"kind": "move"}):
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


def redirect_config(tmp_path, alternates):
    sites = {s: {"auto_roi": [0, 0, 10, 10]} for s in ("pinky", "belt", "floor", "plate")}
    sites["belt"]["alternates"] = alternates
    path = tmp_path / "cell.json"
    path.write_text(json.dumps({"sites": sites}))
    return path


def carry_with_full(full):
    done = []

    def carry(config_path, catalog, sites, src, dst, log_dir):
        done.append((src, dst))
        return {"from": src, "to": dst, "dest_full": dst in full,
                "result": "stopped: no usable object" if dst in full else "placed"}
    return carry, done


def test_a_full_destination_redirects_to_its_alternates_in_order(tmp_path):
    carry, done = carry_with_full({"belt", "floor"})
    out = tr.run_task(task(kind="move", **{"from": "pinky", "to": "belt"}),
                      redirect_config(tmp_path, ["floor", "moon", "pinky", "plate"]), tmp_path / "c.json", tmp_path, carry=carry)
    # unknown "moon" and the source "pinky" are never tried
    assert out["status"] == "done" and done == [("pinky", "belt"), ("pinky", "floor"), ("pinky", "plate")]
    assert out["steps"][-1]["redirected_from"] == "belt"


def test_no_redirect_when_the_stop_was_not_for_room_or_none_is_declared(tmp_path):
    carry, done = carry_with_full(set())
    stop = lambda c, k, s, src, dst, l: (done.append((src, dst)), {"from": src, "to": dst, "result": "stopped: planner"})[1]  # noqa: E731
    out = tr.run_task(task(kind="move", **{"from": "pinky", "to": "belt"}), redirect_config(tmp_path, ["floor"]),
                      tmp_path / "c.json", tmp_path, carry=stop)
    assert out["status"] == "stopped" and done == [("pinky", "belt")]
    carry, done = carry_with_full({"belt", "floor"})
    out = tr.run_task(task(kind="move", **{"from": "pinky", "to": "belt"}), redirect_config(tmp_path, ["floor"]),
                      tmp_path / "c.json", tmp_path, carry=carry)
    assert out["status"] == "stopped" and done == [("pinky", "belt"), ("pinky", "floor")] and "pinky -> floor" in out["why"]


def test_later_carries_take_the_object_from_where_it_was_redirected(tmp_path):
    carry, done = carry_with_full({"belt"})
    out = tr.run_task(task(kind="shuttle", a="pinky", b="belt"), redirect_config(tmp_path, ["plate"]),
                      tmp_path / "c.json", tmp_path, carry=carry)
    assert out["status"] == "done" and done == [("pinky", "belt"), ("pinky", "plate"), ("plate", "pinky")]


def test_run_carry_marks_a_destination_full_only_for_room_on_a_single_attempt(tmp_path):
    class Proc:
        def __init__(self, result):
            self.stdout, self.stderr, self.returncode = json.dumps(result), "", 0

    sites = {"pinky": {"auto_roi": [0, 0, 10, 10]}}
    full = [{"why": "place: does not fit on the surface / something is already there"}]
    stop = "stopped: no usable object"
    cases = (
        ({"result": stop, "attempts": [{"refused": full}]}, True),
        ({"result": stop, "attempts": [{"refused": full + [{"why": "planner: y"}]}]}, False),
        ({"result": stop, "attempts": [{"refused": [{"why": "place: no map at the destination"}]}]}, False),
        ({"result": stop, "attempts": [{"refused": [{"why": "place: nothing under it at the lower tier"}]}]}, False),
        # a second attempt means the first one acted: never redirect after motion
        ({"result": stop, "attempts": [{"refused": []}, {"refused": full}]}, False),
        ({"result": "placed", "attempts": [{"refused": []}]}, False),
    )
    for result, expected in cases:
        step = tr.run_carry(tmp_path / "c.json", tmp_path / "k.json", sites, "pinky", "belt", tmp_path,
                            run=lambda *a, r=result, **k: Proc(r))
        assert step["dest_full"] is expected, result


def test_a_swap_never_redirects(tmp_path):
    carry, done = carry_with_full({"pinky"})
    path = redirect_config(tmp_path, [])
    cfg = json.loads(path.read_text())
    cfg["sites"]["pinky"]["alternates"] = ["plate"]
    path.write_text(json.dumps(cfg))
    out = tr.run_task(task(kind="swap", a="pinky", b="belt", buffer="floor"), path, tmp_path / "c.json", tmp_path, carry=carry)
    assert out["status"] == "stopped" and done == [("pinky", "floor"), ("belt", "pinky")]


def test_only_the_next_take_from_the_full_site_follows_the_redirect(tmp_path):
    full = {"belt"}
    done = []

    def carry(config_path, catalog, sites, src, dst, log_dir):
        done.append((src, dst))
        hit = dst in full and len(done) == 1  # belt is full only for the first carry
        return {"from": src, "to": dst, "dest_full": hit, "result": "stopped: no usable object" if hit else "placed"}

    out = tr.run_task(task(kind="shuttle", a="pinky", b="belt", cycles=2), redirect_config(tmp_path, ["plate"]),
                      tmp_path / "c.json", tmp_path, carry=carry)
    assert out["status"] == "done" and done == [
        ("pinky", "belt"), ("pinky", "plate"), ("plate", "pinky"), ("pinky", "belt"), ("belt", "pinky")]
