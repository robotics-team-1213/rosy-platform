"""land.py selection and changed-path browser tier, with the calling module passed in.

The caller owns Stop, subprocess/environment and helper seams, including when land
runs as __main__. Keep its public wrappers and defaults in the gateway.
"""

from __future__ import annotations

import json
from harness import affected_exclusive
import sys
from pathlib import Path

SAFETY_TRIGGER = ": safety path (platform_parts concern: safety)"  # affected_tests.SAFETY_TRIGGER
# D-889 addendum 12: simulation suites in an automatic FULL tier only when the change touches simulation.
SIM_SUITES = ("integrations/simulation/gazebo/test", "learning/envs/isaac/test")
SIM_PATHS = ("integrations/simulation/", "learning/envs/isaac/")


def without_sim(invocations: list[list[str]], changed: list[str]) -> list[list[str]]:
    """An automatic FULL tier without the simulation suites, unless a changed path is simulation's own."""
    if any(p.startswith(SIM_PATHS) for p in changed):
        return invocations
    kept = [[w for w in inv if not any(w == s or w.startswith(s + "/") for s in SIM_SUITES)] for inv in invocations]
    return [inv for inv in kept if any(not w.startswith(("ROSY_", "-")) for w in inv)]


def _affected(land, wt: Path, python: str, base: str, head: str | None, full: bool = False) -> dict:
    # Strict UTF-8: the JSON must parse whole; PYTHONUTF8 makes the child write UTF-8.
    result = land.subprocess.run([python, land.HARNESS, "affected", "--base", base, *(["--head", head] if head else []),
                                  "--json", *(["--full"] if full else [])], cwd=wt,
                                 capture_output=True, text=True, encoding="utf-8", env=land.ENV)
    if result.returncode != 0:
        raise land.Stop(f"affected selector failed (exit {result.returncode}); not guessing tests:\n"
                        f"{result.stdout}{result.stderr}".rstrip())
    return json.loads(result.stdout)


def _guard_set() -> tuple[str, ...]:
    """The selector's guard set (affected_tests.GUARD_SET): every selection carries it, so sharing it says
    nothing about two changes meeting (D-889 25)."""
    sys.path.insert(0, str(Path(__file__).resolve().parent / "harness"))
    try:
        from affected_tests import GUARD_SET
    except ImportError:
        return ()
    return tuple(GUARD_SET)


def overlaps(delta: list[list[str]], mine: list[list[str]], ignore=()) -> bool:
    """Whether any test path of ``mine`` is, contains or sits in one of ``delta`` (node ids by file); the paths in or
    under ``ignore`` and the guard set aside. 11-02: the guard set (test_protocol_version_alignment,
    test/architecture/...) sat in every selection, so every pair overlapped and addenda 18, 22, 23 rarely applied."""
    skip = tuple(ignore) + _guard_set()

    def paths(invs):
        found = {w.replace("\\", "/").split("::")[0].rstrip("/") for inv in invs for w in inv
                 if not w.startswith(("ROSY_", "-"))}
        return {p for p in found if not any(p == g or p.startswith(g + "/") for g in skip)}
    return any(a == b or a.startswith(b + "/") or b.startswith(a + "/") for a in paths(delta) for b in paths(mine))


def _guards_only(invocations: list[list[str]], guards) -> list[list[str]]:
    """The invocations whose every test path is one of ``guards`` (or inside one)."""
    def paths(inv):
        return [w.replace("\\", "/").split("::")[0].rstrip("/") for w in inv if not w.startswith(("ROSY_", "-"))]
    return [inv for inv in invocations
            if paths(inv) and all(any(p == g or p.startswith(g + "/") for g in guards) for p in paths(inv))]


DELTA_NOTE = "main's landed delta reaches whole suite folders: they run before the turn"  # D-889 27


MAX_DELTA_YIELDS = 2  # D-970 1: then the turn (30 min budget after two send-backs) runs the suite folders


def delta_yields(ticket, base: dict | None) -> bool:
    """Whether a DELTA_NOTE turn yields to run the suites before the turn: only with a queue ticket and a clean
    earlier tier for the delta record to stand on. 11-03 14:18-14:34 a LOAD-FLAKY pretest (no tier) yielded twice
    and saved nothing; without a base the suites run in the turn as before (D-889 27). After MAX_DELTA_YIELDS the
    turn runs them itself: 11-03 15:58-18:07 one ticket yielded three times while main kept moving past it."""
    return ticket is not None and base is not None and int(base.get("yields") or 0) < MAX_DELTA_YIELDS


def _suite_dirs(inv: list[str]) -> bool:
    """Whether an invocation names a whole test folder (not single files or node ids)."""
    return any(not w.startswith(("ROSY_", "-")) and not w.split("::")[0].endswith(".py") for w in inv)


def _unique(invocations: list[list[str]]) -> list[list[str]]:
    return [list(inv) for inv in dict.fromkeys(map(tuple, invocations))]


def select(land, wt: Path, base: str, python: str, head: str | None = None,
           landed: bool = False, full: bool = False) -> tuple[list[list[str]], str | None]:
    """pytest invocations for base...HEAD (or base...head), and a FULL note owed to the summary.

    The D-436 selector (`rosy_harness.py affected`) when the harness is present —
    it adds the guard set and reverse dependents — otherwise the nearest test/ dir.
    ``landed``: base...head is main's delta, already on main with its own FULL tier when it escalated.
    """
    def browsers(reach: list[list[str]] | None = None) -> list[list[str]]:
        """The changed paths' browser tier. D-889 addendum 12: main's landed delta passed its own browser tests,
        so they repeat only when this branch changes UI too; on 2026-10-31 docs landings ran 50-80 browser
        minutes each for other landings' UI, and speculation 471 of 1,703 browser minutes."""
        if not (landed and head):
            return land.browser_tier(wt, base, head)
        own = land.browser_tier(wt, head)
        if not own:
            return []
        delta = land.browser_tier(wt, base, head)
        if reach is None:
            return _unique(own + delta)
        # D-889 19/24: like the own pytest invocations (18), only the own browser chunks the delta's browser chunks
        # reach. Not its suites: a suite folder (operations/fleet/test) holds the browser files, so every chunk
        # counted as reached (11-02 03:32, a 6-invocation turn ran 7 serial browser chunks for 34 min). The
        # nightly full run covers browser tests (addendum 12).
        # The delta's own chunks too only where this branch's reach them (D-889 22's rule): 11-02 04:06 a turn reran
        # 10 delta chunks of 8 min for a branch whose own chunks touched few of them.
        return _unique([inv for inv in delta if overlaps(own, [inv])] + [inv for inv in own if overlaps(delta, [inv])])

    if (wt / "tools/harness/affected_tests.py").is_file():
        try:
            sel = _affected(land, wt, python, base, head, full)
            if full:
                if (sel["mode"] != "full" or not valid_plan(sel["full_invocations"])
                        or not affected_exclusive.canonical_full(sel["full_invocations"])):
                    raise ValueError("forced selector did not supply the canonical whole FULL plan")
                return sel["full_invocations"] + all_browsers(land, wt, python), "explicit canonical FULL"
            # D-889 3 (combined affected, not FULL per cycle): a delta that escalated landed on main with its own
            # FULL tier, and this branch passed its own tier before the turn. Repeating FULL for every lander
            # behind a FULL landing was 35 % of pretest time on 2026-10-26; what is left is both changes' own
            # suites on the merged tree. A safety path in this branch keeps FULL (D-889 6). One in main's delta
            # no longer does (D-889 addendum 8): a branch touching a safety path lands only through its own FULL
            # tier, and the delta's selection keeps the suites mapped to those safety paths.
            own = _affected(land, wt, python, head, None) if landed and head and sel["escalations"] else None
            if own is not None and not any(e.endswith(SAFETY_TRIGGER) for e in own["escalations"]):
                print("[tests] main's delta escalated but landed with its own FULL tier: its mapped suites and"
                      " this branch's own selection on the merged tree")
                mine = own["local_invocations"] if own["mode"] == "full" else own["invocations"]
                # D-889 addendum 10 item 2: this branch's suites passed its pretest, and main's delta reaches none of
                # them (guards aside, which the delta's run carries): only the delta's suites. A FULL-mode own too
                # (D-889 16): re-running it every turn ran past the 10 min cap, so it never landed (11-01).
                # Browser chunks only where addendum 12 says (browsers()).
                # D-889 18: the same rule per invocation: only the own invocations the delta reaches rerun. 11-01 18:01
                # a foundation landing's turn reran all 485 own invocations for a delta that reached a few (45 min).
                guards = getattr(getattr(land, "land_guards", None), "GUARDS", ())
                reached = [inv for inv in mine if overlaps(sel["local_invocations"], [inv], guards)]
                safe_delta = any(e.endswith(SAFETY_TRIGGER) for e in sel["escalations"])  # addendum 8 keeps those
                if not reached and not safe_delta and own["mode"] != "full":  # D-889 22: ran here as on main
                    print("[tests] main's delta and this branch reach none of each other's suites: the guards only")
                    return _unique(_guards_only(sel["local_invocations"], guards) + browsers(sel["local_invocations"])), None
                if len(reached) < len(mine):
                    print(f"[tests] main's delta reaches {len(reached)} of this branch's {len(mine)} invocations: those rerun")
                # D-889 27: whole suite folders here ran 15-22 min inside the lock and gave the turn back at its
                # cap (11-03, 17 stalls over 30 min); land.py runs them before the turn under the "delta" tier.
                big = [inv for inv in sel["local_invocations"] + reached
                       if _suite_dirs(inv) and not _guards_only([inv], guards)]
                note = f"{DELTA_NOTE} ({len(big)} suite folder invocation(s))" if big else None
                return _unique(sel["local_invocations"] + reached + browsers(sel["local_invocations"])), note
            if sel["mode"] == "full":
                # D-762 stage 0: a FULL-class landing runs the whole tier on the lab PCs, never
                # guards alone; not via GitHub, which would publish unpushed main commits.
                note = "selector escalated to FULL (" + "; ".join(sel["escalations"][:3]) + "): full tier on the lab PCs"
                print(f"[tests] {note}")
                changed = land.lines(wt, "diff", "--name-only", f"{base}...{head or 'HEAD'}")
                if landed and head:
                    changed += land.lines(wt, "diff", "--name-only", f"{head}...HEAD")
                return without_sim(sel["full_invocations"], changed) + browsers(), note
            if landed and head:
                # D-889 22: an ordinary delta (not escalated) the same way: when this branch and main's delta reach
                # none of each other's suites, those suites run on the merged tree as they ran on main. 11-02: a
                # docs landing's turn took 7 min for the delta's suites; queued landings waited ~125 min for turns.
                own = _affected(land, wt, python, head, None)
                guards = getattr(getattr(land, "land_guards", None), "GUARDS", ())
                mine = own["local_invocations"] if own["mode"] == "full" else own["invocations"]
                if (own["mode"] != "full"  # a FULL own reaches more than its local suites name
                        and not any(e.endswith(SAFETY_TRIGGER) for e in own["escalations"] + sel["escalations"])
                        and not overlaps(sel["invocations"], mine, guards)):
                    print("[tests] main's delta and this branch reach none of each other's suites: the guards only")
                    return _unique(_guards_only(sel["invocations"], guards) + browsers(sel["invocations"])), None
            return sel["invocations"] + browsers(), None
        except (ValueError, KeyError, TypeError) as exc:
            raise land.Stop(f"affected selector printed unusable JSON ({exc!r}); not guessing tests") from exc
    if full:
        raise land.Stop("explicit FULL requires the canonical harness; not guessing tests")
    changed = land.lines(wt, "diff", "--name-only", f"{base}...{head or 'HEAD'}")  # main's delta when head is given
    return land.pack(wt, land.fallback_targets(wt, changed)) + land.browser_tier(wt, base, head), None


def browser_tier(land, wt: Path, base: str, head: str | None = None) -> list[list[str]]:
    """The real-Chromium tests for the paths base...head changes, opted in on the test host only."""
    changed = land.lines(wt, "diff", "--name-only", f"{base}...{head or 'HEAD'}")
    return [inv for group in land.pack(wt, land.browser_scope.targets(changed)) for inv in land.land_browser.chunks(wt, group)]


def pack(wt: Path, paths: list[str]) -> list[list[str]]:
    """Split paths into pytest invocations so no two test files share a basename."""
    groups: list[tuple[list[str], set[str]]] = []
    for path in paths:
        root = wt / path
        names = {root.name} if root.is_file() else {p.name for p in root.rglob("test_*.py")}
        for members, seen in groups:
            if not names & seen:
                members.append(path)
                seen |= names
                break
        else:
            groups.append(([path], set(names)))
    return [members for members, _ in groups]


def valid_plan(value):
    return (isinstance(value, list) and bool(value) and all(isinstance(inv, list) and bool(inv)
            and all(isinstance(word, str) and bool(word) for word in inv) for inv in value))


def all_browsers(land, wt, python):
    result = land.subprocess.run([python, "tools/land_selection.py", "--all-browsers"], cwd=wt,
                                capture_output=True, text=True, encoding="utf-8", env=land.ENV)
    try:
        if result.returncode:
            raise ValueError(f"browser selector exit {result.returncode}: {result.stderr}")
        plan = json.loads(result.stdout)
        if not valid_plan(plan) or any("ROSY_RUN_BROWSER_TESTS=1" not in inv
                or not any(not word.startswith("ROSY_") for word in inv) for inv in plan):
            raise ValueError("empty or unusable canonical browser plan")
        return plan
    except (ValueError, TypeError) as exc:
        raise land.Stop(f"explicit FULL browser plan unavailable: {exc}") from exc


def configure(land, args):
    """Initialize CLI policy before delegation to main's landing gateway."""
    land.EXTRA.clear()
    land.land_mainred.CARRIED.clear()
    land.land_mainred.PASSES.clear()
    if args.tests not in ("auto", "none", "full") and land.os.environ.get(land.FIXTURE_ENV) != "1":
        land.EXTRA.append(land.shlex.split(args.tests))
        args.tests = "auto"
    if args.tests == "none" and not args.skip_reason.strip() and land.os.environ.get(land.FIXTURE_ENV) != "1":
        print("[land] STOP: --tests none lands with no test, guard or pretest; only on the user's explicit words,"
              ' as --skip-reason "<their words>" (docs/solutions first-field-result-...-2026-10-10.md 4)',
              file=land.sys.stderr)
        return False
    return True


def begin(land, args):
    if args.tests == "full":
        args._full_witness = None  # A previous process's tier cannot prove its guards were clean.
        if args.no_queue:
            raise land.Stop("explicit FULL requires queued current preparation; --no-queue is unsupported")


def eligible(land, summary):
    return not any("LOAD-FLAKY" in line or land.land_cache.NARROW in line for line in summary)


def require_eligible(land, args, qualifies, summary=()):
    if args.tests == "full" and (not qualifies or land.land_mainred.CARRIED
                                 or any("main-red carried:" in line for line in summary)):
        raise land.Stop("explicit FULL has no qualifying clean evidence; not saving or landing")


def tier(land, summary, full):
    """Carry refuses restart reuse; other unclean auto evidence retains its nonqualifying delta bridge."""
    if land.land_mainred.CARRIED:
        return "carried"
    return ("full" if full else "affected") if eligible(land, summary) else None


def required(land, wt, main, python):
    candidate = land.out(wt, "rev-parse", "HEAD")
    plan, note = land.select(wt, main, python, head=candidate, full=True)
    env = land.land_cache.env_id(wt, candidate)
    if not isinstance(env, str) or not env:
        raise land.Stop("explicit FULL test-environment identity is unavailable")
    return plan, note, env


def current_main(land, wt, args, branch, main, python):
    witness = getattr(args, "_full_witness", None)
    if not witness:
        return None
    plan, _, env = required(land, wt, main, python)
    record = land.land_full.prepared(wt, branch, witness["main"])
    if (plan != witness["invocations"] or env != witness["env"] or not record
            or any(record.get(k) != witness[k] for k in ("candidate", "main", "invocations"))
            or record.get("tier") != "full" or land.land_full.restore(wt, branch) != witness["main"]):
        return None
    return witness["main"]


def main(argv=None):
    if (sys.argv[1:] if argv is None else argv) != ["--all-browsers"]:
        raise SystemExit("expected --all-browsers")
    root = Path(__file__).resolve().parents[1]
    if not all((root / p).is_file() for p in ("test/browser_scope.py", "tools/land_browser.py")):
        raise SystemExit("candidate browser registry/builder is missing")
    sys.path[:0] = [str(root / "test"), str(root / "tools/remote")]
    import browser_scope
    import land_browser
    paths = browser_scope.all_targets()
    print(json.dumps([inv for group in pack(root, paths) for inv in land_browser.chunks(root, group)]))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
