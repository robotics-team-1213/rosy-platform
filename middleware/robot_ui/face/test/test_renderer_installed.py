"""Run the pure renderer from setuptools output, outside its source checkout."""

from pathlib import Path
import shutil
import subprocess
import sys


def test_built_renderer_imports_and_packs_without_the_source_tree(tmp_path):
    root = Path(__file__).resolve().parents[1]
    package = tmp_path / "package"
    package.mkdir()
    for name in ("setup.py", "package.xml"):
        shutil.copy2(root / name, package / name)
    for name in ("emotion", "resource"):
        shutil.copytree(root / name, package / name, ignore=shutil.ignore_patterns("__pycache__"))
    build = tmp_path / "built"
    subprocess.run(
        [sys.executable, "setup.py", "build_py", "--build-lib", str(build)],
        cwd=package, check=True, capture_output=True, text=True, timeout=60,
    )
    probe = """
import sys
from pathlib import Path
sys.path.insert(0, sys.argv[1])
from emotion import info_screen as card, lcd_primitives
root = Path(sys.argv[1]).resolve()
assert Path(card.__file__).resolve().is_relative_to(root)
assert Path(lcd_primitives.__file__).resolve().is_relative_to(root)
image = card.render_card({'kind': 'drive', 'mode': 'MANUAL', 'battery_percent': 73})
assert image.size == (320, 240)
pixels = card.to_panel(image)
assert pixels.shape == (320, 240, 2) and str(pixels.dtype) == 'uint8'
assert 'rclpy' not in sys.modules
"""
    subprocess.run(
        [sys.executable, "-I", "-c", probe, str(build)],
        cwd=tmp_path, check=True, capture_output=True, text=True, timeout=30,
    )
