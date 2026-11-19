"""Conflict-free log/API shard creator and scheduled record consolidator (D-1052)."""

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

import rosy_harness as harness  # noqa: E402

ADR_FILE = re.compile(r"^(D-\d+)-.*\.md$")
TITLE_LINE = re.compile(r"^#+\s*(?:D-\d+[:\s-]*)?(.+)$", re.M)


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


def write_api_fragment(repo: Path, slug: str, *, summary: str, contract: str = "", date: str | None = None) -> Path:
    """Write a non-conflicting API change fragment under `docs/reference/api-changes/`."""
    day = date or dt.date.today().isoformat()
    api_dir = repo / "docs" / "reference" / "api-changes"
    api_dir.mkdir(parents=True, exist_ok=True)
    target = _unique_path(api_dir, f"{day}-{_slugify(slug)}")
    body = [f"# {day} · {_slugify(slug)}", "", f"- 요약: {summary.strip()}"]
    if contract.strip():
        body.append(f"- 계약: {contract.strip()}")
    target.write_text("\n".join(body) + "\n", encoding="utf-8", newline="\n")
    return target


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
        title = tm.group(1).strip() if tm else fp.stem
        status = "Accepted" if "Accepted" in raw else "Proposed"
        row = f"| {adr_id} | {title} | {status} |\n"
        text = text.replace("\n---\n", f"\n{row}---\n", 1) if "\n---\n" in text else text.rstrip("\n") + "\n" + row
        added.append(adr_id)
    if added:
        adr_log_path.write_text(text, encoding="utf-8", newline="\n")
    return added


def consolidate(repo: Path, *, dry_run: bool = False) -> dict:
    """Fold `<module>/logs/**/*.md` shards into `<module>/logs.md`, sync ADR rows, and regenerate records."""
    config = harness.load_config(repo)
    folded, written = [], []
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
            combined = existing.rstrip("\n") + "\n\n" + "\n\n".join(additions) + "\n"
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
    return {"folded": folded, "adrs_synced": adrs_synced, "generated": written}


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
    sp_api = sub.add_parser("api")
    sp_api.add_argument("slug")
    sp_api.add_argument("--summary", required=True)
    sp_api.add_argument("--contract", default="")
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
        out = write_api_fragment(repo, args.slug, summary=args.summary, contract=args.contract, date=args.date)
        print(out.relative_to(repo).as_posix())
    else:
        print(consolidate(repo, dry_run=args.dry_run))
    return 0


if __name__ == "__main__":
    sys.exit(main())
