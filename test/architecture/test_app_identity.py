"""D-374 1항: an app's folder, package, icon and Android id all come from one role id.

For every `surfaces.yaml` row with an `app_name` (an app a person opens), the role id
(kebab) must match:
- the folder's last name (snake: `-` -> `_`),
- `package.xml` `<name>` when the folder is a ROS package (snake),
- the icon file name (kebab),
- for an Android app (`app/build.gradle.kts`): `applicationId` and `namespace`
  `io.github.livsbittt.rosy.<compact>` and Gradle `rootProject.name = "rosy-<kebab>"`.

Rows still waiting for their rename stage are listed in PENDING. A pending row must
still break the rule, so the line is deleted in the stage commit that fixes it.
"""

from __future__ import annotations

import re
import xml.etree.ElementTree as ET
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[2]
REGISTRY = ROOT / "src/hmi/web_common/surfaces.yaml"
ANDROID_PREFIX = "io.github.livsbittt.rosy."
KEBAB = re.compile(r"^[a-z][a-z0-9]*(?:-[a-z0-9]+)*$")

#: Rows not yet renamed, keyed by current registry id (plan 2026-09-30-app-identity-rename-plan.md §3).
PENDING = {
    "rosy-pilot": "D-374 stage 2: registry id rosy-pilot -> pilot",
    "robot-dashboard": "D-374 stage 3: src/hmi/dashboard -> src/hmi/robot_dashboard (D-362 gate)",
    "fleet-console": "D-374 stage 4: fleet/server/web -> src/site/site_console, id site-console (D-362 gate)",
}


#: Participants that are not surfaces (no `app_name`, no icon) but still take a D-374 role id.
NON_SURFACE_PARTICIPANTS = [
    {"id": "site-vision", "path": "src/site/site_vision"},
]


def _apps() -> list[dict]:
    rows = yaml.safe_load(REGISTRY.read_text(encoding="utf-8"))["surfaces"]
    return [row for row in rows if row.get("app_name")]


def _gradle_value(text: str, key: str) -> str | None:
    match = re.search(rf'^\s*{re.escape(key)}\s*=\s*"([^"]+)"', text, flags=re.MULTILINE)
    return match.group(1) if match else None


def identity_problems(row: dict, root: Path = ROOT, *, check_icon: bool = True) -> list[str]:
    """Every way `row` breaks the D-374 naming rule; empty when it follows it."""
    role = row["id"]
    if not KEBAB.match(role):
        return [f"id {role!r} is not kebab-case"]
    snake, compact = role.replace("-", "_"), role.replace("-", "")
    folder = root / row["path"]
    problems = []
    if folder.name != snake:
        problems.append(f"folder {row['path']!r} should end in {snake!r}")
    icon = row.get("icon")
    if check_icon and (not icon or Path(icon).name != f"{role}.svg"):
        problems.append(f"icon {icon!r} should be named {role}.svg")
    package_xml = folder / "package.xml"
    if package_xml.is_file():
        name = ET.parse(package_xml).getroot().findtext("name")
        if name != snake:
            problems.append(f"package.xml <name> {name!r} should be {snake!r}")
    gradle = folder / "app" / "build.gradle.kts"
    if gradle.is_file():
        text = gradle.read_text(encoding="utf-8")
        for key in ("applicationId", "namespace"):
            value = _gradle_value(text, key)
            if value != ANDROID_PREFIX + compact:
                problems.append(f"{key} {value!r} should be {ANDROID_PREFIX + compact!r}")
        settings = (folder / "settings.gradle.kts").read_text(encoding="utf-8")
        root_name = _gradle_value(settings, "rootProject.name")
        if root_name != f"rosy-{role}":
            problems.append(f"rootProject.name {root_name!r} should be 'rosy-{role}'")
    if not package_xml.is_file() and not gradle.is_file():
        problems.append(f"{row['path']!r} is neither a ROS package nor an Android app")
    return problems


@pytest.mark.parametrize("row", _apps(), ids=lambda row: row["id"])
def test_app_identity_follows_its_role_id(row):
    problems = identity_problems(row)
    if row["id"] in PENDING:
        assert problems, f"{row['id']} now follows D-374; delete its PENDING line ({PENDING[row['id']]})"
    else:
        assert problems == []


@pytest.mark.parametrize("participant", NON_SURFACE_PARTICIPANTS, ids=lambda row: row["id"])
def test_non_surface_participant_follows_its_role_id(participant):
    assert identity_problems(participant, check_icon=False) == []


def test_pending_rows_exist_in_the_registry():
    assert set(PENDING) <= {row["id"] for row in _apps()}


def test_android_app_is_not_a_colcon_package():
    for row in _apps():
        folder = ROOT / row["path"]
        if (folder / "app" / "build.gradle.kts").is_file():
            assert (folder / "COLCON_IGNORE").is_file(), row["path"]


def test_rule_catches_each_mismatch(tmp_path):
    app = tmp_path / "src/site/ceiling_camera"
    (app / "app").mkdir(parents=True)
    (app / "app/build.gradle.kts").write_text(
        'namespace = "io.github.livsbittt.rosy.ceilingcamera"\n'
        'applicationId = "io.github.livsbittt.rosy.overhead"\n', encoding="utf-8")
    (app / "settings.gradle.kts").write_text('rootProject.name = "rosy-overhead"\n', encoding="utf-8")
    row = {"id": "ceiling-camera", "path": "src/site/ceiling_camera",
           "icon": "src/hmi/web_common/icons/overhead-camera-app.svg"}
    problems = identity_problems(row, tmp_path)
    assert len(problems) == 3, problems
    assert any("applicationId" in p for p in problems)
    assert any("rootProject.name" in p for p in problems)
    assert any("icon" in p for p in problems)

    ros = tmp_path / "src/site/site_vision"
    ros.mkdir(parents=True)
    (ros / "package.xml").write_text("<package><name>overhead</name></package>", encoding="utf-8")
    row = {"id": "site-vision", "path": "src/site/site_vision", "icon": "icons/site-vision.svg"}
    assert identity_problems(row, tmp_path) == ["package.xml <name> 'overhead' should be 'site_vision'"]
    assert identity_problems({"id": "Rosy_Pilot", "path": "x", "icon": None}, tmp_path)
