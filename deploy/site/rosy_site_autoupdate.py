#!/usr/bin/env python3
"""Install signed site candidates whose commits strictly descend from the running one.

The reviewed updater, I/O ports and verifier are installed together outside
candidate folders. Switching exceptions roll back; a durable switch journal
is recovered before selecting another candidate. See deploy/site/README.md.
"""

from __future__ import annotations
import argparse
import datetime as _dt
import json
import os
from pathlib import Path
import re
import shlex
import shutil
import subprocess
import sys
import time
from typing import Callable

# Import only the reviewed modules installed beside this script, never candidate code.
SCRIPT_DIR = Path(__file__).resolve().parent
if __package__:
    from .verify_candidate import CandidateVerificationError, verify_candidate
    from .site_update_io import (
        ConfigError, EXIT_CONFIG, EXIT_FAILED, EXIT_LOCKED, EXIT_OK, Http, Paths,
        PROJECT, Refused, Rejected, Runner, SERVICES, SIGNATURE, STACK_UNIT, Transient,
        _COMMIT, _LIST_LIMIT, _MAX_PAGES, _PART, _SMALL_LIMIT, _TAG, _now,
        containers_reason, forget_failed, functional_reason, load_config, load_update_state, log, read_env,
        run_lock, runtime_reason, safe_extract, set_hold, swap_link, write_env_tag,
    )
else:  # pragma: no cover - installed host CLI
    if str(SCRIPT_DIR) not in sys.path:
        sys.path.insert(0, str(SCRIPT_DIR))
    from verify_candidate import CandidateVerificationError, verify_candidate
    from site_update_io import (
        ConfigError, EXIT_CONFIG, EXIT_FAILED, EXIT_LOCKED, EXIT_OK, Http, Paths,
        PROJECT, Refused, Rejected, Runner, SERVICES, SIGNATURE, STACK_UNIT, Transient,
        _COMMIT, _LIST_LIMIT, _MAX_PAGES, _PART, _SMALL_LIMIT, _TAG, _now,
        containers_reason, forget_failed, functional_reason, load_config, load_update_state, log, read_env,
        run_lock, runtime_reason, safe_extract, set_hold, swap_link, write_env_tag,
    )


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
        self._accepted_images = {}

    # state
    def load_state(self) -> dict:
        return load_update_state(self.paths)

    def save_state(self, state: dict) -> None:
        self.paths.state.parent.mkdir(parents=True, exist_ok=True)
        temporary = self.paths.state.with_name(self.paths.state.name + ".new")
        with temporary.open('w', encoding='utf-8') as stream:
            stream.write(json.dumps(state, indent=2, sort_keys=True) + "\n")
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, self.paths.state)
        if os.name != 'nt':
            descriptor = os.open(self.paths.state.parent, os.O_RDONLY)
            try:
                os.fsync(descriptor)
            finally:
                os.close(descriptor)

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
        for row in site:
            if row['tag_name'] == f'site-{current[:12]}':
                continue
            names = {asset.get("name") for asset in row.get("assets") or []
                     if isinstance(asset, dict)}
            if not {"release.json", SIGNATURE, "SHA256SUMS"} <= names:
                continue  # not signed yet
            if row["tag_name"] in state["failed"]:
                continue
            if not self.is_newer(current, row['tag_name']):
                continue
            return row
        return None

    def is_newer(self, current: str, candidate: str) -> bool:
        # Later pages omit changed files but retain ancestry metadata.
        url = f"https://api.github.com/repos/{self.config['repo']}/compare/{current}...{candidate}?per_page=1&page=2"
        try:
            comparison = json.loads(self.http.get(url, _LIST_LIMIT))
            return (comparison['status'] == 'ahead'
                    and comparison['merge_base_commit']['sha'] == current)
        except (json.JSONDecodeError, KeyError, TypeError):
            raise Transient('commit comparison is malformed') from None

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
            return link.resolve(strict=True)
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
        # Migration also renames the active path: journal it before the first rename.
        shutil.copy2(self.paths.site_env, self.paths.env_backup)
        with self.paths.env_backup.open('rb') as stream:
            os.fsync(stream.fileno())
        current = read_env(self.paths.site_env)['ROSY_SITE_IMAGE_TAG']
        self._state['switch'] = {'previous': str(destination.resolve()), 'current': current,
                                 'commit': current, 'tag': f'site-{current[:12]}', 'migration': True}
        self.save_state(self._state)
        try:
            os.rename(link, destination)
            swap_link(link, destination)
            log("migrated", from_dir=str(link), to_dir=str(destination))
        except BaseException:
            self.rollback(self._state)
            raise
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
                if self.paths.link.is_symlink() and self.paths.link.resolve() == target.resolve():
                    raise Rejected("refusing to replace the running candidate folder")
                shutil.rmtree(target)
            os.replace(folder, target)
            return target
        finally:
            shutil.rmtree(staging, ignore_errors=True)

    def _verify(self, folder: Path, *, loaded: bool, expected_commit: str | None = None) -> dict:
        try:
            manifest = self.verifier(folder, trusted_key_id=self.config["key_id"],
                                     trusted_public_key=self.config["public_key"],
                                     runner=self.runner, inspect_loaded_images=loaded)
            if manifest.get('source_commit') != (expected_commit or folder.name):
                raise Rejected('signed manifest commit differs from candidate commit')
            if loaded:
                self._accepted_images[manifest['source_commit']] = manifest.get('accepted_image_ids', {})
            return manifest
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
                if reason == '':
                    reason = functional_reason(self.config, self.http)
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
        reason = containers_reason(rows, commit, self._accepted_images.get(commit, {}), self._run)
        if reason:
            return reason
        try:
            output = self._compose(env, 'config', '--hash', '*', tag=commit).stdout
            hashes = dict(line.split() for line in output.splitlines() if line.strip())
            return runtime_reason(rows, hashes, self._run)
        except Transient as error:
            return str(error)
        except ValueError:
            return 'Compose configuration hashes cannot be verified'

    def _restart(self) -> None:
        self._run(["systemctl", "restart", STACK_UNIT], timeout=300)

    def switch(self, env: dict[str, str], previous: Path, target: Path, commit: str,
               current: str) -> tuple[bool, str]:
        shutil.copy2(self.paths.site_env, self.paths.env_backup)
        with self.paths.env_backup.open('rb') as stream:
            os.fsync(stream.fileno())
        state = self._state
        state['switch'] = {'previous': str(previous.resolve()), 'current': current,
                           'commit': commit, 'tag': f'site-{commit[:12]}'}
        self.save_state(state)
        try:
            write_env_tag(self.paths.site_env, commit)
            swap_link(self.paths.link, target)
            log("switched", commit=commit, previous=current)
            self._restart()
            ok, reason = self.healthy(env, commit)
            if ok:
                return True, reason  # journal cleared with installed state, before pruning
        except BaseException:
            self.rollback(state)
            raise
        log("health-failed", commit=commit, reason=reason)
        self.rollback(state)
        return False, f'{reason}; rollback healthy'

    def rollback(self, state: dict) -> None:
        transaction = state['switch']
        previous = Path(transaction['previous'])
        if (not self.paths.env_backup.is_file()
                or read_env(self.paths.env_backup).get('ROSY_SITE_IMAGE_TAG') != transaction['current']):
            raise Refused('rollback backup does not match journal commit')
        verification_path = previous if previous.exists() else self.paths.link
        self._verify(verification_path, loaded=True, expected_commit=transaction['current'])
        if (transaction.get('migration') and not previous.exists()
                and self.paths.link.is_dir() and not self.paths.link.is_symlink()):
            os.rename(self.paths.link, previous)
        if not previous.is_dir() or not self.paths.env_backup.is_file():
            raise Transient('interrupted switch has no rollback folder or environment backup')
        restored = self.paths.site_env.with_name(self.paths.site_env.name + '.restore')
        shutil.copy2(self.paths.env_backup, restored)
        with restored.open('rb') as stream:
            os.fsync(stream.fileno())
        os.replace(restored, self.paths.site_env)
        swap_link(self.paths.link, previous)
        self._restart()
        ok, reason = self.healthy(read_env(self.paths.site_env), transaction['current'])
        log('rolled-back', commit=transaction['current'], healthy=ok, reason=reason)
        if not ok:
            raise Transient(f'rollback is unhealthy: {reason}')
        state.pop('switch')
        self.save_state(state)

    # pruning
    def prune(self, keep_dirs: set[Path]) -> None:
        if self.load_state().get('switch'):
            raise Transient('pruning forbidden while a switch needs recovery')
        # Both inventories must succeed before any destructive operation.
        listed = self._run(['docker', 'image', 'ls', '--format',
                            '{{.Repository}}:{{.Tag}}']).stdout or ''
        used = set((self._run(['docker', 'ps', '--all', '--format', '{{.Image}}']).stdout or '').split())
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
        for folder in kept:
            try:
                commit = json.loads((folder / 'release.json').read_text(encoding='utf-8'))['source_commit']
            except (OSError, ValueError, KeyError, TypeError):
                # An unidentified rollback directory cannot authorize image deletion.
                return
            if not isinstance(commit, str) or not _COMMIT.fullmatch(commit):
                return
            kept_commits.add(commit)
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
        except Refused as error:
            log('state-refused', reason=str(error))
            return EXIT_FAILED

    def _run_locked(self) -> int:
        state = self.load_state()
        self._state = state
        state["last_run"] = {"time": _now()}
        try:
            if state.get('switch'):
                if self.dry_run:
                    state['last_run']['result'] = 'recovery-required'
                    return EXIT_FAILED
                try:
                    self.rollback(state)
                except Exception as error:
                    log('recovery-pending', reason=str(error))
                    state['last_run']['result'] = 'recovery-pending'
                    return EXIT_FAILED
                state['last_run']['result'] = 'recovered'
                return EXIT_FAILED
            if state.get('hold'):
                log('held')
                state['last_run']['result'] = 'held'
                return EXIT_OK
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
            self._verify(self.paths.link, loaded=True, expected_commit=current)
            reason = self._containers_reason(env, current)
            if not reason:
                reason = functional_reason(self.config, self.http)
            if reason:
                raise Rejected(reason)
            installed = state.get('installed')
            if not self.dry_run and (not isinstance(installed, dict) or installed.get('commit') != current):
                state['installed'] = {'commit': current, 'tag': f'site-{current[:12]}',
                                      'origin': 'manual', 'time': _now()}
                state.pop('previous', None)  # never invent rollback history for a manual switch
                log('adopted-current', commit=current)
            release = self.select(self.list_releases(), current, state)
        except Rejected as error:
            log('refused', reason=f'running candidate verification failed: {error}')
            state['last_run']['result'] = 'refused'
            return EXIT_FAILED
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
            if not self.is_newer(current, commit):
                raise Rejected('candidate commit is not a strict descendant of the running commit')
            self.check_overrides(env, commit)
            if self.dry_run:
                log("would-install", tag=tag, commit=commit, current=current)
                state["last_run"]["result"] = "dry-run"
                return EXIT_OK
            log("staging", tag=tag, commit=commit)
            target = self.stage(release, commit, sums)
            self._verify(target, loaded=False)
            load = self._run(["docker", "image", "load", "--input", str(target / "images.tar")],
                             timeout=1800, check=False)
            if load.returncode != 0:
                raise Rejected("docker image load failed")
            self._verify(target, loaded=True)
            previous = self._prior_target()
            ok, reason = self.switch(env, previous, target, commit, current)
        except Refused as error:
            log("refused", tag=tag, reason=str(error))
            state["last_run"]["result"] = "refused"
            return EXIT_FAILED
        except Transient as error:
            log("error", tag=tag, reason=str(error))
            state["last_run"]["result"] = "error"
            return EXIT_FAILED
        except Rejected as error:
            state["failed"][tag] = {"time": _now(), "reason": str(error)}
            log("rejected", tag=tag, reason=str(error))
            state["last_run"]["result"] = "rejected"
            return EXIT_FAILED
        except Exception as error:
            log('error', tag=tag, reason=str(error))
            state['last_run']['result'] = 'error'
            return EXIT_FAILED
        if not ok:
            state["failed"][tag] = {"time": _now(), "reason": reason}
            state["last_run"]["result"] = "rolled-back"
            return EXIT_FAILED
        state["previous"] = state.get("installed")
        state["installed"] = {"tag": tag, "commit": commit, "time": _now(),
                              "created_at": release.get("created_at")}
        state["last_run"]["result"] = "installed"
        state.pop('switch', None)
        self.save_state(state)
        log("installed", tag=tag, commit=commit, previous=current)
        try:
            self.prune({target, previous})
        except (Transient, OSError) as error:
            log('prune-deferred', reason=str(error))
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
    hold = commands.add_parser('hold', help='pause new updates during local maintenance')
    hold.add_argument('reason')
    commands.add_parser('resume', help='allow updates after local maintenance')
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
        return forget_failed(updater, args.tag)
    if args.command in {'hold', 'resume'}:
        return set_hold(updater, args.reason if args.command == 'hold' else None)
    return updater.run()


if __name__ == "__main__":
    sys.exit(main())
