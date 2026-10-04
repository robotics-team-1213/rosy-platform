"""deploy/site/auto_sign_candidates.py: signing-PC policy (D-441), against a fake gh."""

from __future__ import annotations

import hashlib
import json
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

from deploy.site import auto_sign_candidates as auto
from deploy.site.candidate_signing import verify_manifest_signature

REPO = "example-owner/example-repo"
KEY_ID = "rosy-site-test-1"
COMMIT = "ab" * 20
TAG = f"site-{COMMIT[:12]}"
WORKFLOW = f"{REPO}/.github/workflows/build-site-candidate.yml"


def test_gh_utf8_output_survives_windows_legacy_locale(tmp_path, monkeypatch):
    """Exercise real pipe decoding, including gh's Unicode progress on stderr."""
    monkeypatch.setattr(subprocess, "_text_encoding", lambda: "cp949")
    output = json.dumps({"verified": "\u2713"}, ensure_ascii=False) + "\n"
    progress = "\u2713 Verification succeeded\n"
    script = ("import sys; sys.stdout.buffer.write(" + repr(output.encode("utf-8"))
              + "); sys.stderr.buffer.write(" + repr(progress.encode("utf-8")) + ")")

    def run_child(argv, **kwargs):
        return subprocess.run([sys.executable, "-c", script], **kwargs)

    signer = auto.AutoSigner({"repo": REPO, "gh": "gh", "state_dir": tmp_path},
                             runner=run_child)
    assert json.loads(signer._gh("attestation", "verify")) == {"verified": "\u2713"}


def _keys(directory: Path) -> tuple[Path, Path]:
    private = directory / "site.key"
    public = directory / "site.pub.pem"
    subprocess.run(["openssl", "genpkey", "-algorithm", "ed25519", "-out", str(private)],
                   check=True, capture_output=True)
    subprocess.run(["openssl", "pkey", "-in", str(private), "-pubout", "-out", str(public)],
                   check=True, capture_output=True)
    return private, public


@pytest.fixture(scope="module")
def keys(tmp_path_factory):
    return _keys(tmp_path_factory.mktemp("auto-sign-keys"))


def _manifest(commit: str = COMMIT) -> bytes:
    return (json.dumps({"manifest_version": 1, "source_commit": commit, "image_tag": commit,
                        "platform": "linux/amd64"}, sort_keys=True) + "\n").encode()


class FakeGh:
    """Serves releases, downloads, attestations and compare results."""

    def __init__(self, *, manifest: bytes | None = None, tag: str = TAG,
                 attested: str | None = None, source_ref: str = "refs/heads/main",
                 compare: str = "ahead", signed: bool = False):
        self.manifest = manifest if manifest is not None else _manifest()
        self.tag = tag
        digest = hashlib.sha256(self.manifest).hexdigest()
        self.attested = attested or digest
        self.source_ref = source_ref
        self.compare = compare
        self.assets = ["SHA256SUMS", "release.json", "rosy-site-candidate.tar.part00"]
        if signed:
            self.assets.append("release.json.sig")
        self.uploads: list[bytes] = []
        self.calls: list[list[str]] = []
        self.ci_runs = [{"id": 101, "head_sha": COMMIT, "head_branch": "main",
                         "event": "push", "status": "completed", "conclusion": "success"}]
        self.ci_jobs = [{"name": "ci-result", "status": "completed", "conclusion": "success"}]

    def _ok(self, stdout: str = "") -> SimpleNamespace:
        return SimpleNamespace(returncode=0, stdout=stdout, stderr="")

    def __call__(self, argv, **kwargs):
        args = list(argv[1:])
        self.calls.append(args)
        if args[0] == "api" and "/actions/workflows/ci.yml/runs?" in args[1]:
            return self._ok(json.dumps({"workflow_runs": self.ci_runs}))
        if args[0] == "api" and "/actions/runs/101/jobs?" in args[1]:
            return self._ok(json.dumps({"jobs": self.ci_jobs}))
        if args[:2] == ["api", "--paginate"]:
            rows = [
                {"tag": self.tag, "draft": False, "created_at": "2026-10-04T01:00:00Z",
                 "assets": self.assets},
                {"tag": "payload-007", "draft": False, "created_at": "2026-10-04T02:00:00Z",
                 "assets": ["release.json"]},
            ]
            return self._ok("".join(json.dumps(row) + "\n" for row in rows))
        if args[0] == "api" and "/releases/tags/" in args[1]:
            return self._ok(json.dumps(self.assets))
        if args[0] == "api" and "/compare/" in args[1]:
            assert args[1].endswith("...main")
            return self._ok(self.compare + "\n")
        if args[:2] == ["release", "download"]:
            folder = Path(args[args.index("--dir") + 1])
            assert args[args.index("--pattern") + 1] == "release.json"
            (folder / "release.json").write_bytes(self.manifest)
            return self._ok()
        if args[:2] == ["attestation", "verify"]:
            assert args[args.index("--signer-workflow") + 1] == WORKFLOW
            if args[args.index("--source-ref") + 1] != self.source_ref:
                return SimpleNamespace(returncode=1, stdout="",
                                       stderr="verification failed: source ref mismatch\n")
            result = [{"verificationResult": {
                "signature": {"certificate": {
                    "sourceRepositoryRef": self.source_ref,
                    "buildSignerURI": f"https://github.com/{WORKFLOW}@{self.source_ref}"}},
                "statement": {"subject": [
                    {"name": "release.json", "digest": {"sha256": self.attested}},
                    {"name": "SHA256SUMS", "digest": {"sha256": "0" * 64}}]},
            }}]
            return self._ok(json.dumps(result))
        if args[:2] == ["release", "upload"]:
            assert "--clobber" not in args
            self.uploads.append(Path(args[3]).read_bytes())
            self.assets.append("release.json.sig")
            return self._ok()
        raise AssertionError(f"unexpected gh call: {args}")


def _config(tmp_path: Path, keys) -> dict:
    config_path = tmp_path / "signer.json"
    config_path.write_text(json.dumps({
        "repo": REPO, "key_id": KEY_ID, "private_key": str(keys[0]),
        "public_key": str(keys[1]), "state_dir": str(tmp_path / "state"), "keep": 2,
    }), encoding="utf-8")
    return auto.load_config(config_path)


def _audit(tmp_path: Path) -> list[dict]:
    path = tmp_path / "state" / "audit.jsonl"
    if not path.exists():
        return []
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]


@pytest.mark.parametrize("case", ["failed", "pending", "missing", "wrong-sha", "missing-gate", "failed-gate",
                                  "newer-pending", "wrong-event"])
def test_ci_must_pass_before_signing_and_remains_retryable(tmp_path, keys, case):
    gh = FakeGh()
    if case == "failed":
        gh.ci_runs[0]["conclusion"] = "failure"
    elif case == "pending":
        gh.ci_runs[0]["status"] = "in_progress"
    elif case == "missing":
        gh.ci_runs = []
    elif case == "wrong-sha":
        gh.ci_runs[0]["head_sha"] = "ff" * 20
    elif case == "missing-gate":
        gh.ci_jobs = []
    elif case == "failed-gate":
        gh.ci_jobs[0]["conclusion"] = "failure"
    elif case == "newer-pending":
        gh.ci_runs.insert(0, {**gh.ci_runs[0], "id": 102, "status": "queued"})
    elif case == "wrong-event":
        gh.ci_runs[0]["event"] = "pull_request"
    signer = auto.AutoSigner(_config(tmp_path, keys), runner=gh)
    assert signer.run() == auto.EXIT_REFUSED
    assert gh.uploads == []
    assert json.loads((tmp_path / "state/auto-sign-state.json").read_text())["refused"] == []
    gh.ci_runs = [{"id": 101, "head_sha": COMMIT, "head_branch": "main", "event": "push",
                   "status": "completed", "conclusion": "success"}]
    gh.ci_jobs = [{"name": "ci-result", "status": "completed", "conclusion": "success"}]
    assert signer.run() == auto.EXIT_SIGNED


def test_happy_path_signs_uploads_and_audits(tmp_path, keys):
    gh = FakeGh()
    signer = auto.AutoSigner(_config(tmp_path, keys), runner=gh)

    assert signer.run() == auto.EXIT_SIGNED
    assert len(gh.uploads) == 1
    verify_manifest_signature(gh.manifest, gh.uploads[0], trusted_key_id=KEY_ID,
                              public_key=keys[1])
    record = _audit(tmp_path)[-1]
    assert record["decision"] == "signed" and record["tag"] == TAG
    assert record["source_commit"] == COMMIT
    assert record["manifest_sha256"] == hashlib.sha256(gh.manifest).hexdigest()
    assert (tmp_path / "state" / "signed" / TAG / "release.json.sig").is_file()
    assert not any((tmp_path / "state" / "work").iterdir())
    # Only the site tag was downloaded; payload-* is never touched.
    downloads = [call for call in gh.calls if call[:2] == ["release", "download"]]
    assert [call[2] for call in downloads] == [TAG]

    # The next run sees the signature and has nothing to do.
    assert auto.AutoSigner(_config(tmp_path, keys), runner=gh).run() == auto.EXIT_IDLE


def test_attestation_digest_mismatch_is_refused(tmp_path, keys):
    gh = FakeGh(attested="f" * 64)

    assert auto.AutoSigner(_config(tmp_path, keys), runner=gh).run() == auto.EXIT_REFUSED
    assert gh.uploads == []
    record = _audit(tmp_path)[-1]
    assert record["decision"] == "refused"
    assert "digest differs" in record["reason"]

    # Same bytes are not re-checked or re-logged on the next run.
    calls = len(gh.calls)
    assert auto.AutoSigner(_config(tmp_path, keys), runner=gh).run() == auto.EXIT_IDLE
    assert len(_audit(tmp_path)) == 1
    assert not any(call[:2] == ["attestation", "verify"] for call in gh.calls[calls:])


def test_build_from_another_ref_is_refused(tmp_path, keys):
    gh = FakeGh(source_ref="refs/heads/feature")

    assert auto.AutoSigner(_config(tmp_path, keys), runner=gh).run() == auto.EXIT_REFUSED
    assert gh.uploads == []
    assert "source ref mismatch" in _audit(tmp_path)[-1]["reason"]
    assert _audit(tmp_path)[-1]['decision'] == 'error'


@pytest.mark.parametrize("status", ["behind", "diverged", ""])
def test_commit_not_on_main_is_refused(tmp_path, keys, status):
    gh = FakeGh(compare=status)

    assert auto.AutoSigner(_config(tmp_path, keys), runner=gh).run() == auto.EXIT_REFUSED
    assert gh.uploads == []
    assert "not on main" in _audit(tmp_path)[-1]["reason"]


def test_identical_to_main_is_accepted(tmp_path, keys):
    gh = FakeGh(compare="identical")

    assert auto.AutoSigner(_config(tmp_path, keys), runner=gh).run() == auto.EXIT_SIGNED


def test_already_signed_release_is_skipped(tmp_path, keys):
    gh = FakeGh(signed=True)

    assert auto.AutoSigner(_config(tmp_path, keys), runner=gh).run() == auto.EXIT_IDLE
    assert gh.uploads == []
    assert not any(call[:2] == ["release", "download"] for call in gh.calls)


def test_tag_that_does_not_name_the_commit_is_refused(tmp_path, keys):
    gh = FakeGh(manifest=_manifest("cd" * 20))

    assert auto.AutoSigner(_config(tmp_path, keys), runner=gh).run() == auto.EXIT_REFUSED
    assert gh.uploads == []
    assert "does not name source commit" in _audit(tmp_path)[-1]["reason"]
    assert not any("/compare/" in " ".join(call) for call in gh.calls)


def test_signature_attached_meanwhile_is_not_overwritten(tmp_path, keys):
    gh = FakeGh()
    original = gh.__call__

    def racing(argv, **kwargs):
        if list(argv[1:3]) == ["attestation", "verify"]:
            gh.assets.append("release.json.sig")
        return original(argv, **kwargs)

    assert auto.AutoSigner(_config(tmp_path, keys), runner=racing).run() == auto.EXIT_IDLE
    assert gh.uploads == []
    assert _audit(tmp_path)[-1]["decision"] == "skipped"


def test_dry_run_checks_everything_but_neither_signs_nor_uploads(tmp_path, keys):
    gh = FakeGh()

    signer = auto.AutoSigner(_config(tmp_path, keys), runner=gh, dry_run=True)
    assert signer.run() == auto.EXIT_IDLE
    assert gh.uploads == []
    assert _audit(tmp_path)[-1]["decision"] == "would-sign"


def test_config_rejects_bad_values(tmp_path, keys):
    path = tmp_path / "bad.json"
    path.write_text(json.dumps({"repo": "not a repo", "key_id": KEY_ID}), encoding="utf-8")
    with pytest.raises(auto.ConfigError, match="owner/repository"):
        auto.load_config(path)
    path.write_text(json.dumps({"repo": REPO, "key_id": KEY_ID, "private_key": str(keys[0]),
                                "public_key": str(keys[1]), "state_dir": str(tmp_path),
                                "token": "x"}), encoding="utf-8")
    with pytest.raises(auto.ConfigError, match="unknown config keys"):
        auto.load_config(path)
    assert auto.main(["--config", str(path)]) == auto.EXIT_CONFIG


def test_a_second_run_does_not_wait_for_the_lock(tmp_path, keys):
    config = _config(tmp_path, keys)
    config["state_dir"].mkdir(parents=True)
    with auto._run_lock(config["state_dir"]):
        with pytest.raises(auto.ConfigError, match="holds the lock"):
            with auto._run_lock(config["state_dir"]):
                pass


@pytest.mark.parametrize('operation', ['attestation', 'compare'])
def test_network_failure_is_retried_on_next_run(tmp_path, keys, operation):
    gh = FakeGh()

    def unavailable(argv, **kwargs):
        if (operation == 'attestation' and argv[1] == 'attestation') or (
                operation == 'compare' and '/compare/' in ' '.join(argv)):
            raise subprocess.TimeoutExpired(argv, 120)
        return gh(argv, **kwargs)
    config = _config(tmp_path, keys)
    assert auto.AutoSigner(config, runner=unavailable).run() == auto.EXIT_REFUSED
    assert json.loads((tmp_path / 'state/auto-sign-state.json').read_text())['refused'] == []
    assert auto.AutoSigner(config, runner=gh).run() == auto.EXIT_SIGNED
