"""Contact polls remain off the control thread and retain their oldest sample time."""
import importlib
import importlib.util
import threading

from core_features.docking.agent import DockReachability, DockStatus


def poller(poll, now, utc):
    name = 'core_features.docking.station_sensors'
    assert importlib.util.find_spec(name) is not None, 'station sensor cache is missing'
    return importlib.import_module(name).StationDockPoller(
        poll, clock=lambda: now[0], source_clock=lambda: utc[0], interval_s=60.0, max_age_s=0.25)


def test_slow_poll_does_not_run_on_control_thread_and_cannot_become_fresh_at_reply():
    now, utc = [10.], [100.]
    entered, finish = threading.Event(), threading.Event()

    def slow():
        entered.set()
        finish.wait(1.)
        return DockStatus(DockReachability.OK, load_present=True)

    value = poller(slow, now, utc)
    value.start()
    try:
        assert entered.wait(1.)
        assert value.snapshot() is None  # No HTTP call or wait on this path.
        now[0], utc[0] = 10.5, 100.5
        finish.set()
        assert value.poll_finished.wait(1.)
        assert value.snapshot() is None  # HTTP request itself consumed the freshness budget.
    finally:
        finish.set()
        value.close()


def test_snapshot_keeps_source_and_local_start_times_and_expires():
    now, utc = [10.], [100.]
    value = poller(lambda: DockStatus(DockReachability.OK, load_present=True), now, utc)
    value.poll_once()
    sample = value.snapshot()
    assert sample.status.load_present and sample.source_at == 100. and sample.monotonic_at == 10.
    now[0] = 10.3
    assert value.snapshot() is None
    value.close()
    assert value.snapshot() is None


def test_poll_failure_replaces_previous_contact_instead_of_replaying_it():
    now, utc = [10.], [100.]
    fail = [False]

    def read():
        if fail[0]:
            raise OSError('connection lost')
        return DockStatus(DockReachability.OK, load_present=True)

    value = poller(read, now, utc)
    value.poll_once()
    assert value.snapshot() is not None
    fail[0] = True
    value.poll_once()
    assert value.snapshot() is None
    value.close()
