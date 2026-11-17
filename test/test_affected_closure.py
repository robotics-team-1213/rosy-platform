"""D-436 addendum (D-1037): a module's registered test directory narrows to the test files that reach the changed .py."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools" / "harness"))

import affected_tests as affected  # noqa: E402

PKG = "middleware/pkg"
FILES = {
    "tools/harness/harness.yaml": f"modules:\n  - name: pkg\n    path: {PKG}\n    tests: [{PKG}/test]\n",
    "tools/harness/platform_parts.yaml": f"roots:\n  - path: {PKG}\n    import_prefix: [pkg]\n",
    f"{PKG}/pkg/x.py": "X = 1\n",
    f"{PKG}/pkg/y.py": "Y = 1\n",
    f"{PKG}/pkg/data.json": "{}\n",
    f"{PKG}/test/conftest.py": "",
    f"{PKG}/test/test_x.py": "from pkg import x\n\ndef test_x():\n    assert x.X\n",
    f"{PKG}/test/test_y.py": "from pkg.y import Y\n\ndef test_y():\n    assert Y\n",
    f"{PKG}/test/test_dyn.py": "import importlib\n\ndef test_d():\n    importlib.import_module('pkg.x')\n",
}


@pytest.fixture(scope="module")
def sample(tmp_path_factory) -> Path:
    root = tmp_path_factory.mktemp("closure")
    subprocess.run(["git", "-C", str(root), "init", "-q", "-b", "main"], check=True)
    for rel, text in FILES.items():
        (root / rel).parent.mkdir(parents=True, exist_ok=True)
        (root / rel).write_text(text, encoding="utf-8")
    subprocess.run(["git", "-C", str(root), "add", "-A"], check=True)
    subprocess.run(["git", "-C", str(root), "-c", "user.name=t", "-c", "user.email=t@example.invalid",
                    "commit", "-q", "-m", "base"], check=True)
    return root


def _tests(sample: Path, change: str) -> set[str]:
    sel = affected.select(affected.Repo.load(sample), [change])
    return {p for p in sel.reasons if p.startswith(PKG)}


def test_a_py_change_selects_only_the_test_files_that_reach_it(sample):
    # test_dyn.py loads modules dynamically, so it always stays; test_y.py never reaches x.py
    assert _tests(sample, f"{PKG}/pkg/x.py") == {f"{PKG}/test/test_x.py", f"{PKG}/test/test_dyn.py"}
    assert _tests(sample, f"{PKG}/pkg/y.py") == {f"{PKG}/test/test_y.py", f"{PKG}/test/test_dyn.py"}


@pytest.mark.parametrize("change", [f"{PKG}/pkg/data.json", f"{PKG}/test/conftest.py"])
def test_non_py_and_conftest_changes_keep_the_whole_test_directory(sample, change):
    assert _tests(sample, change) == {f"{PKG}/test"}


def test_a_py_nobody_imports_keeps_the_whole_test_directory(tmp_path):
    root = tmp_path
    for rel, text in {**FILES, f"{PKG}/pkg/orphan.py": "Z = 1\n"}.items():
        (root / rel).parent.mkdir(parents=True, exist_ok=True)
        (root / rel).write_text(text, encoding="utf-8")
    subprocess.run(["git", "-C", str(root), "init", "-q", "-b", "main"], check=True)
    subprocess.run(["git", "-C", str(root), "add", "-A"], check=True)
    assert _tests(root, f"{PKG}/pkg/orphan.py") == {f"{PKG}/test"}
