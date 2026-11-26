"""D-1024 3 / D-793 2: the chunk runner's lease watchdog, the supervisor's feed and their grant format."""
from __future__ import annotations

import ast
import json
from pathlib import Path
import sys
import time
from types import SimpleNamespace

import pytest

ROOT = Path(__file__).resolve().parents[1]
for _p in (ROOT / "deploy/robot/omx", ROOT / "middleware/devices/omx/adapter"):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

import chunk_runner_loop  # noqa: E402
import chunk_runner_lease as crl  # noqa: E402
import cell_policy_lease as cpl  # noqa: E402

DIGEST = "e" * 64


def grant(*seq, **over):
    seq = seq[0] if seq else 1
    return {"lease_id": "L", "episode_id": "E", "workcell_id": "arm_s", "policy_digest": DIGEST, "rig_revision": "rig",
            "calibration_revision": "cal", "ttl_s": 1.0, "seq": seq, "window_remaining_s": 60.0, **over}


class Rig:
    """A watch on a temp file with a clock the test moves."""

    def __init__(self, tmp_path):
        self.now, self.path = [100.0], tmp_path / crl.LEASE_FILE
        self.watch = crl.PolicyLeaseWatch(self.path, lambda: self.now[0])

    def push(self, body):
        import os
        self.n = getattr(self, "n", 0) + 1
        self.path.write_text(json.dumps(body))
        os.utime(self.path, ns=(self.n, self.n))  # a distinct mtime per write, as the real writer's new file has

    def poll(self, running=True):
        return self.watch.poll(running)


def test_grant_format_is_the_push_receivers():
    tree = ast.parse((ROOT / "middleware/robot_execution/local/src/rosy/execution/local/policy_lease_push.py").read_text(encoding="utf-8"))
    values = {}
    for node in tree.body:
        if isinstance(node, ast.Assign) and isinstance(node.targets[0], ast.Name) and node.targets[0].id in ("_GRANT", "MAX_LEASE_S", "MAX_WINDOW_S"):
            call = node.value
            values[node.targets[0].id] = (frozenset(ast.literal_eval(call.args[0])) if isinstance(call, ast.Call)
                                          else eval(compile(ast.Expression(call), "x", "eval")))
    assert values == {"_GRANT": crl.GRANT_KEYS, "MAX_LEASE_S": crl.MAX_LEASE_S, "MAX_WINDOW_S": crl.MAX_WINDOW_S}


def test_nothing_arms_without_a_grant_and_a_stale_file_is_removed(tmp_path):
    (tmp_path / crl.LEASE_FILE).write_text(json.dumps(grant()))
    rig = Rig(tmp_path)
    assert not rig.path.exists()
    for step in range(50):
        rig.now[0] += 1.0
        assert rig.poll() is None
    assert rig.watch.status()["armed"] is False


def test_renewed_lease_holds_nothing_and_a_missing_renewal_closes_for_good(tmp_path):
    rig = Rig(tmp_path)
    rig.push(grant(1))
    assert rig.poll() is None and rig.watch.status()["armed"] is True and rig.watch.seq == 1
    for seq in range(2, 8):  # renewed every 0.5 s with a 1 s ttl
        rig.now[0] += 0.5
        rig.push(grant(seq))
        assert rig.poll() is None
    rig.now[0] += 0.99
    assert rig.poll() is None
    rig.now[0] += 0.02  # ttl over, no renewal
    assert rig.poll() == "lease_expired"
    rig.now[0] += 0.1
    rig.push(grant(99))  # nothing re-arms
    assert rig.poll() == "lease_expired" and rig.watch.status()["closed"] is True


def test_expiry_outside_a_policy_chunk_waits_for_the_next_policy_chunk(tmp_path):
    rig = Rig(tmp_path)
    rig.push(grant(1))
    rig.poll(False)
    rig.now[0] += 5
    assert rig.poll(False) is None
    assert rig.poll(True) == "lease_expired"


@pytest.mark.parametrize("bad", [
    grant(1, ttl_s=2.5), grant(1, ttl_s=0), grant(1, ttl_s=True), grant(1, ttl_s=float("nan")), grant(1, seq=0),
    grant(1, seq=True), grant(1, window_remaining_s=1801), grant(1, window_remaining_s=0), grant(1, policy_digest="E" * 64),
    grant(1, lease_id=""), {k: v for k, v in grant(1).items() if k != "rig_revision"}, {**grant(1), "extra": 1}])
def test_a_malformed_first_grant_never_arms(tmp_path, bad):
    rig = Rig(tmp_path)
    rig.push(bad)
    assert rig.poll() in (None, "lease_replay") and rig.watch.status()["armed"] is False


@pytest.mark.parametrize("bad", [
    grant(2, ttl_s=2.5), grant(2, window_remaining_s=1801), grant(1), grant(0), grant(2, episode_id="other"),
    grant(2, lease_id="other"), grant(2, policy_digest="a" * 64), grant(2, calibration_revision="x"), {"seq": 2}])
def test_a_bad_renewal_closes_an_armed_watch(tmp_path, bad):
    rig = Rig(tmp_path)
    rig.push(grant(1))
    assert rig.poll() is None
    rig.now[0] += 0.1
    rig.push(bad)
    assert rig.poll() is not None


def test_the_first_window_is_never_lengthened_by_later_grants(tmp_path):
    rig = Rig(tmp_path)
    rig.push(grant(1, window_remaining_s=2.0))
    rig.poll()
    rig.now[0] += 1.0
    rig.push(grant(2, window_remaining_s=600.0))  # a late grant claims a long window; the first deadline stands
    assert rig.poll() is None
    rig.now[0] += 1.01
    assert rig.poll() == "lease_expired"


def test_released_marker_disarms_and_a_clock_step_back_closes(tmp_path):
    rig = Rig(tmp_path)
    rig.push(grant(1))
    rig.poll()
    rig.push({"released": True, "episode_id": "E"})
    rig.now[0] += 10
    assert rig.poll() is None and rig.watch.status()["armed"] is False
    rig.now[0] -= 1
    assert rig.poll(True) == "lease_clock_fault"


def test_a_garbled_file_closes_an_armed_watch(tmp_path):
    rig = Rig(tmp_path)
    rig.push(grant(1))
    rig.poll()
    rig.path.write_text("{not json")
    import os
    os.utime(rig.path, ns=(1, 2))
    assert rig.poll() == "lease_unreadable"


# -- the runner loop turns a closed watch into its normal human-hold ------------------------------------------------------------

def _loop(tmp_path, monkeypatch, ticks, *, chunk="policy", renew=True, lease=True):
    monkeypatch.setattr(chunk_runner_loop, "wait_aligned_before_start", lambda *a: True)
    monkeypatch.setattr(chunk_runner_loop, "interrupt_tick", lambda *a: False)
    now, commands = [100.0], []
    runner = SimpleNamespace(
        fps=10, clock=lambda: now[0], sleep=lambda s: now.__setitem__(0, now[0] + 0.1), present=lambda: [0.0] * 6,
        target=None, last_present=None, pending=[], chunk=chunk, signals=None, human_hold_latched=False, ticks=0, live=None,
        idle=lambda: False, last_input=0.0, idle_parks=0, policy_playback=None, lag=0.0, fault=None)
    runner.lease_watch = crl.PolicyLeaseWatch(tmp_path / crl.LEASE_FILE, runner.clock) if lease else None

    def command(line):
        commands.append((round(now[0], 1), line))
        if line.split()[0] == "human-hold":
            runner.human_hold_latched = True
        return True

    runner.command = command
    count = [0]

    def lines():
        count[0] += 1
        if count[0] > ticks:
            raise StopIteration
        if lease and (count[0] == 1 or (renew and count[0] % 5 == 0)):  # a grant every 0.5 s of runner time
            body = grant(count[0])
            (tmp_path / crl.LEASE_FILE).write_text(json.dumps(body))
            import os
            os.utime(tmp_path / crl.LEASE_FILE, ns=(count[0], count[0]))
        return []

    with pytest.raises(StopIteration):
        chunk_runner_loop.run(runner, lines)
    return runner, commands


def test_loop_renewed_lease_never_holds(tmp_path, monkeypatch):
    runner, commands = _loop(tmp_path, monkeypatch, 100)
    assert commands == [] and runner.human_hold_latched is False and runner.lease_watch.status()["armed"] is True


def test_loop_lost_renewal_issues_one_human_hold_within_the_ttl(tmp_path, monkeypatch):
    runner, commands = _loop(tmp_path, monkeypatch, 100, renew=False)
    assert [c for _, c in commands] == ["human-hold"] and runner.human_hold_latched is True
    assert 101.0 <= commands[0][0] <= 101.4  # first grant at 100.0, ttl 1 s, one 0.1 s tick of slack


def test_loop_without_a_lease_or_outside_a_policy_chunk_is_unchanged(tmp_path, monkeypatch):
    assert _loop(tmp_path, monkeypatch, 60, lease=False)[1] == []
    assert _loop(tmp_path, monkeypatch, 60, chunk="home", renew=False)[1] == []


# -- the supervisor's feed ---------------------------------------------------------------------------------------------------

class FakeCell:
    def __init__(self, io, armed=True):
        self.io, self.armed, self.sent, self.chunk = io, armed, [], None

    def policy_state(self):
        body = json.loads((Path(self.io) / cpl.LEASE_FILE).read_text()) if (Path(self.io) / cpl.LEASE_FILE).exists() else {}
        if not self.armed or body.get("released") or "seq" not in body:
            return {"t": time.time(), "chunk": self.chunk}
        return {"t": time.time(), "chunk": self.chunk, "policy_lease": {"armed": True, "closed": False, "seq": body["seq"],
                                                               "episode_id": body["episode_id"], "lease_id": body["lease_id"]}}


def _feed(tmp_path, cell, **kw):
    return cpl.LeaseFeed(cell, episode_id="E", workcell_id="arm_s", policy_digest=DIGEST, rig_revision="r", calibration_revision="c",
                         period_s=0.02, ack_timeout_s=0.5, **kw)


def test_feed_writes_valid_increasing_grants_and_releases(tmp_path):
    feed = _feed(tmp_path, FakeCell(tmp_path))
    assert feed.start() is None
    import time
    time.sleep(0.15)
    body = json.loads((tmp_path / cpl.LEASE_FILE).read_text())
    assert set(body) == crl.GRANT_KEYS and body["seq"] >= 2 and 0 < body["ttl_s"] <= crl.MAX_LEASE_S and body["episode_id"] == "E"
    feed.stop()
    assert json.loads((tmp_path / cpl.LEASE_FILE).read_text()) == {"released": True, "episode_id": "E"}


def test_feed_refuses_when_the_runner_never_arms_the_lease(tmp_path):
    feed = _feed(tmp_path, FakeCell(tmp_path, armed=False))
    assert feed.start() == cpl.UNACKED
    seq = feed.seq
    import time
    time.sleep(0.1)
    assert feed.seq == seq  # renewals stopped with the refusal


def test_feed_stops_renewing_after_its_window(tmp_path):
    clock = [0.0]
    feed = _feed(tmp_path, FakeCell(tmp_path), window_s=1.0, monotonic=lambda: clock[0])
    assert feed.start() is None
    clock[0] = 2.0
    import time
    time.sleep(0.1)
    last = feed.seq
    time.sleep(0.1)
    assert feed.seq == last
    feed.stop()


@pytest.mark.parametrize("live", ["policy", "home -> policy", "unreadable", "stale"])
def test_feed_does_not_release_unless_a_fresh_live_json_shows_no_policy_chunk(tmp_path, live):
    cell = FakeCell(tmp_path)
    feed = _feed(tmp_path, cell)
    assert feed.start() is None
    armed_state = cell.policy_state
    if live == "unreadable":
        cell.policy_state = lambda: None
    elif live == "stale":
        cell.policy_state = lambda: {"t": time.time() - 30, "chunk": None}
    else:
        cell.chunk = live  # an abnormal end mid-chunk: the lease runs out into the runner's hold, never into a release
    feed.stop()
    assert "released" not in json.loads((tmp_path / cpl.LEASE_FILE).read_text())
    cell.policy_state = armed_state


def test_loop_holds_a_chunk_labelled_with_policy_inside_a_chain(tmp_path, monkeypatch):
    runner, commands = _loop(tmp_path, monkeypatch, 100, chunk="home -> policy", renew=False)
    assert [c for _, c in commands] == ["human-hold"]
