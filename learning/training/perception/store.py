"""The store folder: source of truth for datasets and models (D-373 decision 8).

One path. Today a local folder on the site PC; later a NAS mount or a Google
Drive folder (Drive for desktop on the site PC, drive.mount in Colab) with the
same layout. Changing the backend changes the path, not this code.

    datasets/<name>/<content_sha>/   immutable once written
    evalsets/<name>/<content_sha>/   fixed evaluation sets (D-379 d3), same rules;
                                     optional, so not part of layout()
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
import json
import os
import re
import shutil
import stat
from pathlib import Path

READY = "READY"
REASON = "REJECTED.txt"
IGNORED = frozenset({".DS_Store", "desktop.ini", "Thumbs.db"})
_NAME = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]*")
_SHA = re.compile(r"[0-9a-f]{64}")
_REF = re.compile(r"^(?:store:)?(?P<name>[A-Za-z0-9][A-Za-z0-9._-]*)@(?P<sha>[0-9a-f]{64})$")


class StoreError(ValueError):
    """The store refuses: bad name, a version that would change, a clash."""


def publication_group(path: Path) -> int | None:
    """An existing setgid destination opts into a shared POSIX publication group."""
    if os.name != 'posix':
        return None
    path = Path(path).absolute()
    for ancestor in [*reversed(path.parents), path]:
        if ancestor.is_symlink():
            raise StoreError('publication path refuses a symlink ancestor')
    while not path.exists() and not path.is_symlink():
        path = path.parent
    info = path.lstat()
    if not stat.S_ISDIR(info.st_mode):
        raise StoreError('publication parent must be a directory, never a symlink')
    if not info.st_mode & stat.S_ISGID:
        return None
    if info.st_gid not in {*os.getgroups(), os.getegid()}:
        raise StoreError('publisher is not a member of the destination group')
    return info.st_gid


def publication_directory(path: Path, *, exist_ok=True) -> int | None:
    """Create missing destination ancestors without a private umask hiding them."""
    path = Path(path)
    group = publication_group(path)
    missing = []
    cursor = path
    while not cursor.exists() and not cursor.is_symlink():
        missing.append(cursor)
        cursor = cursor.parent
    path.mkdir(parents=True, exist_ok=exist_ok)
    if group is not None:
        for directory in reversed(missing):
            if directory.stat().st_gid != group:
                os.chown(directory, -1, group)
            directory.chmod(0o2770)
    return group


def refuse_publication_links(root: Path) -> None:
    """Permissions must never apply through source/destination links."""
    for path in [Path(root), *Path(root).rglob('*')]:
        if path.is_symlink():
            raise StoreError('shared publication refuses a symlink')
        if not (path.is_file() or path.is_dir()):
            raise StoreError('shared publication refuses a special file')


def shared_publication_permissions(root: Path, group: int | None) -> None:
    """Prepare new artifact bytes for group reading before publishing READY/rename."""
    if group is None:
        return
    refuse_publication_links(root)
    paths = sorted(Path(root).rglob('*'), key=lambda p: len(p.parts), reverse=True) + [Path(root)]
    for path in paths:
        if path.stat().st_gid != group:
            os.chown(path, -1, group)
        path.chmod(0o2770 if path.is_dir() else 0o640)


def _sha256(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def file_hashes(folder) -> dict[str, str]:
    """{"a/b.png": sha256} for every counted file under folder."""
    folder = Path(folder)
    if os.name == "nt":
        # Regular Windows paths can silently omit deep files during is_file().
        absolute = os.path.abspath(folder)
        if not absolute.startswith("\\\\?\\"):
            absolute = ("\\\\?\\UNC\\" + absolute[2:] if absolute.startswith("\\\\")
                        else "\\\\?\\" + absolute)
        folder = Path(absolute)
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
        self.evalsets_dir = self.root / "evalsets"
        self.eval_reservations_dir = self.root / "eval-reservations"
        self.inbox = self.root / "models" / "inbox"
        self.accepted = self.root / "models" / "accepted"
        self.rejected = self.root / "models" / "rejected"

    def layout(self) -> list[Path]:
        return [self.datasets_dir, self.inbox, self.accepted, self.rejected]

    def ensure_layout(self) -> None:
        for d in self.layout():
            publication_directory(d)

    # --- datasets ---------------------------------------------------------------------------

    def dataset_path(self, name: str, sha: str) -> Path:
        if not safe_name(name) or not _SHA.fullmatch(sha or ""):
            raise StoreError(f"bad dataset ref {name!r}@{sha!r}")
        return self.datasets_dir / name / sha

    def datasets(self) -> dict[str, list[str]]:
        return _versions(self.datasets_dir)

    # --- eval sets (D-379 decision 3) ---------------------------------------------------------

    def evalset_path(self, name: str, sha: str) -> Path:
        if not safe_name(name) or not _SHA.fullmatch(sha or ""):
            raise StoreError(f"bad eval set ref {name!r}@{sha!r}")
        return self.evalsets_dir / name / sha

    def evalsets(self) -> dict[str, list[str]]:
        return _versions(self.evalsets_dir)

    def eval_reservations(self) -> dict[str, str]:
        """Session -> capture group; malformed or changed reservations block training."""
        base = self.eval_reservations_dir
        if not base.exists() and not base.is_symlink():
            return {}
        if base.is_symlink() or not base.is_dir():
            raise StoreError("invalid eval reservation directory")
        result = {}
        for directory in base.iterdir():
            if directory.is_symlink() or not directory.is_dir() or not safe_name(directory.name):
                raise StoreError("invalid eval reservation session")
            files = list(directory.iterdir())
            if len(files) != 1 or files[0].is_symlink() or not files[0].is_file():
                raise StoreError("invalid eval reservation file")
            path = files[0]
            raw = path.read_bytes()
            if (len(raw) > 512 or path.name != hashlib.sha256(raw).hexdigest() + ".json"):
                raise StoreError("eval reservation changed")
            try:
                row = json.loads(raw)
            except ValueError as exc:
                raise StoreError("invalid eval reservation JSON") from exc
            if (not isinstance(row, dict) or set(row) != {"schema", "source_session", "capture_group"}
                    or row["schema"] != "rosy.eval-reservation/1"
                    or row["source_session"] != directory.name
                    or not safe_name(row["capture_group"])):
                raise StoreError("invalid eval reservation identity")
            result[directory.name] = row["capture_group"]
        return result

    def reserve_eval_source(self, source_session: str, capture_group: str) -> Path:
        if not safe_name(source_session) or not safe_name(capture_group):
            raise StoreError("invalid eval reservation identity")
        self.eval_reservations()
        publication_directory(self.eval_reservations_dir)
        directory = self.eval_reservations_dir / source_session
        try:
            directory.mkdir()
        except FileExistsError as exc:
            raise StoreError(f"{source_session} already reserved") from exc
        row = {"schema": "rosy.eval-reservation/1", "source_session": source_session,
               "capture_group": capture_group}
        raw = (json.dumps(row, sort_keys=True, separators=(",", ":")) + "\n").encode()
        path = directory / (hashlib.sha256(raw).hexdigest() + ".json")
        path.write_bytes(raw)
        shared_publication_permissions(directory, publication_group(self.eval_reservations_dir))
        return path

    def put_dataset(self, src_dir, name: str) -> tuple[Path, str]:
        """Copy src_dir to datasets/<name>/<content_sha>/ (temp sibling, then rename).
        The same content again is a no-op; a different folder at that sha is refused."""
        if not safe_name(name):
            raise StoreError(f"dataset name {name!r}: expected [A-Za-z0-9][A-Za-z0-9._-]*")
        group = publication_group(self.root)
        if group is not None:
            refuse_publication_links(Path(src_dir))
        sha = content_sha(src_dir)
        dest = self.dataset_path(name, sha)
        if dest.exists():
            if content_sha(dest) != sha:
                raise StoreError(f"{dest} exists and its content differs: never overwritten")
            return dest, sha
        publication_directory(dest.parent)
        tmp = dest.parent / f".tmp-{sha[:12]}-{os.getpid()}"
        shutil.rmtree(tmp, ignore_errors=True)
        try:
            shutil.copytree(src_dir, tmp, ignore=shutil.ignore_patterns(*IGNORED, READY))
            if content_sha(tmp) != sha:
                raise StoreError(f"{src_dir} changed while it was copied")
            shared_publication_permissions(tmp, group)
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
        return {"root": str(self.root), "datasets": self.datasets(), "evalsets": self.evalsets(),
                "inbox_ready": ready,
                "inbox_waiting": len(dirs) - ready, "accepted": count(self.accepted),
                "rejected": count(self.rejected)}


def _versions(base: Path) -> dict[str, list[str]]:
    """{name: [content_sha, ...]} for <base>/<name>/<content_sha>/ folders."""
    if not base.is_dir():
        return {}
    return {d.name: sorted(v.name for v in d.iterdir() if v.is_dir() and _SHA.fullmatch(v.name))
            for d in sorted(base.iterdir()) if d.is_dir() and safe_name(d.name)}


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
