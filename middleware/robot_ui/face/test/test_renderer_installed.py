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
    consumer = root.parents[2] / "deploy/robot/pinky_pro/native/face_card_renderer.py"
    shutil.copy2(consumer, tmp_path / consumer.name)
    probe = """
import sys
from pathlib import Path
from PIL import ImageChops
sys.path.insert(0, sys.argv[1])
sys.path.insert(0, sys.argv[2])
import face_card_renderer
from emotion import info_screen as card, lcd_primitives
root = Path(sys.argv[1]).resolve()
assert Path(card.__file__).resolve().is_relative_to(root)
assert Path(lcd_primitives.__file__).resolve().is_relative_to(root)
assert Path(face_card_renderer.__file__).parent == Path(sys.argv[2])
render = face_card_renderer.card_renderer(card)
for kind in ['info', 'drive']:
    payload = {'kind': kind, 'mode': 'MANUAL', 'battery_percent': 73}
    image = render({'screen': {'kind': 'face', 'overlay': {'payload': payload}},
                    'bar': ('Fixture', 'ok', 73, False)})
    assert image.size == (320, 240)
    expected = card.render_card(payload, size=(320, 208))
    assert ImageChops.difference(image.crop(card.expression_box()), expected).getbbox() is None
    pixels = card.to_panel(image)
    assert pixels.shape == (320, 240, 2) and str(pixels.dtype) == 'uint8'
assert 'rclpy' not in sys.modules
"""
    subprocess.run(
        [sys.executable, "-I", "-c", probe, str(build), str(tmp_path)],
        cwd=tmp_path, check=True, capture_output=True, text=True, timeout=30,
    )
