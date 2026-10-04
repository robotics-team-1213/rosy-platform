"""Driver-side stale command protection tests."""

import pytest

from bringup.command_deadman import CommandDeadman


class FakeClock:
    def __init__(self) -> None:
        self.now = 0.0

    def __call__(self) -> float:
        return self.now


def test_deadman_is_unarmed_until_first_command():
    clock = FakeClock()
    deadman = CommandDeadman(timeout_s=0.5, clock=clock)

    clock.now = 10.0

    assert deadman.should_stop() is False


def test_deadman_remains_expired_until_stop_is_confirmed():
    clock = FakeClock()
    deadman = CommandDeadman(timeout_s=0.5, clock=clock)
    deadman.mark_command()

    clock.now = 0.49
    assert deadman.should_stop() is False

    clock.now = 0.50
    assert deadman.should_stop() is True
    assert deadman.should_stop() is True

    deadman.mark_stopped()
    assert deadman.should_stop() is False


def test_new_command_rearms_deadman_after_expiry():
    clock = FakeClock()
    deadman = CommandDeadman(timeout_s=0.5, clock=clock)
    deadman.mark_command()
    clock.now = 0.5
    assert deadman.should_stop() is True


def test_failed_stop_is_retried_until_driver_acknowledges():
    clock = FakeClock()
    deadman = CommandDeadman(timeout_s=0.5, clock=clock)
    deadman.mark_command()
    clock.now = 0.5
    attempts = iter([False, True])

    assert deadman.attempt_stop(lambda: next(attempts)) is False
    assert deadman.should_stop() is True
    assert deadman.attempt_stop(lambda: next(attempts)) is True
    assert deadman.should_stop() is False
    deadman.mark_stopped()

    clock.now = 2.0
    deadman.mark_command()
    clock.now = 2.5

    assert deadman.should_stop() is True


def test_timeout_must_be_positive():
    with pytest.raises(ValueError, match="timeout_s must be positive"):
        CommandDeadman(timeout_s=0.0)


def test_unconfirmed_stop_arms_an_immediate_retry_from_disarmed_state():
    clock = FakeClock()
    deadman = CommandDeadman(0.5, clock=clock)
    attempts = iter([False, True])

    deadman.mark_stop_required()

    assert deadman.should_stop() is True
    assert deadman.attempt_stop(lambda: next(attempts)) is False
    assert deadman.should_stop() is True
    assert deadman.attempt_stop(lambda: next(attempts)) is True
    assert deadman.should_stop() is False
