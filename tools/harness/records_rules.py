"""Records cutover rules (D-1061): PRs add fragments; only the records bot edits shared record lines.

Shared lines every PR used to touch, so two PRs always conflicted in the merge queue: the API
reference `**Version:**` header, its newest-first `### v1.N` sections and `| v1.N |` history rows,
`CONTRACT` in contract_version.py, module `logs.md` and the ADR Log index rows.

Cutover instant = when MARKER entered origin/main (first-parent commit date). A PR whose oldest own
commit (author date, survives rebase and merging main) predates it is grandfathered. Before the
marker lands nothing is enforced. The rule runs on pull_request and local runs only: in a merge
group the diff also holds earlier queue entries.

Strict mode (records bot branch, scheduled run, or ROSY_RECORDS_STRICT=1) keeps stale index.md and
ADR files without a Log row as errors; everywhere else they are warnings the bot fixes.
"""

from __future__ import annotations

import datetime as dt
import os
import re
import subprocess
from pathlib import Path

MARKER = "docs/reference/api-changes/README.md"
API_CHANGES = "docs/reference/api-changes"
BOT_PREFIXES = ("bot/records-", "chore/refresh-generated-records")
API_REF = "docs/reference/ROSY API & Protocol Reference.md"
CONTRACT_FILE = "middleware/core/api/core_api_web/api/contract_version.py"
ADR_LOG = "docs/reference/ROSY ADR Log.md"
SHARED_LINES = {
    API_REF: re.compile(r"^[+-](?:\*\*Version:\*\* |### v1\.\d+|\| v1\.\d+ \|)"),
    CONTRACT_FILE: re.compile(r"^[+-]CONTRACT\s*="),
    ADR_LOG: re.compile(r"^[+-]\| D-\d+ \|"),
}
SURFACES = {"fleet": "Fleet", "core": "CORE", "cell": "Cell"}
KINDS = ("additive", "breaking")
FRAGMENT_KEYS = ("surface", "kind", "slug", "date", "title")
ADR_NUMBER = re.compile(r"^D-(\d+)-")
LENIENT_ADR = "body section missing from index"


def _git(repo: Path, *args: str) -> str | None:
    try:
        res = subprocess.run(["git", "-C", str(repo), *args], capture_output=True, text=True,
                             encoding="utf-8", check=False)
    except OSError:
        return None
    return res.stdout if res.returncode == 0 else None


def branch(repo: Path) -> str:
    return (os.environ.get("GITHUB_HEAD_REF") or os.environ.get("GITHUB_REF_NAME")
            or (_git(repo, "rev-parse", "--abbrev-ref", "HEAD") or "").strip())


def is_bot(name: str) -> bool:
    return name.startswith(BOT_PREFIXES)


def strict(repo: Path) -> bool:
    return (os.environ.get("ROSY_RECORDS_STRICT") == "1" or os.environ.get("GITHUB_EVENT_NAME") == "schedule"
            or is_bot(branch(repo)))


def split_strict(errors: list[str], is_strict: bool, lenient) -> tuple[list[str], list[str]]:
    """(errors, warnings): findings matching `lenient` become warnings unless strict."""
    if is_strict:
        return errors, []
    return [e for e in errors if not lenient(e)], [f"{e} (the records bot fixes this)" for e in errors if lenient(e)]


# --- API fragments --------------------------------------------------------------------------------

def parse_fragment(text: str) -> tuple[dict[str, str], str]:
    """Front matter between the first two `---` lines (`key: value`), then the body."""
    text = text.replace("\r\n", "\n")
    if not text.startswith("---\n") or "\n---\n" not in text[3:]:
        return {}, text
    head, body = text[4:].split("\n---\n", 1)
    meta = {}
    for line in head.splitlines():
        if ":" in line:
            key, value = line.split(":", 1)
            meta[key.strip()] = value.strip()
    return meta, body.strip("\n")


def validate_fragment(name: str, text: str) -> list[str]:
    meta, _ = parse_fragment(text)
    if not meta:
        return ["no front matter (write it with tools/new_record.py api)"]
    errors = [f"missing {k}" for k in FRAGMENT_KEYS if not meta.get(k)]
    if meta.get("surface") and meta["surface"] not in SURFACES:
        errors.append(f"surface {meta['surface']!r} not one of {', '.join(SURFACES)}")
    if meta.get("kind") and meta["kind"] not in KINDS:
        errors.append(f"kind {meta['kind']!r} not one of {', '.join(KINDS)}")
    if meta.get("kind") == "breaking" and not meta.get("reason"):
        errors.append("breaking fragment needs a reason")
    if meta.get("slug") and meta["slug"] != Path(name).stem:
        errors.append(f"slug {meta['slug']!r} differs from the file name")
    if re.search(r"v1[.-]\d+", Path(name).stem):
        errors.append("fragment names carry no version number; the bot assigns it")
    return errors


def fragment_findings(repo: Path) -> list[str]:
    folder = repo / API_CHANGES
    return [f"{API_CHANGES}/{p.name}: {e}" for p in sorted(folder.glob("*.md")) if p.name != "README.md"
            for e in validate_fragment(p.name, p.read_text(encoding="utf-8"))] if folder.is_dir() else []


# --- cutover rule ---------------------------------------------------------------------------------

def _when(text: str | None) -> dt.datetime | None:
    lines = (text or "").split()
    return dt.datetime.fromisoformat(lines[-1]) if lines else None


def cutover_time(repo: Path, main_ref: str = "origin/main") -> dt.datetime | None:
    return _when(_git(repo, "log", main_ref, "--first-parent", "--diff-filter=A", "--format=%cI", "--", MARKER))


def first_own_commit(repo: Path, base: str) -> dt.datetime | None:
    return _when(_git(repo, "log", "--no-merges", "--format=%aI", f"{base}..HEAD"))


def shared_line_edits(repo: Path, base: str, module_logs: list[str]) -> list[str]:
    hits = [f"{rel}: edited directly" for rel in (_git(repo, "diff", "--name-only", base, "HEAD", "--", *module_logs)
                                                  or "").split("\n") if rel] if module_logs else []
    for rel, pattern in SHARED_LINES.items():
        for line in (_git(repo, "diff", "-U0", base, "HEAD", "--", rel) or "").splitlines():
            if pattern.match(line) and not line.startswith(("+++", "---")):
                hits.append(f"{rel}: edits shared line {line[:70]!r}")
                break
    return hits


def cutover_findings(repo: Path, base: str | None, module_logs: list[str], *, branch_name: str,
                     event: str, cut: dt.datetime | None) -> tuple[list[str], list[str]]:
    if cut is None or is_bot(branch_name) or event not in ("", "pull_request"):
        return [], []
    if base is None:
        return [], ["records cutover rule skipped: no base ref (origin/main merge base) to diff against"]
    first = first_own_commit(repo, base)
    if first is None or first < cut:
        return [], []
    return [f"{hit}; after the records cutover use fragments: tools/new_record.py api|log, and add only the "
            "docs/adr file (the records bot writes Log rows, versions and CONTRACT)"
            for hit in shared_line_edits(repo, base, module_logs)], []


# --- ADR numbers ----------------------------------------------------------------------------------

def _numbers(names) -> dict[str, list[str]]:
    out: dict[str, list[str]] = {}
    for name in names:
        if m := ADR_NUMBER.match(Path(name).name):
            out.setdefault(m.group(1), []).append(Path(name).name)
    return out


def adr_number_findings(repo: Path, base: str | None, refs: tuple[str, ...] = ("origin/main",)) -> list[str]:
    adr_dir = repo / "docs" / "adr"
    names = [p.name for p in adr_dir.glob("D-*.md")] if adr_dir.is_dir() else []
    errors = [f"docs/adr: D-{n} used by {', '.join(sorted(files))}" for n, files in _numbers(names).items()
              if len(files) > 1]
    if base is None:
        return errors
    added = (_git(repo, "diff", "--name-only", "--diff-filter=A", base, "HEAD", "--", "docs/adr") or "").split()
    for ref in dict.fromkeys((base, *refs)):
        upstream = _numbers((_git(repo, "ls-tree", "--name-only", ref, "docs/adr/") or "").split())
        for rel in added:
            m = ADR_NUMBER.match(Path(rel).name)
            others = [f for f in upstream.get(m.group(1), []) if f != Path(rel).name] if m else []
            if others:
                errors.append(f"{rel}: D-{m.group(1)} already taken by {others[0]} on {ref[:12]}; "
                              "run tools/harness/adr_reserve.py next")
    return list(dict.fromkeys(errors))


def base_ref(repo: Path) -> str | None:
    ref = os.environ.get("GITHUB_REF", "")
    if os.environ.get("GITHUB_EVENT_NAME") == "pull_request" and re.fullmatch(r"refs/pull/\d+/merge", ref):
        revisions = (_git(repo, "rev-parse", "HEAD", "HEAD^1", "HEAD^2") or "").split()
        if len(revisions) == 3 and revisions[0] == os.environ.get("GITHUB_SHA"):
            # The event base may be older than the test merge's actual base.
            return revisions[1]
    requested = os.environ.get("HARNESS_BASE_REF") or ""
    if requested and set(requested) != {"0"} and _git(repo, "rev-parse", "--verify", "--quiet", f"{requested}^{{commit}}"):
        return requested
    for ref in ("origin/main", "main"):
        if mb := (_git(repo, "merge-base", "HEAD", ref) or "").strip():
            return mb
    return None


def lint_findings(repo: Path, module_logs: list[str]) -> tuple[list[str], list[str]]:
    """Fragment format, the cutover rule and the ADR number guard, for `rosy_harness.py lint`."""
    base = base_ref(repo)
    errors = fragment_findings(repo) + adr_number_findings(repo, base)
    cut_errors, warnings = cutover_findings(repo, base, module_logs, branch_name=branch(repo),
                                            event=os.environ.get("GITHUB_EVENT_NAME", ""), cut=cutover_time(repo))
    return errors + cut_errors, warnings
