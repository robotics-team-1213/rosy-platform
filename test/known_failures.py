"""Compare a pytest run against test/known_failures.txt.

Usage (from the repo root):

    python -m pytest <paths> -q -rfE -p no:cacheprovider > run.txt
    python test/known_failures.py run.txt        # or pipe the output on stdin

Exit 0: every FAILED/ERROR line is a listed pre-existing failure or FLAKY.
Exit 1: at least one failure is not listed (the branch introduced it, or the list is stale).
A listed id that did not fail is printed as "not failing here" (fixed, or not selected).

D-762 stage 1: a failure listed in flaky_quarantine.txt that passed on one rerun is FLAKY,
not NEW. The runner (tools/remote/remote_pytest.py, CI) reruns only those ids
(``rerun_ids``) once, with ``-rA``, and appends that output after ``RERUN_MARKER``.
"""

from __future__ import annotations

import argparse
from pathlib import Path
import re
import sys

LIST = Path(__file__).with_name("known_failures.txt")
QUARANTINE = Path(__file__).with_name("flaky_quarantine.txt")
RERUN_MARKER = "=== D-762 flaky quarantine rerun ==="
SUMMARY = re.compile(r"^(?:FAILED|ERROR) (?P<nodeid>\S.*?)(?: - .*)?$")
PASSED = re.compile(r"^PASSED (?P<nodeid>\S+)")
# ROS's launch_testing pytest hook imports each module while collecting and catches only
# Exception, so one module-level pytest.importorskip (Skipped is a BaseException) skips the
# whole session: "collected 0 items / 1 skipped", exit 0. No suite here is a launch test.
# One token each, so callers that read every non-dash word as a path stay right.
NO_ROS_LAUNCH_PLUGINS = ["-pno:launch_testing", "-pno:launch_ros"]
# pytest-xdist prints "6 workers [0 items]" instead of "collected 0 items". Line starts only: a -v test id may
# hold the words (2026-10-29: test_omx_hotfix ids failed a fully passing root-test CI job).
NOTHING_COLLECTED = re.compile(r"^(?:(?:collecting \.\.\. )?collected 0 items\b|\d+ workers? \[0 items\])", re.M)


def collected_nothing(report: str, paths: list[str]) -> bool:
    """A -v run over several paths that collected no item: the session itself was skipped or emptied."""
    return len(paths) > 1 and bool(NOTHING_COLLECTED.search(report.split(RERUN_MARKER, 1)[0]))


def load_known(text: str) -> dict[str, str]:
    known: dict[str, str] = {}
    for line in text.splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        nodeid, _, reason = line.partition("  # ")
        known[nodeid.strip()] = reason.strip()
    return known


def failed_ids(report: str) -> list[str]:
    ids = []
    for line in report.splitlines():
        match = SUMMARY.match(line.strip())
        if match:
            ids.append(match.group("nodeid").replace("\\", "/"))
    return ids


def _matches(failed: str, known: str) -> bool:
    # A run started inside a module (cd middleware/core/gateway) prints a shorter
    # node id; accept it when it is a path-boundary suffix of the listed id.
    return failed == known or known.endswith("/" + failed)


def rerun_ids(report: str, quarantine: dict[str, str]) -> list[str]:
    """Failed ids of the first run that the quarantine lists: the only ones a runner may rerun."""
    first = report.split(RERUN_MARKER, 1)[0]
    return list(dict.fromkeys(f for f in failed_ids(first) if any(_matches(f, q) for q in quarantine)))


def _rerun_clean(ids: list[str], section: str) -> list[str]:
    """Ids the rerun section shows PASSED and never FAILED/ERROR (a teardown error prints both)."""
    passed = {m.group("nodeid").replace("\\", "/") for line in section.splitlines()
              if (m := PASSED.match(line.strip()))}
    bad = set(failed_ids(section))
    return [i for i in ids if i in passed and i not in bad]


def flaky(report: str, quarantine: dict[str, str]) -> list[str]:
    """Quarantined first-run failures that the rerun after RERUN_MARKER passed cleanly."""
    return _rerun_clean(rerun_ids(report, quarantine), report.partition(RERUN_MARKER)[2])


def should_rerun(code: int, failed: list[str], quarantined: list[str]) -> bool:
    """D-762 stage 1: rerun only a pytest exit 1 whose every failure (ERROR lines included) is quarantined."""
    return code == 1 and bool(failed) and set(failed) == set(quarantined)


def rerun_passed(code: int, failed: list[str], quarantined: list[str], rerun_code: int, section: str) -> bool:
    """The one rerun turns the invocation green: it was due, exited 0 and passed every id cleanly."""
    return (should_rerun(code, failed, quarantined) and rerun_code == 0
            and _rerun_clean(quarantined, section) == list(dict.fromkeys(quarantined)))


def compare(report: str, known: dict[str, str]) -> tuple[list[str], list[str], list[str]]:
    """Return (new failures, listed failures seen, listed ids not failing) of the first run."""
    new, seen = [], []
    for failed in failed_ids(report.split(RERUN_MARKER, 1)[0]):
        hit = next((k for k in known if _matches(failed, k)), None)
        if hit is None:
            new.append(failed)
        elif hit not in seen:
            seen.append(hit)
    quiet = [k for k in known if k not in seen]
    return new, seen, quiet


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("report", nargs="?", help="saved pytest output (default: stdin)")
    parser.add_argument("--must-fail", action="append", default=[], metavar="NODEID",
                        help="a listed id this run must see failing (land.py: ids the landing adds to the list)")
    args = parser.parse_args(argv)
    if args.report:
        data = Path(args.report).read_bytes()
        report = data.decode(
            "utf-16" if data.startswith((b"\xff\xfe", b"\xfe\xff")) else "utf-8-sig",
            errors="replace",
        )
    else:
        report = sys.stdin.read()
    new, seen, quiet = compare(report, load_known(LIST.read_text(encoding="utf-8")))
    passed_once = flaky(report, load_known(QUARANTINE.read_text(encoding="utf-8")) if QUARANTINE.is_file() else {})
    new = [nodeid for nodeid in new if nodeid not in passed_once]
    for nodeid in seen:
        print(f"known     {nodeid}")
    for nodeid in quiet:
        print(f"not failing here  {nodeid}")
    for nodeid in passed_once:
        print(f"FLAKY     {nodeid}")
    for nodeid in new:
        print(f"NEW       {nodeid}")
    # Design 0.7 rule 7: a line added to the list must hide a real failure, not a passing test.
    passing = [nodeid for nodeid in args.must_fail if nodeid not in seen]
    for nodeid in passing:
        print(f"MUST-FAIL {nodeid}  (added to known_failures.txt, but it did not fail here)")
    print(f"{len(new)} new, {len(seen)} known, {len(passed_once)} flaky, {len(quiet)} listed but not failing")
    return 1 if new or passing else 0


if __name__ == "__main__":
    raise SystemExit(main())
