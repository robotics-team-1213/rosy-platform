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
sha, base = sys.argv[1:]
request = json.load(sys.stdin)
def command(args):
    run = subprocess.run([sys.executable, *args], capture_output=True, text=True,
                         encoding="utf-8", check=True)
    return json.loads(run.stdout)
selection = command(["tools/harness/rosy_harness.py", "affected", "--base", base,
                     "--head", sha, "--json", "--full"])
full = selection["full_invocations"]
browsers = command(["tools/land_selection.py", "--all-browsers"])
assert selection["mode"] == "full" and valid_plan(full) and ["test"] in full
assert valid_plan(browsers) and all("ROSY_RUN_BROWSER_TESTS=1" in inv for inv in browsers)
plan = full + browsers
variants = {}
for inv in request["invocations"]:
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
print(json.dumps({"plan": plan, "variants": variants, "env": land_cache.env_id(root, sha),
                  "clean": [clean(row) for row in request["rows"]]}))
'''


def describe(publish, repo, sha, base, invocations, rows):
    """Use the existing publication checkout location and cleanup policy for immutable selection."""
    holder = Path(publish.git(repo, "rev-parse", "--path-format=absolute", "--git-common-dir").stdout.strip())
    temp = holder / "rosy-publish" / f"proof-{sha[:10]}-{uuid.uuid4().hex[:8]}"
    publish.git(repo, "worktree", "add", "--detach", str(temp), sha)
    try:
        result = subprocess.run([sys.executable, "-c", DESCRIBE, sha, base], cwd=temp,
                                input=json.dumps({"invocations": invocations, "rows": rows}),
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
    if record.get("tier") != "full" or not valid_plan(record.get("invocations")):
        return "no explicit FULL execution plan"
    invocations = record["invocations"]
    if not any("ROSY_RUN_BROWSER_TESTS=1" in inv for inv in invocations):
        return "no opted-in canonical browser chunks"
    prepared = record.get("prepared_candidate")
    sources = [(sha, record["base"])]
    if prepared:
        on = record.get("prepared_on")
        if (not isinstance(prepared, str) or not land_cache.OID.fullmatch(prepared)
                or not isinstance(on, str) or not land_cache.OID.fullmatch(on)
                or not publish.ancestor(repo, on, prepared)
                or not land_full.bridge(repo, prepared, on, sha, record["base"])):
            return "invalid prepared-candidate provenance"
        if prepared != sha:
            sources.append((prepared, on))
    entries = land_cache.entries(repo)
    descriptions, evidence, final_logs = [], [], set()
    for commit, base in sources:
        tree = publish.git(repo, "rev-parse", f"{commit}^{{tree}}").stdout.strip()
        rows = [row for row in entries if row["commit"] == commit and row["tree"] == tree]
        if not rows:
            return f"missing exact execution mappings for {commit[:10]} (possibly pruned)"
        description = describe(publish, repo, commit, base, invocations, rows)
        if not description or not description.get("env") or not valid_plan(description.get("plan")):
            return f"canonical candidate plan/environment unavailable for {commit[:10]}"
        usable = [row for row, clean in zip(rows, description["clean"])
                  if clean and row["env"] == description["env"]]
        mapped = {tuple(row["argv"]) for row in usable}
        if commit == sha:
            final_logs = {row["log"] for row in usable}
        descriptions.append(description)
        evidence.append(mapped)
    current = descriptions[0]
    if any(d["plan"] != current["plan"] or d["env"] != current["env"] for d in descriptions[1:]):
        return "prepared and final candidate FULL plans or environments differ"
    if not all(inv in invocations for inv in current["plan"]):
        return "record omits a canonical FULL invocation or exact browser chunk"
    for inv in invocations:
        if not any(all(tuple(part) in mapped for part in variant)
                   for description, mapped in zip(descriptions, evidence)
                   for variant in description["variants"][json.dumps(inv)]):
            return f"missing clean exact execution/log proof for {' '.join(inv)}"
    logs = record.get("logs")
    if (not isinstance(logs, list) or not all(isinstance(log, str) for log in logs)
            or not set(logs) <= final_logs):
        return "final-round logs lack clean exact final-candidate mappings"
    return None


def qualified(publish, repo, sha, record):
    try:
        why = reason(publish, repo, sha, record)
    except (OSError, ValueError, KeyError, TypeError, subprocess.SubprocessError):
        why = "execution proof could not be read or validated"
    if why:
        print(f"[publish] FULL {sha[:10]} not qualified: {why}", file=sys.stderr)
    return why is None
