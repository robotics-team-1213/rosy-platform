"""D-60: navigation does not import swarm. Swarm aims; navigation executes."""

from __future__ import annotations

import ast
from pathlib import Path

NAV = Path(__file__).resolve().parents[2] / "core_features" / "core_features" / "navigation"


def test_navigation_tree_has_no_swarm_module():
    assert not (NAV / "swarm.py").exists()


def test_navigation_sources_do_not_import_swarm():
    for path in NAV.glob("*.py"):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                names = [a.name for a in node.names]
            elif isinstance(node, ast.ImportFrom) and node.module:
                names = [node.module]
            else:
                continue
            for name in names:
                assert "swarm" not in name.split("."), path.name
