"""Engineering OS publication phases for the existing, locked robot CD coordinator.

No SSH, device acceptance, production BUILD_GO or rollout promotion lives here.
An empty signed canary list keeps the published candidate ineligible everywhere.
"""
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import uuid

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
WORKFLOW = "build-pinky-image.yml"
REPO = "robotics-team-1213/rosy-platform"


def approved_image_run(run, *, sha, ref, repo_id, workflow_id):
    return (run.get("head_sha") == sha and run.get("head_branch") == ref
            and run.get("event") == "workflow_dispatch" and run.get("workflow_id") == workflow_id
            and run.get("status") == "completed" and run.get("conclusion") == "success"
            and run.get("repository", {}).get("id") == repo_id
            and run.get("head_repository", {}).get("id") == repo_id
            and type(run.get("id")) is int and run["id"] > 0
            and type(run.get("run_attempt")) is int and run["run_attempt"] > 0)


def _identity(c, run):
    return (isinstance(run, dict)
        and (not c.state.get("build_run") or run.get("id") == c.state["build_run"])
        and (not c.state.get("os_run_attempt") or run.get("run_attempt") == c.state["os_run_attempt"])
        and approved_image_run(dict(run, status="completed", conclusion="success"),
        sha=c.state["sha"], ref=c.state["os_build_ref"], repo_id=c.config["repo_id"],
        workflow_id=c.state["os_workflow_id"]))


def _artifact(c):
    state = c.state
    listed = c.api(f"actions/runs/{state['build_run']}/artifacts?per_page=100")
    rows = listed.get("artifacts")
    if not isinstance(rows, list) or listed.get("total_count") != len(rows) or len(rows) > 100:
        raise ValueError("OS build artifact inventory is incomplete")
    name = f"rosy-pinky-image-unsigned-{state['release_id']}-{state['sha']}"
    found = [row for row in rows if row.get("name") == name]
    if len(found) != 1:
        raise ValueError("OS build must have exactly one source-bound unsigned artifact")
    item = found[0]
    bound = item.get("workflow_run", {})
    if (type(item.get("id")) is not int or item["id"] <= 0 or item.get("expired") is not False
            or type(item.get("size_in_bytes")) is not int or not 0 < item["size_in_bytes"] <= 32 * 1024**3
            or not isinstance(item.get("digest"), str) or not re.fullmatch(r"sha256:[0-9a-f]{64}", item["digest"])
            or bound.get("id") != state["build_run"] or bound.get("head_sha") != state["sha"]
            or bound.get("head_branch") != state["os_build_ref"]
            or bound.get("repository_id") != c.config["repo_id"]
            or bound.get("head_repository_id") != c.config["repo_id"]):
        raise ValueError("OS artifact identity, digest or source differs")
    return {key: item[key] for key in ("id", "name", "size_in_bytes", "digest")}


def _unsigned_identity(dist, release_id, sha):
    """Check candidate identity before allowing either local private key to sign."""
    from os_state_layout import _pairs
    from tools.release.publish_os_release import _plain
    records = {}
    for name in ("manifest.json", "build-provenance.json", "os-bundle-inputs/inputs.json"):
        path = dist / name
        for parent in path.parents:
            if parent == dist:
                break
            _plain(parent, directory=True)
        if not 0 < _plain(path).st_size <= 65536:
            raise ValueError("unsigned OS identity record exceeds its bound")
        records[name] = json.loads(path.read_bytes(), object_pairs_hook=_pairs)
    manifest, provenance, inputs = records.values()
    if (manifest.get("schema_version") != 2 or manifest.get("release_id") != release_id
            or manifest.get("product") != "rosy-os" or manifest.get("board") != "pinky_pro"
            or manifest.get("architecture") != "arm64" or provenance.get("source_revision") != sha
            or provenance.get("architecture") != "aarch64" or inputs.get("release_id") != release_id
            or inputs.get("source_revision") != sha or inputs.get("boot_abi") != 2):
        raise ValueError("unsigned OS image differs from the approved build source")


def _prepare(c):
    import download_artifact as download
    from tools.release import prepare_os_release as prepare
    from tools.release.publish_os_release import publish
    from sign_image_release import sign_image_release
    from robot_cd import ROOT
    state = c.state
    release_id, sha = state["release_id"], state["sha"]
    base = c.folder / ("os-" + release_id)
    base.mkdir(exist_ok=True)
    public = ROOT / "deploy/robot/pinky_pro/release/public-keys" / (c.config["key_name"] + ".pem")
    output = base / "signed"
    # The preparer exposes this directory atomically after its independent guest
    # verification. A killed tick can resume it without signing a second bundle.
    if output.exists():
        publish(output, public, release_id=release_id, source_revision=sha, publication_only=True)
        return output, public
    current = _artifact(c)
    if current != state["os_artifact"]:
        raise ValueError("OS artifact changed after build acceptance")
    archive = base / "unsigned.zip"
    github = download.GitHub("https://api.github.com", c.repo, download.github_token())
    artifact = github.artifact(current["id"], None, None)
    if any(artifact.get(key) != value for key, value in current.items()):
        raise ValueError("OS download identity differs from the accepted artifact")
    if not archive.exists():
        # The downloader's existing range journal survives a timeout; the next
        # tick resumes it. Its bounded child does not own transaction state.
        try:
            subprocess.run([sys.executable, "-B", str(Path(download.__file__)), "--repo", c.repo,
                "--artifact-id", str(current["id"]), "--out", str(archive)], check=True, timeout=3600)
        except (subprocess.SubprocessError, OSError):
            raise ValueError("OS artifact download incomplete; resume the same transaction") from None
    download.check_archive(archive, current["size_in_bytes"])
    digest = hashlib.sha256()
    with archive.open("rb") as stream:
        while raw := stream.read(8 * 1024**2):
            digest.update(raw)
    if "sha256:" + digest.hexdigest() != current["digest"]:
        raise ValueError("OS archive digest differs from its accepted Actions artifact")
    attempt = state.get("os_attempt", 0) + 1
    if attempt > 3:
        raise ValueError("OS preparation interrupted three times; preserved attempts require review")
    c.save(os_attempt=attempt)
    dist = base / f"attempt-{attempt}"
    if dist.exists():
        raise ValueError("OS attempt directory already exists; refusing mutable input reuse")
    download.safe_extract(archive, dist)
    _unsigned_identity(dist, release_id, sha)
    private = Path(os.environ["LOCALAPPDATA"]) / "Rosy/signing" / (c.config["key_name"] + ".private.pem")
    sign_image_release(dist, private, public)
    manifest = json.loads((ROOT / "trusted-snapshot.json").read_text(encoding="utf-8"))
    prepare.prepare_release("pinky_pro", dist, output, private, public, Path(c.config["os_cms_private_key"]),
        release_id=release_id, source_revision=sha, canary=[],
        tools_source=(Path(c.config["source_repository"]), manifest["source_revision"]), stage_timeout=3600)
    publish(output, public, release_id=release_id, source_revision=sha, publication_only=True)
    return output, public


def advance(c, sha, ci, reason=None):
    """Advance one durable OS transaction; build observation never waits for CI."""
    from robot_cd import dispatch_expired, next_release_id
    from tools.release.publish_os_release import publish
    if c.repo != REPO or c.config.get("os_engineering") is not True:
        raise ValueError("engineering OS publication requires explicit opt-in for the reviewed repository")
    if ci != "success":
        if ci == "failed":
            c.save(sha=sha, phase="failed", reason="OS source main CI failed")
            return c.audit("ci_failed")
        return c.audit("waiting_os_ci")
    if not c.state.get("phase", "").startswith("os_"):
        refs = c.api("git/matching-refs/tags/payload-")
        names = [row["ref"].removeprefix("refs/tags/") for row in refs]
        # Reservation refs share the payload allocator, so both channels consume
        # one monotonic sequence without contacting any robot.
        names += [row["ref"].removeprefix("refs/tags/os-pinky-pro-")
                  for row in c.api("git/matching-refs/tags/os-pinky-pro-")]
        release_id = next_release_id(datetime.now(timezone.utc).strftime("%Y.%m.%d"), names)
        workflow = c.api("actions/workflows/" + WORKFLOW)
        if type(workflow.get("id")) is not int or workflow["id"] <= 0:
            raise ValueError("OS build workflow has no numeric identity")
        baseline = {key: c.state[key] for key in ("deployed_sha", "delivery_base_sha", "payload_tarball", "os_published_sha")
                    if key in c.state}
        if c.state:
            c.audit("previous_transaction")
        c.state = {}
        c.save(sha=sha, release_id=release_id, phase="os_reserving", delivery_policy="os-image", reason=reason,
               os_build_ref="payload-reserved-" + release_id, os_workflow_id=workflow["id"],
               os_publication={"nonce": uuid.uuid4().hex}, **baseline)
    state = c.state
    if state["phase"] == "os_reserving":
        refs = c.api("git/matching-refs/tags/" + state["os_build_ref"])
        exact = [row for row in refs if row.get("ref") == "refs/tags/" + state["os_build_ref"]]
        if exact:
            # A lost POST acknowledgement and another signer winning this ID
            # are indistinguishable. Never adopt even a matching source ref;
            # that could dispatch the same build from two signing PCs.
            raise ValueError("OS reservation has no durable receipt; review before dispatch")
        else:
            c.gh("api", "--method", "POST", f"repos/{c.repo}/git/refs", "-f",
                 "ref=refs/tags/" + state["os_build_ref"], "-f", "sha=" + sha)
        c.save(phase="os_dispatching", dispatched_at=datetime.now(timezone.utc).isoformat())
        c.gh("workflow", "run", WORKFLOW, "--repo", c.repo, "--ref", state["os_build_ref"],
             "-f", "release_id=" + state["release_id"])
        c.save(phase="os_building")
        return c.audit("os_build_dispatched")
    if state["phase"] in ("os_dispatching", "os_building"):
        if state.get("build_run"):
            run = c.api(f"actions/runs/{state['build_run']}")
        else:
            result = c.api(f"actions/workflows/{WORKFLOW}/runs?branch={state['os_build_ref']}&event=workflow_dispatch&per_page=100")
            rows = result.get("workflow_runs")
            if not isinstance(rows, list) or result.get("total_count") != len(rows):
                raise ValueError("OS build run inventory is incomplete")
            if not rows:
                if dispatch_expired(state["dispatched_at"]):
                    raise ValueError("OS dispatch not registered; review without redispatching")
                return c.audit("waiting_os_build_registration")
            if len(rows) != 1:
                raise ValueError("duplicate OS build identity")
            run = rows[0]
        if not _identity(c, run):
            raise ValueError("OS build source, repository, workflow or ref differs")
        c.save(build_run=run["id"], os_run_attempt=run["run_attempt"])
        if run.get("status") != "completed":
            return c.audit("waiting_os_build")
        if not approved_image_run(run, sha=sha, ref=state["os_build_ref"], repo_id=c.config["repo_id"], workflow_id=state["os_workflow_id"]):
            c.save(phase="failed", reason="OS unsigned image build failed")
            return c.audit("os_build_failed")
        c.save(os_artifact=_artifact(c), phase="os_preparing")
        return c.audit("os_build_verified")
    if state["phase"] == "os_preparing":
        run = c.api(f"actions/runs/{state['build_run']}")
        if not _identity(c, run) or not approved_image_run(run, sha=sha, ref=state["os_build_ref"], repo_id=c.config["repo_id"], workflow_id=state["os_workflow_id"]):
            raise ValueError("accepted OS build changed before signing")
        output, public = _prepare(c)
        c.save(phase="os_publishing", os_output=str(output), os_public_key=str(public))
        return c.audit("os_prepared")
    if state["phase"] == "os_publishing":
        result = publish(Path(state["os_output"]), Path(state["os_public_key"]), release_id=state["release_id"],
            source_revision=sha, apply=True, publication_only=True, transaction=state["os_publication"],
            journal=lambda transaction: c.save(os_publication=transaction))
        c.save(phase="done", os_published_sha=sha, os_publication_result=result,
               reason="engineering OS prerelease verified; empty rollout authorizes no device")
        return c.audit("os_published")
    raise ValueError("unknown OS publication phase")
