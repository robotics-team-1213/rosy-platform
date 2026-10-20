"""Each site CLI must start with only its own sys.path edits.

conftest.py adds middleware/perception and contracts/foundation for every
test, which masked the D-424 break (control imports core_common). These tests
run the CLIs in a subprocess with a clean PYTHONPATH instead.
"""
import os
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[3]
SOURCE_HOLDERS = ("learning/curation/perception", "learning/registry/perception",
                  "learning/training/perception", "learning/evaluation/perception", "tools/perception")
INTERNAL_MODULES = {file.stem for holder in SOURCE_HOLDERS for file in (ROOT / holder).glob("*.py")}
CLIS = [
    "learning/curation/perception/autolabel.py",
    "learning/curation/perception/build.py",
    "learning/curation/perception/edge_capture.py",
    "learning/curation/perception/edge_capture_session.py",
    "learning/curation/perception/extract.py",
    "learning/curation/perception/lane_failure_loop.py",
    "learning/curation/perception/object_boxes.py",
    "learning/curation/perception/prelabel.py",
    "learning/curation/perception/qwen_points.py",
    "learning/curation/perception/sam3_road_draft.py",
    "learning/registry/perception/convert.py",
    "learning/registry/perception/deliver.py",
    "learning/registry/perception/export_class_names.py",
    "learning/registry/perception/export_onnx.py",
    "learning/registry/perception/intake.py",
    "learning/registry/perception/sign_model.py",
    "learning/evaluation/perception/road_replay.py",
    "learning/curation/perception/review_bridge.py",
    "learning/curation/perception/review_eval_package.py",
    "tools/lane_replay.py",
]


@pytest.mark.parametrize("cli", CLIS)
def test_cli_help_with_clean_pythonpath(cli):
    env = {k: v for k, v in os.environ.items() if k != "PYTHONPATH"}
    env["PYTHONIOENCODING"] = "utf-8"  # help text has non-cp949 characters on Windows
    proc = subprocess.run([sys.executable, str(ROOT / cli), "--help"], cwd=ROOT, env=env,
                          capture_output=True, text=True, encoding="utf-8", timeout=120)
    err = proc.stderr
    if proc.returncode != 0 and "ModuleNotFoundError" in err and "core_common" not in err:
        missing = err.strip().splitlines()[-1]
        assert not any(f"No module named '{name}'" in missing for name in INTERNAL_MODULES), err
        pytest.skip(f"--help needs an optional package that is absent: {missing}")
    assert proc.returncode == 0, err[-2000:]


@pytest.mark.parametrize("entry", ["review_dataset", "review_eval_companion", "review_eval_package"])
def test_review_source_imports_resolve_canonical_holders_without_suite_paths(entry):
    # Only the entry's curation directory is supplied. Each production module
    # must establish its own curation/registry dependencies before lazy calls.
    curation = ROOT / "learning/curation/perception"
    expected = {name: str(ROOT / holder / (name + ".py")) for name, holder in (
        ("build", "learning/curation/perception"), ("mcap_proof", "learning/curation/perception"),
        ("review_evidence", "learning/curation/perception"), ("store", "learning/registry/perception"),
    )}
    code = ("import sys,pathlib;sys.path.insert(0," + repr(str(curation)) + ");"
            "__import__(" + repr(entry) + ");"
            "expected=" + repr(expected) + ";"
            "assert all(str(pathlib.Path(__import__(name).__file__).resolve())==path "
            "for name,path in expected.items());"
            "assert 'dataset.build' not in sys.modules")
    proc = subprocess.run([sys.executable, "-I", "-B", "-c", code], cwd=ROOT,
                          capture_output=True, text=True, encoding="utf-8", timeout=120)
    assert proc.returncode == 0, proc.stderr[-2000:]
