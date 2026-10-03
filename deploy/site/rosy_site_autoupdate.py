#!/usr/bin/env python3
"""Site host automatic updater for signed site candidates (D-441).

Runs from rosy-site-autoupdate.timer as root. It is installed by the operator
into /usr/local/lib/rosy-site next to the reviewed verify_candidate.py and
candidate_signing.py and never runs code from the candidate it is about to
verify (D-301 3). One ``run``:

1. takes a non-blocking lock and reads ROSY_SITE_IMAGE_TAG from site.env;
2. lists the public releases (HTTPS, no token, paginated) and picks the newest
   ``site-<12 hex>`` release created after the installed one that carries
   ``release.json.sig`` and has not failed here before;
3. refuses, without changing anything, when the stack unit or site.env adds a
   Compose file beyond the candidate's ``compose.yaml``/``compose.pairing.yaml``
   or when ``docker compose config`` with the new tag does not resolve every
   site service to ``rosy-site-<service>:<commit>`` (an override pinning an
   image would otherwise keep the old code running "healthy");
4. downloads the assets, checks SHA256SUMS, joins the parts, checks every tar
   member, extracts into /opt/rosy/candidates/<commit>, and adds the signature;
5. verifies signature and file hashes with the installed verifier and the
   trusted key from /etc/rosy/site/autoupdate.conf, runs ``docker image load``,
   then the full verifier (loaded image IDs);
6. switches: site.env tag written atomically (backup kept), /opt/rosy/candidate
   swapped atomically to the new folder (a real directory there is migrated
   to /opt/rosy/candidates/<its commit> once), rosy-site-stack.service
   restarted;
7. health gate: healthz returns 200 and every site container is running,
   healthy and on the new image within the timeout; otherwise rolls back
   (previous link, site.env backup, restart) and records the tag as failed
   (never retried automatically);
8. keeps the newest ``keep`` candidate folders and removes older rosy-site
   images that no container uses.

Every decision is one JSON line on stdout (the journal) and the state is in
/var/lib/rosy/site-autoupdate.json.

    rosy_site_autoupdate.py run [--dry-run]
    rosy_site_autoupdate.py status
    rosy_site_autoupdate.py forget-failed <site-tag>

Standard library only.
"""

from __future__ import annotations

import argparse
import contextlib
import datetime as _dt
import hashlib
import json
import os
from pathlib import Path
import re
import shlex
import shutil
import ssl
import subprocess
import sys
import tarfile
import time
import urllib.error
import urllib.request
from typing import Callable, Iterator

# The unit runs python3 -I: the reviewed verifier sits beside this file.
SCRIPT_DIR = Path(__file__).resolve().parent
if __package__:
    from .verify_candidate import CandidateVerificationError, verify_candidate
else:  # pragma: no cover - the installed host CLI
    if str(SCRIPT_DIR) not in sys.path:
        sys.path.insert(0, str(SCRIPT_DIR))
    from verify_candidate import CandidateVerificationError, verify_candidate

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
        with self._open(url) as response:
            data = response.read(limit + 1)
        if len(data) > limit:
            raise Transient(f"GET {url} exceeded {limit} bytes")
        return data

    def download(self, url: str, destination: Path) -> str:
        digest = hashlib.sha256()
        try:
            with self._open(url) as response, destination.open("wb") as stream:
                for chunk in iter(lambda: response.read(1024 * 1024), b""):
                    digest.update(chunk)
                    stream.write(chunk)
        except OSError as error:
            raise Transient(f"download {url} failed: {error}") from None
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


# -- updater ---------------------------------------------------------------------

class SiteUpdater:
    def __init__(self, config: dict, *, paths: Paths | None = None,
                 runner: Runner = subprocess.run, http: Http | None = None,
                 verifier: Callable[..., dict] = verify_candidate,
                 sleep: Callable[[float], None] = time.sleep,
                 clock: Callable[[], float] = time.monotonic, dry_run: bool = False):
        self.config = config
        self.paths = paths or Paths()
        self.runner = runner
        self.http = http or Http()
        self.verifier = verifier
        self.sleep = sleep
        self.clock = clock
        self.dry_run = dry_run

    # state
    def load_state(self) -> dict:
        try:
            state = json.loads(self.paths.state.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            state = {}
        if not isinstance(state, dict):
            state = {}
        if not isinstance(state.get("failed"), dict):
            state["failed"] = {}
        return state

    def save_state(self, state: dict) -> None:
        self.paths.state.parent.mkdir(parents=True, exist_ok=True)
        temporary = self.paths.state.with_name(self.paths.state.name + ".new")
        temporary.write_text(json.dumps(state, indent=2, sort_keys=True) + "\n",
                             encoding="utf-8")
        os.replace(temporary, self.paths.state)

    # commands
    def _run(self, args: list[str], *, timeout: int = 120, env: dict | None = None,
             check: bool = True) -> subprocess.CompletedProcess:
        try:
            result = self.runner(args, capture_output=True, text=True, check=False,
                                 timeout=timeout, env=env)
        except (OSError, subprocess.SubprocessError) as error:
            raise Transient(f"{args[0]} {args[1] if len(args) > 1 else ''} could not run: "
                            f"{type(error).__name__}") from None
        if check and result.returncode != 0:
            tail = (result.stderr or "").strip().splitlines()[-1:] or [""]
            raise Transient(f"{' '.join(args[:3])} failed: {tail[0][:200]}")
        return result

    def _compose_files(self, env: dict[str, str]) -> list[str]:
        pairing = shlex.split(env.get("ROSY_SITE_PAIRING_COMPOSE", ""))
        return ["-f", str(self.paths.link / "deploy/site/compose.yaml"), *pairing]

    def _compose(self, env: dict[str, str], *args: str, tag: str | None = None,
                 timeout: int = 120, check: bool = True) -> subprocess.CompletedProcess:
        process_env = None
        if tag is not None:
            # The shell environment beats --env-file in Compose.
            process_env = {**os.environ, "ROSY_SITE_IMAGE_TAG": tag}
        return self._run(["docker", "compose", "--project-name", PROJECT, "--env-file",
                          str(self.paths.site_env), *self._compose_files(env), *args],
                         timeout=timeout, env=process_env, check=check)

    # selection
    def list_releases(self) -> list[dict]:
        releases = []
        for page in range(1, _MAX_PAGES + 1):
            url = (f"https://api.github.com/repos/{self.config['repo']}/releases"
                   f"?per_page=100&page={page}")
            try:
                rows = json.loads(self.http.get(url, _LIST_LIMIT))
            except json.JSONDecodeError:
                raise Transient("release list is not JSON") from None
            if not isinstance(rows, list):
                raise Transient("release list is malformed")
            releases.extend(row for row in rows if isinstance(row, dict))
            if len(rows) < 100:
                break
        return releases

    def select(self, releases: list[dict], current: str, state: dict) -> dict | None:
        site = [row for row in releases
                if isinstance(row.get("tag_name"), str) and _TAG.fullmatch(row["tag_name"])
                and not row.get("draft")]
        site.sort(key=lambda row: str(row.get("created_at") or ""), reverse=True)
        floor = str((state.get("installed") or {}).get("created_at") or "")
        for row in site:
            if row["tag_name"] == f"site-{current[:12]}":
                floor = max(floor, str(row.get("created_at") or ""))
        for row in site:
            if floor and str(row.get("created_at") or "") <= floor:
                break  # never install an older candidate than the running one
            names = {asset.get("name") for asset in row.get("assets") or []
                     if isinstance(asset, dict)}
            if not {"release.json", SIGNATURE, "SHA256SUMS"} <= names:
                continue  # not signed yet
            if row["tag_name"] in state["failed"]:
                continue
            return row
        return None

    def _asset_url(self, release: dict, name: str) -> str:
        tag = release["tag_name"]
        expected = f"https://github.com/{self.config['repo']}/releases/download/{tag}/{name}"
        for asset in release.get("assets") or []:
            if isinstance(asset, dict) and asset.get("name") == name:
                if asset.get("browser_download_url") != expected:
                    raise Rejected(f"asset {name} has an unexpected download URL")
                return expected
        raise Rejected(f"release {tag} has no asset {name}")

    # host checks
    def check_overrides(self, env: dict[str, str], commit: str) -> None:
        """Refuse when anything could pin a site image other than the candidate's."""
        link_compose = "/opt/rosy/candidate/deploy/site/compose.yaml"
        allowed_pairing = ([], ["-f", "/opt/rosy/candidate/deploy/site/compose.pairing.yaml"])
        if shlex.split(env.get("ROSY_SITE_PAIRING_COMPOSE", "")) not in allowed_pairing:
            raise Refused("ROSY_SITE_PAIRING_COMPOSE adds a Compose file other than "
                          "the candidate's compose.pairing.yaml")
        if env.get("COMPOSE_FILE") or env.get("COMPOSE_PROFILES"):
            raise Refused("site.env sets COMPOSE_FILE/COMPOSE_PROFILES")
        unit = self._run(["systemctl", "cat", STACK_UNIT]).stdout
        for line in unit.splitlines():
            line = line.strip()
            if line.startswith("Environment") and "COMPOSE_FILE" in line:
                raise Refused(f"{STACK_UNIT} sets COMPOSE_FILE")
            if not line.startswith(("ExecStart=", "ExecStartPre=", "ExecStop=",
                                    "ExecReload=")):
                continue
            words = shlex.split(line.partition("=")[2])
            if "compose" not in words:
                continue
            for index, word in enumerate(words):
                if word in {"-f", "--file"}:
                    value = words[index + 1] if index + 1 < len(words) else ""
                    if value != link_compose:
                        raise Refused(f"{STACK_UNIT} adds Compose file {value}")
                elif word.startswith(("--file=", "-f=")):
                    raise Refused(f"{STACK_UNIT} adds Compose file {word}")
        result = self._compose(env, "config", "--format", "json", tag=commit)
        try:
            services = json.loads(result.stdout).get("services") or {}
        except (json.JSONDecodeError, AttributeError):
            raise Transient("docker compose config output is not JSON") from None
        for service in SERVICES:
            image = (services.get(service) or {}).get("image")
            if image != f"rosy-site-{service}:{commit}":
                raise Refused(f"Compose resolves {service} to {image!r}, not the candidate "
                              f"image; remove the image override first")

    def _prior_target(self) -> Path:
        """Return the installed candidate folder, migrating a real directory once."""
        link = self.paths.link
        if link.is_symlink():
            return Path(os.readlink(link))
        if not link.is_dir():
            raise Refused(f"{link} does not exist; install the first candidate by hand")
        try:
            commit = json.loads((link / "release.json").read_text(encoding="utf-8")).get(
                "source_commit")
        except (OSError, json.JSONDecodeError, AttributeError):
            commit = None
        self.paths.candidates.mkdir(parents=True, exist_ok=True)
        name = commit if isinstance(commit, str) and _COMMIT.fullmatch(commit) else None
        destination = self.paths.candidates / (name or "")
        if name is None or destination.exists():
            stamp = _dt.datetime.now(_dt.timezone.utc).strftime("%Y%m%dT%H%M%SZ")
            destination = self.paths.candidates / f"prev-{stamp}"
        os.rename(link, destination)
        swap_link(link, destination)
        log("migrated", from_dir=str(link), to_dir=str(destination))
        return destination

    # download + verify
    def stage(self, release: dict, commit: str, sums: bytes) -> Path:
        tag = release["tag_name"]
        self.paths.candidates.mkdir(parents=True, exist_ok=True)
        staging = self.paths.candidates / f".staging-{tag}"
        if staging.exists():
            shutil.rmtree(staging)
        download = staging / "download"
        extract = staging / "extract"
        download.mkdir(parents=True)
        extract.mkdir()
        try:
            expected: dict[str, str] = {}
            parts: list[str] = []
            for line in sums.decode("ascii").splitlines():
                digest, _, name = line.partition("  ")
                if not re.fullmatch(r"[0-9a-f]{64}", digest) or name in expected:
                    raise Rejected("bad SHA256SUMS line")
                match = _PART.fullmatch(name)
                if name != "release.json" and not (match and match.group(1) == commit):
                    raise Rejected(f"unexpected asset in SHA256SUMS: {name}")
                expected[name] = digest
                if match:
                    parts.append(name)
            parts.sort()
            if "release.json" not in expected or not parts or [
                    _PART.fullmatch(name).group(2) for name in parts] != [
                    f"{index:02d}" for index in range(len(parts))]:
                raise Rejected("SHA256SUMS does not list release.json and parts 00..NN")
            for name in ("release.json", SIGNATURE, *parts):
                actual = self.http.download(self._asset_url(release, name), download / name)
                if name in expected and actual != expected[name]:
                    raise Rejected(f"{name} does not match SHA256SUMS")
            archive = download / f"rosy-site-candidate-{commit}.tar"
            with archive.open("wb") as joined:
                for name in parts:
                    with (download / name).open("rb") as part:
                        shutil.copyfileobj(part, joined, 1024 * 1024)
                    (download / name).unlink()
            safe_extract(archive, extract, commit)
            archive.unlink()
            folder = extract / commit
            if (folder / "release.json").read_bytes() != (download / "release.json").read_bytes():
                raise Rejected("release.json in the archive differs from the release asset")
            if (folder / SIGNATURE).exists():
                raise Rejected("the archive already carries a release.json.sig")
            shutil.copyfile(download / SIGNATURE, folder / SIGNATURE)
            target = self.paths.candidates / commit
            if target.exists():
                if self.paths.link.is_symlink() and Path(os.readlink(self.paths.link)) == target:
                    raise Rejected("refusing to replace the running candidate folder")
                shutil.rmtree(target)
            os.replace(folder, target)
            return target
        finally:
            shutil.rmtree(staging, ignore_errors=True)

    def _verify(self, folder: Path, *, loaded: bool) -> dict:
        try:
            return self.verifier(folder, trusted_key_id=self.config["key_id"],
                                 trusted_public_key=self.config["public_key"],
                                 runner=self.runner, inspect_loaded_images=loaded)
        except (CandidateVerificationError, OSError) as error:
            raise Rejected(f"verification failed: {error}") from None

    # switch + health
    def healthy(self, env: dict[str, str], commit: str) -> tuple[bool, str]:
        deadline = self.clock() + self.config["health_timeout_s"]
        reason = "not checked"
        while True:
            status = self.http.status(self.config["health_url"], self.config["health_ca"])
            reason = f"healthz returned {status}"
            if status == 200:
                reason = self._containers_reason(env, commit)
                if reason == "":
                    return True, "healthy"
            if self.clock() >= deadline:
                return False, reason
            self.sleep(5)

    def _containers_reason(self, env: dict[str, str], commit: str) -> str:
        try:
            out = self._compose(env, "ps", "--all", "--format", "json").stdout.strip()
        except Transient as error:
            return str(error)
        try:
            rows = json.loads(out) if out.startswith("[") else [
                json.loads(line) for line in out.splitlines() if line.strip()]
        except json.JSONDecodeError:
            return "docker compose ps output is not JSON"
        by_service = {row.get("Service"): row for row in rows if isinstance(row, dict)}
        for service in SERVICES:
            row = by_service.get(service)
            if row is None:
                return f"{service} container is missing"
            if row.get("Image") != f"rosy-site-{service}:{commit}":
                return f"{service} runs {row.get('Image')!r}"
            if row.get("State") != "running" or row.get("Health") != "healthy":
                return f"{service} is {row.get('State')}/{row.get('Health') or 'no health'}"
        return ""

    def _restart(self) -> None:
        self._run(["systemctl", "restart", STACK_UNIT], timeout=300, check=False)

    def switch(self, env: dict[str, str], previous: Path, target: Path, commit: str,
               current: str) -> tuple[bool, str]:
        shutil.copy2(self.paths.site_env, self.paths.env_backup)
        write_env_tag(self.paths.site_env, commit)
        swap_link(self.paths.link, target)
        log("switched", commit=commit, previous=current)
        self._restart()
        ok, reason = self.healthy(env, commit)
        if ok:
            return True, reason
        log("health-failed", commit=commit, reason=reason)
        swap_link(self.paths.link, previous)
        os.replace(self.paths.env_backup, self.paths.site_env)
        self._restart()
        back, back_reason = self.healthy(env, current)
        log("rolled-back", commit=current, healthy=back, reason=back_reason)
        return False, f"{reason}; rollback {'healthy' if back else 'UNHEALTHY: ' + back_reason}"

    # pruning
    def prune(self, keep_dirs: set[Path]) -> None:
        folders = sorted(
            (path for path in self.paths.candidates.iterdir()
             if path.is_dir() and not path.is_symlink() and not path.name.startswith(".")),
            key=lambda path: path.stat().st_mtime, reverse=True)
        kept = set(keep_dirs) | set(folders[: self.config["keep"]])
        for folder in folders:
            if folder not in kept:
                shutil.rmtree(folder, ignore_errors=True)
                log("pruned-candidate", folder=folder.name)
        kept_commits = {folder.name for folder in kept}
        listed = self._run(["docker", "image", "ls", "--format",
                            "{{.Repository}}:{{.Tag}}"], check=False).stdout or ""
        used = set((self._run(["docker", "ps", "--all", "--format", "{{.Image}}"],
                              check=False).stdout or "").split())
        for reference in listed.split():
            match = re.fullmatch(r"rosy-site-(?:fleet|vision|proxy):([0-9a-f]{40})", reference)
            if match and match.group(1) not in kept_commits and reference not in used:
                self._run(["docker", "image", "rm", reference], check=False)
                log("pruned-image", image=reference)

    # main flow
    def run(self) -> int:
        try:
            with run_lock(self.paths.lock):
                return self._run_locked()
        except BlockingIOError as error:
            log("locked", reason=str(error))
            return EXIT_LOCKED

    def _run_locked(self) -> int:
        state = self.load_state()
        state["last_run"] = {"time": _now()}
        try:
            return self._update(state)
        finally:
            self.save_state(state)

    def _update(self, state: dict) -> int:
        env = read_env(self.paths.site_env)
        current = env.get("ROSY_SITE_IMAGE_TAG", "")
        if not _COMMIT.fullmatch(current):
            log("refused", reason="ROSY_SITE_IMAGE_TAG is not a 40-hex commit; "
                                  "install the first candidate by hand")
            state["last_run"]["result"] = "refused"
            return EXIT_FAILED
        try:
            release = self.select(self.list_releases(), current, state)
        except Transient as error:
            log("error", reason=str(error))
            state["last_run"]["result"] = "error"
            return EXIT_FAILED
        if release is None:
            log("idle", current=current)
            state["last_run"]["result"] = "idle"
            return EXIT_OK
        tag = release["tag_name"]
        try:
            sums = self.http.get(self._asset_url(release, "SHA256SUMS"), _SMALL_LIMIT)
            commits = {m.group(1) for m in (
                _PART.fullmatch(line.partition("  ")[2])
                for line in sums.decode("ascii", "replace").splitlines()) if m}
            if len(commits) != 1 or not next(iter(commits)).startswith(tag[5:]):
                raise Rejected("SHA256SUMS part names do not match the tag")
            commit = commits.pop()
            self.check_overrides(env, commit)
            if self.dry_run:
                log("would-install", tag=tag, commit=commit, current=current)
                state["last_run"]["result"] = "dry-run"
                return EXIT_OK
            previous = self._prior_target()
            log("staging", tag=tag, commit=commit)
            target = self.stage(release, commit, sums)
            self._verify(target, loaded=False)
            load = self._run(["docker", "image", "load", "--input", str(target / "images.tar")],
                             timeout=1800, check=False)
            if load.returncode != 0:
                raise Rejected("docker image load failed")
            self._verify(target, loaded=True)
            ok, reason = self.switch(env, previous, target, commit, current)
        except Refused as error:
            log("refused", tag=tag, reason=str(error))
            state["last_run"]["result"] = "refused"
            return EXIT_FAILED
        except Transient as error:
            log("error", tag=tag, reason=str(error))
            state["last_run"]["result"] = "error"
            return EXIT_FAILED
        except (Rejected, OSError) as error:
            state["failed"][tag] = {"time": _now(), "reason": str(error)}
            log("rejected", tag=tag, reason=str(error))
            state["last_run"]["result"] = "rejected"
            return EXIT_FAILED
        if not ok:
            state["failed"][tag] = {"time": _now(), "reason": reason}
            state["last_run"]["result"] = "rolled-back"
            return EXIT_FAILED
        state["previous"] = state.get("installed")
        state["installed"] = {"tag": tag, "commit": commit, "time": _now(),
                              "created_at": release.get("created_at")}
        state["last_run"]["result"] = "installed"
        log("installed", tag=tag, commit=commit, previous=current)
        self.prune({target, previous})
        return EXIT_OK


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    commands = parser.add_subparsers(dest="command", required=True)
    run = commands.add_parser("run", help="one update attempt (the timer runs this)")
    run.add_argument("--dry-run", action="store_true",
                     help="select and check overrides only; download and change nothing")
    commands.add_parser("status", help="print the state file")
    forget = commands.add_parser("forget-failed", help="allow a failed tag to be tried again")
    forget.add_argument("tag")
    args = parser.parse_args(argv)
    paths = Paths()
    if args.command == "status":
        print(paths.state.read_text(encoding="utf-8") if paths.state.exists() else "{}")
        return EXIT_OK
    try:
        config = load_config(paths.config)
    except ConfigError as error:
        log("config-error", reason=str(error))
        return EXIT_CONFIG
    updater = SiteUpdater(config, paths=paths, dry_run=getattr(args, "dry_run", False))
    if args.command == "forget-failed":
        state = updater.load_state()
        removed = state["failed"].pop(args.tag, None)
        updater.save_state(state)
        log("forget-failed", tag=args.tag, removed=removed is not None)
        return EXIT_OK
    return updater.run()


if __name__ == "__main__":
    sys.exit(main())
