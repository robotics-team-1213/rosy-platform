"""Only an accepted signed code generation may drive the review release."""

import importlib.util
import json
import os
from pathlib import Path
import sys

import pytest


SCRIPT = Path(__file__).resolve().parents[1] / "deploy/model_pc/auto_review_release.py"
sys.path.insert(0, str(SCRIPT.parent))
spec = importlib.util.spec_from_file_location("auto_review_release", SCRIPT)
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)


@pytest.mark.skipif(os.name == "nt", reason="Windows account cannot create POSIX symlinks")
def test_new_generation_activates_and_recheck_is_idle(tmp_path, monkeypatch):
    root = tmp_path / "model"
    root.mkdir()
    (root / "work.lock").touch()
    commit = "a" * 40
    signed = root / "releases" / f"20-{commit}"
    for name in (module.APP, module.WEB / "index.html", module.WEB / "pixels.html",
                 Path("shared/web/shared-assets.json")):
        file = signed / name
        file.parent.mkdir(parents=True, exist_ok=True)
        file.write_text("signed")
    (signed / "data").symlink_to(tmp_path, target_is_directory=True)
    (root / "current").symlink_to(signed, target_is_directory=True)
    (root / "state.json").write_text(json.dumps({"sequence": 20, "source_commit": commit, "result": "idle"}))
    review = tmp_path / "review"
    seen = []

    def install(source, release, review_root, *_args):
        assert (source / module.APP).read_text() == "signed"
        assert not (source / "data").exists()
        seen.append(release)
        target = review_root / "releases" / release
        target.mkdir(parents=True)
        review_root.joinpath("current").symlink_to(target, target_is_directory=True)

    monkeypatch.setattr(module, "install", install)
    args = (root, review, tmp_path / "state", tmp_path / "python", "127.0.0.1", 8774, tmp_path / "unit", 19)
    assert module.apply(*args) == f"activated: model-code-20-{commit[:12]}"
    assert module.apply(*args) == f"already active: model-code-20-{commit[:12]}"
    assert seen == [f"model-code-20-{commit[:12]}"]


@pytest.mark.skipif(os.name == "nt", reason="Windows account cannot create POSIX symlinks")
def test_old_or_mismatched_generation_does_not_activate(tmp_path, monkeypatch):
    root = tmp_path / "model"
    root.mkdir()
    (root / "work.lock").touch()
    state = {"sequence": 19, "source_commit": "a" * 40, "result": "idle"}
    (root / "state.json").write_text(json.dumps(state))
    args = (root, tmp_path / "review", tmp_path / "state", tmp_path / "python",
            "127.0.0.1", 8774, tmp_path / "unit", 19)
    assert module.apply(*args).startswith("waiting")
    state["sequence"] = 20
    (root / "state.json").write_text(json.dumps(state))
    wrong = root / "releases" / ("20-" + "b" * 40)
    wrong.mkdir(parents=True)
    (root / "current").symlink_to(wrong, target_is_directory=True)
    with pytest.raises(ValueError, match="differs"):
        module.apply(*args)
