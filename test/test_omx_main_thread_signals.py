"""Interrupts reach only the main thread, so gated_close's main-thread block holds for the whole process (Linux).

Each case runs in a fresh interpreter, as chunk_runner.py does: routing first, then the imports and a worker thread."""
import json
import os
from pathlib import Path
import signal
import subprocess
import sys

import pytest

OMX = Path(__file__).parents[1] / "deploy/robot/omx"
ADAPTER = Path(__file__).parents[1] / "middleware/devices/omx/adapter"  # chunk_runner.py adds it to sys.path itself

linux_only = pytest.mark.skipif(not hasattr(signal, "pthread_sigmask") or not Path("/proc/self/task").is_dir(),
                                reason="Linux only: pthread_sigmask and /proc/self/task")
sys.path[:0] = [str(OMX), str(ADAPTER)]  # as chunk_runner.py: its folder and the omx_adapter source
try:
    import chunk_runner_interrupt as ci  # noqa: E402
    import main_thread_signals as mts  # noqa: E402
finally:
    sys.path.remove(str(OMX))
    sys.path.remove(str(ADAPTER))

PROBE = r"""
import json, os, signal, sys, threading, time
sys.path[:0] = [sys.argv[2], sys.argv[3]]  # as chunk_runner.py does: its folder and the omx_adapter source
import main_thread_signals as mts
routed = sys.argv[1] == "routed"
if routed:
    mts.route()
import chunk_runner_interrupt as ci  # the runner's own imports (may start threads)
if routed:
    mts.unblock_main()
stop = threading.Event()
worker = threading.Thread(target=lambda: stop.wait(5), daemon=True)
worker.start()
unrouted = mts.unrouted_threads()
signals, seen = [], []
ci.install(signals)

def close():  # disable_torque would run here: give a stray delivery every chance to run the handler
    os.kill(os.getpid(), signal.SIGTERM)
    deadline = time.monotonic() + 0.3
    while time.monotonic() < deadline:
        sum(range(200))
    seen.append(signal.SIGTERM in signals)

r = type("R", (), {"hold_file": None, "_off_approved": "park settled and home"})()
ci.gated_close(r, signals, None, close)
for _ in range(100):
    if signal.SIGTERM in signals:
        break
    time.sleep(0.01)
stop.set()
print(json.dumps({"unrouted": unrouted, "worker": worker.native_id, "during_close": seen[0],
                  "after": signal.SIGTERM in signals}))
"""


def probe(mode):
    done = subprocess.run([sys.executable, "-c", PROBE, mode, str(OMX), str(ADAPTER)], capture_output=True, text=True, timeout=60)
    assert done.returncode == 0, done.stderr
    return json.loads(done.stdout.strip().splitlines()[-1])


@linux_only
def test_with_routing_no_other_thread_takes_sigterm_and_the_close_is_untouched():
    out = probe("routed")
    assert out["unrouted"] == [] and out["during_close"] is False and out["after"] is True


@linux_only
def test_without_routing_a_worker_takes_sigterm_and_the_handler_runs_inside_the_close():
    """The control: what review 7 found. An unblocked worker accepts SIGTERM while the main thread blocks it."""
    out = probe("plain")
    assert out["worker"] in out["unrouted"] and out["during_close"] is True


@linux_only
def test_route_names_threads_that_already_existed():
    code = ("import sys, threading; sys.path.insert(0, sys.argv[1]); import main_thread_signals as mts; "
            "e = threading.Event(); threading.Thread(target=e.wait, daemon=True).start(); print(mts.route())")
    done = subprocess.run([sys.executable, "-c", code, str(OMX)], capture_output=True, text=True, timeout=60)
    assert "Thread-" in done.stdout and "may take SIGTERM" in done.stderr


NUMPY_PROBE = r"""
import json, os, sys
sys.path[:0] = [sys.argv[2]]
import main_thread_signals as mts
early = sys.argv[1] == "numpy-first"
if early:
    import numpy
mts.route()
import numpy  # OpenBLAS starts its pool here (or at the first product)
a = numpy.ones((400, 400))
(a @ a).sum()
unrouted = mts.unblock_main()
print(json.dumps({"tasks": len(os.listdir("/proc/self/task")), "unrouted": unrouted}))
"""


def numpy_probe(mode):
    env = {**os.environ, "OPENBLAS_NUM_THREADS": "4", "OMP_NUM_THREADS": "4"}  # make the pool exist on purpose
    done = subprocess.run([sys.executable, "-c", NUMPY_PROBE, mode, str(OMX)], capture_output=True, text=True,
                          timeout=120, env=env)
    if "No module named 'numpy'" in done.stderr:
        pytest.skip("numpy is not installed in this venv")
    assert done.returncode == 0, done.stderr
    return json.loads(done.stdout.strip().splitlines()[-1])


@linux_only
def test_openblas_threads_started_after_routing_block_the_signals():
    out = numpy_probe("routed")
    if out["tasks"] == 1:
        pytest.skip("this numpy starts no BLAS threads")
    assert out["unrouted"] == []


@linux_only
def test_openblas_threads_started_before_routing_are_found():
    """The control for review 8: a pool started with an open mask is reported (and gated_close re-checks)."""
    out = numpy_probe("numpy-first")
    if out["tasks"] == 1:
        pytest.skip("this numpy starts no BLAS threads")
    assert out["unrouted"]


def test_quiet_blas_sets_one_thread_unless_the_caller_chose():
    env = {"OMP_NUM_THREADS": "8"}
    mts.quiet_blas(env)
    assert env == {"OMP_NUM_THREADS": "8", "OPENBLAS_NUM_THREADS": "1", "MKL_NUM_THREADS": "1"}


def test_gated_close_rechecks_right_before_the_torque_off():
    """A handler that runs between the verdict and the close (a signal taken by an unrouted thread): no close."""
    class LateSignal(list):
        reads = 0

        def __iter__(self):
            LateSignal.reads += 1
            if LateSignal.reads == 2 and signal.SIGTERM not in list.__iter__(self):
                list.append(self, signal.SIGTERM)  # recorded just after the first verdict
            return list.__iter__(self)

    signals, closed, slept = LateSignal(), [], []
    r = type("R", (), {"hold_file": None})()

    def sleep(s):
        slept.append(s)
        if len(slept) == 2:
            signals.append(ci.OPERATOR_RELEASE or 12)

    saved = ci.OPERATOR_RELEASE
    ci.OPERATOR_RELEASE = saved or 12
    try:
        ci.gated_close(r, signals, None, lambda: closed.append(len(slept)), sleep=sleep)
    finally:
        ci.OPERATOR_RELEASE = saved
    assert closed == [2]  # not at the verdict: only after the hold and the person's release
