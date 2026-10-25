"""Existing candidate verification and runtime I/O for the site updater.

Installed with the reviewed updater and I/O ports, outside candidate folders.
Switch and rollback ordering remain in SiteUpdater.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
import shlex
import subprocess

if __package__:
    from .site_update_io import (
        PROJECT, STACK_UNIT, Rejected, Transient, containers_reason,
        functional_inventory, functional_reason, runtime_reason,
    )
    from .verify_candidate import CandidateVerificationError
else:  # pragma: no cover - installed host CLI
    from site_update_io import (
        PROJECT, STACK_UNIT, Rejected, Transient, containers_reason,
        functional_inventory, functional_reason, runtime_reason,
    )
    from verify_candidate import CandidateVerificationError


class SiteRuntimeIO:
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

    def _verify(self, folder: Path, *, loaded: bool, expected_commit: str | None = None,
                env: dict | None = None) -> dict:
        try:
            manifest = self.verifier(folder, trusted_key_id=self.config["key_id"],
                                     trusted_public_key=self.config["public_key"],
                                     runner=self.runner, inspect_loaded_images=loaded)
            if manifest.get('source_commit') != (expected_commit or folder.name):
                raise Rejected('signed manifest commit differs from candidate commit')
            overlays = shlex.split((env or {}).get('ROSY_SITE_PAIRING_COMPOSE', ''))
            for name, field in (('account', 'account_https'), ('omx', 'omx'), ('workcell', 'workcell')):
                if f'/opt/rosy/candidate/deploy/site/compose.{name}.yaml' in overlays and not manifest.get(field):
                    raise Rejected(f'{name} overlay is not covered by this signed candidate')
            if loaded:
                self._accepted_images[manifest['source_commit']] = manifest.get('accepted_image_ids', {})
            return manifest
        except (CandidateVerificationError, OSError) as error:
            raise Rejected(f"verification failed: {error}") from None

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
