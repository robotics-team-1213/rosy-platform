#!/usr/bin/env python3
"""Fetch only the allowlisted ROBOTIS repositories at full immutable commits."""

from __future__ import annotations

import re
import subprocess
import sys
from pathlib import Path

import yaml


SHA1 = re.compile(r"^[0-9a-f]{40}$")
ALLOWED_ORG = "https://github.com/ROBOTIS-GIT/"


def load_locked_sources(lock_path: Path) -> list[tuple[str, str, str]]:
    data = yaml.safe_load(lock_path.read_text(encoding="utf-8"))
    if not isinstance(data, dict) or data.get("schema") != "rosy.omx-vendor-stack-lock.v1":
        raise ValueError("unsupported OMX vendor lock schema")
    vendor = data.get("vendor")
    if not isinstance(vendor, dict):
        raise ValueError("vendor lock is missing")
    sources = [("open_manipulator", vendor.get("repository"), vendor.get("revision"))]
    repositories = vendor.get("repositories")
    if not isinstance(repositories, list) or not repositories:
        raise ValueError("vendor repositories lock is missing")
    for item in repositories:
        if not isinstance(item, dict):
            raise ValueError("invalid repository entry")
        sources.append((item.get("name"), item.get("repository"), item.get("revision")))
    names: set[str] = set()
    for name, repository, revision in sources:
        if not isinstance(name, str) or not re.fullmatch(r"[A-Za-z0-9_.-]+", name) or name in names:
            raise ValueError(f"invalid or duplicate source name: {name!r}")
        names.add(name)
        if not isinstance(repository, str) or not repository.startswith(ALLOWED_ORG) or not repository.endswith(".git"):
            raise ValueError(f"source is outside the ROBOTIS-GIT allowlist: {repository!r}")
        if not isinstance(revision, str) or not SHA1.fullmatch(revision):
            raise ValueError(f"source revision must be a full lowercase commit SHA: {name}")
    return [(str(name), str(repository), str(revision)) for name, repository, revision in sources]


def fetch(lock_path: Path, destination: Path) -> None:
    for name, repository, revision in load_locked_sources(lock_path):
        checkout = destination / name
        subprocess.run(["git", "init", str(checkout)], check=True, capture_output=True, text=True)
        subprocess.run(["git", "-C", str(checkout), "remote", "add", "origin", repository], check=True)
        subprocess.run(
            ["git", "-C", str(checkout), "fetch", "--depth=1", "origin", revision],
            check=True,
        )
        subprocess.run(["git", "-C", str(checkout), "checkout", "--detach", "FETCH_HEAD"], check=True)
        actual = subprocess.run(
            ["git", "-C", str(checkout), "rev-parse", "HEAD"],
            check=True,
            capture_output=True,
            text=True,
        ).stdout.strip()
        if actual != revision:
            raise RuntimeError(f"resolved {name} to {actual}, expected {revision}")


def main(argv: list[str]) -> int:
    if len(argv) != 3:
        print("usage: fetch_sources.py LOCK.yaml DESTINATION", file=sys.stderr)
        return 2
    fetch(Path(argv[1]), Path(argv[2]))
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
