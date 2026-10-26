"""land.py selection and changed-path browser tier, with the calling module passed in.

The caller owns Stop, subprocess/environment and helper seams, including when land
runs as __main__. Keep its public wrappers and defaults in the gateway.
"""

from __future__ import annotations

import json
from pathlib import Path


def select(land, wt: Path, base: str, python: str, head: str | None = None,
           landed: bool = False) -> tuple[list[list[str]], str | None]:
    """pytest invocations for base...HEAD (or base...head), and a FULL note owed to the summary.

    The D-436 selector (`rosy_harness.py affected`) when the harness is present —
    it adds the guard set and reverse dependents — otherwise the nearest test/ dir.
    ``landed``: base...head is main's delta, already on main with its own FULL tier when it escalated.
    """
    if (wt / "tools/harness/affected_tests.py").is_file():
        # Strict UTF-8: the JSON must parse whole; PYTHONUTF8 makes the child write UTF-8.
        result = land.subprocess.run([python, land.HARNESS, "affected", "--base", base, *(["--head", head] if head else []),
                                 "--json"], cwd=wt,
                                capture_output=True, text=True, encoding="utf-8", env=land.ENV)
        if result.returncode != 0:
            raise land.Stop(f"affected selector failed (exit {result.returncode}); not guessing tests:\n"
                       f"{result.stdout}{result.stderr}".rstrip())
        try:
            sel = json.loads(result.stdout)
            if landed and sel["escalations"] and all(e.endswith(land.HARNESS_TRIGGER) for e in sel["escalations"]):
                # A harness edit on main passed its own FULL tier when it landed; a FULL tier for every lander
                # behind it held the queue an hour each (2026-10-25). Its guards and mapped suites still run.
                print("[tests] main's delta escalated only for harness files that landed with their own FULL"
                      " tier: the guards and its mapped suites")
                return sel["local_invocations"] + land.browser_tier(wt, base, head), None
            if sel["mode"] == "full":
                # D-762 stage 0: a FULL-class landing runs the whole tier on the lab PCs, never
                # guards alone; not via GitHub, which would publish unpushed main commits.
                note = "selector escalated to FULL (" + "; ".join(sel["escalations"][:3]) + "): full tier on the lab PCs"
                print(f"[tests] {note}")
                return sel["full_invocations"] + land.browser_tier(wt, base, head), note
            return sel["invocations"] + land.browser_tier(wt, base, head), None
        except (ValueError, KeyError, TypeError) as exc:
            raise land.Stop(f"affected selector printed unusable JSON ({exc!r}); not guessing tests") from exc
    changed = land.lines(wt, "diff", "--name-only", f"{base}...{head or 'HEAD'}")  # main's delta when head is given
    return land.pack(wt, land.fallback_targets(wt, changed)) + land.browser_tier(wt, base, head), None


def browser_tier(land, wt: Path, base: str, head: str | None = None) -> list[list[str]]:
    """The real-Chromium tests for the paths base...head changes, opted in on the test host only."""
    changed = land.lines(wt, "diff", "--name-only", f"{base}...{head or 'HEAD'}")
    return [inv for group in land.pack(wt, land.browser_scope.targets(changed)) for inv in land.land_browser.chunks(wt, group)]
