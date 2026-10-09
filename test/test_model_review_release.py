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
    assert b"current/learning/training/perception/dataset" in unit.read_bytes()
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
