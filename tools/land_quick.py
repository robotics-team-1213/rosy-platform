"""D-436 addendum (fail-fast): a quick static-contract run on a test host before a landing takes a queue ticket.

One-line doc and contract misses stopped long landings only after the heavy suites (7 days: 23 of 30 landings over
2 h had NEW failures). These files import no ROS or browser and run in under a minute; they run first, with the
turn's host priority, and a confirmed NEW failure stops the landing before it waits for the queue.
"""

from __future__ import annotations

import os
import threading
from pathlib import Path

WAIT_S = 180.0  # a quick check never waits for a full pool: the real rounds do that
QUICK = (
    "test/architecture/test_module_structure.py",
    "test/architecture/test_document_placement.py",
    "test/test_harness_contracts.py",
    "test/test_release_boundary_guards.py",
    "test/test_native_systemd_contract.py",
    "middleware/core/gateway/test/test_protocol_version_alignment.py",
    "middleware/core/gateway/test/test_event_catalogue.py",
)


def run(land, wt: Path, python: str, quick: tuple[str, ...] = QUICK) -> None:
    """Stop (``land.Stop``) on a confirmed NEW failure; a host that cannot be reached is not a verdict, so the landing goes on."""
    present = [p for p in quick if (wt / p).is_file()]
    if not present or os.environ.get("ROSY_LAND_NO_QUICK"):
        return
    head = land.out(wt, "rev-parse", "HEAD")
    logdir = land.tmp_dir(land.out(wt, "rev-parse", "--abbrev-ref", "HEAD"))
    log = logdir / "quick.txt"
    inv = [present]
    land.os.environ[land.TURN_ENV] = "1"  # queue-jumping on the hosts: seconds, not a full job
    stop = threading.Event()
    timer = threading.Timer(WAIT_S, stop.set)
    timer.daemon = True
    timer.start()
    try:
        codes = land.remote_pytest.run(inv, [log], head, repo=wt, label="land-quick", stop=stop)
    except SystemExit as exc:  # no host / pool full: leave it to the real rounds, which wait properly
        print(f"[quick] skipped: {exc}", flush=True)
        return
    finally:
        timer.cancel()
        land.os.environ[land.TURN_ENV] = ""
    if codes == [land.remote_pytest.CANCELLED]:
        print("[quick] skipped: no host free within the quick budget", flush=True)
        return
    if codes == [0]:
        print(f"[quick] {len(present)} contract file(s) passed", flush=True)
        return
    code, flaky, why = land.land_checks.verdict(wt, present, log, logdir, "quick", python, land.remote_pytest.run, head)
    if code and not flaky:
        raise land.Stop(f"quick contract check failed before taking a queue ticket:\n{why[-2000:]}")
