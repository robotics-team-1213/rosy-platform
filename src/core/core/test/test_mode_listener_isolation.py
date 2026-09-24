"""A mode listener that raises cannot undo a committed mode change (N3).

`ModeMachine.transition` commits the mode and then calls its listeners. An
exception from one of them used to escape to the caller *after* the commit: the
e-stop API then skipped `trigger_estop`, so the mode said EMERGENCY while the
latch was never set, and the other listeners never ran.
"""

from __future__ import annotations

import pytest

from core_features.command.arbitration import Mode, ModeMachine
from core_features.command.manager import ZERO, Twist
from core.bridge.cmd_vel import cmd_vel_cycle

from test_docking_mode_ownership import OPERATOR, docking_robot, wheels


def boom(old, new):
    raise RuntimeError("listener failed")


def test_a_raising_listener_neither_escapes_nor_stops_the_others():
    modes = ModeMachine()
    seen = []
    modes.change_listeners.extend([boom, lambda old, new: seen.append((old, new))])
    assert modes.transition(Mode.NAVIGATION) == (True, "")
    assert modes.mode is Mode.NAVIGATION
    assert seen == [(Mode.IDLE, Mode.NAVIGATION)]


def test_an_estop_with_a_raising_listener_still_latches_and_stops(core_client):
    client, services = docking_robot(core_client)
    services.modes.change_listeners.insert(0, boom)
    services.command.set_docking_twist(Twist(0.03, 0.1))
    response = client.post("/api/v1/safety/stop", headers=OPERATOR)
    assert response.status_code == 200, response.text
    assert services.safety.estop
    assert services.modes.mode is Mode.EMERGENCY
    assert wheels(services) == (0.0, 0.0)


def test_the_estop_latch_is_set_before_the_mode_listeners_run(core_client):
    client, services = docking_robot(core_client)
    latched = []
    services.modes.change_listeners.insert(
        0, lambda old, new: latched.append(services.safety.estop))
    client.post("/api/v1/safety/stop", headers=OPERATOR)
    assert latched == [True]


def test_leaving_docking_clears_the_slot_even_if_the_cancel_raises(core_client):
    _, services = docking_robot(core_client)

    def cancel_fails():
        raise RuntimeError("cancel failed")

    services.docking.cancel = cancel_fails
    services.command.set_docking_twist(Twist(0.03, 0.1))
    assert services.modes.transition(Mode.IDLE) == (True, "")
    assert services.command._docking_twist is None


class RaisingCommand:
    announced = False

    def select_output(self):
        raise RuntimeError("policy failed")

    def announce_pending(self):
        self.announced = True


class Power:
    def on_activity(self, source):
        raise AssertionError("no activity on a failed cycle")


def test_a_raising_output_policy_sends_zero_and_keeps_the_timer_alive():
    sent, warnings = [], []
    cmd_vel_cycle(RaisingCommand(), Power(), sent.append, warn=warnings.append)
    assert sent == [ZERO]
    assert warnings and "policy failed" in warnings[0]


def test_a_raising_output_policy_without_a_logger_still_sends_zero():
    sent = []
    cmd_vel_cycle(RaisingCommand(), Power(), sent.append)
    assert sent == [ZERO]


@pytest.mark.parametrize("raises", [False, True])
def test_the_policy_estop_latches_before_the_mode_changes(core_client, raises):
    """`_policy_output`'s refusal path: latch first, then EMERGENCY."""
    _, services = docking_robot(core_client)
    latched = []
    services.modes.change_listeners.insert(
        0, lambda old, new: latched.append(services.safety.estop))
    if raises:
        services.modes.change_listeners.insert(0, boom)
    services.safety.evaluate_candidate = lambda *args, **kwargs: None
    services.command.set_docking_twist(Twist(0.03, 0.1))
    assert services.command.select_output() == ZERO
    assert services.safety.estop
    assert services.modes.mode is Mode.EMERGENCY
    assert latched == [True]
