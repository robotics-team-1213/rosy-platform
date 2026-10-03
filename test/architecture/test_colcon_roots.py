"""D-427 wave 0 item 5: the colcon source roots live in one manifest line.

``tools/harness/platform_parts.yaml`` holds ``colcon_roots``. Shell consumers
read it through ``tools/harness/colcon_roots.py``; Python consumers import that
reader. These tests keep every consumer on the same value.
"""

from __future__ import annotations

import importlib.util
import subprocess
import sys
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[2]
MANIFEST = ROOT / "tools" / "harness" / "platform_parts.yaml"
READER = ROOT / "tools" / "harness" / "colcon_roots.py"


def _reader():
    spec = importlib.util.spec_from_file_location("colcon_roots_reader", READER)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _manifest_roots() -> list[str]:
    return yaml.safe_load(MANIFEST.read_text(encoding="utf-8"))["colcon_roots"]


def test_reader_matches_the_yaml_manifest_and_every_root_exists():
    roots = _manifest_roots()

    assert list(_reader().colcon_roots()) == roots
    assert roots and len(roots) == len(set(roots))
    for root in roots:
        assert (ROOT / root).is_dir(), root


def test_reader_cli_prints_the_roots_space_separated():
    completed = subprocess.run([sys.executable, str(READER)], capture_output=True,
                               text=True, check=True)

    assert completed.stdout.split() == _manifest_roots()
