"""Jira issue keys in branch names and commits: an advisory check and a sprint report.

The team tracks work in Jira (project key ``KAN``) and decisions in Confluence.
GitHub links to both only through the issue key written in the branch, commit
and PR title (``docs/reference/atlassian-integration.md``). This tool reads git
only: no network, no token, no Atlassian address. Usage::

    python tools/jira_refs.py check [--branch NAME] [--message-file PATH] [--project KAN] [--strict]
    python tools/jira_refs.py report --range origin/main..HEAD [--project KAN] [--format md|json]

``check`` says whether the branch name (default: the current branch) and an
optional commit message carry a key. It exits 0 unless ``--strict``: the key is
a team convention, not a repository rule, so nothing here blocks a push.

``report`` lists the commits of a revision range grouped by issue key, with the
commits that carry no key at the end. The Markdown table is meant to be pasted
into the sprint review page; JSON is for other scripts.
"""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from pathlib import Path

DEFAULT_PROJECT = "KAN"
FIELD = "\x1f"
RECORD = "\x1e"


def key_pattern(project: str) -> re.Pattern[str]:
    """``KAN-14`` in a commit, ``kan-14`` in a branch name; not ``XKAN-1`` or ``KAN-1x``."""
    return re.compile(rf"(?<![A-Za-z0-9]){re.escape(project)}-(\d+)(?![A-Za-z0-9])", re.IGNORECASE)


def find_keys(text: str, project: str) -> list[str]:
    """Distinct keys in first-seen order, upper-cased the way Jira writes them."""
    seen: list[str] = []
    for match in key_pattern(project).finditer(text):
        key = f"{project.upper()}-{int(match.group(1))}"
        if key not in seen:
            seen.append(key)
    return seen


def git(repo: Path, *args: str) -> str:
    return subprocess.run(["git", "-C", str(repo), *args], check=True, capture_output=True,
                          text=True, encoding="utf-8").stdout


def current_branch(repo: Path) -> str:
    return git(repo, "rev-parse", "--abbrev-ref", "HEAD").strip()


def commits(repo: Path, revision_range: str) -> list[dict[str, str]]:
    out = git(repo, "log", "--no-merges", f"--format=%H{FIELD}%as{FIELD}%s{FIELD}%b{RECORD}", revision_range)
    rows = []
    for record in out.split(RECORD):
        record = record.strip("\n")
        if not record:
            continue
        sha, date, subject, body = (record.split(FIELD) + ["", "", ""])[:4]
        rows.append({"sha": sha, "date": date, "subject": subject, "body": body.strip()})
    return rows


Commit = dict[str, str]


def group_by_key(rows: list[Commit], project: str) -> tuple[dict[str, list[Commit]], list[Commit]]:
    grouped: dict[str, list[Commit]] = {}
    unkeyed: list[Commit] = []
    for row in rows:
        keys = find_keys(f"{row['subject']}\n{row['body']}", project)
        if not keys:
            unkeyed.append(row)
        for key in keys:
            grouped.setdefault(key, []).append(row)
    ordered = dict(sorted(grouped.items(), key=lambda item: int(item[0].rsplit("-", 1)[1])))
    return ordered, unkeyed


def markdown(grouped: dict[str, list[dict[str, str]]], unkeyed: list[dict[str, str]], revision_range: str) -> str:
    lines = [f"범위: `{revision_range}` · 이슈 {len(grouped)}개 · 키 없는 커밋 {len(unkeyed)}개", "",
             "| 이슈 | 날짜 | 커밋 | 요약 |", "|---|---|---|---|"]
    for key, rows in grouped.items():
        for row in rows:
            lines.append(f"| {key} | {row['date']} | `{row['sha'][:9]}` | {row['subject'].replace('|', '/')} |")
    for row in unkeyed:
        lines.append(f"| (없음) | {row['date']} | `{row['sha'][:9]}` | {row['subject'].replace('|', '/')} |")
    return "\n".join(lines) + "\n"


def cmd_check(args: argparse.Namespace) -> int:
    repo = Path(args.repo)
    branch = args.branch or current_branch(repo)
    missing = []
    branch_keys = find_keys(branch, args.project)
    print(f"branch {branch}: {', '.join(branch_keys) if branch_keys else 'no ' + args.project + ' key'}")
    if not branch_keys:
        missing.append("branch")
    if args.message_file:
        text = Path(args.message_file).read_text(encoding="utf-8")
        message_keys = find_keys(text, args.project)
        print(f"message: {', '.join(message_keys) if message_keys else 'no ' + args.project + ' key'}")
        if not message_keys:
            missing.append("message")
    if missing:
        print(f"hint: add the Jira key, e.g. feat/{args.project.lower()}-14-topic and '... ({args.project}-14)'"
              " (docs/reference/atlassian-integration.md)")
    return 1 if missing and args.strict else 0


def cmd_report(args: argparse.Namespace) -> int:
    grouped, unkeyed = group_by_key(commits(Path(args.repo), args.range), args.project)
    if args.format == "json":
        payload = {"range": args.range, "project": args.project.upper(), "issues": grouped, "unkeyed": unkeyed}
        print(json.dumps(payload, ensure_ascii=False, indent=2))
    else:
        sys.stdout.write(markdown(grouped, unkeyed, args.range))
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--repo", default=".", help="repository or worktree path (default: current directory)")
    parser.add_argument("--project", default=DEFAULT_PROJECT, help="Jira project key (default: KAN)")
    sub = parser.add_subparsers(dest="command", required=True)
    check = sub.add_parser("check", help="advisory: does the branch / commit message carry a key")
    check.add_argument("--branch", help="branch name (default: current branch)")
    check.add_argument("--message-file", help="commit message file, e.g. .git/COMMIT_EDITMSG")
    check.add_argument("--strict", action="store_true", help="exit 1 when a key is missing")
    check.set_defaults(func=cmd_check)
    report = sub.add_parser("report", help="commits of a range grouped by issue key")
    report.add_argument("--range", required=True, help="git revision range, e.g. origin/main..HEAD")
    report.add_argument("--format", choices=("md", "json"), default="md")
    report.set_defaults(func=cmd_report)
    args = parser.parse_args(argv)
    reconfigure = getattr(sys.stdout, "reconfigure", None)
    if reconfigure is not None:  # the report is Korean; a Windows console defaults to cp1252
        reconfigure(encoding="utf-8")
    try:
        return args.func(args)
    except subprocess.CalledProcessError as error:  # bad range, not a repository
        print(f"jira_refs: git failed: {(error.stderr or '').strip()}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
