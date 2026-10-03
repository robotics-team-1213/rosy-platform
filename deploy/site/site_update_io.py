"""Reviewed HTTP and filesystem ports for the site updater (D-441)."""

from __future__ import annotations
import contextlib
import datetime as _dt
import hashlib
import http.client
import json
import os
from pathlib import Path
import re
import ssl
import subprocess
import sys
import tarfile
import urllib.error
import urllib.request
from typing import Callable, Iterator

Runner = Callable[..., subprocess.CompletedProcess]

SERVICES = ("fleet", "vision", "proxy")
PROJECT = "rosy-site"
STACK_UNIT = "rosy-site-stack.service"
SIGNATURE = "release.json.sig"
EXIT_OK = 0
EXIT_FAILED = 1
EXIT_CONFIG = 2
EXIT_LOCKED = 3

_TAG = re.compile(r"^site-[0-9a-f]{12}$")
_COMMIT = re.compile(r"^[0-9a-f]{40}$")
_REPO = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_-]*/[A-Za-z0-9][A-Za-z0-9_.-]*$")
_KEY_ID = re.compile(r"^[A-Za-z0-9._-]{1,64}$")
_PART = re.compile(r"^rosy-site-candidate-([0-9a-f]{40})\.tar\.part(\d{2})$")
_MAX_PAGES = 10
_LIST_LIMIT = 16 * 1024 * 1024
_SMALL_LIMIT = 8 * 1024 * 1024


class Transient(Exception):
    """Try again on the next timer run; nothing is recorded as failed."""


class Rejected(Exception):
    """This candidate is not installed; recorded as failed for its tag."""


class Refused(Exception):
    """Host configuration forbids automatic updates; nothing is changed."""


class ConfigError(ValueError):
    """autoupdate.conf is unusable."""


def _now() -> str:
    return _dt.datetime.now(_dt.timezone.utc).replace(microsecond=0).isoformat()


def log(event: str, **fields) -> None:
    print(json.dumps({"time": _now(), "event": event, **fields}, sort_keys=True), flush=True)


class Paths:
    """Host paths; ``root`` is "/" on the host and a temporary folder in tests."""

    def __init__(self, root: Path = Path("/")):
        root = Path(root)
        self.site_env = root / "etc/rosy/site/site.env"
        self.env_backup = root / "etc/rosy/site/site.env.autoupdate-prev"
        self.config = root / "etc/rosy/site/autoupdate.conf"
        self.candidates = root / "opt/rosy/candidates"
        self.link = root / "opt/rosy/candidate"
        self.state = root / "var/lib/rosy/site-autoupdate.json"
        self.lock = root / "run/lock/rosy-site-autoupdate.lock"


def load_config(path: Path) -> dict:
    try:
        raw = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise ConfigError(f"cannot read {path}: {type(error).__name__}") from None
    if not isinstance(raw, dict):
        raise ConfigError("config must be a JSON object")
    allowed = {"repo", "key_id", "public_key", "keep", "health_url", "health_ca",
               "health_timeout_s"}
    if set(raw) - allowed:
        raise ConfigError(f"unknown config keys: {sorted(set(raw) - allowed)}")
    if not isinstance(raw.get("repo"), str) or not _REPO.fullmatch(raw["repo"]):
        raise ConfigError("repo must be owner/repository")
    if not isinstance(raw.get("key_id"), str) or not _KEY_ID.fullmatch(raw["key_id"]):
        raise ConfigError("key_id is malformed")
    if not isinstance(raw.get("public_key"), str) or not Path(raw["public_key"]).is_file():
        raise ConfigError("public_key must name the enrolled public key file")
    url = raw.get("health_url")
    if not isinstance(url, str) or not url.startswith("https://"):
        raise ConfigError("health_url must be an https:// URL")
    ca = raw.get("health_ca")
    if ca is not None and (not isinstance(ca, str) or not Path(ca).is_file()):
        raise ConfigError("health_ca must name a CA file")
    keep = raw.get("keep", 3)
    if type(keep) is not int or not 2 <= keep <= 20:
        raise ConfigError("keep must be an integer from 2 to 20")
    timeout = raw.get("health_timeout_s", 300)
    if type(timeout) is not int or not 30 <= timeout <= 1800:
        raise ConfigError("health_timeout_s must be an integer from 30 to 1800")
    return {"repo": raw["repo"], "key_id": raw["key_id"], "public_key": Path(raw["public_key"]),
            "keep": keep, "health_url": url, "health_ca": ca, "health_timeout_s": timeout}


# -- HTTPS ----------------------------------------------------------------------

class _HttpsOnly(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        if not newurl.startswith("https://"):
            raise urllib.error.HTTPError(newurl, code, "refusing a non-https redirect",
                                         headers, fp)
        return super().redirect_request(req, fp, code, msg, headers, newurl)


class Http:
    """Unauthenticated HTTPS GETs; release assets are public (D-437)."""

    def __init__(self, timeout: int = 60):
        self.timeout = timeout
        self.opener = urllib.request.build_opener(
            _HttpsOnly, urllib.request.HTTPSHandler(context=ssl.create_default_context()))

    def _open(self, url: str):
        if not url.startswith("https://"):
            raise Transient(f"refusing a non-https URL: {url}")
        request = urllib.request.Request(url, headers={
            "Accept": "application/vnd.github+json", "User-Agent": "rosy-site-autoupdate"})
        try:
            return self.opener.open(request, timeout=self.timeout)
        except (OSError, urllib.error.URLError) as error:
            raise Transient(f"GET {url} failed: {error}") from None

    def get(self, url: str, limit: int) -> bytes:
        try:
            with self._open(url) as response:
                expected = getattr(response, 'headers', {}).get('Content-Length')
                data = response.read(limit + 1)
        except (OSError, http.client.HTTPException) as error:
            raise Transient(f"GET {url} failed: {error}") from None
        if len(data) > limit:
            raise Transient(f"GET {url} exceeded {limit} bytes")
        _check_length(expected, len(data))
        return data

    def download(self, url: str, destination: Path) -> str:
        digest = hashlib.sha256()
        received = 0
        try:
            with self._open(url) as response, destination.open("wb") as stream:
                expected = getattr(response, 'headers', {}).get('Content-Length')
                for chunk in iter(lambda: response.read(1024 * 1024), b""):
                    received += len(chunk)
                    digest.update(chunk)
                    stream.write(chunk)
        except (OSError, http.client.HTTPException) as error:
            raise Transient(f"download {url} failed: {error}") from None
        _check_length(expected, received)
        return digest.hexdigest()

    def status(self, url: str, ca_file: str | None) -> int:
        context = ssl.create_default_context(cafile=ca_file)
        try:
            with urllib.request.urlopen(url, timeout=5, context=context) as response:
                return response.status
        except urllib.error.HTTPError as error:
            return error.code
        except (OSError, urllib.error.URLError):
            return 0


# -- helpers ----------------------------------------------------------------------


def _check_length(expected, received: int) -> None:
    if expected is not None:
        try:
            complete = int(expected) == received
        except (TypeError, ValueError):
            complete = False
        if not complete:
            raise Transient('HTTP body does not match Content-Length')


def load_update_state(paths: Paths) -> dict:
    try:
        state = json.loads(paths.state.read_text(encoding='utf-8'))
    except FileNotFoundError:
        if paths.env_backup.exists():
            raise Refused('state missing while a rollback backup exists') from None
        state = {}
    except (OSError, ValueError):
        raise Refused('update state cannot be read; preserve and recover it manually') from None
    if not isinstance(state, dict) or not isinstance(state.get('failed', {}), dict):
        raise Refused('update state has an invalid schema')
    if 'switch' in state:
        journal = state['switch']
        if not isinstance(journal, dict):
            raise Refused('switch journal has an invalid schema')
        for key in ('current', 'commit'):
            if not isinstance(journal.get(key), str) or not _COMMIT.fullmatch(journal[key]):
                raise Refused('switch journal has an invalid commit')
        if journal.get('tag') != f"site-{journal['commit'][:12]}":
            raise Refused('switch journal tag does not match commit')
        previous = journal.get('previous')
        if (not isinstance(previous, str) or not Path(previous).is_absolute()
                or Path(previous).resolve().parent != paths.candidates.resolve()
                or type(journal.get('migration', False)) is not bool):
            raise Refused('switch journal has an invalid rollback path')
    state.setdefault('failed', {})
    return state


def forget_failed(updater, tag: str) -> int:
    try:
        with run_lock(updater.paths.lock):
            state = updater.load_state()
            removed = state['failed'].pop(tag, None)
            updater.save_state(state)
            log('forget-failed', tag=tag, removed=removed is not None)
            return EXIT_OK
    except BlockingIOError as error:
        log('locked', reason=str(error))
        return EXIT_LOCKED
    except Refused as error:
        log('state-refused', reason=str(error))
        return EXIT_FAILED


def containers_reason(rows, commit: str, accepted: dict, run) -> str:
    if not isinstance(rows, list):
        return 'docker compose ps output is not a list'
    for service in SERVICES:
        matches = [row for row in rows if isinstance(row, dict) and row.get('Service') == service]
        if len(matches) != 1:
            return f'{service} needs exactly one running container'
        row = matches[0]
        if row.get('Image') != f'rosy-site-{service}:{commit}':
            return f"{service} runs {row.get('Image')!r}"
        if row.get('State') != 'running' or row.get('Health') != 'healthy':
            return f"{service} is {row.get('State')}/{row.get('Health') or 'no health'}"
        if not row.get('ID'):
            return f'{service} container ID is missing'
        try:
            identity = run(['docker', 'container', 'inspect', '--format', '{{.Image}}', row['ID']]).stdout.strip()
        except Transient as error:
            return str(error)
        if identity not in accepted.get(service, ()):
            return f'{service} running image identity differs from signed candidate'
    return ''


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def read_env(path: Path) -> dict[str, str]:
    values = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        value = value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in "'\"":
            value = value[1:-1]
        values[key.strip()] = value
    return values


def write_env_tag(path: Path, commit: str) -> None:
    """Replace the ROSY_SITE_IMAGE_TAG line atomically, keeping mode and owner."""
    lines = path.read_text(encoding="utf-8").splitlines(keepends=True)
    out, found = [], False
    for line in lines:
        if line.strip().startswith("ROSY_SITE_IMAGE_TAG="):
            out.append(f"ROSY_SITE_IMAGE_TAG={commit}\n")
            found = True
        else:
            out.append(line)
    if not found:
        raise Refused("site.env has no ROSY_SITE_IMAGE_TAG line")
    temporary = path.with_name(path.name + ".autoupdate-new")
    with temporary.open("w", encoding="utf-8", newline="\n") as stream:
        stream.writelines(out)
        stream.flush()
        os.fsync(stream.fileno())
    info = path.stat()
    os.chmod(temporary, info.st_mode & 0o7777)
    if hasattr(os, "chown"):
        with contextlib.suppress(PermissionError):
            os.chown(temporary, info.st_uid, info.st_gid)
    os.replace(temporary, path)


def swap_link(link: Path, target: Path) -> None:
    """Point ``link`` at ``target`` with one rename (never a missing link)."""
    temporary = link.with_name(link.name + ".autoupdate-new")
    with contextlib.suppress(FileNotFoundError):
        temporary.unlink()
    os.symlink(target, temporary, target_is_directory=True)
    os.replace(temporary, link)


def safe_extract(archive: Path, destination: Path, commit: str) -> None:
    """Same member rules as fetch_candidate.sh (D-437): only regular files and
    directories under <commit>/, then tarfile's ``data`` filter."""
    if sys.version_info < (3, 12):
        raise Rejected("python3 >= 3.12 is required (tarfile data extraction filter)")
    try:
        with tarfile.open(archive, "r:") as bundle:
            members = bundle.getmembers()
            for member in members:
                name = member.name
                if not (member.isfile() or member.isdir()):
                    raise Rejected(f"refusing non-regular archive member: {name}")
                if (name.startswith("/") or ".." in name.split("/")
                        or not (name == commit or name.startswith(commit + "/"))):
                    raise Rejected(f"unexpected archive member: {name}")
            bundle.extractall(destination, members=members, filter="data")
    except tarfile.TarError as error:
        raise Rejected(f"candidate archive is unreadable: {error}") from None


@contextlib.contextmanager
def run_lock(path: Path) -> Iterator[None]:
    path.parent.mkdir(parents=True, exist_ok=True)
    stream = path.open("a+b")
    try:
        try:
            if os.name == "nt":
                import msvcrt
                stream.seek(0)
                msvcrt.locking(stream.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl
                fcntl.flock(stream.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError:
            raise BlockingIOError("another rosy-site-autoupdate run holds the lock") from None
        yield
    finally:
        stream.close()
