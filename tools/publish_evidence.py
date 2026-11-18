"""Bind publication's canonical FULL plan to exact, usable execution evidence."""

from __future__ import annotations

import json
import os
from pathlib import Path
import subprocess
import sys
import uuid

import land_cache
import land_full
from land_selection import valid_plan


# Imports and selectors run in a fresh interpreter against the immutable candidate,
# including its environment recipe, browser chunker, sharder and quarantine policy.
DESCRIBE = r'''
import hashlib, json, re, subprocess, sys, tempfile
from pathlib import Path
root = Path.cwd()
sys.path[:0] = [str(root / p) for p in ("tools", "tools/remote", "test")]
import land_cache, land_browser, work_queue, known_failures
from land_selection import valid_plan
exclusive = None
if (root / "tools/harness/affected_exclusive.py").is_file():
    from harness import affected_exclusive as exclusive
sha, base, scope_base = sys.argv[1:]
request = json.load(sys.stdin)
def command(args):
    run = subprocess.run([sys.executable, *args], capture_output=True, text=True,
                         encoding="utf-8", check=True)
    return json.loads(run.stdout)
selection = command(["tools/harness/rosy_harness.py", "affected", "--base", base,
                     "--head", sha, "--json", "--full"])
full = selection["full_invocations"]
# D-1036 addendum: the browser chunks the publish delta (origin/main...sha) maps to, by land.py's own landing
# mapping (land_selection.browser_tier); any failure falls back to every registered chunk (fail closed).
try:
    import types, browser_scope, land_selection
    def lines(wt, *args):
        return [line for line in subprocess.run(["git", "-C", str(wt), *args], capture_output=True, text=True,
                encoding="utf-8", check=True).stdout.splitlines() if line]
    tier = types.SimpleNamespace(lines=lines, pack=land_selection.pack, browser_scope=browser_scope,
                                 land_browser=land_browser)
    browsers, scope = land_selection.browser_tier(tier, root, scope_base, sha), "delta"
except Exception:
    browsers, scope = command(["tools/land_selection.py", "--all-browsers"]), "all"
    assert valid_plan(browsers)
assert selection["mode"] == "full" and valid_plan(full)
assert exclusive.canonical_full(full) if exclusive is not None else ["test"] in full
if exclusive is not None:
    exclusive.validate(request["invocations"], True)
assert all("ROSY_RUN_BROWSER_TESTS=1" in inv for inv in browsers)
variants = {}
for inv in request["invocations"] + browsers + request.get("extra", []):
    choices = []
    for n in range(work_queue.MAX_SPLIT + 1):
        split = work_queue.split(root, [inv], seen={tuple(inv): work_queue.SPLIT_S * n})
        if split not in choices:
            choices.append(split)
    variants[json.dumps(inv)] = choices
known = known_failures.load_known(known_failures.LIST.read_text(encoding="utf-8"))
quarantine = (known_failures.load_known(known_failures.QUARANTINE.read_text(encoding="utf-8"))
              if known_failures.QUARANTINE.is_file() else {})
def clean(row):
    log = Path(row.get("log", ""))
    try:
        data = log.read_bytes()
    except OSError:
        return False
    if row.get("log_sha256") != hashlib.sha256(data).hexdigest():
        return False
    if exclusive is not None and exclusive.dedicated(row["argv"]):
        with tempfile.TemporaryDirectory(prefix="rosy-publish-log-") as temporary:
            snapshot = Path(temporary) / "execution.txt"
            snapshot.write_bytes(data)
            return exclusive.evidence(snapshot, 0) is None
    text = data.decode("utf-8-sig", errors="replace")
    summaries = [line for line in text.splitlines()
                 if re.search(r"\b\d+ (?:passed|failed|skipped|errors?)\b.* in [0-9.]+s", line)]
    if (not summaries or "no tests ran" in text or "LOAD-FLAKY" in text
            or "[tailscale-ssh: process died: signal:" in text):
        return False
    if "ROSY_RUN_BROWSER_TESTS=1" in row["argv"]:
        with tempfile.TemporaryDirectory(prefix="rosy-publish-log-") as temporary:
            snapshot = Path(temporary) / "execution.txt"
            snapshot.write_bytes(data)
            if land_browser.vacuous(row["argv"], snapshot):
                return False
    if any(re.search(r"\b[1-9]\d* (?:failed|errors?)\b", line) for line in summaries) \
            and not known_failures.failed_ids(text):
        return False
    new, _, _ = known_failures.compare(text, known)
    return not (set(new) - set(known_failures.flaky(text, quarantine)))
reach = ({a: land_cache.reach(root, a, sha, sys.executable) for a in request.get("ancestors", [])}
         if hasattr(land_cache, "reach") else {})  # a candidate older than D-970 3 reuses nothing across trees
print(json.dumps({"plan": full, "browsers": browsers, "scope": scope, "variants": variants, "env": land_cache.env_id(root, sha),
                  "clean": [clean(row) for row in request["rows"]], "reach": reach}))
'''


def describe(publish, repo, sha, base, invocations, rows, ancestors=(), scope_base="", extra=()):
    """Use the existing publication checkout location and cleanup policy for immutable selection."""
    holder = Path(publish.git(repo, "rev-parse", "--path-format=absolute", "--git-common-dir").stdout.strip())
    temp = holder / "rosy-publish" / f"proof-{sha[:10]}-{uuid.uuid4().hex[:8]}"
    publish.git(repo, "worktree", "add", "--detach", str(temp), sha)
    try:
        result = subprocess.run([sys.executable, "-c", DESCRIBE, sha, base, scope_base], cwd=temp,
                                input=json.dumps({"invocations": invocations, "rows": rows,
                                                  "ancestors": list(ancestors), "extra": list(extra)}),
                                capture_output=True, text=True, encoding="utf-8",
                                env={**os.environ, "PYTHONUTF8": "1"})
        if result.returncode:
            return None
        return json.loads(result.stdout)
    finally:
        publish.git(repo, "worktree", "remove", "--force", str(temp), check=False)
        if temp.exists():
            publish.worktree_rules.leave_tombstone(temp)


def reason(publish, repo, sha, record):
    """None for qualified proof; a fail-closed reason otherwise. Legacy tier guesses never qualify."""
    return check(publish, repo, sha, record)[0]


def check(publish, repo, sha, record):
    """(reason or None, browser chunks lacking proof, browser count note). The chunks are listed only when they are
    the sole failure: every other check runs first (D-1036 addendum, publish_main --fill-browsers)."""
    if record.get("tier") != "full" or not valid_plan(record.get("invocations")):
        return "no explicit FULL execution plan", [], ""
    invocations = record["invocations"]
    # D-1036 addendum (2026-11-18): browser chunks are those the publish delta maps to, not every registered one.
    scope_base = publish.git(repo, "rev-parse", "--verify", "-q", "origin/main^{commit}", check=False).stdout.strip()
    prepared = record.get("prepared_candidate")
    sources = [(sha, record["base"])]
    if prepared:
        on = record.get("prepared_on")
        if (not isinstance(prepared, str) or not land_cache.OID.fullmatch(prepared)
                or not isinstance(on, str) or not land_cache.OID.fullmatch(on)
                or not publish.ancestor(repo, on, prepared)
                or not land_full.bridge(repo, prepared, on, sha, record["base"])):
            return "invalid prepared-candidate provenance", [], ""
        if prepared != sha:
            sources.append((prepared, on))
    entries = land_cache.entries(repo)
    descriptions, evidence, final_logs = [], [], set()
    for commit, base in sources:
        tree = publish.git(repo, "rev-parse", f"{commit}^{{tree}}").stdout.strip()
        rows = [row for row in entries if row["commit"] == commit and row["tree"] == tree]
        if not rows:
            return f"missing exact execution mappings for {commit[:10]} (possibly pruned)", [], ""
        older = ancestor_rows(publish, repo, commit, entries)
        ancestors = list(dict.fromkeys(row["commit"] for row in older))
        extra = descriptions[0]["browsers"] if descriptions else ()  # the final candidate's chunks, proven anywhere
        description = describe(publish, repo, commit, base, invocations, rows + older, ancestors, scope_base, extra)
        if not description or not description.get("env") or not valid_plan(description.get("plan")):
            return f"canonical candidate plan/environment unavailable for {commit[:10]}", [], ""
        usable = [row for row, clean in zip(rows, description["clean"])
                  if clean and row["env"] == description["env"]]
        mapped = {tuple(row["argv"]) for row in usable}
        # D-970 3: an ancestor's clean exact pass counts when the candidate's own selector, recomputed here, reaches
        # none of its paths (land_cache.reach); the land record's word for it is never taken.
        reach = description.get("reach") or {}
        for row, clean in zip(older, description["clean"][len(rows):]):
            delta, paths = reach.get(row["commit"]), land_cache._paths(row["argv"])
            if (clean and row["env"] == description["env"] and isinstance(delta, list) and paths
                    and not any(land_cache._overlap(p, d) for p in paths for d in delta)):
                mapped.add(tuple(row["argv"]))
        if commit == sha:
            final_logs = {row["log"] for row in usable}
        descriptions.append(description)
        evidence.append(mapped)
    current = descriptions[0]
    if any(d["plan"] != current["plan"] or d["env"] != current["env"] for d in descriptions[1:]):
        return "prepared and final candidate FULL plans or environments differ", [], ""
    if not all(inv in invocations for inv in current["plan"]):
        return "record omits a canonical FULL invocation", [], ""

    def proven(inv):
        return any(all(tuple(part) in mapped for part in variant)
                   for description, mapped in zip(descriptions, evidence)
                   for variant in description["variants"].get(json.dumps(inv), []))
    for inv in invocations:
        if not proven(inv):
            return f"missing clean exact execution/log proof for {' '.join(inv)}", [], ""
    logs = record.get("logs")
    if (not isinstance(logs, list) or not all(isinstance(log, str) for log in logs)
            or not set(logs) <= final_logs):
        return "final-round logs lack clean exact final-candidate mappings", [], ""
    # The record need not list them: each needs clean exact proof on this sha or a non-reaching ancestor (D-970 3).
    missing = [inv for inv in current["browsers"] if not proven(inv)]
    need = len(current["browsers"])
    note = f"browser chunks {need - len(missing)}/{need} evidenced ({current['scope']} scope)"
    if missing:
        return f"{note}; missing clean exact execution/log proof for {' '.join(missing[0])}", missing, note
    return None, [], note


def nightly_sha(publish, repo):
    """The newest main sha whose nightly FULL was green (tools/land_nightly.py keeps it in the shared git dir)."""
    holder = Path(publish.git(repo, "rev-parse", "--path-format=absolute", "--git-common-dir").stdout.strip())
    try:
        sha = (holder / "rosy-nightly-green").read_text(encoding="utf-8").strip()
    except OSError:
        return None
    return sha if land_cache.OID.fullmatch(sha) else None


def ancestor_rows(publish, repo, commit, entries, recent=20):
    """Exact rows (their own tree) of the land_cache.NARROW_COMMITS strict ancestors of commit, among the ``recent``
    newest commits with rows, that hold the most rows: an earlier FULL candidate of the same branch. The newest green
    nightly sha always competes, so a night older than ``recent`` later rows still vouches for its unchanged suites."""
    nightly = nightly_sha(publish, repo)
    seen = list(dict.fromkeys(row["commit"] for row in reversed(entries) if row["commit"] != commit))[:recent]
    if nightly and nightly != commit and nightly not in seen and any(row["commit"] == nightly for row in entries):
        seen.append(nightly)
    kept = {}
    for a in seen:
        if publish.ancestor(repo, a, commit):
            tree = publish.git(repo, "rev-parse", f"{a}^{{tree}}").stdout.strip()
            kept[a] = [row for row in entries if row["commit"] == a and row["tree"] == tree]
    best = sorted(kept, key=lambda a: -len(kept[a]))[:land_cache.NARROW_COMMITS]
    if nightly in kept and nightly not in best:
        best = best[:-1] + [nightly]
    return [row for a in best for row in kept[a]]


ERRORS = (OSError, ValueError, KeyError, TypeError, subprocess.SubprocessError)


def qualified(publish, repo, sha, record):
    try:
        why, _, note = check(publish, repo, sha, record)
    except ERRORS:
        why, note = "execution proof could not be read or validated", ""
    if why:
        print(f"[publish] FULL {sha[:10]} not qualified: {why}", file=sys.stderr)
    elif note:
        print(f"[publish] FULL {sha[:10]} qualified: {note}", file=sys.stderr)
    return why is None


def fill(publish, repo, apply):
    """D-1036 addendum: on the newest candidate whose only failure is missing browser proof, run those chunks on a
    test host (remote_pytest, the chunk argv carries ROSY_RUN_BROWSER_TESTS=1) and record the clean passes as
    tools/land_nightly.py does. Dry run unless ``apply``."""
    import land_browser
    import land_checks
    for sha in publish.git(repo, "rev-list", "--topo-order", "--ancestry-path", "origin/main..main").stdout.split():
        record = publish.land_record.read(repo, sha)
        if not record or publish.tier(record) != "full" or not publish.ancestor(repo, record["base"], sha):
            continue
        try:
            why, missing, note = check(publish, repo, sha, record)
        except ERRORS:
            why, missing, note = "execution proof could not be read or validated", [], ""
        if why is None:
            return f"{sha[:10]} already qualifies ({note}); nothing to fill"
        print(f"[publish] FULL {sha[:10]} not qualified: {why}", file=sys.stderr)
        if missing:
            break
    else:
        return "no candidate past origin/main lacks only browser evidence"
    shown = "\n".join("  " + " ".join(inv) for inv in missing)
    if not apply:
        return f"dry run: {sha} {note}; would run {len(missing)} chunk(s), rerun with --apply:\n{shown}"
    logdir = land_checks.tmp_dir(f"publish-fill-{sha[:10]}")
    logs = [logdir / f"browser-{n}.txt" for n in range(len(missing))]
    codes = land_cache.remote_pytest.run(missing, logs, sha, repo=repo, label="publish-fill")
    env = land_cache.env_id(repo, sha)
    tree = publish.git(repo, "rev-parse", f"{sha}^{{tree}}").stdout.strip()
    passed = 0
    for inv, log, code in zip(missing, logs, codes):
        # Only a clean pass becomes a row: landings reuse these rows, publication re-checks them with clean().
        if (env and code == 0 and log.is_file() and land_cache.unusable(code, log) is None
                and not land_browser.vacuous(inv, log)):
            land_cache.record(repo, sha, tree, env, inv, log)
            passed += 1
    return f"{sha[:10]}: {passed}/{len(missing)} missing browser chunk(s) passed and recorded (logs {logdir})"
