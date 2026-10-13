#!/usr/bin/env python3
"""Join the team tailnet with the provisioned one-time auth key (D-477).

tailscaled (the tailscale package unit) is the daemon; this oneshot helper only
spends the key. The first-boot provisioner may write
/etc/rosy/tailscale-join.json (0600, root) from the one-time bundle (D-154,
D-226): {"auth_key": ..., "tags": [...], "hostname": ...}. This program

* validates the file again on its own — it never trusts what wrote it,
* resolves the tailscale CLI and refuses to run anything else,
* when the daemon is not logged in yet, runs
  `tailscale up --auth-key=... --advertise-tags=... --hostname=...
  --accept-dns=false --accept-routes=false`, each step bounded,
* rewrites the file in place WITHOUT the key (same inode; /etc/rosy stays
  read-only otherwise) so a spent key cannot be replayed from the card,
* records the outcome in /var/lib/rosy/tailscale/join-result.json.

The key never reaches the journal, the result file or an exception tail: every
subprocess message is scrubbed against the key before it is kept. Fail closed:
a refused or failed join leaves the file untouched and exits non-zero, so the
next boot retries (StartLimitIntervalSec=0 on the unit). An already-joined
robot still consumes the key and reports already_joined.

Standard library only; run as `python3 -I -B`. ROSY_TAILSCALE_ROOT and
ROSY_TAILSCALE_CLI are test seams (the unit sets neither).
"""

from __future__ import annotations

import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
from typing import Any

sys.dont_write_bytecode = True

SCHEMA = 1
#: The provisioned one-time join request (root 0600, rewritten in place).
JOIN = "etc/rosy/tailscale-join.json"
#: The join outcome, in the unit's StateDirectory=rosy/tailscale.
RESULT = "var/lib/rosy/tailscale/join-result.json"
#: One `tskey-...` auth key, issued by the tailnet owner (never printed).
KEY_PATTERN = re.compile(r"tskey-[a-z]+-[A-Za-z0-9-]{10,128}")
TAG_PATTERN = re.compile(r"tag:[a-z0-9][a-z0-9-]{0,40}")
HOSTNAME_PATTERN = re.compile(r"[a-z0-9][a-z0-9-]{0,62}")
DEFAULT_TAG = "tag:rosy-robot"
MAX_TAGS = 4
JOIN_FILE_MAX_BYTES = 4096
STATUS_TIMEOUT_S = 15.0
UP_TIMEOUT_S = 90.0
REDUCED = "<redacted>"


def _scrub(text: str, secret: str) -> str:
    if not secret:
        return text
    return text.replace(secret, REDUCED)


def _tail(text: str, limit: int = 400) -> str:
    cleaned = " ".join(text.split())
    return cleaned[-limit:]


def _load_join(path: Path) -> dict[str, Any]:
    if path.stat().st_size > JOIN_FILE_MAX_BYTES:
        raise ValueError("join file is implausibly large")
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict) or set(data) != {"auth_key", "tags", "hostname"}:
        raise ValueError("join file keys are invalid")
    key = data["auth_key"]
    if not isinstance(key, str) or not KEY_PATTERN.fullmatch(key):
        raise ValueError("join auth key is invalid")
    tags = data["tags"]
    if not isinstance(tags, list) or not 1 <= len(tags) <= MAX_TAGS:
        raise ValueError("join tags are invalid")
    for tag in tags:
        if not isinstance(tag, str) or not TAG_PATTERN.fullmatch(tag):
            raise ValueError("join tags are invalid")
    hostname = data["hostname"]
    if not isinstance(hostname, str) or not HOSTNAME_PATTERN.fullmatch(hostname):
        raise ValueError("join hostname is invalid")
    return data


def _write_result(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_name("." + path.name + ".new")
    temp.write_text(
        json.dumps(payload, sort_keys=True, ensure_ascii=True) + "\n", encoding="utf-8")
    os.replace(temp, path)


def _consume_key(path: Path, data: dict[str, Any]) -> None:
    """Rewrite the join file in place without the key (same inode, then fsync)."""
    kept = {"schema_version": SCHEMA, "tags": data["tags"], "hostname": data["hostname"]}
    with open(path, "r+", encoding="utf-8") as handle:
        handle.write(json.dumps(kept, sort_keys=True, ensure_ascii=True))
        handle.truncate()
        handle.flush()
        os.fsync(handle.fileno())


def _resolve_cli() -> str:
    override = os.environ.get("ROSY_TAILSCALE_CLI")
    if override:
        return override
    found = shutil.which("tailscale")
    if found:
        return found
    if os.access("/usr/bin/tailscale", os.X_OK):
        return "/usr/bin/tailscale"
    raise RuntimeError("the tailscale CLI is not installed")


def _invoke(argv: list[str], timeout_s: float) -> subprocess.CompletedProcess[str]:
    """Runs the CLI. Tests replace this seam; production always subprocesses."""
    return subprocess.run(
        argv, capture_output=True, text=True, timeout=timeout_s, check=False)


def _joined(cli: str) -> bool:
    try:
        done = _invoke([cli, "status", "--json"], STATUS_TIMEOUT_S)
    except (subprocess.TimeoutExpired, OSError):
        return False
    if done.returncode != 0:
        return False
    try:
        status = json.loads(done.stdout)
    except ValueError:
        return False
    return status.get("BackendState") == "Running" and isinstance(status.get("Self"), dict)


def main(argv: list[str] | None = None) -> int:
    root = Path(os.environ.get("ROSY_TAILSCALE_ROOT", "/"))
    join_path = root / JOIN
    result_path = root / RESULT
    try:
        data = _load_join(join_path)
        cli = _resolve_cli()
    except (OSError, ValueError, RuntimeError) as error:
        print(f"rosy-tailscale-join: refusing: {error}", file=sys.stderr)
        return 1

    key = data["auth_key"]
    error_text = ""
    if _joined(cli):
        status = "already_joined"
    else:
        up = [
            cli, "up",
            "--auth-key=" + key,
            "--advertise-tags=" + ",".join(data["tags"]),
            "--hostname=" + data["hostname"],
            "--accept-dns=false",
            "--accept-routes=false",
        ]
        try:
            done = _invoke(up, UP_TIMEOUT_S)
        except subprocess.TimeoutExpired:
            done = None
            error_text = "tailscale up timed out"
        except OSError as error:
            done = None
            error_text = _scrub(str(error), key)
        if done is not None and done.returncode == 0:
            status = "joined"
        else:
            status = "failed"
            if not error_text:
                parts = [done.stderr, done.stdout]  # type: ignore[union-attr]
                error_text = _tail(_scrub(" ".join(parts), key))
    if status != "failed":
        _consume_key(join_path, data)
    result = {"schema_version": SCHEMA, "status": status, "hostname": data["hostname"]}
    if error_text:
        result["error"] = _tail(error_text)
    _write_result(result_path, result)
    print(f"rosy-tailscale-join: {status} ({data['hostname']})", file=sys.stderr)
    return 0 if status != "failed" else 1


if __name__ == "__main__":
    sys.exit(main())
