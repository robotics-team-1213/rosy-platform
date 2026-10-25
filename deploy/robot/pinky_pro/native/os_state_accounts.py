"""Fixed local account IDs before either root can change shared service homes."""
from __future__ import annotations

import argparse
from pathlib import Path
import re
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent))
from os_state_layout import COMMON, _path, _read

ACCOUNT_IDS = {"rosy-core": 960, "rosy-io": 961, "rosy-display": 962, "rosy-camera": 963, "rosy": 1001}


def _table(root: Path, relative: str, count: int) -> dict:
    text = _read(_path(root, relative), 128 * 1024, root.stat().st_uid).decode("utf-8")
    records = {}
    for line in text.splitlines():
        fields = line.split(":")
        if len(fields) != count or not fields[0] or fields[0] in records:
            raise ValueError("invalid or duplicate local account/group entry")
        indices = (2, 3) if count == 7 else (2,)
        if any(not re.fullmatch(r"0|[1-9][0-9]*", fields[index]) for index in indices):
            raise ValueError("invalid numeric local account/group ID")
        records[fields[0]] = fields
    return records


def validate_local_accounts(root: Path) -> None:
    users = _table(root, "etc/passwd", 7)
    groups = _table(root, "etc/group", 4)
    for name, identity in ACCOUNT_IDS.items():
        user, group = users.get(name), groups.get(name)
        if (user is None or group is None or (int(user[2]), int(user[3]), int(group[2])) !=
                (identity, identity, identity)):
            raise ValueError("OS account IDs differ from the shared-state contract")
        if (any(other != name and int(record[2]) == identity for other, record in users.items())
                or any(other != name and int(record[2]) == identity for other, record in groups.items())):
            raise ValueError("reserved shared-state ID has another account/group alias")
    if users["rosy"][5:] != ["/home/rosy", "/bin/bash"]:
        raise ValueError("operator home or login shell differs")


def validate_shared_owners(root: Path) -> None:
    for relative, name, forbidden in (("var/lib/rosy/core", "rosy-core", 0o027),
                                      ("home/rosy/.ssh", "rosy", 0o077)):
        info = (root / relative).stat()
        if (info.st_uid != ACCOUNT_IDS[name] or info.st_gid != ACCOUNT_IDS[name]
                or info.st_mode & forbidden):
            raise ValueError("shared home owner/group/permissions differ")
    tls = (root / "etc/rosy/tls").stat()
    if (tls.st_uid != root.stat().st_uid or tls.st_gid != ACCOUNT_IDS["rosy-core"]
            or tls.st_mode & 0o7777 != 0o750):
        raise ValueError("shared TLS owner/group/permissions differ")
    for name, uid, gid, mode in (("maps", ACCOUNT_IDS["rosy-io"], ACCOUNT_IDS["rosy-core"], 0o2750),
                                 ("models", root.stat().st_uid, ACCOUNT_IDS["rosy-camera"], 0o750),
                                 ("pilot-recordings", ACCOUNT_IDS["rosy-camera"], ACCOUNT_IDS["rosy-core"], 0o2750)):
        info = (root / "var/lib/rosy" / name).stat()
        if (info.st_uid, info.st_gid, info.st_mode & 0o7777) != (uid, gid, mode):
            raise ValueError("shared data owner/group/permissions differ")
    for relative in ("var/lib/tailscale", COMMON + "/tailscale/join"):
        info = _path(root, relative).stat()
        if info.st_uid != root.stat().st_uid or info.st_mode & 0o7777 != 0o700:
            raise ValueError("shared tailnet owner/permissions differ")


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path("/"))
    args = parser.parse_args(argv)
    try:
        validate_local_accounts(args.root)
    except (OSError, ValueError):
        print("OS_ACCOUNT_HOLD", file=sys.stderr)
        return 1
    print("OS_ACCOUNTS_OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
