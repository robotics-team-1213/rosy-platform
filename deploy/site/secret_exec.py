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
    mounted_paths = {}
    for setting in ("ROSY_CREDENTIAL_PATHS", "ROSY_ADDITIONAL_CREDENTIAL_PATHS"):
        try:
            paths = json.loads(os.environ.pop(setting, "{}"))
        except json.JSONDecodeError:
            raise SystemExit(f"{setting} must be a JSON object") from None
        if not isinstance(paths, dict):
            raise SystemExit(f"{setting} must be a JSON object")
        if mounted_paths.keys() & paths.keys():
            raise SystemExit("additional credentials must not replace existing credential names")
        mounted_paths.update(paths)
    for name, raw_path in mounted_paths.items():
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
