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
    from .verify_candidate import ALL_IMAGE_SERVICES, CandidateVerificationError, verify_candidate
    from .site_update_io import (
        COMPANIONS, ConfigError, EXIT_CONFIG, EXIT_FAILED, EXIT_LOCKED, EXIT_OK, Http, Paths,
        PROJECT, Refused, Rejected, Runner, SERVICES, SIGNATURE, STACK_UNIT, Transient,
        _COMMIT, _LIST_LIMIT, _MAX_PAGES, _PART, _SMALL_LIMIT, _now,
        check_overrides, forget_failed, functional_inventory, functional_reason, load_config, load_update_state, log, read_env,
        hold_expired, hold_until, run_lock, safe_extract, set_hold, swap_link, write_env_tag,
    )
    from .site_update_runtime import SiteRuntimeIO, check_idle_cli, containers_reason, runtime_reason, site_busy_reasons
else:  # pragma: no cover - installed host CLI
    if str(SCRIPT_DIR) not in sys.path:
        sys.path.insert(0, str(SCRIPT_DIR))
    from verify_candidate import ALL_IMAGE_SERVICES, CandidateVerificationError, verify_candidate
    from site_update_io import (
        COMPANIONS, ConfigError, EXIT_CONFIG, EXIT_FAILED, EXIT_LOCKED, EXIT_OK, Http, Paths,
        PROJECT, Refused, Rejected, Runner, SERVICES, SIGNATURE, STACK_UNIT, Transient,
        _COMMIT, _LIST_LIMIT, _MAX_PAGES, _PART, _SMALL_LIMIT, _now,
        check_overrides, forget_failed, functional_inventory, functional_reason, load_config, load_update_state, log, read_env,
        hold_expired, hold_until, run_lock, safe_extract, set_hold, swap_link, write_env_tag,
    )
    from site_update_runtime import SiteRuntimeIO, check_idle_cli, containers_reason, runtime_reason, site_busy_reasons

_PRUNE_IMAGE_REF = re.compile(rf"^rosy-site-(?:{'|'.join(ALL_IMAGE_SERVICES)}):([0-9a-f]{{40}})$")


class SiteUpdater(SiteRuntimeIO):
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
        self._runtime_proofs = {}
        self._image_references = {}
        self._incremental_commits = set()
        self._functional_baseline = None

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
    def check_overrides(self, env: dict[str, str], commit: str, *, folder: Path | None = None,
                        env_file: Path | None = None, services=SERVICES) -> None:
        def compose(env, *args, **kwargs):
            return self._compose(env, *args, folder=folder, env_file=env_file, **kwargs)
        check_overrides(env, commit, self._run, compose, services, self._image_references.get(commit))

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


    # switch + health
    def switch(self, env: dict[str, str], previous: Path, target: Path, commit: str,
               current: str) -> tuple[bool, str]:
        shutil.copy2(self.paths.site_env, self.paths.env_backup)
        with self.paths.env_backup.open('rb') as stream:
            os.fsync(stream.fileno())
        state = self._state
        state['switch'] = {'previous': str(previous.resolve()), 'current': current,
                           'commit': commit, 'tag': f'site-{commit[:12]}',
                           'functional_baseline': self._functional_baseline}
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
        if transaction.get('migration') and (
                read_env(self.paths.site_env).get('ROSY_SITE_IMAGE_TAG') != transaction['current']
                or (self.paths.link.is_symlink() and self.paths.link.resolve() != previous.resolve())
                or (self.paths.link.exists() and not self.paths.link.is_symlink() and previous.exists())):
            raise Refused('physical relocation journal differs from the original current path')
        verification_path = previous if previous.exists() else self.paths.link
        self._verify(verification_path, loaded=True, expected_commit=transaction['current'],
                     env=read_env(self.paths.env_backup))
        backup_env = read_env(self.paths.env_backup)
        self.check_overrides(backup_env, transaction['current'], folder=verification_path,
                             env_file=self.paths.env_backup,
                             services=self._runtime_proofs[transaction['current']])
        if not transaction.get('migration'):
            outgoing = self.paths.candidates / transaction['commit']
            if outgoing.is_symlink() or not outgoing.is_dir():
                raise Rejected('outgoing canonical candidate is unavailable')
            self._verify(outgoing, loaded=True, expected_commit=transaction['commit'], env=backup_env)
            self._retire_postgres(backup_env, outgoing, transaction['commit'],
                                  self._runtime_proofs[transaction['current']])
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
        self._functional_baseline = transaction.get('functional_baseline')
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
        listed = self._run(['docker', 'image', 'ls', '--format', '{{.Repository}}:{{.Tag}}']).stdout or ''
        used = set((self._run(['docker', 'ps', '--all', '--no-trunc', '--format', '{{.Image}}']).stdout or '').split())
        folders = sorted(
            (p for p in self.paths.candidates.iterdir()
             if p.is_dir() and not p.is_symlink() and not p.name.startswith(".")),
            key=lambda p: p.stat().st_mtime, reverse=True)
        kept = set(keep_dirs) | set(folders[: self.config["keep"]])
        kept_commits, kept_references = {folder.name for folder in kept}, set()
        # Validate every retained rollback manifest before deleting any folder or image.
        for folder in kept:
            try:
                manifest = json.loads((folder / 'release.json').read_text(encoding='utf-8'))
                commit, images = manifest['source_commit'], manifest.get('images', {})
            except (OSError, ValueError, KeyError, TypeError, AttributeError):
                return
            if not isinstance(commit, str) or not _COMMIT.fullmatch(commit) or not isinstance(images, dict):
                return
            kept_commits.add(commit)
            for service, row in images.items():
                ref = row.get('reference') if isinstance(row, dict) else None
                if (service not in ALL_IMAGE_SERVICES or not isinstance(ref, str)
                        or not re.fullmatch(rf'rosy-site-{service}:[0-9a-f]{{40}}', ref)):
                    return
                kept_references.add(ref)
        for folder in folders:
            if folder not in kept:
                shutil.rmtree(folder, ignore_errors=True)
                log("pruned-candidate", folder=folder.name)
        for reference in listed.split():
            match = _PRUNE_IMAGE_REF.fullmatch(reference)
            if (match and match.group(1) not in kept_commits
                    and reference not in kept_references and reference not in used):
                rm_res = self._run(["docker", "image", "rm", reference], check=False)
                if rm_res.returncode == 0:
                    log("pruned-image", image=reference)
                else:
                    log("prune-image-failed", image=reference, returncode=rm_res.returncode)

    # main flow
    def _until_contains_ready(self, state: dict) -> bool:
        """True only when the next installable signed candidate provably contains every
        waiting sha (``compare <sha>...<tag>`` ahead or identical, with that sha as the merge base —
        the same evidence ``is_newer`` already reads). Anything unreadable or unprovable
        keeps the hold: fail closed."""
        try:
            current = read_env(self.paths.site_env).get("ROSY_SITE_IMAGE_TAG", "")
            if not _COMMIT.fullmatch(current):
                return False
            release = self.select(self.list_releases(), current, state)
            return release is not None and all(self.is_newer(sha, release["tag_name"], or_same=True)
                                               for sha in state["hold"]["until_contains"])
        except Exception:
            return False

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
                hold = state['hold']
                # The one hold that lifts itself: --until-contains clears only on proven
                # ancestry of the next candidate; a dry run must not consume it.
                if (not self.dry_run and hold.get('until_contains')
                        and self._until_contains_ready(state)):
                    log('hold-cleared', reason=hold['reason'],
                        until_contains=hold['until_contains'])
                    state.pop('hold', None)
                else:
                    fields = {'reason': hold['reason'], 'until': hold.get('until')}
                    if hold.get('until_contains'):
                        fields['until_contains'] = hold['until_contains']
                    log('held-expired' if hold_expired(hold) else 'held', **fields)
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
            self._verify(self.paths.link, loaded=True, expected_commit=current,
                         env=env)
            self.check_overrides(env, current, services=self._runtime_proofs[current])
            reason = self._containers_reason(env, current)
            if not reason:
                self._functional_baseline, missing = functional_inventory(self.config, self.http)
                drift = {path: ids for path, ids in missing.items() if ids}
                if drift:
                    state['last_run']['inventory_drift'] = drift
                    log('inventory-drift', missing=drift)
            if reason:
                raise Rejected(reason)
            installed = state.get('installed')
            if not self.dry_run and (not isinstance(installed, dict) or installed.get('commit') != current):
                state['installed'] = {'commit': current, 'tag': f'site-{current[:12]}',
                                      'origin': 'manual', 'time': _now()}
                state.pop('previous', None)  # never invent rollback history for a manual switch
                log('adopted-current', commit=current)
            release = self.select(self.list_releases(), current, state)
        except Refused as error:
            log('refused', reason=str(error))
            state['last_run'].update(result='refused', reason=str(error)[:200])
            return EXIT_FAILED
        except Rejected as error:
            log('refused', reason=f'running candidate verification failed: {error}')
            state['last_run'].update(result='refused', reason=f'running candidate verification failed: {error}'[:200])
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
            if self.dry_run:
                log("would-install", tag=tag, commit=commit, current=current)
                state["last_run"]["result"] = "dry-run"
                return EXIT_OK
            if self._defer_if_busy(state, tag):
                return EXIT_OK
            log("staging", tag=tag, commit=commit)
            target = self.stage(release, commit, sums)
            proof = self._verify(target, loaded=False, env=env)
            self.check_overrides(env, commit, folder=target, services=proof['verified_images'])
            if proof.get('archive_services', proof['verified_images']):
                load = self._run(["docker", "image", "load", "--input", str(target / "images.tar")],
                                 timeout=1800, check=False)
                if load.returncode != 0:
                    raise Rejected("docker image load failed")
            self._verify(target, loaded=True,
                         env=env)
            if self._defer_if_busy(state, tag):
                return EXIT_OK
            previous = self._prior_target()
            ok, reason = self.switch(env, previous, target, commit, current)
        except Refused as error:
            log("refused", tag=tag, reason=str(error))
            state["last_run"].update(result="refused", reason=str(error)[:200])
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
    hold.add_argument('--hours', type=float, default=24, help='hold length, 24 by default, at most 168')
    hold.add_argument('--until-contains', nargs='+', metavar='SHA',
                      help='also resume automatically once the newest signed candidate '
                           'contains every listed commit')
    commands.add_parser('resume', help='allow updates after local maintenance')
    commands.add_parser('check-idle', help='exit 0 only when Fleet and local cell work are idle')
    args = parser.parse_args(argv)
    paths = Paths()
    if args.command == "status":
        text = paths.state.read_text(encoding="utf-8") if paths.state.exists() else "{}"
        try:  # annotate for update_status.py; an unparsable file is printed as it is
            doc = json.loads(text)
            if isinstance(doc.get('hold'), dict):
                doc['hold'].update(expired=hold_expired(doc['hold']), until=hold_until(doc['hold']).isoformat())
                text = json.dumps(doc, indent=2, sort_keys=True)
        except (ValueError, AttributeError, TypeError):
            pass
        print(text)
        return EXIT_OK
    try:
        config = load_config(paths.config)
    except ConfigError as error:
        log("config-error", reason=str(error))
        return EXIT_CONFIG
    updater = SiteUpdater(config, paths=paths, dry_run=getattr(args, "dry_run", False))
    if args.command == "check-idle":
        return check_idle_cli(updater)
    if args.command == "forget-failed":
        return forget_failed(updater, args.tag)
    if args.command in {'hold', 'resume'}:
        if args.command == 'resume':
            return set_hold(updater, None)
        return set_hold(updater, args.reason, args.hours, args.until_contains)
    return updater.run()


if __name__ == "__main__":
    sys.exit(main())
