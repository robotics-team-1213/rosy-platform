"""C15 robot 3D: the pure model (node), and the generated meshes match tools/robot_meshes.py inside the size budget."""

from pathlib import Path
import importlib.util
import shutil
import subprocess

import pytest

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[2]


def test_robot_3d_model_contract(tmp_path):
    node = shutil.which("node")
    if node is None:
        pytest.skip("Node.js is unavailable")
    result = subprocess.run([node, "--test", "--test-reporter=spec", str(HERE / "robot-3d-model.test.mjs")],
                            cwd=tmp_path, capture_output=True, text=True, encoding="utf-8", timeout=60)
    assert result.returncode == 0, result.stdout + result.stderr


def _script():
    spec = importlib.util.spec_from_file_location("robot_meshes", REPO / "tools" / "robot_meshes.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_checked_in_meshes_are_exactly_what_the_script_builds_and_fit_the_budget():
    script = _script()
    built = script.build()  # raises SystemExit over the budget
    on_disk = {p.name: p.read_bytes() for p in (HERE.parent / "meshes").iterdir()}
    assert sorted(built) == sorted(on_disk)
    assert [name for name in built if built[name] != on_disk[name]] == [], "run python tools/robot_meshes.py"
    assert sum(map(len, on_disk.values())) <= script.BUDGET_BYTES


def test_vendored_three_is_pinned_with_its_license():
    vendor = HERE.parent / "vendor"
    assert "MIT License" in (vendor / "three.LICENSE").read_text(encoding="utf-8")
    assert 'const t="183"' in (vendor / "three.core.min.js").read_text(encoding="utf-8")[:400]
    import hashlib
    # npm three@0.183.2 build/ files, unmodified
    pinned_sha256 = {'three.module.min.js': '0a61c95f14e0fa015b3083475c73424f360e5f6f5b74c282b50fdbc2f4c228fc', 'three.core.min.js': '0a9c2f0672c7b8d993ba7639e71919db181ca50c9dff99c78476d3e19057ca9c'}
    for name, digest in pinned_sha256.items():
        assert hashlib.sha256((vendor / name).read_bytes()).hexdigest() == digest, name
