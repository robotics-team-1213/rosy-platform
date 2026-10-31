"""tools/land_stall.py: read-only diagnosis of the 2026-10-31 queue stalls."""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools"))
import land_stall  # noqa: E402

NOW = 1_800_000_000.0


def queue(tmp_path, *rows):
    qdir = tmp_path / "rosy-land-queue"
    qdir.mkdir()
    for n, row in enumerate(rows):
        (qdir / f"0{n:019d}-1.json").write_text(json.dumps({"pid": 100 + n, "start": NOW - 600, **row}))
    return land_stall.tickets(qdir)


def test_batch_deadlock_names_the_member_to_stop(tmp_path):
    rows = queue(tmp_path, {"branch": "land/m", "status": "waiting"},
                 {"branch": "land/l", "status": "waiting", "batch": ["land/m"]})
    found = land_stall.diagnose(rows, [], {}, 0, NOW)
    assert len(found) == 1 and found[0].startswith("batch-deadlock: member land/m") and "pid 100" in found[0]


def test_a_carried_member_holding_later_tickets_while_its_leader_prepares(tmp_path):
    rows = queue(tmp_path, {"branch": "land/m", "status": "waiting"},
                 {"branch": "land/l", "status": "preparing", "batch": ["land/m"]},
                 {"branch": "land/x", "status": "waiting"})
    assert [f.split(":")[0] for f in land_stall.diagnose(rows, [], {}, 0, NOW)] == ["carried-member"]


def test_turns_that_go_back_to_preparing_twice_are_bounces():
    events = [{"t": NOW - 3000 + i, "event": e, "branch": "land/b"} for i, e in
              enumerate(["turn", "prepared", "turn", "prepared", "turn", "landed"])]
    assert land_stall.bounces(events, NOW) == {"land/b": 2}
    assert land_stall.diagnose([], events, {}, 0, NOW)[0].startswith("turn-bounce: land/b")


def test_turn_holder_waiting_for_host_room_and_old_code(tmp_path):
    rows = queue(tmp_path, {"branch": "land/t", "status": "turn", "worktree": "wt-t"})
    logs = {"wt-t": ("x\n[remote-pytest] waiting for host room (2 job(s))\n", NOW - 3600)}
    found = land_stall.diagnose(rows, [], logs, NOW - 60, NOW)
    assert [f.split(":")[0] for f in found] == ["turn-host-room", "old-code"]
    admitted = {"wt-t": (logs["wt-t"][0] + "[remote-pytest] host room after waiting\n", NOW - 3600)}
    assert land_stall.diagnose(rows, [], admitted, 0, NOW) == []


def test_a_healthy_queue_has_no_cause(tmp_path):
    rows = queue(tmp_path, {"branch": "land/a", "status": "turn", "worktree": "wt-a"},
                 {"branch": "land/b", "status": "waiting"}, {"branch": "land/c", "status": "preparing"})
    assert land_stall.diagnose(rows, [], {"wt-a": ("running\n", NOW)}, 0, NOW) == []
