"""Existing candidate verification and runtime I/O for the site updater.

Installed with the reviewed updater and I/O ports, outside candidate folders.
Switch and rollback ordering remain in SiteUpdater.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
import re
import shlex
import subprocess

if __package__:
    from .site_update_io import (
        ACCOUNT_OVERLAY, COMPANIONS, PROJECT, SERVICES, STACK_UNIT, Rejected,
        Transient, active_services, allowed_overlays, companion_services, functional_inventory, functional_reason,
        log, read_env,
    )
    from .verify_candidate import CandidateVerificationError, verified_services
else:  # pragma: no cover - installed host CLI
    from site_update_io import (
        ACCOUNT_OVERLAY, COMPANIONS, PROJECT, SERVICES, STACK_UNIT, Rejected,
        Transient, active_services, allowed_overlays, companion_services, functional_inventory, functional_reason,
        log, read_env,
    )
    from verify_candidate import CandidateVerificationError, verified_services


def _healthy(service, row):
    # Older signed peer images have no healthcheck.
    return row.get('Health') == 'healthy' or (service == 'control-unit-peer' and not row.get('Health'))


def runtime_reason(rows, hashes: dict, run) -> str:
    """Detect operational drift without logging inspect output or credentials."""
    for service in COMPANIONS:
        if service in hashes:
            matches = [row for row in rows if isinstance(row, dict) and row.get('Service') == service]
            if (len(matches) != 1 or matches[0].get('State') != 'running'
                    or not _healthy(service, matches[0])):
                health = '' if service == 'control-unit-peer' else 'healthy '
                return f'{service} needs exactly one {health}running container'
    for row in rows:
        if not isinstance(row, dict):
            continue
        service = row.get('Service')
        if service not in (*SERVICES, *COMPANIONS):
            continue
        try:
            details = json.loads(run(['docker', 'container', 'inspect', row['ID']]).stdout)[0]
            host = details['HostConfig']
            labels = details['Config'].get('Labels') or {}
            if not hashes.get(service) or labels.get('com.docker.compose.config-hash') != hashes[service]:
                return f'{service} runtime differs from current Compose configuration'
            if host.get('ReadonlyRootfs') is not True or host.get('Privileged') is not False:
                return f'{service} runtime no longer has a read-only unprivileged root'
        except (ValueError, KeyError, IndexError, TypeError, AttributeError):
            return f'{service} runtime configuration cannot be verified'
    return ''


def containers_reason(rows, commit: str, accepted: dict, run, services=SERVICES,
                      image_references: dict | None = None, companions=None) -> str:
    if not isinstance(rows, list):
        return 'docker compose ps output is not a list'
    independent = 'account' in services or 'account' in accepted or 'account' in (image_references or {})
    if independent and (not accepted.get('account') or not (image_references or {}).get('account')):
        return 'account signed image identity proof is incomplete'
    own_monitoring = 'monitoring' in services or 'monitoring' in accepted or 'monitoring' in (image_references or {})
    if own_monitoring and (not accepted.get('monitoring') or not (image_references or {}).get('monitoring')):
        return 'monitoring signed image identity proof is incomplete'
    if any(isinstance(row, dict) and row.get('Service') in SERVICES
           and row['Service'] not in services for row in rows):
        return 'runtime contains a managed service outside the signed candidate'
    present = {row.get('Service') for row in rows
               if isinstance(row, dict) and row.get('Service') in COMPANIONS}
    if companions is None:
        companions = present - {'control-unit-peer'} - ({'account'} if independent else set())
    if present - (set(services) | companions):
        return 'runtime contains an unconfigured companion'
    if ('account' in present and not independent and
            (tuple(services) not in (SERVICES[:3], SERVICES) or set(accepted) != set(services)
             or (image_references is not None and set(image_references) != set(services)))):
        return 'account legacy signed inventory proof is incomplete'
    for service in (*services, *sorted(companions - set(services))):
        owner = service if service in services else COMPANIONS.get(service, service)
        matches = [row for row in rows if isinstance(row, dict) and row.get('Service') == service]
        if len(matches) != 1:
            return f'{service} needs exactly one running container'
        row = matches[0]
        if row.get('Image') != (image_references or {}).get(owner, f'rosy-site-{owner}:{commit}'):
            return f"{service} runs {row.get('Image')!r}"
        if row.get('State') != 'running' or not _healthy(service, row):
            return f"{service} is {row.get('State')}/{row.get('Health') or 'no health'}"
        if not row.get('ID'):
            return f'{service} container ID is missing'
        try:
            identity = run(['docker', 'container', 'inspect', '--format', '{{.Image}}', row['ID']]).stdout.strip()
        except Transient as error:
            return str(error)
        if identity not in accepted.get(owner, ()):
            return f'{service} running image identity differs from signed candidate'
    return ''


class SiteRuntimeIO:
    def _compose_files(self, env: dict[str, str], folder: Path | None = None) -> list[str]:
        pairing = allowed_overlays(env)
        if folder is not None:
            pairing = [str(folder / "deploy/site" / Path(p).name) if p != '-f' else p for p in pairing]
        return ["-f", str((folder or self.paths.link) / "deploy/site/compose.yaml"), *pairing]

    def _compose(self, env: dict[str, str], *args: str, tag: str | None = None,
                 timeout: int = 120, check: bool = True, folder: Path | None = None,
                 env_file: Path | None = None) -> subprocess.CompletedProcess:
        process_env = None
        if tag is not None:
            # The shell environment beats --env-file in Compose.
            process_env = {**os.environ, "ROSY_SITE_IMAGE_TAG": tag}
        return self._run(["docker", "compose", "--project-name", PROJECT, "--env-file",
                          str(env_file or self.paths.site_env), *self._compose_files(env, folder), *args],
                         timeout=timeout, env=process_env, check=check)

    def _verify(self, folder: Path, *, loaded: bool, expected_commit: str | None = None,
                env: dict | None = None) -> dict:
        commit = expected_commit or folder.name
        if loaded:
            self._runtime_proofs.pop(commit, None)
            self._accepted_images.pop(commit, None)
        try:
            manifest = self.verifier(folder, trusted_key_id=self.config["key_id"],
                                     trusted_public_key=self.config["public_key"],
                                     runner=self.runner, inspect_loaded_images=loaded)
            if manifest.get('source_commit') != commit:
                raise Rejected('signed manifest commit differs from candidate commit')
            services = verified_services(manifest.get('verified_images'))
            refs = manifest.get('image_references')
            if 'account' in services and refs is None:
                raise Rejected('independent Account signed image reference proof is missing')
            if refs is not None:
                if (not isinstance(refs, dict) or set(refs) != set(services)
                        or any(not isinstance(refs[s], str)
                               or not re.fullmatch(f'rosy-site-{s}:[0-9a-f]{{40}}', refs[s]) for s in services)):
                    raise Rejected('signed image reference proof is incomplete')
                self._image_references[commit] = refs
            if manifest.get('manifest_version') == 2:
                self._incremental_commits.add(commit)
            overlays = shlex.split((env or {}).get('ROSY_SITE_PAIRING_COMPOSE', ''))
            for name, field in (('account', 'account_https'), ('omx', 'omx'), ('workcell', 'workcell'),
                                ('control-unit', 'control_unit'), ('control-unit-remote', 'control_unit_remote'),
                                ('monitoring', 'monitoring')):
                if f'/opt/rosy/candidate/deploy/site/compose.{name}.yaml' in overlays and not manifest.get(field):
                    raise Rejected(f'{name} overlay is not covered by this signed candidate')
            if loaded:
                accepted = manifest.get('accepted_image_ids')
                if (not isinstance(accepted, dict) or set(accepted) != set(services)
                        or any(not isinstance(accepted[s], list) or not accepted[s]
                               or any(not isinstance(i, str) or not re.fullmatch(r'sha256:[0-9a-f]{64}', i)
                                      for i in accepted[s]) for s in services)):
                    raise Rejected('loaded candidate image identity proof is incomplete')
                self._accepted_images[commit] = accepted
                self._runtime_proofs[commit] = services
            return manifest
        except CandidateVerificationError as error:  # fixed strings of our verifier
            raise Rejected(f"verification failed: {error}") from None
        except OSError as error:  # its text names host paths
            raise Rejected(f"verification failed: {type(error).__name__}") from None

    def healthy(self, env: dict[str, str], commit: str) -> tuple[bool, str]:
        deadline = self.clock() + self.config["health_timeout_s"]
        reason = "not checked"
        while True:
            status = self.http.status(self.config["health_url"], self.config["health_ca"])
            reason = f"healthz returned {status}"
            if status == 200:
                reason = self._containers_reason(env, commit)
                if reason == '':
                    if self._functional_baseline is None:
                        reason = functional_reason(self.config, self.http)
                    else:
                        try:
                            observed, _ = functional_inventory(self.config, self.http)
                            if any(not set(ids) <= set(observed.get(path, []))
                                   for path, ids in self._functional_baseline.items()):
                                reason = 'functional API lost previously observed IDs'
                        except Rejected as error:
                            reason = str(error)
                if reason == "":
                    return True, "healthy"
            if self.clock() >= deadline:
                return False, reason
            self.sleep(5)

    def _containers_reason(self, env: dict[str, str], commit: str) -> str:
        inventory = self._runtime_proofs.get(commit)
        if inventory is None:
            return 'runtime has no verified service-set proof'
        overlays = allowed_overlays(env)
        services = active_services(inventory, overlays)
        try:
            out = self._compose(env, "ps", "--all", "--format", "json").stdout.strip()
        except Transient as error:
            log('compose-ps-failed', detail=str(error))  # last_run.reason is only ever our own fixed text
            return 'docker compose ps failed (see the journal)'
        try:
            rows = json.loads(out) if out.startswith("[") else [
                json.loads(line) for line in out.splitlines() if line.strip()]
        except json.JSONDecodeError:
            return "docker compose ps output is not JSON"
        try:
            output = self._compose(env, 'config', '--hash', '*', tag=commit).stdout
            hashes = dict(line.split() for line in output.splitlines() if line.strip())
        except Transient as error:
            log('compose-config-failed', detail=str(error))
            return 'docker compose config failed (see the journal)'
        except ValueError:
            return 'Compose configuration hashes cannot be verified'
        companions = companion_services(overlays, inventory, hashes)
        reason = containers_reason(rows, commit, self._accepted_images.get(commit, {}), self._run, services,
                                   self._image_references.get(commit), companions=companions)
        return reason or runtime_reason(rows, hashes, self._run)

    def _restart(self) -> None:
        env = read_env(self.paths.site_env)
        if env.get('ROSY_SITE_IMAGE_TAG') in self._incremental_commits:
            active = self._run(['systemctl', 'is-active', '--quiet', STACK_UNIT], check=False)
            if active.returncode != 0:
                self._run(['systemctl', 'start', STACK_UNIT], timeout=300)
                return
            self._run(['python3', str(self.paths.link / 'deploy/site/site-firewall.py'),
                       'check', '--verify-certs', '--env-file', str(self.paths.site_env),
                       '--compose-file', str(self.paths.link / 'deploy/site/compose.yaml')])
            self._compose(env, 'up', '-d', '--no-build', '--pull', 'never', timeout=300)
            return
        self._run(["systemctl", "restart", STACK_UNIT], timeout=300)

    def _retire_postgres(self, env: dict, folder: Path, commit: str, incoming: tuple) -> None:
        """D-887: a fresh outgoing proof authorizes only exact-ID PostgreSQL cleanup."""
        outgoing = self._runtime_proofs[commit]
        self.check_overrides(env, commit, folder=folder, env_file=self.paths.env_backup,
                             services=outgoing)
        # Account remains an optional overlay across old Fleet-owned and new independent images.
        outgoing = tuple(s for s in outgoing if s not in ('account', 'monitoring'))  # D-1001: optional overlays
        incoming = tuple(s for s in incoming if s not in ('account', 'monitoring'))
        if outgoing == incoming:
            return
        if set(outgoing) - set(incoming) != {'postgres'}:
            if set(outgoing) <= set(incoming):
                return
            raise Rejected('unsupported retired service set')
        output = self._compose(env, 'config', '--hash', '*', tag=commit, folder=folder,
                               env_file=self.paths.env_backup).stdout
        try:
            hashes = dict(line.split() for line in output.splitlines() if line.strip())
        except ValueError:
            raise Rejected('outgoing Compose hashes cannot be verified') from None
        expected_hash = hashes.get('postgres')
        if not expected_hash:
            raise Rejected('outgoing PostgreSQL hash is missing')
        args = ['docker', 'ps', '--all', '--no-trunc', '--quiet', '--filter', f'label=com.docker.compose.project={PROJECT}',
                '--filter', 'label=com.docker.compose.service=postgres']
        ids = self._run(args).stdout.split()
        canonical = []
        manual = set()
        for cid in ids:
            try:
                rows = json.loads(self._run(['docker', 'container', 'inspect', cid]).stdout)
                if not isinstance(rows, list) or len(rows) != 1:
                    raise ValueError
                row = rows[0]
                config, labels = row['Config'], row['Config']['Labels']
                if (row['Id'] != cid or labels.get('com.docker.compose.project') != PROJECT
                        or labels.get('com.docker.compose.service') != 'postgres'):
                    raise ValueError
                if not labels.get('com.docker.compose.config-hash'):
                    manual.add(cid)
                    continue  # Manual containers are outside this cleanup authority.
                if (labels['com.docker.compose.config-hash'] != expected_hash
                        or config['Image'] != self._image_references.get(commit, {}).get(
                            'postgres', f'rosy-site-postgres:{commit}')
                        or row['Image'] not in self._accepted_images[commit]['postgres']
                        or type(row['State']['Running']) is not bool):
                    raise ValueError
                canonical.append((cid, row['State']['Running']))
            except (ValueError, KeyError, TypeError, IndexError, AttributeError):
                raise Rejected('retired PostgreSQL identity cannot be verified') from None
        if len(canonical) > 1:
            raise Rejected('retired PostgreSQL identity is ambiguous')
        for cid, running in canonical:
            if running:
                self._run(['docker', 'container', 'stop', '--', cid], timeout=300)
            self._run(['docker', 'container', 'rm', '--', cid])
        if set(self._run(args).stdout.split()) - manual:
            raise Transient('retired PostgreSQL remains or changed after removal')
