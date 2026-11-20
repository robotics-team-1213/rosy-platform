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


def _repo(root: Path, files: dict[str, str]) -> Path:
    for rel, text in files.items():
        (root / rel).parent.mkdir(parents=True, exist_ok=True)
        (root / rel).write_text(text, encoding="utf-8")
    subprocess.run(["git", "-C", str(root), "init", "-q", "-b", "main"], check=True)
    subprocess.run(["git", "-C", str(root), "add", "-A"], check=True)
    return root


FLAT = {
    "tools/harness/harness.yaml": (f"modules:\n  - name: pkg\n    path: {PKG}\n    tests: [{PKG}/test]\n"
                                   "  - name: user\n    path: middleware/user\n    tests: [middleware/user/test]\n"),
    # source_packages mirrors fleet's entry for its flat holders, so the dotted-name reverse rule resolves them.
    "tools/harness/platform_parts.yaml": (f"roots:\n  - path: {PKG}\n    import_prefix: [pkg]\n"
                                          "    source_packages: {pkg/server/ledger: pkg.server, pkg/server/work: pkg.server}\n"
                                          "  - path: middleware/user\n    import_prefix: [user]\n"),
    f"{PKG}/pkg/__init__.py": "",
    f"{PKG}/pkg/server/__init__.py": "",
    # No __init__.py: installed flat into pkg.server, the way fleet/server/ledger is (fleet._source_layout).
    f"{PKG}/pkg/server/ledger/charge.py": "C = 1\n",
    f"{PKG}/pkg/server/work/task.py": "T = 1\n",
    f"{PKG}/pkg/server/app.py": "from pkg.server import charge, task\n",
    f"{PKG}/test/test_charge.py": "from pkg.server import charge\n\ndef test_c():\n    assert charge.C\n",
    f"{PKG}/test/test_task.py": "from pkg.server.task import T\n\ndef test_t():\n    assert T\n",
    f"{PKG}/test/test_app.py": "from pkg.server import app\n\ndef test_a():\n    assert app\n",
    "middleware/user/user/client.py": "from pkg.server import charge\n",
    "middleware/user/user/other.py": "from pkg.server import task\n",
    "middleware/user/test/test_client.py": "from user import client\n\ndef test_u():\n    assert client\n",
    "middleware/user/test/test_other.py": "from user import other\n\ndef test_o():\n    assert other\n",
}


def test_a_flat_installed_module_resolves_by_its_installed_name(tmp_path):
    root = _repo(tmp_path, FLAT)
    picked = _tests(root, f"{PKG}/pkg/server/ledger/charge.py")
    # Through app.py too, unless app.py is a composition root (next test).
    assert picked == {f"{PKG}/test/test_charge.py", f"{PKG}/test/test_app.py"}


def test_a_reverse_dependent_suite_keeps_only_the_files_that_reach_the_change(tmp_path):
    root = _repo(tmp_path, FLAT)
    sel = affected.select(affected.Repo.load(root), [f"{PKG}/pkg/server/ledger/charge.py"])
    assert {p for p in sel.reasons if p.startswith("middleware/user")} == {"middleware/user/test/test_client.py"}


def test_narrow_contract_empty_means_no_test_reaches_and_none_means_unknown(tmp_path):
    files = {k: v for k, v in FILES.items() if not k.endswith(("test_dyn.py", "conftest.py"))}
    repo = affected.Repo.load(_repo(tmp_path, {**files, f"{PKG}/pkg/lone.py": "L = 1\n"}))
    closure = affected.affected_closure.Closure(repo)
    narrow = affected.affected_closure.narrow
    test_dir = f"{PKG}/test"
    # reverse, nothing reaches and no dynamic loader: [] (certainly no test)
    assert narrow(repo, f"{PKG}/pkg/lone.py", test_dir, closure, True) == []
    assert narrow(repo, f"{PKG}/pkg/x.py", test_dir, closure, True) == [f"{PKG}/test/test_x.py"]
    # not reverse, nobody reaches: None (whole folder), never []
    assert narrow(repo, f"{PKG}/pkg/lone.py", test_dir, closure, False) is None
    # not a .py, or a single test file: None (cannot judge)
    assert narrow(repo, f"{PKG}/pkg/data.json", test_dir, closure, True) is None
    assert affected._narrowed_tests(repo, f"{PKG}/pkg/x.py", f"{PKG}/test/test_x.py", reverse=True) is None


def test_a_package_import_follows_its_init_reexports(tmp_path):
    """robot-ca 2026-11-20: `import pkg` reaches what pkg/__init__.py re-exports, so a reverse
    narrowing never drops a test that only touches the changed module through the package."""
    files = {k: v for k, v in FILES.items() if not k.endswith(("test_dyn.py", "conftest.py"))}
    files.update({f"{PKG}/pkg/__init__.py": "from .node import N\n",
                  f"{PKG}/pkg/node.py": "N = 1\n",
                  f"{PKG}/test/test_init.py": "import pkg\n\ndef test_i():\n    assert pkg.N\n"})
    repo = affected.Repo.load(_repo(tmp_path, files))
    closure = affected.affected_closure.Closure(repo)
    reached = affected.affected_closure.narrow(repo, f"{PKG}/pkg/node.py", f"{PKG}/test", closure, True)
    assert f"{PKG}/test/test_init.py" in reached
    # `from pkg.y import Y` runs pkg/__init__.py too, so it reaches node through the package
    assert f"{PKG}/test/test_y.py" in reached


def test_a_dynamic_loader_or_conftest_reach_is_never_empty(sample):
    repo = affected.Repo.load(sample)
    closure = affected.affected_closure.Closure(repo)
    narrow = affected.affected_closure.narrow
    assert narrow(repo, f"{PKG}/pkg/data.py", f"{PKG}/test", closure, True) == [f"{PKG}/test/test_dyn.py"]


def test_the_closure_does_not_walk_through_a_composition_root(tmp_path, monkeypatch):
    root = _repo(tmp_path, FLAT)
    monkeypatch.setattr(affected.affected_closure, "COMPOSITION_ROOTS", (f"{PKG}/pkg/server/app.py",))
    assert _tests(root, f"{PKG}/pkg/server/ledger/charge.py") == {f"{PKG}/test/test_charge.py"}
    # A change to the composition root itself still reaches the tests that import it.
    assert _tests(root, f"{PKG}/pkg/server/app.py") == {f"{PKG}/test/test_app.py"}


def test_composition_roots_exist_in_this_repository():
    for root in affected.affected_closure.COMPOSITION_ROOTS:
        assert (ROOT / root).exists(), root
