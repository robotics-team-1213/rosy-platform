"""D-625: exercise the mover on disposable registered worktrees only."""
import json
import os
from pathlib import Path
import subprocess
import sys

import pytest


SCRIPT = Path(__file__).resolve().parents[1] / "tools/harness/structure_move.py"
SOURCE = "middleware/core/navigation"
TARGET = "middleware/control/drive/planning/nav2"


def git(root, *args):
    return subprocess.check_output(["git", "-C", str(root), *args], text=True).strip()


@pytest.fixture
def repo(tmp_path):
    main = tmp_path / "product"
    main.mkdir()
    git(main, "init", "-b", "main")
    git(main, "config", "user.email", "test@example.invalid")
    git(main, "config", "user.name", "Migration test")
    folder = main / SOURCE
    folder.mkdir(parents=True)
    (folder / "module.py").write_bytes(b"# unchanged\r\n")
    (folder / "asset.bin").write_bytes(b"\0\xff\x01")
    (folder / "package.xml").write_text("<package><name>navigation</name></package>")
    (main / "consumer.py").write_text(f'PATH = "{SOURCE}/package.xml"\n')
    history = main / "docs/adr/history.md"
    history.parent.mkdir(parents=True)
    history.write_text(f"old record: {SOURCE}")
    manifest = main / "tools/harness/platform_parts.yaml"
    manifest.parent.mkdir(parents=True)
    manifest.write_text("roots: []\nsafety_modules: []\n")
    paths = [str(p.relative_to(main)) for p in main.rglob("*") if p.is_file() and ".git" not in p.parts]
    git(main, "add", "--", *paths)
    git(main, "commit", "-m", "fixture")
    work = main / ".worktrees/topic"
    git(main, "worktree", "add", "-b", "feat/move-test", str(work))
    return main, work


def run(root, *args):
    return subprocess.run([sys.executable, str(SCRIPT), "drive-nav2", *args], cwd=root,
                          capture_output=True, text=True)


def apply(work, head=None):
    return run(work, "--apply", "--expected-head", head or git(work, "rev-parse", "HEAD"))


def test_preview_reports_consumers_without_mutation(repo):
    _, work = repo
    before = git(work, "status", "--porcelain")
    result = run(work)
    assert result.returncode == 0, result.stderr
    data = json.loads(result.stdout)
    assert data["source"] == SOURCE and data["target"] == TARGET
    assert data["references_updated"] is False
    assert any(r["path"] == "consumer.py" for r in data["references"])
    assert not any(r["path"].startswith("docs/adr/") for r in data["references"])
    assert git(work, "status", "--porcelain") == before == ""
    assert (work / SOURCE).is_dir() and not (work / TARGET).exists()


def test_move_preserves_bytes_and_requires_followup_reference_edits(repo):
    _, work = repo
    before = {p.name: p.read_bytes() for p in (work / SOURCE).iterdir()}
    consumers = (work / "consumer.py").read_bytes()
    history = (work / "docs/adr/history.md").read_bytes()
    result = apply(work)
    assert result.returncode == 0, result.stderr
    assert json.loads(result.stdout)["state"] == "moved_needs_reference_edits"
    assert not (work / SOURCE).exists()
    assert {p.name: p.read_bytes() for p in (work / TARGET).iterdir()} == before
    assert (work / "consumer.py").read_bytes() == consumers
    assert (work / "docs/adr/history.md").read_bytes() == history
    assert not git(work, "diff", "--name-only")
    assert "consumer.py" not in git(work, "diff", "--cached", "--name-only")
    (work / SOURCE).parent.mkdir(parents=True, exist_ok=True)
    git(work, "mv", "--", TARGET, SOURCE)
    assert git(work, "status", "--porcelain") == ""


@pytest.mark.parametrize("kind", ["dirty", "staged", "untracked", "ignored", "collision", "stale", "safety", "safety_parent", "symlink"])
def test_rejection_leaves_files_and_index_untouched(repo, kind):
    _, work = repo
    head = git(work, "rev-parse", "HEAD")
    if kind in ("dirty", "staged"):
        (work / "consumer.py").write_text("changed")
        if kind == "staged":
            git(work, "add", "--", "consumer.py")
    elif kind == "untracked":
        (work / SOURCE / "private.txt").write_text("keep me")
    elif kind == "ignored":
        (work / ".gitignore").write_text("private.txt\n")
        git(work, "add", "--", ".gitignore")
        git(work, "commit", "-m", "ignore fixture")
        head = git(work, "rev-parse", "HEAD")
        (work / SOURCE / "private.txt").write_text("keep ignored file")
    elif kind == "collision":
        (work / TARGET).mkdir(parents=True)
    elif kind == "stale":
        head = "0" * 40
    elif kind in ("safety", "safety_parent"):
        text = (f"roots: []\nsafety_modules: [{SOURCE}/module.py]\n" if kind == "safety"
                else "roots: [{path: middleware/core, concern: safety}]\nsafety_modules: []\n")
        (work / "tools/harness/platform_parts.yaml").write_text(text)
        git(work, "add", "--", "tools/harness/platform_parts.yaml")
        git(work, "commit", "-m", "safety fixture")
        head = git(work, "rev-parse", "HEAD")
    elif kind == "symlink":
        if os.name == "nt":
            pytest.skip("Windows symlink privilege is not required by this fixture")
        (work / "external").mkdir()
        (work / "middleware/control").symlink_to(work / "external", target_is_directory=True)
    files = {str(p.relative_to(work)): p.read_bytes() for p in work.rglob("*") if p.is_file()}
    status = git(work, "status", "--porcelain")
    result = apply(work, head)
    assert result.returncode != 0
    reason = {"dirty": "not clean", "staged": "not clean", "untracked": "untracked/ignored",
              "ignored": "untracked/ignored", "collision": "target already exists", "stale": "stale HEAD",
              "safety": "Safety move", "safety_parent": "Safety move", "symlink": "linked path"}[kind]
    assert reason in result.stderr, result.stderr
    assert (work / SOURCE).is_dir()
    assert git(work, "status", "--porcelain") == status
    assert {str(p.relative_to(work)): p.read_bytes() for p in work.rglob("*") if p.is_file()} == files


def test_main_and_unregistered_location_refused(repo, tmp_path):
    main, _ = repo
    result = apply(main)
    assert result.returncode != 0 and "worktree" in result.stderr.lower()
    outside = tmp_path / "outside"
    git(main, "worktree", "add", "-b", "feat/outside", str(outside))
    result = apply(outside)
    assert result.returncode != 0 and "worktree" in result.stderr.lower()
    assert (outside / SOURCE).is_dir()


def test_apply_requires_reviewed_head(repo):
    _, work = repo
    result = run(work, "--apply")
    assert result.returncode != 0 and "expected-head" in result.stderr
    assert (work / SOURCE).is_dir()


def test_missing_manifest_fails_closed(repo):
    _, work = repo
    (work / "tools/harness/platform_parts.yaml").unlink()
    result = apply(work)
    assert result.returncode != 0 and "platform_parts.yaml missing" in result.stderr
    assert (work / SOURCE).is_dir()


def test_manifest_contains_only_whole_holder_moves():
    manifest = SCRIPT.with_name("platform_structure_moves.json")
    data = json.loads(manifest.read_text(encoding="utf-8"))
    behaviors = {'drive-behavior-' + name.replace('_', '-') for name in (
        'line_follow', 'docking', 'navigation', 'localization', 'swarm', 'road_behaviour', 'traffic_policy')}
    assert set(data["units"]) == {"core-api", "pinky-device", "omx-device", "drive-nav2"} | behaviors
    assert all(data['units'][name]['manual_safety'] for name in behaviors)
    for unit in data["units"].values():
        assert unit["source"].startswith("middleware/")
        assert unit["target"].startswith("middleware/")
        assert unit["consumers"] and unit["preserve"]


@pytest.mark.parametrize("path", ["../escape", "/absolute", "C:/outside", "middleware/../escape", ".git/objects", "middleware\\core", "middleware/core/"])
def test_path_boundary_validation(repo, path):
    # The same validation must also protect manifest changes, not just CLI choices.
    import importlib.util
    spec = importlib.util.spec_from_file_location("structure_move_under_test", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    with pytest.raises(ValueError):
        module.checked_path(repo[1], path)


def test_tracked_source_symlink_fails_closed(repo, tmp_path):
    if os.name == "nt":
        pytest.skip("Windows symlink privilege is not required by this fixture")
    _, work = repo
    outside = tmp_path / "private.txt"
    outside.write_text("outside data must stay outside")
    link = work / SOURCE / "link.txt"
    link.symlink_to(outside)
    git(work, "add", "--", f"{SOURCE}/link.txt")
    git(work, "commit", "-m", "linked source fixture")
    result = apply(work)
    assert result.returncode != 0 and "linked path" in result.stderr
    assert outside.read_text() == "outside data must stay outside"
    assert link.is_symlink() and git(work, "status", "--porcelain") == ""
