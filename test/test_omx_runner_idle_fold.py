"""An idle fold a blocked joint holds is tried once more, then the arm is held for a person (2026-11-03: before, the
runner retried the fold every idle_park_s for good, pushing the blocked joint with torque on)."""
import pytest

from test_omx_chunk_runner import HOME, Robot, library, m


class BlockedRoll(Robot):
    """The wrist roll sits at 40 and never moves (arm_a, 2026-11-01); the guard's sent command comes back."""

    def __init__(self):
        super().__init__(blocked=(4,))
        self.pos[4] = 40.0

    def send_action(self, action):
        super().send_action(action)
        return action


def observe_latched_runner(runner, poll, ticks):
    """End the simulation at its horizon even when the runner appropriately refuses stop."""
    class EndOfObservation(Exception):
        pass

    remaining = iter(range(ticks))

    def bounded_poll():
        if next(remaining, None) is None:
            raise EndOfObservation
        return poll()

    with pytest.raises(EndOfObservation):
        runner.run(bounded_poll)


def test_an_idle_fold_a_hold_stopped_is_tried_once_more_then_held_for_a_person():
    lib = library()
    lib["chunks"]["home"] = [HOME]
    status, clock = [], [0.0]
    r = m.Runner(BlockedRoll(), lib, fps=30, status=lambda row: status.append(dict(row, clock=clock[0])),
                 clock=lambda: clock[0], sleep=lambda s: clock.__setitem__(0, clock[0] + 1 / 30),
                 params={"runner.idle_park_s": 5.0, "runner.idle_retry_s": 20.0, "runner.idle_stop_s": 5.0})
    observe_latched_runner(r, lambda: ["stop"] if clock[0] > 120 else [], 121 * 30)
    parks = [s for s in status if s["command"] == "run park"]
    assert [s["ok"] for s in parks] == [False, False] and all("wrist_roll" in s["error"] for s in parks)
    assert parks[1]["clock"] - parks[0]["clock"] >= 20.0  # the retry waits idle_retry_s, not idle_park_s
    person = [s for s in status if s.get("person_needed") and s["command"] == "park"]
    assert len(person) == 1 and "a person must free the arm" in person[0]["error"]
    held = [s for s in status if s.get("person_needed") and s["command"] == "human-hold"]
    assert len(held) == 1 and held[0]["ok"]
    assert status[-1]["command"] == "stop" and status[-1]["clock"] > 120
    assert not status[-1]["ok"] and "human hold latched" in status[-1]["error"]
    assert r.human_hold_latched


def test_state_observation_after_a_held_fold_preserves_the_latch():
    lib = library()
    lib["chunks"]["home"] = [HOME]
    status, clock, sent = [], [0.0], []

    def lines():
        if clock[0] > 40 and not sent:
            sent.append(1)
            return ["state"]
        return ["stop"] if clock[0] > 200 else []

    r = m.Runner(BlockedRoll(), lib, fps=30, status=lambda row: status.append(dict(row, clock=clock[0])),
                 clock=lambda: clock[0], sleep=lambda s: clock.__setitem__(0, clock[0] + 1 / 30),
                 params={"runner.idle_park_s": 5.0, "runner.idle_retry_s": 20.0, "runner.idle_stop_s": 5.0})
    observe_latched_runner(r, lines, 201 * 30)
    parks = [s["clock"] for s in status if s["command"] == "run park"]
    assert len(parks) == 2 and max(parks) < 40
    assert any(row["command"] == "state" and row["ok"] for row in status)
    assert r.human_hold_latched and not status[-1]["ok"] and status[-1]["command"] == "stop"


def test_a_chunk_longer_than_the_idle_window_is_not_idle_time():
    lib = library()
    lib["chunks"]["home"] = [HOME]
    lib["chunks"]["long_move"] = [[k * 0.1, *HOME[1:]] for k in range(240)]  # ~8.0 s at 30 fps (> idle_park_s 5.0 s)
    status, clock = [], [0.0]
    sent, next_cmd = [], []
    r = m.Runner(
        Robot(),
        lib,
        fps=30,
        status=lambda row: status.append(dict(row, clock=clock[0])),
        clock=lambda: clock[0],
        sleep=lambda s: clock.__setitem__(0, clock[0] + 1 / 30),
        params={"runner.idle_park_s": 5.0, "runner.idle_stop_s": 5.0},
    )

    def lines():
        if not sent:
            sent.append(1)
            return ["run long_move"]
        if len(sent) == 1 and r.chunk is None and not r.queue and clock[0] >= 7.0:
            sent.append(2)
            next_cmd.extend(["state", "stop"])
        return [next_cmd.pop(0)] if next_cmd else []

    r.run(lines)
    long_done = [s for s in status if s["command"] == "run long_move"][0]
    assert long_done["ok"] is True and long_done["settled"] is True and long_done["clock"] >= 7.0
    assert not [s for s in status if s["command"] == "run park"]
    state_rows = [s for s in status if s["command"] == "state"]
    assert state_rows and state_rows[0]["ok"] is True
    assert status[-1]["command"] == "stop" and "no command" not in status[-1].get("reason", "")


def test_idle_park_still_fires_after_a_long_chunk_when_caller_goes_silent():
    lib = library()
    lib["chunks"]["home"] = [HOME]
    lib["chunks"]["long_move"] = [[k * 0.1, *HOME[1:]] for k in range(240)]  # ~8.0 s at 30 fps (> idle_park_s 5.0 s)
    status, clock, sent = [], [0.0], []
    r = m.Runner(
        Robot(),
        lib,
        fps=30,
        status=lambda row: status.append(dict(row, clock=clock[0])),
        clock=lambda: clock[0],
        sleep=lambda s: clock.__setitem__(0, clock[0] + 1 / 30),
        params={"runner.idle_park_s": 5.0, "runner.idle_stop_s": 5.0},
    )

    def lines():
        if not sent:
            sent.append(1)
            return ["run long_move"]
        return []

    r.run(lines)
    long_done = [s for s in status if s["command"] == "run long_move"][0]
    park_done = [s for s in status if s["command"] == "run park"]
    assert long_done["ok"] is True and long_done["clock"] >= 7.0
    assert len(park_done) == 1 and park_done[0]["ok"] is True
    assert park_done[0]["clock"] > long_done["clock"] + 5.0
    assert status[-1]["command"] == "stop" and "no command" in status[-1]["reason"]
    assert clock[0] >= long_done["clock"] + 10.0
