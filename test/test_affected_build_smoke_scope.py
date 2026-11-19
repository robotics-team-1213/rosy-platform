"""build-smoke runs only when one of its steps can read a changed file (2026-11-20, ralph aff-loop).

ci.yml's smoke job is colcon build + flake8 + core boot + SaveMap, and every step reads only files
inside a ``platform_parts.yaml`` colcon root. A change confined to documents or to trees outside
every root (tools, root ``test/``) skips the job; product files, .github/, deploy/ and
platform_parts.yaml (colcon_roots.py's input) keep it, and the full tier always builds.
"""

from __future__ import annotations

from pathlib import Path

import affected_ci
import affected_tests as affected

ROOT = Path(__file__).resolve().parents[1]


def _buildable(changed: list[str], mode: str = "affected") -> bool:
    return affected_ci.buildable(affected.Repo.load(ROOT), affected.Selection(mode, changed))


def test_trees_outside_every_colcon_root_build_nothing():
    assert not _buildable(["tools/land_cache.py"])
    assert not _buildable(["test/test_land_cache.py", "docs/reference/developer-guide.md"])


def test_workflow_deploy_and_build_data_conservatively_keep_the_smoke_job():
    assert _buildable([".github/workflows/ci.yml"])
    assert _buildable(["deploy/robot/omx/arm_status_bridge.py"])
    assert _buildable(["tools/harness/platform_parts.yaml"])


def test_colcon_root_files_and_build_data_keep_the_smoke_job():
    assert _buildable(["middleware/core/gateway/core/node.py"])
    assert _buildable(["operations/fleet/test/test_model_cooperation.py"])


def test_the_full_tier_always_builds():
    assert _buildable(["docs/adr/D-1.md"], mode="full")
