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

    assert set(jobs) == {"check-release-free", "build-unsigned-candidate",
                         "attest-provenance", "publish-unsigned-prerelease"}
    assert jobs["check-release-free"]["permissions"] == {"contents": "read"}
    assert build["runs-on"] == "ubuntu-24.04"
    assert build["permissions"] == {"contents": "read"}
    assert release["permissions"] == {"contents": "write"}
    assert release["needs"] == ["build-unsigned-candidate", "attest-provenance"]
    assert all(job["timeout-minutes"] <= 120 for job in jobs.values())
    assert not any("GH_TOKEN" in step.get("env", {}) for step in build["steps"])
    assert build["needs"] == "check-release-free"
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
    jobs = _workflow()["jobs"]
    build = jobs["build-unsigned-candidate"]
    run = _run_text(build)

    assert 'sha256sum "$UPLOAD_DIR/release.json"' in run
    assert '>>"$GITHUB_STEP_SUMMARY"' in run
    assert "::notice title=release.json SHA-256::" in run
    assert "--expected-manifest-sha256" in run

    # Provenance lives in its own job: the only one with OIDC/attestation write.
    writers = {name for name, job in jobs.items()
               if {"id-token", "attestations"} & set(job["permissions"])}
    assert writers == {"attest-provenance"}
    attest_job = jobs["attest-provenance"]
    assert attest_job["permissions"] == {
        "contents": "read", "id-token": "write", "attestations": "write"}
    assert attest_job["needs"] == "build-unsigned-candidate"
    assert not any("run" in step and "build_candidate" in step["run"]
                   for step in attest_job["steps"])
    attest = next(step for step in attest_job["steps"]
                  if step.get("uses", "").startswith("actions/attest-build-provenance@"))
    assert attest["with"]["subject-path"].split() == [
        "provenance-subjects/release.json", "provenance-subjects/SHA256SUMS"]
    download = attest_job["steps"][0]
    assert download["uses"].startswith("actions/download-artifact@")
    assert download["with"]["name"].startswith("rosy-site-candidate-manifest-")
    assert not any(step.get("uses", "").startswith("actions/attest-build-provenance@")
                   for step in build["steps"])


def test_release_job_prunes_only_older_site_releases_after_creating_the_new_one():
    release = _workflow()["jobs"]["publish-unsigned-prerelease"]
    names = [step.get("name", "") for step in release["steps"]]
    prune = next(step for step in release["steps"] if step.get("name", "").startswith("Prune"))
    run = prune["run"]

    assert names.index("Create unsigned prerelease") < names.index(prune["name"])
    assert "test(\"^site-[0-9a-f]{12}$\")" in run  # jq selection
    assert "[[ \"$old\" =~ ^site-[0-9a-f]{12}$ ]]" in run  # per-tag guard
    assert ".[3:]" in run and "sort_by(.createdAt) | reverse" in run
    assert 'gh release delete "$old" --cleanup-tag --yes' in run
    assert '[[ "$old" != "$TAG" ]]' in run
    assert "payload" not in run.replace("payload-*", "")


def test_every_action_is_pinned_to_a_full_commit_sha():
    uses = [step["uses"] for job in _workflow()["jobs"].values()
            for step in job["steps"] if "uses" in step]
    text = WORKFLOW.read_text(encoding="utf-8")

    assert len(uses) == 7
    for ref in uses:
        assert re.fullmatch(r"[\w.-]+/[\w.-]+@[0-9a-f]{40}", ref), ref
        assert re.search(re.escape(ref) + r" # v\d+\.\d+\.\d+\n", text), ref


def test_pre_job_fails_fast_when_the_site_release_exists():
    jobs = _workflow()["jobs"]
    check = jobs["check-release-free"]
    run = _run_text(check)
    build_run = _run_text(jobs["build-unsigned-candidate"])

    assert check["timeout-minutes"] <= 15
    assert 'gh api "repos/${GH_REPO}/releases/tags/${tag}"' in run
    assert 'grep -q "HTTP 404"' in run
    assert "already exists" in run
    assert 'test "$commit" = "$CHECKED_COMMIT"' in build_run


def test_tool_output_cannot_issue_workflow_commands_before_the_hash_is_published():
    steps = _workflow()["jobs"]["build-unsigned-candidate"]["steps"]
    by_name = {step.get("name"): step for step in steps}
    names = [step.get("name") for step in steps]
    tool_steps = ("Check Docker Buildx keeps images in the local store", "Install pinned syft",
                  "Build unsigned candidate", "Package candidate into release-sized parts")
    markers = {"Install pinned syft": "sha256sum --check --strict",
               "Build unsigned candidate": "deploy/site/build_candidate.py",
               "Package candidate into release-sized parts": "docker system prune",
               "Check Docker Buildx keeps images in the local store": "docker buildx inspect"}

    for name in tool_steps:
        run = by_name[name]["run"]
        stop = run.index('echo "::stop-commands::${token}"')
        resume = run.rindex('echo "::${token}::"')
        assert 'token="$(openssl rand -hex 16)"' in run[:stop], name
        assert stop < run.index(markers[name]) < resume, name
        assert not run[resume:].strip().replace('echo "::${token}::"', ""), name

    hash_step = by_name["Publish the manifest hash for the signing station"]
    assert "stop-commands" not in hash_step["run"]
    assert max(names.index(name) for name in tool_steps) < names.index(hash_step["name"])
    readme = (ROOT / "deploy" / "site" / "README.md").read_text(encoding="utf-8")
    assert "job summary table" in readme
    assert "gh attestation verify" in readme and "--format json" in readme
