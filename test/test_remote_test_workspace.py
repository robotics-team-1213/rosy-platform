"""The writer's scratch marker is consumable by the existing host storage timer."""

import io
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tarfile
import time

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools/remote"))
import prepare_test_workspace as workspace


def install_capability(home):
    maintenance = home / "rosy-test/maintenance"
    maintenance.mkdir(parents=True)
    (maintenance / "host_storage.py").write_text("TEST_WORKSPACE_RETENTION = 1\n")


@pytest.mark.parametrize("source", [False, True])
@pytest.mark.skipif(sys.platform == "win32" or not shutil.which("bash"), reason="requires lab bash and GNU tar")
def test_private_workspace_is_marked_before_use_and_preserves_only_the_archive(tmp_path, source):
    install_capability(tmp_path)
    data = io.BytesIO()
    if source:
        with tarfile.open(fileobj=data, mode="w") as archive:
            entry = tarfile.TarInfo("test_fixture.py")
            entry.size = 7
            archive.addfile(entry, io.BytesIO(b"fixture"))
    hours = workspace.SOURCE_HOURS if source else workspace.TEMP_HOURS
    started = int(time.time())
    result = subprocess.run(
        ["bash", "-c", workspace.CREATE, "remote", "sample", str(hours * 3600),
         workspace.metadata("owner", "test fixture"), "source" if source else "temp"],
        input=data.getvalue(), capture_output=True, env={**os.environ, "HOME": str(tmp_path)}, check=True,
    )
    receipt = workspace.receipt("lab", result.stdout)
    path = Path(receipt["path"])
    marker = json.loads((path / ".rosy-retention.json").read_text())
    assert path.parent == tmp_path / "rosy-test/studies"
    assert path.stat().st_mode & 0o777 == 0o700
    assert marker == {"schema": "rosy.test-workspace-retention/1", "owner": "owner", "reason": "test fixture",
                      "expires": receipt["expires"]}
    assert started + hours * 3600 <= marker["expires"] <= int(time.time()) + hours * 3600
    assert (path / "src").exists() == source
    if source:
        assert (path / "src/test_fixture.py").read_bytes() == b"fixture"


@pytest.mark.skipif(sys.platform == "win32" or not shutil.which("bash"), reason="requires lab bash and GNU tar")
def test_failed_transfer_still_expires_and_linked_root_is_refused(tmp_path):
    install_capability(tmp_path)
    args = ["bash", "-c", workspace.CREATE, "remote", "failed", "259200",
            workspace.metadata("owner", "failed transfer"), "source"]
    result = subprocess.run(args, env={**os.environ, "HOME": str(tmp_path)}, input=b"broken", capture_output=True)
    assert result.returncode and b"ROSYWORKSPACE" not in result.stdout
    [path] = list((tmp_path / "rosy-test/studies").iterdir())
    assert json.loads((path / ".rosy-retention.json").read_text())["expires"] >= int(time.time())
    home = tmp_path / "linked"
    home.mkdir()
    (home / "rosy-test").symlink_to(tmp_path / "rosy-test", target_is_directory=True)
    result = subprocess.run(args, env={**os.environ, "HOME": str(home)}, input=b"", capture_output=True)
    assert result.returncode and list((tmp_path / "rosy-test/studies").iterdir()) == [path]


@pytest.mark.skipif(sys.platform == "win32" or not shutil.which("bash"), reason="requires lab bash")
def test_old_storage_checker_refuses_before_creating_a_study(tmp_path):
    install_capability(tmp_path)
    (tmp_path / "rosy-test/maintenance/host_storage.py").write_text("TEST_WORKSPACE_RETENTION = 0\n")
    result = subprocess.run(
        ["bash", "-c", workspace.CREATE, "remote", "blocked", "172800",
         workspace.metadata("owner", "old checker"), "temp"],
        input=b"", capture_output=True, env={**os.environ, "HOME": str(tmp_path)},
    )
    assert result.returncode and b"retention support is not deployed" in result.stderr
    assert not (tmp_path / "rosy-test/studies").exists()


@pytest.mark.skipif(sys.platform == "win32" or not shutil.which("bash"), reason="requires lab bash and GNU tar")
def test_source_workspace_streams_the_commit_and_ignores_checkout_changes(tmp_path, monkeypatch):
    home = tmp_path / "host"
    install_capability(home)
    repo = tmp_path / "repo"
    repo.mkdir()
    tracked = repo / "test_fixture.py"
    tracked.write_text("committed")
    workspace.rp.git(repo, "init", "-q")
    workspace.rp.git(repo, "add", "test_fixture.py")
    workspace.rp.git(repo, "-c", "user.name=Fixture", "-c", "user.email=fixture@localhost",
                     "-c", "commit.gpgsign=false", "commit", "-qm", "fixture")
    commit = workspace.rp.git(repo, "rev-parse", "HEAD")
    tracked.write_text("worktree edit")
    (repo / "only-in-worktree").write_text("not committed")

    def local_step(argv, **options):
        assert argv[-2] == "lab"
        return subprocess.run(["bash", "-c", argv[-1]], env={**os.environ, "HOME": str(home)}, **options)

    monkeypatch.setattr(workspace.rp, "capped", lambda host: "")
    monkeypatch.setattr(workspace.remote_job, "step", local_step)
    result = workspace.prepare("lab", repo, "pinned", "owner", "one revision", commit)
    path = Path(result["path"])
    marker = json.loads((path / ".rosy-retention.json").read_text())
    assert marker["source_sha"] == commit
    assert (path / "src/test_fixture.py").read_text() == "committed"
    assert not (path / "src/only-in-worktree").exists()


def test_rejects_a_marker_too_large_for_the_cleaner_before_ssh(monkeypatch):
    monkeypatch.setattr(workspace, "choose_host", lambda _: pytest.fail("must not contact a host"))
    with pytest.raises(SystemExit, match="2"):
        workspace.main(["probe", "--owner", "owner", "--reason", "x" * 66000])


def test_scratch_never_selects_an_unconfigured_or_site_host(monkeypatch):
    monkeypatch.setattr(workspace.lab_hosts, "test_hosts", lambda: ["model", "site", "tagged-site"])
    monkeypatch.setattr(workspace.lab_hosts, "site_host", lambda: "site")
    monkeypatch.setattr(workspace.rp, "SITES", {"site"})

    def placed(kind, hosts):
        assert (kind, hosts) == ("pytest", ["model", "tagged-site"])
        workspace.rp.SITES.add("tagged-site")
        return ["tagged-site", "model"]

    monkeypatch.setattr(workspace.rp, "placed_hosts", placed)
    assert workspace.choose_host(None) == "model"
    with pytest.raises(SystemExit, match="configured"):
        workspace.choose_host("unknown")
