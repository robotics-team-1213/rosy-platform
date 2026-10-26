"""Optional SD tooling must verify its own archive and keep default test envs intact."""
from __future__ import annotations

import hashlib
import importlib
import io
import json
from pathlib import Path
import sys
import tarfile

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools/remote"))
import remote_pytest as rp  # noqa: E402
import remote_job as rj  # noqa: E402
import remote_test_tools as recipes  # noqa: E402

PROFILE = "sd-writer"
PINS = "tools/remote/powershell-test-tool.json"
HELPER = "tools/remote/sd_test_tools.py"


def test_sd_profile_has_a_separate_committed_dependency_identity(monkeypatch):
    base = rp.deps(ROOT, "HEAD")
    selected = rp.deps(ROOT, "HEAD", test_tools=PROFILE)
    assert selected[0] != base[0] and selected[1] == base[1]
    original = rp.git
    for path in (PINS, HELPER):
        with monkeypatch.context() as patch:
            def changed(repo, *args):
                return "a" * 40 if args == ("rev-parse", f"HEAD:{path}") else original(repo, *args)
            patch.setattr(rp, "git", changed)
            assert rp.deps(ROOT, "HEAD", test_tools=PROFILE)[0] != selected[0]
            assert rp.deps(ROOT, "HEAD") == base


def test_sd_recipe_does_not_change_default_or_raw_recipes():
    assert recipes.render_setup(rp.VENV, None) == rp.VENV
    raw = recipes.render_job(rj.JOB, "pinky-raw")
    selected = recipes.render_job(rj.JOB, PROFILE)
    assert selected != raw and recipes.render_job(rj.JOB, None) == rj.JOB
    assert "sd-tools" in selected and "raw-tools" not in selected
    assert selected.index("test-tools context mismatch") < selected.index("shift 5")


def _archive(version="7.6.8", unsafe=False):
    buffer = io.BytesIO()
    body = ("#!/bin/sh\nprintf '%s\\n' '" + version + "'\n").encode()
    with tarfile.open(fileobj=buffer, mode="w:gz") as archive:
        entry = tarfile.TarInfo("../outside" if unsafe else "pwsh")
        entry.size, entry.mode = len(body), 0o755
        archive.addfile(entry, io.BytesIO(body))
    return buffer.getvalue()


def _case(tmp_path, monkeypatch, archive):
    tools = importlib.import_module("sd_test_tools")
    root = tmp_path / "new-profile"
    root.mkdir()
    default = tmp_path / "existing-default"
    default.mkdir()
    (default / "untouched").write_bytes(b"existing environment")
    pins = tmp_path / "pins.json"
    pins.write_text(json.dumps({
        "version": "7.6.8", "architecture": "x86_64", "size_bytes": len(archive),
        "url": "https://github.com/PowerShell/PowerShell/releases/download/v7.6.8/powershell-7.6.8-linux-x64.tar.gz",
        "sha256": hashlib.sha256(archive).hexdigest(),
    }), encoding="utf-8")
    monkeypatch.setattr(tools, "urlopen", lambda *args, **kwargs: io.BytesIO(archive))
    return tools, root, pins, default


@pytest.mark.skipif(sys.platform == "win32", reason="native Linux dependency fixture")
def test_install_runs_the_configured_tool_and_preserves_other_environments(tmp_path, monkeypatch):
    tools, root, pins, default = _case(tmp_path, monkeypatch, _archive())
    tools.install(root, pins)
    tools.ready(root, pins)
    assert (root / "sd-tools/powershell").resolve() == (root / "sd-tools/pwsh").resolve()
    assert (root / ".sd-pins").read_bytes() == pins.read_bytes()
    assert (default / "untouched").read_bytes() == b"existing environment"


@pytest.mark.skipif(sys.platform == "win32", reason="native Linux dependency fixture")
def test_bad_archive_hash_never_reaches_extraction_or_execution(tmp_path, monkeypatch):
    tools, root, pins, default = _case(tmp_path, monkeypatch, _archive())
    data = json.loads(pins.read_text())
    data["sha256"] = "0" * 64
    pins.write_text(json.dumps(data))
    with pytest.raises(ValueError, match="SHA256"):
        tools.install(root, pins)
    assert not (root / "sd-tools").exists()
    assert (default / "untouched").read_bytes() == b"existing environment"


@pytest.mark.skipif(sys.platform == "win32", reason="native Linux dependency fixture")
def test_matching_digest_does_not_allow_archive_path_escape(tmp_path, monkeypatch):
    tools, root, pins, default = _case(tmp_path, monkeypatch, _archive(unsafe=True))
    with pytest.raises(ValueError, match="archive"):
        tools.install(root, pins)
    assert not (tmp_path / "outside").exists()
    assert not (root / "outside").exists()
    assert (default / "untouched").read_bytes() == b"existing environment"


@pytest.mark.skipif(sys.platform == "win32", reason="native Linux dependency fixture")
def test_successful_process_with_wrong_version_is_not_ready(tmp_path, monkeypatch):
    tools, root, pins, _ = _case(tmp_path, monkeypatch, _archive(version="7.5.0"))
    with pytest.raises(ValueError, match="version"):
        tools.install(root, pins)


@pytest.mark.skipif(sys.platform == "win32", reason="native Linux dependency fixture")
@pytest.mark.parametrize("escaped", ["pwsh", "powershell"])
def test_readiness_rejects_a_tool_resolving_outside_its_profile(tmp_path, monkeypatch, escaped):
    tools, root, pins, _ = _case(tmp_path, monkeypatch, _archive())
    target = root / "sd-tools"
    target.mkdir()
    marker = tmp_path / "executed"
    outside = tmp_path / "outside-tool"
    outside.write_text(f"#!/bin/sh\ntouch '{marker}'\nprintf '7.6.8\\n'\n")
    outside.chmod(0o755)
    if escaped == "pwsh":
        (target / "pwsh").symlink_to(outside)
        (target / "powershell").symlink_to("pwsh")
    else:
        (target / "pwsh").write_text("#!/bin/sh\nprintf '7.6.8\\n'\n")
        (target / "pwsh").chmod(0o755)
        (target / "powershell").symlink_to(outside)
    (root / ".sd-pins").write_bytes(pins.read_bytes())
    with pytest.raises(ValueError, match="outside"):
        tools.ready(root, pins)
    assert not marker.exists()
