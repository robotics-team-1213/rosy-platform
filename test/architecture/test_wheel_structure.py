"""Wheels (``pyproject.toml`` without ``package.xml``) carry the same P2 markers as ROS packages.

``test_module_structure.py`` finds packages through ``package.xml`` only, so a
wheel was never checked for ``COLCON_IGNORE`` (contracts/AGENTS.md), its own
``AGENTS.md`` (P2 b) or its own tests (P2 d). The exception list is checked both
ways (P5): a wheel that gains tests must leave it.
"""

from __future__ import annotations

import subprocess
from pathlib import Path, PurePosixPath

import yaml

ROOT = Path(__file__).resolve().parents[2]

#: Wheels whose tests live with their consumers or in the repository test/ suite.
KNOWN_WITHOUT_OWN_TESTS = {
    "applications/fleet/gateway": "installed-entrypoint tests in test/test_platform_*",
    "contracts/learning": "consumer suites (operations/fleet, learning/registry, robot_execution)",
    "contracts/skill": "consumer suites (robot_execution/local, test/test_motion_contract_delivery.py)",
    "integrations/robots/omx": "test/test_platform_omx_transfer_provider.py and other test/test_platform_*",
    "middleware/devices/omx/agent": "test/test_platform_workcell_coordinator.py and test/test_platform_owner_barriers.py",
    "middleware/skills/api": "test/test_platform_transfer_owner_boundary.py and test/test_platform_contract_mapping.py",
    "middleware/skills/manipulation": "test/test_platform_transfer_owner_boundary.py",
    "operations/site_execution": "robot_execution/local and operations/fleet suites",
}


def _tracked() -> set[str]:
    out = subprocess.run(["git", "ls-files", "-z"], cwd=ROOT, capture_output=True, check=True).stdout
    return set(filter(None, out.decode("utf-8").split("\0")))


TRACKED = _tracked()
WHEELS = sorted(
    str(PurePosixPath(name).parent) for name in TRACKED
    if PurePosixPath(name).name == "pyproject.toml" and f"{PurePosixPath(name).parent}/package.xml" not in TRACKED
)


def test_the_scan_sees_the_wheels():
    assert len(WHEELS) >= 15, WHEELS


def test_every_wheel_is_hidden_from_colcon():
    missing = [wheel for wheel in WHEELS if f"{wheel}/COLCON_IGNORE" not in TRACKED]
    assert missing == [], missing


def test_every_wheel_has_agents_md():
    missing = [wheel for wheel in WHEELS if f"{wheel}/AGENTS.md" not in TRACKED]
    assert missing == [], missing


def test_every_wheel_owns_tests():
    without = {
        wheel for wheel in WHEELS
        if not any(name.startswith(f"{wheel}/test/") and PurePosixPath(name).name.startswith("test_")
                   for name in TRACKED)
    }
    assert without == set(KNOWN_WITHOUT_OWN_TESTS), (
        f"new: {sorted(without - set(KNOWN_WITHOUT_OWN_TESTS))}, "
        f"stale: {sorted(set(KNOWN_WITHOUT_OWN_TESTS) - without)}"
    )


def test_every_control_wheel_is_a_harness_module():
    # P2 c for wheels, control only (2026-10-27 debate, consensus 3): real-arm paths show up in STATUS.md.
    harness = ROOT / "tools" / "harness"
    roots = yaml.safe_load((harness / "platform_parts.yaml").read_text(encoding="utf-8"))["roots"]
    modules = {m["path"] for m in yaml.safe_load((harness / "harness.yaml").read_text(encoding="utf-8"))["modules"]}
    control = {r["path"] for r in roots if r.get("concern") == "control"} & set(WHEELS)
    assert control, "no concern: control wheel found"
    assert sorted(control - modules) == []
