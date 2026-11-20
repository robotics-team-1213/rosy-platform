"""Interrupts reach only the main thread, so gated_close's main-thread block holds for the whole process (Linux).

Each case runs in a fresh interpreter, as chunk_runner.py does: routing first, then the imports and a worker thread."""
import json
from pathlib import Path
import signal
import subprocess
import sys

import pytest

OMX = Path(__file__).parents[1] / "deploy/robot/omx"
ADAPTER = Path(__file__).parents[1] / "middleware/devices/omx/adapter"  # chunk_runner.py adds it to sys.path itself

pytestmark = pytest.mark.skipif(not hasattr(signal, "pthread_sigmask") or not Path("/proc/self/task").is_dir(),
                                reason="Linux only: pthread_sigmask and /proc/self/task")

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


def test_with_routing_no_other_thread_takes_sigterm_and_the_close_is_untouched():
    out = probe("routed")
    assert out["unrouted"] == [] and out["during_close"] is False and out["after"] is True


def test_without_routing_a_worker_takes_sigterm_and_the_handler_runs_inside_the_close():
    """The control: what review 7 found. An unblocked worker accepts SIGTERM while the main thread blocks it."""
    out = probe("plain")
    assert out["worker"] in out["unrouted"] and out["during_close"] is True


def test_route_names_threads_that_already_existed():
    code = ("import sys, threading; sys.path.insert(0, sys.argv[1]); import main_thread_signals as mts; "
            "e = threading.Event(); threading.Thread(target=e.wait, daemon=True).start(); print(mts.route())")
    done = subprocess.run([sys.executable, "-c", code, str(OMX)], capture_output=True, text=True, timeout=60)
    assert "Thread-" in done.stdout and "may take SIGTERM" in done.stderr
