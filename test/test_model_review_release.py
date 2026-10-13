"""The Model PC code switch must never replace review state or strand its service."""

import importlib.util
import json
import os
import shutil
import sys
from pathlib import Path

import pytest


SCRIPT = Path(__file__).resolve().parents[1] / "deploy/model_pc/install_review_release.py"
SPEC = importlib.util.spec_from_file_location("install_review_release", SCRIPT)
release = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(release)


def source_tree(path):
    for name in (release.APP, release.WEB / "index.html", release.WEB / "pixels.html",
                 Path("shared/web/shared-assets.json")):
        file = path / name
        file.parent.mkdir(parents=True, exist_ok=True)
        file.write_text(name.as_posix(), encoding="utf-8")


@pytest.mark.skipif(os.name == "nt", reason="Windows account cannot create POSIX symlinks")
def test_install_preserves_state_and_failed_update_restores_service(tmp_path, monkeypatch):
    source = tmp_path / "source"
    source_tree(source)
    state = tmp_path / "state"
    state.mkdir()
    database = state / "reviews.sqlite3"
    database.write_bytes(b"existing-human-decisions")
    root = tmp_path / "releases-root"
    unit = tmp_path / "rosy-review-v13.service"
    unit.write_bytes(b"original service\n")
    monkeypatch.setattr(release.subprocess, "run", lambda *args, **kwargs: None)
    monkeypatch.setattr(release, "run_systemctl", lambda *args: None)
    monkeypatch.setattr(release, "check_live", lambda *args: None)

    first = release.install(source, "first", root, state, Path(sys.executable),
                            "127.0.0.1", 8774, unit)
    assert (root / "current").resolve() == first
    assert database.read_bytes() == b"existing-human-decisions"
    assert json.loads((first / "REVIEW_RELEASE.json").read_text())["source_sha256"]
    assert b"current/learning/curation/perception" in unit.read_bytes()
    assert str(Path(sys.executable)).encode() in unit.read_bytes()
    assert (root / "rosy-review-v13.service.before-managed").read_bytes() == b"original service\n"

    second_source = tmp_path / "second-source"
    shutil.copytree(source, second_source)
    (second_source / release.WEB / "index.html").write_text("new UI", encoding="utf-8")
    working_unit = unit.read_bytes()

    def fail_live(*args):
        raise RuntimeError("HTTP check failed")

    monkeypatch.setattr(release, "check_live", fail_live)
    with pytest.raises(RuntimeError, match="HTTP check failed"):
        release.install(second_source, "second", root, state, Path(sys.executable),
                        "127.0.0.1", 8774, unit)
    assert (root / "current").resolve() == first
    assert unit.read_bytes() == working_unit
    assert database.read_bytes() == b"existing-human-decisions"


def test_refuses_state_inside_release_source(tmp_path):
    source = tmp_path / "source"
    source_tree(source)
    with pytest.raises(ValueError, match="separate"):
        release.check_source(source, tmp_path / "root", source / "state")


def test_split_source_requires_drive_closure_and_hashes_it(tmp_path):
    source = tmp_path / "source"
    source_tree(source)
    helper = source / "middleware/perception/control/_source_layout.py"
    helper.parent.mkdir(parents=True)
    helper.write_text("pass\n")
    with pytest.raises(ValueError, match="missing"):
        release.check_source(source, tmp_path / "root", tmp_path / "state")
    for name in release.SPLIT_REQUIRED:
        path = source / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b"source\n")
    release.check_source(source, tmp_path / "root", tmp_path / "state")
    before = release.digest_tree(source)
    (source / "middleware/drive/safety/command_gate.py").write_bytes(b"changed\n")
    assert release.digest_tree(source) != before


@pytest.mark.skipif(os.name == "nt", reason="Linux managed review release symlinks")
def test_retained_legacy_release_reactivation_roundtrip_preserves_code_state_and_receipts(tmp_path, monkeypatch):
    source = tmp_path / "source"
    source_tree(source)
    state = tmp_path / "state"
    state.mkdir()
    database = state / "reviews.sqlite3"
    database.write_bytes(b"persistent human decisions")
    root = tmp_path / "root"
    unit = tmp_path / release.SERVICE
    unit.write_bytes(b"existing service\n")
    monkeypatch.setattr(release.subprocess, "run", lambda *a, **kw: None)
    monkeypatch.setattr(release, "run_systemctl", lambda *a: None)
    monkeypatch.setattr(release, "check_live", lambda *a: None)
    canonical = release.install(source, "canonical", root, state, Path(sys.executable),
                                "127.0.0.1", 8774, unit)
    # Only managed source fields may change: even exact holder prefixes in the
    # interpreter, state argument, other env tokens and unrelated unit text stay.
    interpreter = str(root / "current/tools/perception/python")
    state_argument = str(root / "current/learning/curation/perception-state")
    unrelated = str(tmp_path / (str(root / "current/tools/perception").lstrip("/")) / "other")
    text = unit.read_text().replace(str(Path(sys.executable)), interpreter).replace(str(state), state_argument)
    text += f"Environment=OTHER={unrelated}\nDescription={root / 'current/tools/perception'}\n"
    text = text.replace("Environment=PYTHONPATH=", f"Environment=PYTHONPATH={unrelated}:")
    unit.write_text(text)
    canonical_unit = unit.read_bytes()
    legacy = root / "releases" / "retained"
    old_app = legacy / release.LEGACY_APP
    old_app.parent.mkdir(parents=True)
    old_app.write_bytes(b"unchanged retained review implementation\n")
    (legacy / "REVIEW_RELEASE.json").write_bytes(b'{"source_sha256":"retained-original-digest"}\n')
    before = {file.relative_to(legacy): file.read_bytes() for file in legacy.rglob("*") if file.is_file()}
    release.install(None, "retained", root, None, None, "127.0.0.1", 8774, unit)
    assert (root / "current").resolve() == legacy
    assert f"WorkingDirectory={root / 'current' / release.LEGACY_APP.parent}\n" in unit.read_text()
    assert f"{root / 'current' / release.LEGACY_APP} --state {state_argument}" in unit.read_text()
    assert f"ExecStart={interpreter} " in unit.read_text()
    assert f"Environment=OTHER={unrelated}\nDescription={root / 'current/tools/perception'}\n" in unit.read_text()
    release.install(None, "canonical", root, None, None, "127.0.0.1", 8774, unit)
    assert (root / "current").resolve() == canonical
    assert unit.read_bytes() == canonical_unit
    assert {file.relative_to(legacy): file.read_bytes() for file in legacy.rglob("*") if file.is_file()} == before
    assert database.read_bytes() == b"persistent human decisions"


def test_generated_unit_uses_exact_canonical_runtime_holders(tmp_path):
    current = tmp_path / "current"
    text = release.unit_contents(current, tmp_path / "state", Path("/usr/bin/python3"), "127.0.0.1", 8774)
    path_line = next(line for line in text.splitlines() if line.startswith("Environment=PYTHONPATH="))
    paths = path_line.partition("=")[2].partition("=")[2].split(":")
    assert paths == [str(current / relative) for relative in (
        "middleware/perception", "contracts/foundation", "tools/perception",
        "learning/registry/perception", "learning/curation/perception", "learning/training/perception",
    )]
    assert len(paths) == len(set(paths))

@pytest.mark.parametrize("missing", [
    "middleware/perception/localization/loc_assist.py",
    "middleware/perception/graph_health/watch.py",
    "middleware/perception/snapshots/capture_trigger.py",
])
def test_functional_holder_cannot_be_omitted_from_review_source(tmp_path, missing):
    assert missing in release.SPLIT_REQUIRED
    source = tmp_path / "source"
    source_tree(source)
    for name in ("middleware/perception/control/_source_layout.py", *release.SPLIT_REQUIRED):
        path = source / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b"source\n")
    (source / missing).unlink()
    with pytest.raises(ValueError, match="missing"):
        release.check_source(source, tmp_path / "root", tmp_path / "state")

def test_generated_unit_can_opt_in_to_private_owner_controls(tmp_path):
    state = tmp_path / 'state'; state.mkdir()
    (state / 'learning-control.json').write_text('{}')
    text = release.unit_contents(tmp_path / 'current', state, Path('/usr/bin/python3'), '127.0.0.1', 8774)
    assert f'--learning-control {state / "learning-control.json"}' in text
