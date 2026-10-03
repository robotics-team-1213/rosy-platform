"""Each site CLI must start with only its own sys.path edits.

conftest.py adds src/runtime/sensing and src/contracts/foundation for every
test, which masked the D-424 break (control imports core_common). These tests
run the CLIs in a subprocess with a clean PYTHONPATH instead.
"""
import os
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[3]
CLIS = [
    "tools/perception/dataset/autolabel.py",
    "tools/perception/dataset/build.py",
    "tools/perception/dataset/extract.py",
    "tools/perception/dataset/object_boxes.py",
    "tools/perception/dataset/prelabel.py",
    "tools/perception/model/convert.py",
    "tools/perception/model/deliver.py",
    "tools/perception/model/export_onnx.py",
    "tools/perception/model/intake.py",
    "tools/perception/model/sign_model.py",
    "tools/perception/road_replay.py",
    "tools/lane_replay.py",
]


@pytest.mark.parametrize("cli", CLIS)
def test_cli_help_with_clean_pythonpath(cli):
    env = {k: v for k, v in os.environ.items() if k != "PYTHONPATH"}
    env["PYTHONIOENCODING"] = "utf-8"  # help text has non-cp949 characters on Windows
    proc = subprocess.run([sys.executable, str(ROOT / cli), "--help"], cwd=ROOT, env=env,
                          capture_output=True, text=True, timeout=120)
    err = proc.stderr
    if proc.returncode != 0 and "ModuleNotFoundError" in err and "core_common" not in err:
        missing = err.strip().splitlines()[-1]
        pytest.skip(f"--help needs an optional package that is absent: {missing}")
    assert proc.returncode == 0, err[-2000:]
