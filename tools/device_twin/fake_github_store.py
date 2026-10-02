"""The file store behind the device twin's fake GitHub (server) and fake gh (CLI). Twin only.

    <store>/<owner>/<repo>/releases.json        [{"tag_name", "target_commitish", "name", "draft",
                                                   "prerelease", "id", "created_at"}], oldest first
    <store>/<owner>/<repo>/assets/<tag>/<name>  asset bytes

Writes are atomic renames so the server never serves a half-written file.
"""

from __future__ import annotations

import datetime as dt
import json
import os
from pathlib import Path
import re

REPO = re.compile(r"^[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+$")
NAME = re.compile(r"^[A-Za-z0-9_.-]+$")


class StoreError(ValueError):
    pass


class Store:
    def __init__(self, root: Path) -> None:
        self.root = Path(root)

    def _repo(self, repo: str) -> Path:
        if not REPO.fullmatch(repo):
            raise StoreError(f"bad repo {repo!r}")
        return self.root / repo

    def releases(self, repo: str) -> list[dict]:
        path = self._repo(repo) / "releases.json"
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except FileNotFoundError:
            return []

    def _save(self, repo: str, releases: list[dict]) -> None:
        self._write(self._repo(repo) / "releases.json", (json.dumps(releases, indent=2) + "\n").encode())

    @staticmethod
    def _write(path: Path, data: bytes) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        temporary = path.with_name(f".{path.name}.tmp")
        temporary.write_bytes(data)
        os.replace(temporary, path)

    def release(self, repo: str, tag: str) -> dict | None:
        return next((item for item in self.releases(repo) if item["tag_name"] == tag), None)

    def create(self, repo: str, tag: str, target: str, title: str) -> dict:
        releases = self.releases(repo)
        if any(item["tag_name"] == tag for item in releases):
            raise StoreError(f"a release with tag {tag} already exists")
        item = {"tag_name": tag, "target_commitish": target, "name": title, "draft": False,
                "prerelease": False, "id": len(releases) + 1,
                "created_at": dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")}
        self._save(repo, releases + [item])
        return item

    def asset_path(self, repo: str, tag: str, name: str) -> Path:
        if not NAME.fullmatch(name) or not NAME.fullmatch(tag):
            raise StoreError(f"bad asset {tag}/{name}")
        return self._repo(repo) / "assets" / tag / name

    def upload(self, repo: str, tag: str, source: Path, clobber: bool) -> None:
        if self.release(repo, tag) is None:
            raise StoreError(f"release not found: {tag}")
        target = self.asset_path(repo, tag, source.name)
        if target.exists() and not clobber:
            raise StoreError(f"asset {source.name} already exists (use --clobber)")
        self._write(target, source.read_bytes())

    def assets(self, repo: str, tag: str) -> list[tuple[str, int]]:
        folder = self._repo(repo) / "assets" / tag
        if not folder.is_dir():
            return []
        return sorted((path.name, path.stat().st_size) for path in folder.iterdir()
                      if path.is_file() and not path.name.startswith("."))
