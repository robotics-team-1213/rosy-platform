"""map_generation: changes whenever the SLAM map origin may have changed (map_generation.py); persisted; independent of boot_id and map_grid_id."""

from __future__ import annotations

from types import SimpleNamespace

from core_features.state.manager import StateManager
from core_common.map_generation import MapGenerationCounter


def test_a_core_start_bumps_and_the_counter_never_goes_backwards_across_restarts(tmp_path):
    path = tmp_path / "map_generation"
    first = MapGenerationCounter(path, wall=lambda: 1000.0)
    assert first.value == 1000                                           # no file: the wall-clock second (above any small earlier value)
    first.bump("a")
    first.bump("b")
    assert first.value == 1002 and path.read_text().strip() == "1002"
    second = MapGenerationCounter(path, wall=lambda: 5.0)                # a CORE restart: +1 on the persisted value, whatever the clock says
    assert second.value == 1003 and path.read_text().strip() == "1003"
    third = MapGenerationCounter(path)
    assert third.value == 1004


def test_a_corrupt_or_unwritable_file_still_gives_a_usable_counter(tmp_path):
    path = tmp_path / "map_generation"
    path.write_text("not a number")
    assert MapGenerationCounter(path, wall=lambda: 2000.0).value == 2000
    blocked = tmp_path / "dir_not_file"
    blocked.mkdir()
    counter = MapGenerationCounter(blocked, wall=lambda: 3000.0)         # os.replace onto a directory fails: in-memory for this boot
    assert counter.value == 3000 and counter.bump("x") == 3001
    memory = MapGenerationCounter(None, wall=lambda: 4000.0)
    assert memory.value == 4000


def _bridge(tmp_path):
    state = StateManager("robot-1", stale_after_s={}, sources_configured=False, map_generation_path=tmp_path / "map_generation")
    svc = SimpleNamespace(state=state, nav=SimpleNamespace(_map_evidence=None), command=SimpleNamespace(_execution_fence=None))
    return SimpleNamespace(_svc=svc), state


def test_a_navigation_lifecycle_activation_bumps_the_generation_and_an_inactive_one_does_not(tmp_path, monkeypatch):
    from core.bridge import map_observation  # noqa: PLC0415
    monkeypatch.setattr(map_observation.map_pose, "invalidate_map_pose", lambda bridge: None)
    bridge, state = _bridge(tmp_path)
    before = state.map_generation.value
    map_observation.lifecycle(bridge, False)                              # slam_toolbox went inactive / shut down: nothing yet, the next ACTIVE is the new origin
    assert state.map_generation.value == before
    map_observation.lifecycle(bridge, True)                               # a restarted navigation stack went ACTIVE
    assert state.map_generation.value == before + 1
    map_observation.lifecycle(bridge, True)
    assert state.map_generation.value == before + 2


def test_the_snapshot_carries_the_generation_independent_of_the_boot_and_the_grid_id(tmp_path):
    state = StateManager("robot-1", stale_after_s={}, sources_configured=False, map_generation_path=tmp_path / "map_generation")
    snap = state.snapshot()
    assert snap.map_generation == state.map_generation.value
    state.set_map_id("occupancy:aaaa", "occupancy:aaaa")
    state.set_map_id("occupancy:bbbb", "occupancy:bbbb")                  # the grid hash changes as the grid grows: the generation does not
    assert state.snapshot().map_generation == snap.map_generation
    state.map_generation.bump("test")
    assert state.snapshot().map_generation == snap.map_generation + 1
    again = StateManager("robot-1", stale_after_s={}, sources_configured=False, map_generation_path=tmp_path / "map_generation")
    assert again.snapshot().map_generation == snap.map_generation + 2     # the CORE restart bump continues from the persisted value

def test_the_bump_comes_after_the_stop_request_and_a_failing_counter_never_breaks_the_lifecycle_handling(tmp_path, monkeypatch):
    from core.bridge import map_observation  # noqa: PLC0415
    order = []
    monkeypatch.setattr(map_observation.map_pose, "invalidate_map_pose", lambda bridge: order.append("invalidate"))
    fence = SimpleNamespace(_ledger=SimpleNamespace(_current="parent"), request_stop=lambda parent: order.append("stop"))
    source = SimpleNamespace(lifecycle=lambda active: order.append("evidence"))
    state = StateManager("robot-1", stale_after_s={}, sources_configured=False, map_generation_path=tmp_path / "map_generation")
    real = state.map_generation.bump
    state.map_generation.bump = lambda reason="": (order.append("bump"), real(reason))[1]
    bridge = SimpleNamespace(_svc=SimpleNamespace(state=state, nav=SimpleNamespace(_map_evidence=source), command=SimpleNamespace(_execution_fence=fence)))
    map_observation.lifecycle(bridge, True)
    assert order == ["stop", "evidence", "invalidate", "bump"]                  # the bump is the very last thing: after the stop and every invalidation
    order.clear()
    state.map_generation.bump = lambda reason="": (_ for _ in ()).throw(OSError("disk full"))
    map_observation.lifecycle(bridge, True)                               # the failing counter is swallowed: the rest of the handling still runs
    assert order == ["stop", "evidence", "invalidate"]


def test_the_value_is_readable_while_a_bump_is_writing_the_file(tmp_path):
    import threading  # noqa: PLC0415
    counter = MapGenerationCounter(tmp_path / "map_generation", wall=lambda: 100.0)
    release, entered = threading.Event(), threading.Event()
    real = counter._write_locked

    def slow():
        entered.set()
        release.wait(5.0)
        real()
    counter._write_locked = slow
    worker = threading.Thread(target=counter.bump, args=("slow",))
    worker.start()
    assert entered.wait(5.0)
    assert counter.value == 100 + 1                                      # no lock, no wait: the increment is visible while the disk write is still blocked
    release.set()
    worker.join(5.0)
    assert (tmp_path / "map_generation").read_text().strip() == "101"
