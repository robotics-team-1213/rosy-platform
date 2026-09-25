"""Read mounted Compose secrets, drop to the app uid, and exec without logging values."""

from __future__ import annotations

import json
import os
import re
import sys
from pathlib import Path

_ENV_NAME = re.compile(r"^[A-Z_][A-Z0-9_]*$")


def main(argv: list[str] | None = None) -> int:
    args = list(sys.argv[1:] if argv is None else argv)
    try:
        separator = args.index("--")
    except ValueError:
        raise SystemExit("secret bootstrap requires '--' before the application command")
    if separator != 0 or len(args) < 2:
        raise SystemExit("unexpected secret bootstrap arguments")
    command = args[1:]
    mapping_text = os.environ.pop("ROSY_SECRET_FILES", "{}")
    try:
        secret_files = json.loads(mapping_text)
    except json.JSONDecodeError as exc:
        raise SystemExit("ROSY_SECRET_FILES must be a JSON object") from exc
    if not isinstance(secret_files, dict):
        raise SystemExit("ROSY_SECRET_FILES must be a JSON object")
    for name, raw_path in secret_files.items():
        if not isinstance(name, str) or not _ENV_NAME.fullmatch(name):
            raise SystemExit("secret environment names must be uppercase identifiers")
        try:
            value = Path(raw_path).read_text(encoding="utf-8").rstrip("\r\n")
        except (OSError, UnicodeDecodeError, TypeError) as exc:
            raise SystemExit(f"cannot read configured secret file for {name}") from exc
        if not value or "\x00" in value or "\n" in value or "\r" in value:
            raise SystemExit(f"configured secret file for {name} is empty or malformed")
        os.environ[name] = value

    uid = int(os.environ.pop("ROSY_RUN_UID", "10001"))
    gid = int(os.environ.pop("ROSY_RUN_GID", "10001"))
    if os.geteuid() == 0:
        os.setgroups([])
        os.setgid(gid)
        os.setuid(uid)
    elif os.geteuid() != uid:
        raise SystemExit("container must start as root or the configured runtime uid")
    os.execvpe(command[0], command, os.environ)
    return 127


if __name__ == "__main__":
    raise SystemExit(main())
