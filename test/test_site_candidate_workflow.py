"""Contracts for the GitHub-hosted, unsigned site candidate workflow (D-437)."""

import re
from pathlib import Path

import yaml


ROOT = Path(__file__).resolve().parents[1]
WORKFLOW = ROOT / ".github" / "workflows" / "build-site-candidate.yml"


def _workflow():
    return yaml.safe_load(WORKFLOW.read_text(encoding="utf-8"))


def _run_text(job):
    return "\n".join(step.get("run", "") for step in job["steps"])


def test_site_candidate_workflow_is_manual_and_uses_no_secrets():
    workflow = _workflow()
    text = WORKFLOW.read_text(encoding="utf-8")
    triggers = workflow.get("on", workflow.get(True))

    assert set(triggers) == {"workflow_dispatch"}
    assert workflow["permissions"] == {"contents": "read"}
    assert "secrets." not in text
    assert set(re.findall(r"\$\{\{\s*github\.(\w+)", text)) <= {
        "sha", "repository", "server_url", "run_id", "token"}
    # The summary may tell the operator what to run; the workflow never signs.
    assert "private-key" not in text and "python3 deploy/site/sign_candidate.py" not in text
    assert workflow["concurrency"]["cancel-in-progress"] is False


def test_build_job_is_read_only_and_release_job_alone_can_write():
    jobs = _workflow()["jobs"]
    build = jobs["build-unsigned-candidate"]
    release = jobs["publish-unsigned-prerelease"]

    assert set(jobs) == {"build-unsigned-candidate", "publish-unsigned-prerelease"}
    assert build["runs-on"] == "ubuntu-24.04"
    # Read-only for the repository; OIDC + attestations only for provenance.
    assert build["permissions"] == {
        "contents": "read", "id-token": "write", "attestations": "write"}
    assert release["permissions"] == {"contents": "write"}
    assert release["needs"] == "build-unsigned-candidate"
    assert all(job["timeout-minutes"] <= 120 for job in jobs.values())
    assert not any("GH_TOKEN" in step.get("env", {}) for step in build["steps"])
    checkout = build["steps"][0]
    assert checkout["uses"].startswith("actions/checkout@")
    assert checkout["with"]["persist-credentials"] is False


def test_build_job_uses_checksum_pinned_syft_and_the_guarded_builder():
    build = _workflow()["jobs"]["build-unsigned-candidate"]
    run = _run_text(build)

    assert re.fullmatch(r"\d+\.\d+\.\d+", build["env"]["SYFT_VERSION"])
    assert re.fullmatch(r"[0-9a-f]{64}", build["env"]["SYFT_SHA256"])
    assert "sha256sum --check --strict" in run
    assert "--proto '=https'" in run
    assert "deploy/site/build_candidate.py" in run
    assert "--sbom-tool syft" in run
    assert 'test -z "$(git status --porcelain --untracked-files=all)"' in run
    assert "[[ \"$commit\" =~ ^[0-9a-f]{40}$ ]]" in run
    assert 'git merge-base --is-ancestor "$commit" "$GITHUB_SHA"' in run


def test_candidate_is_split_below_the_release_asset_limit_with_checksums():
    jobs = _workflow()["jobs"]
    run = _run_text(jobs["build-unsigned-candidate"])
    size = re.search(r"split --bytes=(\d+)M", run)

    assert size and int(size.group(1)) * 1024 * 1024 < 2 * 1024 ** 3
    assert "rosy-site-candidate-$COMMIT.tar.part" in run
    assert 'cp "$CANDIDATE_ROOT/$COMMIT/release.json" "$UPLOAD_DIR/release.json"' in run
    assert ">SHA256SUMS" in run
    assert "sha256sum --check --strict SHA256SUMS" in _run_text(jobs["publish-unsigned-prerelease"])


def test_release_job_creates_an_unsigned_prerelease_at_the_built_commit():
    release = _workflow()["jobs"]["publish-unsigned-prerelease"]
    run = _run_text(release)

    assert "gh release create \"$TAG\"" in run
    assert "--prerelease" in run
    assert "--latest" not in run
    assert '--target "$COMMIT"' in run
    assert "UNSIGNED until release.json.sig is attached" in run
    assert "test ! -e release.json.sig" in run
    assert "[[ \"$TAG\" == \"site-${COMMIT:0:12}\" ]]" in run


def test_runbook_signs_manifest_only_and_fetches_before_verified_load():
    readme = (ROOT / "deploy" / "site" / "README.md").read_text(encoding="utf-8")
    section = readme[readme.index("### CI-built candidates (D-437)"):]

    assert "gh workflow run build-site-candidate.yml" in section
    assert section.index("--manifest-only") < section.index("gh release upload") < section.index(
        "fetch_candidate.sh")
    assert "--expected-commit <commit>" in section
    assert "--pattern release.json" in section


def test_build_job_publishes_manifest_hash_and_provenance_for_the_signer():
    build = _workflow()["jobs"]["build-unsigned-candidate"]
    run = _run_text(build)
    attest = next(step for step in build["steps"]
                  if step.get("uses", "").startswith("actions/attest-build-provenance@"))

    assert 'sha256sum "$UPLOAD_DIR/release.json"' in run
    assert '>>"$GITHUB_STEP_SUMMARY"' in run
    assert "::notice title=release.json SHA-256::" in run
    assert "--expected-manifest-sha256" in run
    assert attest["with"]["subject-path"].split() == [
        "/mnt/rosy-site-upload/release.json", "/mnt/rosy-site-upload/SHA256SUMS"]
    names = [step.get("name", "") for step in build["steps"]]
    assert names.index("Package candidate into release-sized parts") < names.index(
        attest["name"])
