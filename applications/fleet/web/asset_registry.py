"""The app's static URL contract, usable without Fleet or ROS."""

import json
from pathlib import Path, PurePosixPath
import re


def _unique(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError(f"duplicate asset registry key: {key}")
        result[key] = value
    return result


def _file(root, relative):
    if not isinstance(relative, str) or not relative or any(c in relative for c in ("\\", ":", "\0")):
        raise ValueError("invalid asset path")
    path = PurePosixPath(relative)
    if path.is_absolute() or ".." in path.parts:
        raise ValueError("asset path escapes its root")
    base = Path(root).resolve()
    target = (base / relative).resolve()
    if not target.is_relative_to(base) or not target.is_file():
        raise ValueError("asset file is missing or outside its root")
    return target


def load_registry(root: Path) -> dict:
    """Read a complete allowlist; reject duplicates, missing files and path escapes."""
    try:
        document = json.loads((Path(root) / "assets.json").read_text(encoding="utf-8"),
                              object_pairs_hook=_unique)
    except OSError as exc:
        raise ValueError("app asset registry is unavailable") from exc
    if not isinstance(document, dict) or set(document) != {"pages", "assets"}:
        raise ValueError("asset registry requires pages and assets")
    for group in ("pages", "assets"):
        if not isinstance(document[group], dict):
            raise ValueError("asset registry entries must be objects")
        for name, entry in document[group].items():
            valid_name = (re.fullmatch(r"/console(?:/[A-Za-z0-9_-]+)*", name) if group == "pages"
                          else re.fullmatch(r"[A-Za-z0-9_][A-Za-z0-9_.-]*", name))
            if not valid_name or not isinstance(entry, dict) or set(entry) != {"path", "media_type"}:
                raise ValueError("invalid asset registry entry")
            mime = entry["media_type"]
            if not isinstance(mime, str) or not re.fullmatch(r"[A-Za-z0-9.+_-]+/[A-Za-z0-9.+_-]+", mime):
                raise ValueError("invalid asset media type")
            _file(root, entry["path"])
    return document


def resolve_entry(root: Path, entries, name: str):
    """Resolve an allowlisted resource again, including after a symlink/file change."""
    entry = entries.get(name)
    if entry is None:
        return None
    try:
        return _file(root, entry["path"]), entry["media_type"]
    except (OSError, ValueError):
        return None
