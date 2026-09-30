"""The store folder: source of truth for datasets and models (D-373 decision 8).

One path. Today a local folder on the site PC; later a NAS mount or a Google
Drive folder (Drive for desktop on the site PC, drive.mount in Colab) with the
same layout. Changing the backend changes the path, not this code.

    datasets/<name>/<content_sha>/   immutable once written
    models/inbox/<folder>/           trainers drop hand-overs here
    models/accepted/<revision>/      intake passed
    models/rejected/<folder>/        intake failed; REJECTED.txt says why

content_sha(folder) = sha256 over the sorted lines "relpath\\0sha256(file)\\n"
(relpath with "/" on every OS), leaving out OS litter and the READY marker.
An inbox folder is complete only when its READY file holds its content_sha:
a half-synced Drive/NAS copy has no marker or a marker that does not match.

Stdlib only: imported by the site watcher, rosy_ml, publish.py and Colab."""

from __future__ import annotations

import datetime as dt
import hashlib
import os
import re
import shutil
from pathlib import Path

READY = "READY"
REASON = "REJECTED.txt"
IGNORED = frozenset({".DS_Store", "desktop.ini", "Thumbs.db"})
_NAME = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]*")
_SHA = re.compile(r"[0-9a-f]{64}")
_REF = re.compile(r"^(?:store:)?(?P<name>[A-Za-z0-9][A-Za-z0-9._-]*)@(?P<sha>[0-9a-f]{64})$")


class StoreError(ValueError):
    """The store refuses: bad name, a version that would change, a clash."""


def _sha256(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def file_hashes(folder) -> dict[str, str]:
    """{"a/b.png": sha256} for every counted file under folder."""
    folder = Path(folder)
    if not folder.is_dir():
        raise FileNotFoundError(f"not a folder: {folder}")
    out = {}
    for p in folder.rglob("*"):
        if not p.is_file() or p.name in IGNORED:
            continue
        rel = p.relative_to(folder).as_posix()
        if rel == READY:
            continue
        out[rel] = _sha256(p)
    return out


def content_sha(folder) -> str:
    lines = sorted(f"{rel}\0{sha}\n".encode("utf-8") for rel, sha in file_hashes(folder).items())
    return hashlib.sha256(b"".join(lines)).hexdigest()


def safe_name(name) -> bool:
    return isinstance(name, str) and _NAME.fullmatch(name) is not None


def parse_dataset_ref(ref: str) -> tuple[str, str]:
    """'store:<name>@<sha>' or '<name>@<sha>' -> (name, sha)."""
    m = _REF.match(ref.strip())
    if not m:
        raise ValueError(f"{ref!r}: expected store:<name>@<64-hex content sha>")
    return m["name"], m["sha"]


def _utc() -> str:
    return dt.datetime.now(dt.timezone.utc).strftime("%Y%m%dT%H%M%SZ")


class Store:
    def __init__(self, root):
        self.root = Path(root)
        self.datasets_dir = self.root / "datasets"
        self.inbox = self.root / "models" / "inbox"
        self.accepted = self.root / "models" / "accepted"
        self.rejected = self.root / "models" / "rejected"

    def layout(self) -> list[Path]:
        return [self.datasets_dir, self.inbox, self.accepted, self.rejected]

    def ensure_layout(self) -> None:
        for d in self.layout():
            d.mkdir(parents=True, exist_ok=True)

    # --- datasets ---------------------------------------------------------------------------

    def dataset_path(self, name: str, sha: str) -> Path:
        if not safe_name(name) or not _SHA.fullmatch(sha or ""):
            raise StoreError(f"bad dataset ref {name!r}@{sha!r}")
        return self.datasets_dir / name / sha

    def datasets(self) -> dict[str, list[str]]:
        if not self.datasets_dir.is_dir():
            return {}
        return {d.name: sorted(v.name for v in d.iterdir() if v.is_dir() and _SHA.fullmatch(v.name))
                for d in sorted(self.datasets_dir.iterdir()) if d.is_dir() and safe_name(d.name)}

    def put_dataset(self, src_dir, name: str) -> tuple[Path, str]:
        """Copy src_dir to datasets/<name>/<content_sha>/ (temp sibling, then rename).
        The same content again is a no-op; a different folder at that sha is refused."""
        if not safe_name(name):
            raise StoreError(f"dataset name {name!r}: expected [A-Za-z0-9][A-Za-z0-9._-]*")
        sha = content_sha(src_dir)
        dest = self.dataset_path(name, sha)
        if dest.exists():
            if content_sha(dest) != sha:
                raise StoreError(f"{dest} exists and its content differs: never overwritten")
            return dest, sha
        dest.parent.mkdir(parents=True, exist_ok=True)
        tmp = dest.parent / f".tmp-{sha[:12]}-{os.getpid()}"
        shutil.rmtree(tmp, ignore_errors=True)
        try:
            shutil.copytree(src_dir, tmp, ignore=shutil.ignore_patterns(*IGNORED, READY))
            if content_sha(tmp) != sha:
                raise StoreError(f"{src_dir} changed while it was copied")
            os.rename(tmp, dest)
        finally:
            shutil.rmtree(tmp, ignore_errors=True)
        return dest, sha

    # --- model inbox ------------------------------------------------------------------------

    def inbox_folder(self, folder) -> Path:
        """An inbox folder by name (or a path inside the inbox); never outside it."""
        name = Path(folder).name if isinstance(folder, Path) else str(folder)
        if isinstance(folder, Path) and folder.parent.resolve() != self.inbox.resolve():
            raise StoreError(f"{folder} is not directly inside {self.inbox}")
        if not safe_name(name):
            raise StoreError(f"inbox folder {name!r}: expected [A-Za-z0-9][A-Za-z0-9._-]*")
        return self.inbox / name

    def inbox_ready(self, folder) -> bool:
        path = self.inbox_folder(folder)
        marker = path / READY
        try:
            want = marker.read_text(encoding="utf-8").strip()
            return path.is_dir() and _SHA.fullmatch(want) is not None and content_sha(path) == want
        except OSError:
            return False

    def _inbox_dirs(self) -> list[Path]:
        if not self.inbox.is_dir():
            return []
        return [p for p in self.inbox.iterdir() if p.is_dir() and safe_name(p.name)]

    def list_inbox(self) -> list[str]:
        """Complete folders, oldest READY marker first."""
        ready = [p for p in self._inbox_dirs() if self.inbox_ready(p)]
        return [p.name for p in sorted(ready, key=lambda p: ((p / READY).stat().st_mtime, p.name))]

    def accept(self, folder, revision: str) -> Path:
        """inbox/<folder> -> accepted/<revision>. The same files already accepted
        under that revision: the inbox copy is dropped. Other files: refused."""
        if not safe_name(revision):
            raise StoreError(f"revision {revision!r}: expected [A-Za-z0-9][A-Za-z0-9._-]*")
        src = self.inbox_folder(folder)
        dest = self.accepted / revision
        if dest.exists():
            have = file_hashes(dest)
            if any(have.get(rel) != sha for rel, sha in file_hashes(src).items()):
                raise StoreError(f"{revision} already accepted with different files")
            shutil.rmtree(src)
            return dest
        _move(src, dest)
        return dest

    def reject(self, folder, reason: str) -> Path:
        src = self.inbox_folder(folder)
        dest = self.rejected / src.name
        if dest.exists():
            dest = self.rejected / f"{src.name}__{_utc()}"
            n = 2
            while dest.exists():
                dest, n = self.rejected / f"{src.name}__{_utc()}_{n}", n + 1
        _move(src, dest)
        (dest / REASON).write_text(reason.rstrip("\n") + "\n", encoding="utf-8")
        return dest

    def status(self) -> dict:
        dirs = self._inbox_dirs()
        ready = sum(self.inbox_ready(p) for p in dirs)

        def count(d: Path) -> int:
            return sum(p.is_dir() for p in d.iterdir()) if d.is_dir() else 0
        return {"root": str(self.root), "datasets": self.datasets(), "inbox_ready": ready,
                "inbox_waiting": len(dirs) - ready, "accepted": count(self.accepted),
                "rejected": count(self.rejected)}


def _move(src: Path, dest: Path) -> None:
    """Rename; across devices (a NAS or Drive mount) copy, verify every file, then remove."""
    dest.parent.mkdir(parents=True, exist_ok=True)
    try:
        os.rename(src, dest)
        return
    except OSError:
        if dest.exists():
            raise
    tmp = dest.parent / f".tmp-{dest.name}-{os.getpid()}"
    shutil.rmtree(tmp, ignore_errors=True)
    try:
        shutil.copytree(src, tmp)
        if file_hashes(tmp) != file_hashes(src):
            raise StoreError(f"copy of {src} does not match; source kept")
        tmp.replace(dest)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
    shutil.rmtree(src)
