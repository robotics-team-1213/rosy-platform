#!/usr/bin/env python3
"""A fake `gh` CLI over the device twin's fake GitHub store (twin only).

Implements what tools/release/publish_payload_release.py calls:

    gh api repos/<owner>/<repo>/git/matching-refs/tags/<tag>
    gh release create <tag> --repo R --target REV --title T --notes N FILE...
    gh release upload <tag> --repo R [--clobber] FILE...
    gh release download <tag> --repo R [--pattern P]... --dir D [--clobber]
    gh release view <tag> --repo R [--json ...]

The store is TWIN_GH_STORE. Only repositories named twin/* are accepted, so a
mistake can never reach a real repository through this file.
"""

from __future__ import annotations

import fnmatch
import json
import os
from pathlib import Path
import shutil
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent))
from fake_github_store import Store, StoreError  # noqa: E402


def _options(args: list[str], flags: set[str], multi: set[str] = frozenset()) -> tuple[list[str], dict]:
    positional, values = [], {}
    index = 0
    while index < len(args):
        item = args[index]
        if item in flags:
            values[item] = True
            index += 1
        elif item.startswith("--"):
            value = args[index + 1]
            if item in multi:
                values.setdefault(item, []).append(value)
            else:
                values[item] = value
            index += 2
        else:
            positional.append(item)
            index += 1
    return positional, values


def _repo(values: dict) -> str:
    repo = values.get("--repo", "")
    if not repo.startswith("twin/"):
        raise StoreError(f"fake gh only serves twin/* repositories, not {repo!r}")
    return repo


def main(argv: list[str]) -> int:
    store_root = os.environ.get("TWIN_GH_STORE")
    if not store_root:
        print("TWIN_GH_STORE is not set", file=sys.stderr)
        return 2
    store = Store(Path(store_root))
    with (Path(store_root) / "gh-calls.jsonl").open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(argv) + "\n")
    try:
        if argv[:1] == ["api"]:
            parts = argv[1].split("/")
            if len(parts) == 7 and parts[0] == "repos" and parts[3:6] == ["git", "matching-refs", "tags"]:
                repo = f"{parts[1]}/{parts[2]}"
                if not repo.startswith("twin/"):
                    raise StoreError(f"fake gh only serves twin/* repositories, not {repo!r}")
                tags = [item["tag_name"] for item in store.releases(repo) if item["tag_name"].startswith(parts[6])]
                print(json.dumps([{"ref": f"refs/tags/{tag}"} for tag in tags]))
                return 0
            raise StoreError(f"unsupported api path {argv[1]}")
        if argv[:1] != ["release"] or len(argv) < 3:
            raise StoreError(f"unsupported command {argv[:2]}")
        action, rest = argv[1], argv[2:]
        if action == "create":
            positional, values = _options(rest, {"--draft", "--prerelease"})
            tag, files = positional[0], positional[1:]
            repo = _repo(values)
            store.create(repo, tag, values.get("--target", ""), values.get("--title", tag))
            for path in files:
                store.upload(repo, tag, Path(path), clobber=False)
            print(f"https://fake-github.twin/{repo}/releases/tag/{tag}")
            return 0
        if action == "upload":
            positional, values = _options(rest, {"--clobber"})
            repo = _repo(values)
            for path in positional[1:]:
                store.upload(repo, positional[0], Path(path), clobber=bool(values.get("--clobber")))
            return 0
        if action == "download":
            positional, values = _options(rest, {"--clobber"}, {"--pattern"})
            repo, tag = _repo(values), positional[0]
            if store.release(repo, tag) is None:
                raise StoreError(f"release not found: {tag}")
            target = Path(values.get("--dir", "."))
            target.mkdir(parents=True, exist_ok=True)
            patterns = values.get("--pattern") or ["*"]
            names = [name for name, _size in store.assets(repo, tag)
                     if any(fnmatch.fnmatchcase(name, pattern) for pattern in patterns)]
            if not names:
                raise StoreError("no assets match the file pattern")
            for name in names:
                if (target / name).exists() and not values.get("--clobber"):
                    raise StoreError(f"{name} already exists (use --clobber)")
                shutil.copyfile(store.asset_path(repo, tag, name), target / name)
            return 0
        if action == "view":
            positional, values = _options(rest, set())
            repo, tag = _repo(values), positional[0]
            release = store.release(repo, tag)
            if release is None:
                raise StoreError(f"release not found: {tag}")
            assets = [{"name": name, "size": size} for name, size in store.assets(repo, tag)]
            print(json.dumps({"tagName": tag, "name": release["name"], "isDraft": False,
                              "isPrerelease": False, "targetCommitish": release["target_commitish"],
                              "assets": assets}))
            return 0
        raise StoreError(f"unsupported release action {action}")
    except (StoreError, OSError, IndexError) as exc:
        print(f"fake gh: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
