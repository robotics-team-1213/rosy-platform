"""os_lock: a second holder is refused while the first holds the lock, and admitted after it lets go."""

import multiprocessing
from pathlib import Path
import sys

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools"))
import os_lock  # noqa: E402


def _try(path: str, out) -> None:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools"))
    import os_lock as lock
    try:
        with lock.locked(Path(path)):
            out.put("got")
    except lock.Busy:
        out.put("busy")


def _other_process(path: Path) -> str:
    out = multiprocessing.get_context("spawn").Queue()
    proc = multiprocessing.get_context("spawn").Process(target=_try, args=(str(path), out))
    proc.start()
    proc.join(30)
    return out.get(timeout=5)


def test_a_held_lock_refuses_another_process_and_frees_on_release(tmp_path):
    path = tmp_path / "x.lock"
    with os_lock.locked(path):
        assert _other_process(path) == "busy"
    assert _other_process(path) == "got"


def test_busy_is_a_system_exit_so_an_uncaught_refusal_ends_the_command():
    assert issubclass(os_lock.Busy, SystemExit)
    with pytest.raises(os_lock.Busy):
        raise os_lock.Busy("x")
