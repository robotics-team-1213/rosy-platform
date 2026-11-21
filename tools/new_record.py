"""Conflict-free log/API shard creator and scheduled record consolidator (D-1052, D-1061).

PRs write unnumbered fragments; `consolidate` (the records bot, one run at a time) numbers API
fragments in (date, slug) order, writes the reference header, newest-first sections, history rows
and CONTRACT together, folds log shards and adds missing ADR Log rows.
"""

from __future__ import annotations

import argparse
import datetime as dt
import re
import subprocess
import sys
from pathlib import Path

HARNESS = Path(__file__).resolve().parent / "harness"
if str(HARNESS) not in sys.path:
    sys.path.insert(0, str(HARNESS))

import records_rules as rules  # noqa: E402
import rosy_harness as harness  # noqa: E402

ADR_FILE = re.compile(r"^(D-\d+)-.*\.md$")
TITLE_LINE = re.compile(r"^#+\s*(?:D-\d+[:\s-]*)?(.+)$", re.M)
STATUS_LINE = re.compile(r"^\*\*Status:\*\*\s*(.+)$", re.M)
API_HEADER = re.compile(r"^\*\*Version:\*\* v1\.(\d+)\b", re.M)
API_SECTION = re.compile(r"^### v1\.\d+", re.M)
HISTORY_HEAD = "| 버전 | 일자 | 내용 |\n|---|---|---|\n"
CONTRACT_VALUE = re.compile(r"ROSY-API-REF-001 v1\.\d+")
NEXT = "v1.next"


LOG_DATE = re.compile(r"^## (\d{4}-\d{2}-\d{2})", re.M)


def _insert_by_date(existing: str, additions: list[str]) -> str:
    """Put each log entry after the last entry dated <= its own date; existing order is never rewritten.

    The log-order lint wants dates non-decreasing; a shard that merged late (older date) used to land
    at the end and fail it. Same-date entries keep arrival order. shortcut: entries are split on
    "## YYYY-MM-DD" headings only, so a header-less preface stays first.
    """
    starts = [m.start() for m in LOG_DATE.finditer(existing)]
    head = existing[:starts[0]] if starts else existing.rstrip("\n") + "\n\n"
    blocks = [existing[a:b].strip("\n") for a, b in zip(starts, starts[1:] + [len(existing)])]
    for add in additions:
        m = LOG_DATE.match(add)
        day = m.group(1) if m else "9999-99-99"
        at = len(blocks)
        while at and (d := LOG_DATE.match(blocks[at - 1])) and d.group(1) > day:
            at -= 1
        blocks.insert(at, add)
    return head + "\n\n".join(blocks) + "\n"


def _slugify(text: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")
    return slug[:48] or "entry"


def _repo_root(start: Path | None = None) -> Path:
    res = subprocess.run(["git", "-C", str(start or Path.cwd()), "rev-parse", "--show-toplevel"],
                         capture_output=True, text=True, encoding="utf-8")
    return Path(res.stdout.strip()) if res.returncode == 0 and res.stdout.strip() else (start or Path.cwd()).resolve()


def _unique_path(folder: Path, prefix: str, suffix: str = ".md") -> Path:
    candidate = folder / f"{prefix}{suffix}"
    n = 2
    while candidate.exists():
        candidate = folder / f"{prefix}-{n}{suffix}"
        n += 1
    return candidate


def write_log_shard(repo: Path, module_name: str, summary: str, *, change: str, evidence: str,
                    gate: str = "없음", decision: str = "없음", lesson: str = "없음",
                    commit: str = "uncommitted", date: str | None = None) -> Path:
    """Validate and write a per-change log shard under `<module>/logs/YYYY/MM/DD-<slug>.md`."""
    config = harness.load_config(repo)
    mod = next((m for m in config["modules"] if m["name"] == module_name), None)
    if mod is None:
        raise SystemExit(f"[new-record] unknown harness module: {module_name}")
    day = date or dt.date.today().isoformat()
    yyyy, mm, dd = day.split("-", 2)
    entry = "\n".join([
        f"## {day} · {commit} · {summary.strip()}",
        "",
        f"- 변경: {change.strip()}",
        f"- 증거: {evidence.strip()}",
        f"- gate 변화: {gate.strip()}",
        f"- 결정: {decision.strip()}",
        f"- 교훈: {lesson.strip()}",
        "",
    ])
    if errors := harness.validate_log(entry):
        raise SystemExit(f"[new-record] invalid log entry: {'; '.join(errors)}")
    out_dir = repo / mod["path"] / "logs" / yyyy / mm
    out_dir.mkdir(parents=True, exist_ok=True)
    target = _unique_path(out_dir, f"{dd}-{_slugify(summary)}")
    target.write_text(entry, encoding="utf-8", newline="\n")
    return target


def write_api_fragment(repo: Path, slug: str, *, surface: str, title: str, history: str = "", body: str = "",
                       kind: str = "additive", reason: str = "", date: str | None = None) -> Path:
    """Write `docs/reference/api-changes/<slug>.md`: no number; the records bot assigns it."""
    slug = _slugify(slug)
    meta = {"surface": surface, "kind": kind, "slug": slug, "date": date or dt.date.today().isoformat(),
            "title": " ".join(title.split()), "history": " ".join(history.split())}
    if reason.strip():
        meta["reason"] = " ".join(reason.split())
    text = "---\n" + "".join(f"{k}: {v}\n" for k, v in meta.items() if v) + "---\n" + body.strip() + "\n"
    target = repo / rules.API_CHANGES / f"{slug}.md"
    if errors := rules.validate_fragment(target.name, text):
        raise SystemExit(f"[new-record] invalid API fragment: {'; '.join(errors)}")
    if target.exists():
        raise SystemExit(f"[new-record] {target.relative_to(repo).as_posix()} exists; pick another slug")
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(text, encoding="utf-8", newline="\n")
    return target


def consolidate_api(repo: Path, today: str | None = None) -> list[tuple[str, str]]:
    """Number API fragments in (date, slug) order and fold them into the reference and CONTRACT."""
    folder = repo / rules.API_CHANGES
    frags = sorted(((rules.parse_fragment(p.read_text(encoding="utf-8")), p) for p in folder.glob("*.md")
                    if p.name != "README.md"), key=lambda fp: (fp[0][0].get("date", ""), fp[0][0].get("slug", ""))) \
        if folder.is_dir() else []
    if not frags:
        return []
    for (meta, _), path in frags:
        if errors := rules.validate_fragment(path.name, path.read_text(encoding="utf-8")):
            raise SystemExit(f"[new-record] {path.name}: {'; '.join(errors)}")
    ref_path, contract_path = repo / rules.API_REF, repo / rules.CONTRACT_FILE
    ref = ref_path.read_text(encoding="utf-8").replace("\r\n", "\n")
    header = API_HEADER.search(ref)
    first_section = API_SECTION.search(ref, header.end()) if header else None
    if header is None or first_section is None or HISTORY_HEAD not in ref:
        raise SystemExit("[new-record] API reference lacks the **Version:** header, a ### v1.N section or the history table")
    number, day = int(header.group(1)), today or dt.date.today().isoformat()
    sections, rows, assigned = [], [], []
    for (meta, body), path in frags:
        number += 1
        version = f"v1.{number}"
        label = rules.SURFACES[meta["surface"]] + (", breaking" if meta["kind"] == "breaking" else "")
        text = body.replace(NEXT, version).strip()
        if meta["kind"] == "breaking":
            text = f"**Breaking.** 사유: {meta['reason'].replace(NEXT, version)}" + (f"\n\n{text}" if text else "")
        sections.insert(0, f"### {version} {meta['title'].replace(NEXT, version)} ({label})\n\n" + (f"{text}\n\n" if text else ""))
        summary = (meta.get("history") or meta["title"]).replace(NEXT, version).replace("|", "\\|")
        rows.insert(0, f"| {version} | {day} | [{label}] {summary} |\n")
        assigned.append((meta["slug"], version))
    at = first_section.start()
    ref = ref[:at] + "".join(sections) + ref[at:]
    ref = API_HEADER.sub(f"**Version:** v1.{number}", ref, count=1)
    ref = ref.replace(HISTORY_HEAD, HISTORY_HEAD + "".join(rows), 1)
    contract, count = CONTRACT_VALUE.subn(f"ROSY-API-REF-001 v1.{number}", contract_path.read_text(encoding="utf-8"))
    if count != 1:
        raise SystemExit(f"[new-record] {rules.CONTRACT_FILE}: expected one CONTRACT value, found {count}")
    ref_path.write_text(ref, encoding="utf-8", newline="\n")
    contract_path.write_text(contract, encoding="utf-8", newline="\n")
    for _, path in frags:
        path.unlink()
    return assigned


def _sync_adr_log(repo: Path, adr_log_path: Path) -> list[str]:
    if not adr_log_path.is_file():
        return []
    text = adr_log_path.read_text(encoding="utf-8").replace("\r\n", "\n")
    adr = harness.parse_adr_log(text, repo / "docs" / "adr")
    added: list[str] = []
    adr_dir = repo / "docs" / "adr"
    for fp in sorted(adr_dir.glob("D-*.md")) if adr_dir.is_dir() else ():
        if not (m := ADR_FILE.match(fp.name)):
            continue
        adr_id = m.group(1)
        if adr_id in adr.index:
            continue
        raw = fp.read_text(encoding="utf-8", errors="replace").replace("\r\n", "\n")
        tm = TITLE_LINE.search(raw)
        title = tm.group(1).strip().replace("|", "\\|") if tm else fp.stem
        sm = STATUS_LINE.search(raw)
        status = sm.group(1).strip().replace("|", "\\|") if sm else ("Accepted" if "Accepted" in raw else "Proposed")
        row = f"| {adr_id} | {title}. [전문](../adr/{fp.name}) | {status} |\n"
        # newest first, right under the table head; old logs without one get the row at the end
        text = text.replace("|---|---|---|\n", f"|---|---|---|\n{row}", 1) if "|---|---|---|\n" in text \
            else text.rstrip("\n") + "\n" + row
        added.append(adr_id)
    if added:
        adr_log_path.write_text(text, encoding="utf-8", newline="\n")
    return added


def consolidate(repo: Path, *, dry_run: bool = False) -> dict:
    """Fold `<module>/logs/**/*.md` shards into `<module>/logs.md`, sync ADR rows, and regenerate records."""
    config = harness.load_config(repo)
    folded, written = [], []
    api = [] if dry_run else consolidate_api(repo)
    for mod in config["modules"]:
        base = repo / mod["path"]
        logs_dir = base / "logs"
        if not logs_dir.is_dir():
            continue
        shards = sorted(logs_dir.rglob("*.md"))
        if not shards:
            continue
        log_file = base / "logs.md"
        existing = log_file.read_text(encoding="utf-8").replace("\r\n", "\n") if log_file.is_file() else f"# {mod['name']} logs\n"
        seen = {line.strip() for line in existing.splitlines() if line.startswith("## ")}
        additions = []
        for s in shards:
            stext = s.read_text(encoding="utf-8").replace("\r\n", "\n").strip()
            heading = next((ln.strip() for ln in stext.splitlines() if ln.startswith("## ")), "")
            if heading and heading not in seen:
                additions.append(stext)
                seen.add(heading)
            folded.append(s.relative_to(repo).as_posix())
        if additions and not dry_run:
            combined = _insert_by_date(existing, additions)
            log_file.write_text(combined, encoding="utf-8", newline="\n")
        if not dry_run:
            for s in shards:
                s.unlink()
            for parent in sorted({p for p in logs_dir.rglob("*") if p.is_dir()} | {logs_dir}, reverse=True):
                if not any(parent.iterdir()):
                    parent.rmdir()
    adrs_synced = [] if dry_run else _sync_adr_log(repo, repo / config["adr_log"])
    if not dry_run:
        written = [p.relative_to(repo).as_posix() for p in harness.generate(repo)]
    return {"api": api, "folded": folded, "adrs_synced": adrs_synced, "generated": written}


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    sub = p.add_subparsers(dest="cmd", required=True)
    sp_log = sub.add_parser("log")
    sp_log.add_argument("module")
    sp_log.add_argument("summary")
    sp_log.add_argument("--change", required=True)
    sp_log.add_argument("--evidence", required=True)
    sp_log.add_argument("--gate", default="없음")
    sp_log.add_argument("--decision", default="없음")
    sp_log.add_argument("--lesson", default="없음")
    sp_log.add_argument("--commit", default="uncommitted")
    sp_log.add_argument("--date")
    sp_api = sub.add_parser("api", help="unnumbered API change fragment; write (v1.next) where the number goes")
    sp_api.add_argument("--surface", required=True, choices=sorted(rules.SURFACES))
    sp_api.add_argument("--slug", required=True)
    sp_api.add_argument("--title", required=True, help="the ### section title, without a version")
    sp_api.add_argument("--history", default="", help="one line for the history table (default: title)")
    sp_api.add_argument("--body", default="", help="section body markdown")
    sp_api.add_argument("--body-file", type=Path, help="read the section body from this file")
    sp_api.add_argument("--kind", default="additive", choices=rules.KINDS)
    sp_api.add_argument("--reason", default="", help="required for --kind breaking")
    sp_api.add_argument("--date")
    sp_con = sub.add_parser("consolidate")
    sp_con.add_argument("--dry-run", action="store_true")
    args = p.parse_args(argv)
    repo = _repo_root()
    if args.cmd == "log":
        out = write_log_shard(repo, args.module, args.summary, change=args.change, evidence=args.evidence,
                              gate=args.gate, decision=args.decision, lesson=args.lesson, commit=args.commit, date=args.date)
        print(out.relative_to(repo).as_posix())
    elif args.cmd == "api":
        body = args.body_file.read_text(encoding="utf-8") if args.body_file else args.body
        out = write_api_fragment(repo, args.slug, surface=args.surface, title=args.title, history=args.history,
                                 body=body, kind=args.kind, reason=args.reason, date=args.date)
        print(out.relative_to(repo).as_posix())
    else:
        print(consolidate(repo, dry_run=args.dry_run))
    return 0


if __name__ == "__main__":
    sys.exit(main())
