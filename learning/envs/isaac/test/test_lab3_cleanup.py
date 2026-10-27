"""Async Kit helpers get a bounded drain, never an unconditional success."""
import importlib.util
from pathlib import Path

import pytest

SOURCE = Path(__file__).resolve().parents[1] / 'lab3' / 'cleanup.py'


def module():
    spec = importlib.util.spec_from_file_location('lab3_cleanup', SOURCE)
    result = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(result)
    return result


def exercise(monkeypatch, states, timeout=3):
    api = module()
    clock = [0.0]
    pending = iter(states)
    latest = [states[-1]]

    def observe():
        latest[0] = next(pending, latest[0])
        return latest[0]

    monkeypatch.setattr(api, 'snapshot', observe)
    monkeypatch.setattr(api.time, 'monotonic', lambda: clock[0])
    monkeypatch.setattr(api.time, 'sleep', lambda seconds: clock.__setitem__(0, clock[0] + seconds))
    return api.wait_for_cleanup(timeout=timeout, interval=1)


CLEAN = {'owned_pids': [], 'gpu_pids': [], 'gpu_query_exit': 0}


def test_waits_for_observed_transmitter_drain(monkeypatch):
    busy = dict(CLEAN, owned_pids=[42])
    result = exercise(monkeypatch, [busy, busy, CLEAN])
    assert result['clean'] is True
    assert len(result['observations']) == 3
    assert result['elapsed_seconds'] == 2


@pytest.mark.parametrize('state', [dict(CLEAN, owned_pids=[42]), dict(CLEAN, gpu_pids=[99]), dict(CLEAN, gpu_query_exit=1)])
def test_persistent_process_gpu_or_query_error_is_failure(monkeypatch, state):
    result = exercise(monkeypatch, [state])
    assert result['clean'] is False
    assert result['elapsed_seconds'] == 3
    assert result['observations'][-1] == state


def test_clean_state_needs_no_sleep(monkeypatch):
    result = exercise(monkeypatch, [CLEAN])
    assert result['clean'] is True
    assert result['elapsed_seconds'] == 0
