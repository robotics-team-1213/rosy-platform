#!/usr/bin/env python3
"""Create and list local teleop-check and drive-record folders.

Recordings stay under data/teleop and data/drive. The tool refuses a
path that would leave those two directories.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from datetime import datetime, timezone
from pathlib import Path


KINDS = ("teleop", "drive")
_LABEL = re.compile(r"^[a-z0-9][a-z0-9-]{0,40}$")


class RunDataError(ValueError):
    """The requested session is not inside the data folders."""


def data_root(repo: Path) -> Path:
    return repo / "data"


def kind_root(repo: Path, kind: str) -> Path:
    if kind not in KINDS:
        raise RunDataError(f"kind must be teleop or drive, not {kind}")
    return data_root(repo) / kind


def _label(text: str) -> str:
    cleaned = text.strip().lower().replace("_", "-")
    if not _LABEL.fullmatch(cleaned):
        raise RunDataError("label must be lowercase letters, digits, and hyphens")
    return cleaned


def create_session(repo: Path, kind: str, label: str, *, when: datetime | None = None) -> Path:
    """Make one session directory and the files that kind is expected to hold."""

    stamp = (when or datetime.now(timezone.utc)).astimezone(timezone.utc)
    name = f"{stamp.strftime('%Y%m%dT%H%M%SZ')}-{_label(label)}"
    root = kind_root(repo, kind)
    session = root / name
    if root.resolve() not in session.resolve().parents:
        raise RunDataError("session path leaves the data folder")
    session.mkdir(parents=True, exist_ok=False)
    document = {
        "kind": kind,
        "label": _label(label),
        "created": stamp.isoformat(timespec="seconds"),
    }
    (session / "session.json").write_text(
        json.dumps(document, ensure_ascii=False, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    (session / "notes.md").write_text(f"# {kind} {document['label']}\n\n", encoding="utf-8")
    if kind == "teleop":
        (session / "commands.jsonl").write_text("", encoding="utf-8")
    else:
        (session / "trace.jsonl").write_text("", encoding="utf-8")
        (session / "bags").mkdir()
    return session


def list_sessions(repo: Path, kind: str) -> list[Path]:
    root = kind_root(repo, kind)
    if not root.is_dir():
        return []
    return sorted(path for path in root.iterdir() if path.is_dir() and (path / "session.json").is_file())


def append_record(session: Path, record: dict) -> Path:
    """Append one JSON line to the file that session kind owns."""

    summary = session_summary(session)
    if not isinstance(record, dict) or not record:
        raise RunDataError("a record must be a non-empty object")
    name = "commands.jsonl" if summary["kind"] == "teleop" else "trace.jsonl"
    target = session / name
    if session.resolve() not in target.resolve().parents:
        raise RunDataError("record path leaves the session")
    with target.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(record, ensure_ascii=False, sort_keys=True) + "\n")
    return target


def session_summary(session: Path) -> dict:
    document = json.loads((session / "session.json").read_text(encoding="utf-8"))
    kind = document.get("kind")
    if kind == "teleop":
        present = {
            "commands": (session / "commands.jsonl").is_file(),
            "notes": (session / "notes.md").is_file(),
        }
    elif kind == "drive":
        present = {
            "trace": (session / "trace.jsonl").is_file(),
            "bags": (session / "bags").is_dir(),
            "notes": (session / "notes.md").is_file(),
        }
    else:
        raise RunDataError("session.json kind is not teleop or drive")
    return {"path": session, "kind": kind, "label": document.get("label"), "present": present}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="run_data")
    parser.add_argument("--repo", type=Path, default=Path(__file__).resolve().parents[1])
    sub = parser.add_subparsers(dest="command", required=True)
    new = sub.add_parser("new")
    new.add_argument("kind", choices=KINDS)
    new.add_argument("label")
    listed = sub.add_parser("list")
    listed.add_argument("kind", choices=KINDS)
    write = sub.add_parser("write")
    write.add_argument("session", type=Path)
    write.add_argument("record")
    args = parser.parse_args(argv)
    try:
        if args.command == "new":
            session = create_session(args.repo, args.kind, args.label)
        elif args.command == "write":
            session = args.session
            append_record(session, json.loads(args.record))
        else:
            for session in list_sessions(args.repo, args.kind):
                print(session)
            return 0
        print(session)
        return 0
    except RunDataError as exc:
        print(f"FAIL: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
