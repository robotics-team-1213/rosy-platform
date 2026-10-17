"""Input invalidation must serialize with the mode lock used by final submission."""

from queue import Queue
import threading
from types import SimpleNamespace

import pytest

from core_features.command.arbitration import Mode, ModeMachine, SourceRegistry
from core_features.command.manager import CommandManager, Twist
from core_features.safety.manager import BatteryPolicy, SafetyManager, SpeedLimits
from core.bridge.cmd_vel import cmd_vel_cycle


class ProbeLock:
    def __init__(self, lock, modes, messages):
        self.lock, self.modes, self.messages = lock, modes, messages

    def acquire(self, *args, **kwargs):
        if threading.current_thread() is self.modes.worker:
            self.messages.put("lock-attempt")
        return self.lock.acquire(*args, **kwargs)

    def release(self):
        self.lock.release()

    def __enter__(self):
        self.acquire()
        return self

    def __exit__(self, *_):
        self.release()


class PausingModes(ModeMachine):
    def __init__(self):
        super().__init__()
        self.worker = None
        self.pause_epoch = False
        self.epoch_read = threading.Event()
        self.continue_clear = threading.Event()

    @property
    def epoch(self):
        value = super().epoch
        if threading.current_thread() is self.worker and self.pause_epoch:
            self.pause_epoch = False
            self.epoch_read.set()
            if not self.continue_clear.wait(3):
                raise RuntimeError("test did not release epoch read")
        return value


@pytest.mark.parametrize("slot,mode", [("navigation", Mode.NAVIGATION),
                                     ("docking", Mode.DOCKING), ("manual", Mode.MANUAL)])
def test_clear_cannot_mutate_after_epoch_read_while_final_mode_fence_is_held(slot, mode):
    modes = PausingModes()
    safety = SafetyManager(SpeedLimits(), BatteryPolicy())
    command = CommandManager(SourceRegistry(), modes, safety)
    assert modes.transition(mode)[0]
    if slot == "manual":
        assert command.teleop(.1, 0.) == (True, "")
        candidate_name = "_manual_twist"
        action = command.clear_manual
    else:
        setter = command.set_nav_twist if slot == "navigation" else command.set_docking_twist
        setter(Twist(.1, 0.), now=10.)
        action = lambda: setter(None)
        candidate_name = "_nav_input" if slot == "navigation" else "_docking_input"
    candidate = getattr(command, candidate_name)
    epoch = command._input_epoch
    native = command.native.current
    messages = Queue()
    modes._lock = ProbeLock(modes._lock, modes, messages)

    def clear():
        try:
            action()
            messages.put("completed")
        except BaseException as exc:
            messages.put(exc)

    worker = threading.Thread(target=clear, daemon=True)
    modes.worker = worker
    try:
        if slot != "manual":
            # Let the existing first epoch read finish before taking the final
            # mode fence. A lock around that read alone cannot serialize clear.
            modes.pause_epoch = True
            worker.start()
            assert modes.epoch_read.wait(3)
            assert messages.get(timeout=3) == "lock-attempt"
        with modes._lock:
            if slot == "manual":
                worker.start()
            else:
                modes.continue_clear.set()
            assert messages.get(timeout=3) == "lock-attempt"
            assert getattr(command, candidate_name) is candidate
            assert command._input_epoch == epoch
            assert command.native.current is native
    finally:
        modes.continue_clear.set()
        worker.join(timeout=3)
    assert not worker.is_alive()
    assert messages.get(timeout=3) == "completed"
    assert getattr(command, candidate_name) is None
    assert command._input_epoch == epoch + 1
    assert command.select_output(now=10.01) == Twist()


def manual_rig():
    modes = PausingModes()
    safety = SafetyManager(SpeedLimits(), BatteryPolicy())
    command = CommandManager(SourceRegistry(), modes, safety)
    assert modes.transition(Mode.MANUAL)[0]
    assert command.teleop(.1, 0.) == (True, "")
    return command, modes


@pytest.mark.parametrize("cause", ["clear", "mode-transition", "policy-clear"])
def test_native_receipt_contention_does_not_delay_the_actual_zero_writer(cause, monkeypatch):
    command, modes = manual_rig()
    messages, sent = Queue(), Queue()
    command._native_lock = ProbeLock(command._native_lock, modes, messages)
    action = command.clear_manual if cause == "clear" else lambda: modes.transition(Mode.IDLE)
    if cause == "policy-clear":
        assert modes.transition(Mode.IDLE)[0]
        assert modes.transition(Mode.NAVIGATION)[0]
        command.set_nav_twist(Twist(.1, 0.), now=10.)
        select = command.select_output
        monkeypatch.setattr(command, "select_output", lambda: select(now=10.01))
        action = command._clear_for_stop  # The real registered policy/E-stop listener.
    clear = threading.Thread(target=action, daemon=True)
    modes.worker = clear
    writer = threading.Thread(
        target=lambda: cmd_vel_cycle(command, SimpleNamespace(on_activity=lambda _: None),
                                     lambda out: sent.put((out.linear, out.angular))), daemon=True)
    try:
        with command._native_lock:
            clear.start()
            assert messages.get(timeout=3) == "lock-attempt"
            writer.start()
            # Announcements may wait on receipt metadata AFTER wheels receive zero.
            assert sent.get(timeout=3) == (0., 0.)
    finally:
        clear.join(timeout=3)
        if writer.ident is not None:
            writer.join(timeout=3)
    assert not clear.is_alive() and not writer.is_alive()


def test_late_native_close_cannot_cancel_a_new_manual_pulse(monkeypatch):
    command, _ = manual_rig()
    entered, proceed = threading.Event(), threading.Event()
    original = command._close_native_pulse

    def delayed_close(result, reason, session=None):
        entered.set()
        if not proceed.wait(3):
            raise RuntimeError("test did not release native close")
        original(result, reason, session)

    monkeypatch.setattr(command, "_close_native_pulse", delayed_close)
    clear = threading.Thread(target=command.clear_manual, daemon=True)
    clear.start()
    try:
        assert entered.wait(3)
        assert command.teleop(.12, 0.) == (True, "")
        replacement = command.native.current
        candidate = command._manual_twist
    finally:
        proceed.set()
        clear.join(timeout=3)
    assert not clear.is_alive()
    assert command.native.current is replacement
    assert command.native.current.phase != "TERMINAL"
    assert command._manual_twist is candidate and candidate is not None
