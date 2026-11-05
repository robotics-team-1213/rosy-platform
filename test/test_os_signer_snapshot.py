"""The installed signer, not incoming main, owns the OS tools archive."""
import hashlib
import json
from pathlib import Path
import re
import shutil
import subprocess
import sys

import pytest

ROOT = Path(__file__).resolve().parents[1]


def test_installer_snapshot_contains_the_os_import_closure(tmp_path):
    installer = (ROOT / "tools/release/install_robot_cd.ps1").read_text(encoding="utf-8")
    files = re.findall(r'^    "([^"]+)"', installer, re.MULTILINE)
    assert "tools/release/source_inventory.py" in files
    files += [str(path.relative_to(ROOT)).replace("\\", "/") for path in
              (ROOT / "deploy/robot/pinky_pro/release/public-keys").glob("*.pem")]
    for name in files:
        destination = tmp_path / name
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(ROOT / name, destination)
    result = subprocess.run([sys.executable, "-I", "-c",
        "import sys;sys.path.insert(0,'.');import tools.release.prepare_os_release;import tools.release.robot_cd_os"],
        cwd=tmp_path, capture_output=True, text=True, timeout=30)
    assert result.returncode == 0, result.stderr


def test_snapshot_archive_uses_installed_revision_even_when_repository_head_moves(tmp_path, monkeypatch):
    from tools.release import prepare_os_release as prepare
    source, snapshot = tmp_path / "repo", tmp_path / "snapshot"
    source.mkdir()
    snapshot.mkdir()

    def git(*args):
        return subprocess.run(["git", "-C", str(source), "-c", "user.name=test", "-c", "user.email=test@example.invalid", *args],
                              check=True, capture_output=True).stdout.decode().strip()

    git("init", "-q")
    (source / "reviewed.py").write_bytes(b"reviewed\n")
    git("add", "reviewed.py")
    git("commit", "-qm", "reviewed snapshot")
    approved = git("rev-parse", "HEAD")
    (snapshot / "reviewed.py").write_bytes(b"reviewed\r\n")
    (snapshot / "trusted-snapshot.json").write_text(json.dumps(dict(source_revision=approved,
        files={"reviewed.py": hashlib.sha256(b"reviewed\r\n").hexdigest()})))
    (source / "reviewed.py").write_bytes(b"incoming unapproved code\n")
    git("commit", "-qam", "new main")
    candidate = git("rev-parse", "HEAD")
    monkeypatch.setattr(prepare, "ROOT", snapshot)
    assert prepare._snapshot_tools_source(source, approved) == (source.resolve(), approved)
    with pytest.raises(ValueError, match="installed trusted snapshot"):
        prepare._snapshot_tools_source(source, candidate)
    # A newly edited installed file cannot be excused by pointing at old Git.
    (snapshot / "reviewed.py").write_text("tampered")
    with pytest.raises(ValueError, match="trusted signer installation changed"):
        prepare._snapshot_tools_source(source, approved)
