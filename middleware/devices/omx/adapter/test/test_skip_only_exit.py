"""This directory's conftest turns a skip-only run (pytest exit 5) into a verdict; failures still fail (D-889 20)."""

import subprocess
import sys
from pathlib import Path

import pytest

CONFTEST = Path(__file__).with_name("conftest.py")


@pytest.mark.parametrize("body, code", [
    ('import pytest\npytest.importorskip("no_such_module_d889")\n', 0),  # the ROS-only file without rclpy
    ("def test_x():\n    assert False\n", 1),
])
def test_a_skip_only_run_exits_0_and_a_failure_still_fails(tmp_path, body, code):
    # the real conftest loaded from its own place (its sys.path setup counts parents from there)
    (tmp_path / "conftest.py").write_text(
        "import importlib.util\n"
        f"spec = importlib.util.spec_from_file_location('omx_adapter_conftest', {str(CONFTEST)!r})\n"
        "module = importlib.util.module_from_spec(spec)\nspec.loader.exec_module(module)\n"
        "pytest_sessionfinish = module.pytest_sessionfinish\n", encoding="utf-8")
    (tmp_path / "test_only.py").write_text(body, encoding="utf-8")
    done = subprocess.run([sys.executable, "-m", "pytest", "-q", "-p", "no:cacheprovider", str(tmp_path / "test_only.py")],
                          cwd=tmp_path, capture_output=True, text=True)
    assert done.returncode == code, done.stdout + done.stderr
