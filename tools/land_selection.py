"""land.py selection and changed-path browser tier, with the calling module passed in.

The caller owns Stop, subprocess/environment and helper seams, including when land
runs as __main__. Keep its public wrappers and defaults in the gateway.
"""

from __future__ import annotations

import json
from pathlib import Path

SAFETY_TRIGGER = ": safety path (platform_parts concern: safety)"  # affected_tests.SAFETY_TRIGGER


def _affected(land, wt: Path, python: str, base: str, head: str | None) -> dict:
    # Strict UTF-8: the JSON must parse whole; PYTHONUTF8 makes the child write UTF-8.
    result = land.subprocess.run([python, land.HARNESS, "affected", "--base", base, *(["--head", head] if head else []),
                                  "--json"], cwd=wt,
                                 capture_output=True, text=True, encoding="utf-8", env=land.ENV)
    if result.returncode != 0:
        raise land.Stop(f"affected selector failed (exit {result.returncode}); not guessing tests:\n"
                        f"{result.stdout}{result.stderr}".rstrip())
    return json.loads(result.stdout)


def _unique(invocations: list[list[str]]) -> list[list[str]]:
    return [list(inv) for inv in dict.fromkeys(map(tuple, invocations))]


def select(land, wt: Path, base: str, python: str, head: str | None = None,
           landed: bool = False) -> tuple[list[list[str]], str | None]:
    """pytest invocations for base...HEAD (or base...head), and a FULL note owed to the summary.

    The D-436 selector (`rosy_harness.py affected`) when the harness is present —
    it adds the guard set and reverse dependents — otherwise the nearest test/ dir.
    ``landed``: base...head is main's delta, already on main with its own FULL tier when it escalated.
    """
    if (wt / "tools/harness/affected_tests.py").is_file():
        try:
            sel = _affected(land, wt, python, base, head)
            # D-889 3 (combined affected, not FULL per cycle): a delta that escalated landed on main with its own
            # FULL tier, and this branch passed its own tier before the turn. Repeating FULL for every lander
            # behind a FULL landing was 35 % of pretest time on 2026-10-26; what is left is both changes' own
            # suites on the merged tree. Safety paths on either side keep FULL (D-889 6).
            own = _affected(land, wt, python, head, None) if landed and head and sel["escalations"] else None
            if own is not None and not any(e.endswith(SAFETY_TRIGGER) for e in sel["escalations"] + own["escalations"]):
                print("[tests] main's delta escalated but landed with its own FULL tier: its mapped suites and"
                      " this branch's own selection on the merged tree")
                mine = own["local_invocations"] if own["mode"] == "full" else own["invocations"]
                return _unique(sel["local_invocations"] + mine + land.browser_tier(wt, base, head)
                               + land.browser_tier(wt, head)), None
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
