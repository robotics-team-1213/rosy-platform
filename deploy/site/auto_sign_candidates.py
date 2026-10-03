"""Automatic manifest-only signer for CI-built site candidates (D-440).

Runs on the operator's signing PC (Windows or Linux) from a scheduled task.
The private key stays on that PC; nothing here sends it anywhere. One
invocation:

1. lists the repository's releases (``gh api --paginate``) and picks tags that
   match ``^site-[0-9a-f]{12}$`` and have ``release.json`` but no
   ``release.json.sig``, newest first, at most ``max_per_run``;
2. downloads only ``release.json`` into a fresh folder;
3. requires GitHub build provenance from this repository's
   ``build-site-candidate.yml`` built from ``refs/heads/main``
   (``gh attestation verify --format json``) whose ``release.json`` subject
   digest equals the SHA-256 of the downloaded bytes;
4. requires the manifest ``source_commit`` to be on ``main`` (compare status
   ``ahead`` or ``identical``) and the tag to be ``site-<source_commit[:12]>``;
5. signs with ``sign_candidate.sign_manifest_only`` (expected commit and the
   attested digest), then uploads ``release.json.sig`` without ``--clobber``;
6. appends one JSON line per decision to ``<state_dir>/audit.jsonl``.

    python auto_sign_candidates.py --config <path-outside-the-repo>.json [--dry-run]

Exit codes: 0 nothing to do, 10 signed at least one and refused nothing,
20 refused or failed at least one, 2 bad configuration or another run holds
the lock. The site host still verifies every file before ``docker load``.
"""

from __future__ import annotations

import argparse
import contextlib
import datetime as _dt
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Callable, Iterator

if __package__:
    from .candidate_signing import CandidateSignatureError, SIGNATURE_FILENAME
    from .sign_candidate import CandidateVerificationError, sign_manifest_only
else:  # pragma: no cover - exercised by the scheduled CLI
    from candidate_signing import CandidateSignatureError, SIGNATURE_FILENAME
    from sign_candidate import CandidateVerificationError, sign_manifest_only

Runner = Callable[..., subprocess.CompletedProcess]

EXIT_IDLE = 0
EXIT_SIGNED = 10
EXIT_REFUSED = 20
EXIT_CONFIG = 2

WORKFLOW_PATH = ".github/workflows/build-site-candidate.yml"
SOURCE_REF = "refs/heads/main"
_TAG = re.compile(r"^site-[0-9a-f]{12}$")
_COMMIT = re.compile(r"^[0-9a-f]{40}$")
_SHA256 = re.compile(r"^[0-9a-f]{64}$")
_REPO = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_-]*/[A-Za-z0-9][A-Za-z0-9_.-]*$")
_KEY_ID = re.compile(r"^[A-Za-z0-9._-]{1,64}$")
_MANIFEST_LIMIT = 8 * 1024 * 1024
_REFUSED_LIMIT = 200


class Refused(Exception):
    """This candidate must not be signed; the reason is recorded."""


class ConfigError(ValueError):
    """The signer configuration is unusable."""


def _now() -> str:
    return _dt.datetime.now(_dt.timezone.utc).replace(microsecond=0).isoformat()


def load_config(path: Path) -> dict:
    """Read the JSON (or YAML, when PyYAML is installed) signer configuration."""
    path = Path(path)
    try:
        text = path.read_text(encoding="utf-8")
    except OSError as error:
        raise ConfigError(f"cannot read config: {error}") from None
    if path.suffix.lower() in {".yaml", ".yml"}:
        try:
            import yaml  # type: ignore[import-untyped]
        except ImportError:
            raise ConfigError("YAML config needs PyYAML; use JSON instead") from None
        raw = yaml.safe_load(text)
    else:
        try:
            raw = json.loads(text)
        except json.JSONDecodeError:
            raise ConfigError("config is not valid JSON") from None
    if not isinstance(raw, dict):
        raise ConfigError("config must be an object")
    allowed = {"repo", "key_id", "private_key", "public_key", "state_dir", "keep",
               "max_per_run", "gh"}
    unknown = set(raw) - allowed
    if unknown:
        raise ConfigError(f"unknown config keys: {sorted(unknown)}")
    repo = raw.get("repo")
    if not isinstance(repo, str) or not _REPO.fullmatch(repo):
        raise ConfigError("repo must be owner/repository")
    key_id = raw.get("key_id")
    if not isinstance(key_id, str) or not _KEY_ID.fullmatch(key_id):
        raise ConfigError("key_id is malformed")
    config = {"repo": repo, "key_id": key_id, "gh": raw.get("gh", "gh")}
    for name in ("private_key", "public_key", "state_dir"):
        value = raw.get(name)
        if not isinstance(value, str) or not value:
            raise ConfigError(f"{name} must be a path")
        config[name] = Path(value)
    for name, default, upper in (("keep", 10, 1000), ("max_per_run", 3, 20)):
        value = raw.get(name, default)
        if type(value) is not int or not 1 <= value <= upper:
            raise ConfigError(f"{name} must be an integer from 1 to {upper}")
        config[name] = value
    if not isinstance(config["gh"], str) or not config["gh"]:
        raise ConfigError("gh must be a command name or path")
    for name in ("private_key", "public_key"):
        if not config[name].is_file():
            raise ConfigError(f"{name} is not a file")
    return config


@contextlib.contextmanager
def _run_lock(state_dir: Path) -> Iterator[None]:
    """One signer at a time; a second invocation stops instead of waiting."""
    path = state_dir / "auto-sign.lock"
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
            raise ConfigError("another auto-sign run holds the lock") from None
        yield
    finally:
        stream.close()


class AutoSigner:
    def __init__(self, config: dict, *, runner: Runner = subprocess.run,
                 openssl_runner: Runner = subprocess.run, dry_run: bool = False):
        self.config = config
        self.repo = config["repo"]
        self.state_dir = Path(config["state_dir"])
        self.runner = runner
        self.openssl_runner = openssl_runner
        self.dry_run = dry_run
        self.results: list[dict] = []

    # -- gh helpers -----------------------------------------------------
    def _gh(self, *args: str, timeout: int = 120) -> str:
        try:
            result = self.runner([self.config["gh"], *args], capture_output=True, text=True,
                                 check=False, timeout=timeout)
        except (OSError, subprocess.SubprocessError) as error:
            raise RuntimeError(f"gh {args[0]} could not run: {type(error).__name__}") from None
        if result.returncode != 0:
            detail = (result.stderr or "").strip().splitlines()[-1:] or [""]
            raise RuntimeError(f"gh {args[0]} failed: {detail[0][:200]}")
        return result.stdout or ""

    def list_unsigned(self) -> list[dict]:
        out = self._gh(
            "api", "--paginate", f"repos/{self.repo}/releases?per_page=100",
            "--jq", ".[] | {tag: .tag_name, draft: .draft, created_at: .created_at, "
                    "assets: [.assets[].name]}",
        )
        releases = []
        for line in out.splitlines():
            if not line.strip():
                continue
            row = json.loads(line)
            tag = row.get("tag")
            assets = row.get("assets") or []
            if (not isinstance(tag, str) or not _TAG.fullmatch(tag) or row.get("draft")
                    or "release.json" not in assets or SIGNATURE_FILENAME in assets):
                continue
            releases.append({"tag": tag, "created_at": str(row.get("created_at") or "")})
        releases.sort(key=lambda row: (row["created_at"], row["tag"]), reverse=True)
        return releases

    def _assets(self, tag: str) -> list[str]:
        out = self._gh("api", f"repos/{self.repo}/releases/tags/{tag}",
                       "--jq", "[.assets[].name]")
        names = json.loads(out or "[]")
        if not isinstance(names, list):
            raise RuntimeError("release asset list is malformed")
        return names

    # -- checks ---------------------------------------------------------
    def _attested_digest(self, manifest: Path, actual: str) -> str:
        workflow = f"{self.repo}/{WORKFLOW_PATH}"
        try:
            out = self._gh(
                "attestation", "verify", str(manifest), "--repo", self.repo,
                "--signer-workflow", workflow, "--source-ref", SOURCE_REF,
                "--format", "json", timeout=180,
            )
        except RuntimeError as error:
            raise Refused(f"provenance check failed: {error}") from None
        try:
            results = json.loads(out)
        except json.JSONDecodeError:
            raise Refused("provenance output is not JSON") from None
        if not isinstance(results, list) or not results:
            raise Refused("provenance output has no verified attestation")
        digests = set()
        for item in results:
            result = item.get("verificationResult") if isinstance(item, dict) else None
            if not isinstance(result, dict):
                raise Refused("provenance output is malformed")
            # gh enforced --signer-workflow and --source-ref; re-check the
            # certificate summary too whenever gh reports it.
            certificate = (result.get("signature") or {}).get("certificate")
            if isinstance(certificate, dict):
                ref = certificate.get("sourceRepositoryRef")
                signer = certificate.get("buildSignerURI") or certificate.get(
                    "subjectAlternativeName")
                if ref is not None and ref != SOURCE_REF:
                    raise Refused(f"provenance source ref is {ref}, not {SOURCE_REF}")
                if signer is not None and not str(signer).startswith(
                        f"https://github.com/{workflow}@"):
                    raise Refused("provenance was signed by another workflow")
            statement = result.get("statement")
            subjects = statement.get("subject") if isinstance(statement, dict) else None
            for subject in subjects or []:
                if isinstance(subject, dict) and subject.get("name") == "release.json":
                    digest = (subject.get("digest") or {}).get("sha256")
                    if isinstance(digest, str):
                        digests.add(digest)
        if not digests:
            raise Refused("provenance has no release.json subject")
        if digests != {actual}:
            raise Refused("attested release.json digest differs from the downloaded bytes")
        return actual

    def _require_on_main(self, commit: str) -> None:
        try:
            status = self._gh("api", f"repos/{self.repo}/compare/{commit}...main",
                              "--jq", ".status").strip()
        except RuntimeError as error:
            raise Refused(f"main ancestry check failed: {error}") from None
        if status not in {"ahead", "identical"}:
            raise Refused(f"source commit is not on main (compare status {status or 'empty'})")

    # -- state ------------------------------------------------------------
    def _state_path(self) -> Path:
        return self.state_dir / "auto-sign-state.json"

    def _load_state(self) -> dict:
        try:
            state = json.loads(self._state_path().read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return {"refused": []}
        if not isinstance(state, dict) or not isinstance(state.get("refused"), list):
            return {"refused": []}
        return state

    def _save_state(self, state: dict) -> None:
        state["refused"] = state["refused"][-_REFUSED_LIMIT:]
        target = self._state_path()
        temporary = target.with_suffix(".tmp")
        temporary.write_text(json.dumps(state, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        os.replace(temporary, target)

    def _audit(self, record: dict) -> None:
        record = {"time": _now(), "repo": self.repo, **record}
        self.results.append(record)
        with (self.state_dir / "audit.jsonl").open("a", encoding="utf-8") as stream:
            stream.write(json.dumps(record, sort_keys=True) + "\n")
        print(json.dumps(record, sort_keys=True))

    def _keep_signed(self, tag: str, folder: Path) -> None:
        signed = self.state_dir / "signed"
        target = signed / tag
        if target.exists():
            shutil.rmtree(target)
        shutil.copytree(folder, target)
        kept = sorted((path for path in signed.iterdir() if path.is_dir()),
                      key=lambda path: path.stat().st_mtime, reverse=True)
        for old in kept[self.config["keep"]:]:
            shutil.rmtree(old, ignore_errors=True)

    # -- one candidate ------------------------------------------------------
    def _sign_one(self, tag: str, state: dict) -> str:
        work = self.state_dir / "work"
        work.mkdir(parents=True, exist_ok=True)
        folder = Path(tempfile.mkdtemp(prefix=f"{tag}-", dir=work))
        digest = None
        try:
            self._gh("release", "download", tag, "--repo", self.repo,
                     "--pattern", "release.json", "--dir", str(folder))
            manifest_path = folder / "release.json"
            names = sorted(path.name for path in folder.iterdir())
            if names != ["release.json"] or manifest_path.is_symlink():
                raise Refused(f"unexpected download contents: {names}")
            manifest_bytes = manifest_path.read_bytes()
            if not manifest_bytes or len(manifest_bytes) > _MANIFEST_LIMIT:
                raise Refused("release.json is empty or exceeds 8 MiB")
            digest = hashlib.sha256(manifest_bytes).hexdigest()
            # A refusal is final for these exact bytes; a replaced release.json
            # (new digest) is checked again.
            if {"tag": tag, "manifest_sha256": digest} in state["refused"]:
                return "skipped"
            return self._run_checks_and_sign(tag, folder, manifest_path, manifest_bytes, digest)
        except Refused as error:
            if digest is not None:
                state["refused"].append({"tag": tag, "manifest_sha256": digest})
            self._audit({"decision": "refused", "tag": tag, "manifest_sha256": digest,
                         "reason": str(error)})
            return "refused"
        finally:
            shutil.rmtree(folder, ignore_errors=True)

    def _run_checks_and_sign(self, tag: str, folder: Path, manifest_path: Path,
                             manifest_bytes: bytes, digest: str) -> str:
        attested = self._attested_digest(manifest_path, digest)
        try:
            manifest = json.loads(manifest_bytes)
        except (UnicodeDecodeError, json.JSONDecodeError):
            raise Refused("release.json is not valid JSON") from None
        commit = manifest.get("source_commit") if isinstance(manifest, dict) else None
        if not isinstance(commit, str) or not _COMMIT.fullmatch(commit):
            raise Refused("release.json source_commit is not a 40-character hex SHA")
        if tag != f"site-{commit[:12]}":
            raise Refused(f"tag {tag} does not name source commit {commit[:12]}")
        self._require_on_main(commit)
        if self.dry_run:
            self._audit({"decision": "would-sign", "tag": tag, "source_commit": commit,
                         "manifest_sha256": attested})
            return "would-sign"
        try:
            result = sign_manifest_only(
                manifest_path, expected_commit=commit, expected_manifest_sha256=attested,
                key_id=self.config["key_id"], private_key=self.config["private_key"],
                public_key=self.config["public_key"], runner=self.openssl_runner,
            )
        except (CandidateSignatureError, CandidateVerificationError) as error:
            raise Refused(f"signer refused: {error}") from None
        # Another signer may have attached a signature meanwhile; never overwrite.
        if SIGNATURE_FILENAME in self._assets(tag):
            self._audit({"decision": "skipped", "tag": tag, "source_commit": commit,
                         "reason": "a signature was attached while this run was signing"})
            return "skipped"
        self._gh("release", "upload", tag, str(folder / SIGNATURE_FILENAME),
                 "--repo", self.repo)
        self._keep_signed(tag, folder)
        self._audit({"decision": "signed", "tag": tag, "source_commit": commit,
                     "manifest_sha256": result["manifest_sha256"],
                     "signing_key_id": result["signing_key_id"]})
        return "signed"

    def run(self) -> int:
        self.state_dir.mkdir(parents=True, exist_ok=True)
        with _run_lock(self.state_dir):
            state = self._load_state()
            try:
                candidates = self.list_unsigned()
            except (RuntimeError, json.JSONDecodeError) as error:
                self._audit({"decision": "error", "reason": f"listing releases: {error}"})
                return EXIT_REFUSED
            outcomes = []
            for row in candidates[: self.config["max_per_run"]]:
                try:
                    outcomes.append(self._sign_one(row["tag"], state))
                except (RuntimeError, OSError) as error:
                    self._audit({"decision": "error", "tag": row["tag"], "reason": str(error)})
                    outcomes.append("error")
            self._save_state(state)
        if any(outcome in {"refused", "error"} for outcome in outcomes):
            return EXIT_REFUSED
        if "signed" in outcomes:
            return EXIT_SIGNED
        return EXIT_IDLE


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--config", required=True, type=Path,
                        help="JSON config kept outside the repository")
    parser.add_argument("--dry-run", action="store_true",
                        help="run every check, but neither sign nor upload")
    args = parser.parse_args(argv)
    try:
        config = load_config(args.config)
        return AutoSigner(config, dry_run=args.dry_run).run()
    except ConfigError as error:
        print(json.dumps({"time": _now(), "decision": "error", "reason": str(error)}),
              file=sys.stderr)
        return EXIT_CONFIG


if __name__ == "__main__":
    sys.exit(main())
