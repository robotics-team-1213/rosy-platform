"""D-377: an app's names all come from one English word — "Rosy + one English word".

For every `surfaces.yaml` row with an `app_name` (an app a person opens), the id `<word>`
(lowercase, letters only) must match:
- the display names: `app_name`, `app_name_en` and `short_name` are `Rosy <Word>` (no Korean),
- the folder's last name: `<word>`,
- `package.xml` `<name>` when the folder is a ROS package: `rosy_<word>`,
- the icon file name: `<word>.svg`,
- for an Android app (`app/build.gradle.kts`): `applicationId` and `namespace`
  `io.github.livsbittt.rosy.<word>` and Gradle `rootProject.name = "rosy-<word>"`.

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
WORD = re.compile(r"^[a-z]+$")

#: Rows not yet moved, keyed by registry id (plan 2026-09-30-app-identity-rename-plan.md §3).
PENDING = {
    "robot": "D-374 stage 3: src/hmi/dashboard -> src/hmi/robot, package rosy_robot (D-362 gate)",
    "console": "D-374 stage 4: fleet/server/web -> src/site/console, package rosy_console (D-362 gate)",
}

#: Packages kept by the D-377 decision table ("unchanged"), keyed by id.
PACKAGE_KEPT = {
    "pilot": "pilot",
}


#: Participants that are not surfaces (no `app_name`, no icon) but still take a D-377 word.
NON_SURFACE_PARTICIPANTS = [
    {"id": "vision", "path": "operations/vision", "console_script": True},
]


def _apps() -> list[dict]:
    rows = yaml.safe_load(REGISTRY.read_text(encoding="utf-8"))["surfaces"]
    return [row for row in rows if row.get("app_name")]


def _gradle_value(text: str, key: str) -> str | None:
    match = re.search(rf'^\s*{re.escape(key)}\s*=\s*"([^"]+)"', text, flags=re.MULTILINE)
    return match.group(1) if match else None


def identity_problems(row: dict, root: Path = ROOT, *, check_icon: bool = True) -> list[str]:
    """Every way `row` breaks the D-377 naming rule; empty when it follows it."""
    word = row["id"]
    if not WORD.match(word):
        return [f"id {word!r} is not one lowercase English word"]
    package = PACKAGE_KEPT.get(word, f"rosy_{word}")
    display = f"Rosy {word.capitalize()}"
    folder = root / row["path"]
    problems = []
    for key in ("app_name", "app_name_en", "short_name"):
        if key in row and row[key] != display:
            problems.append(f"{key} {row[key]!r} should be {display!r}")
    if folder.name != word:
        problems.append(f"folder {row['path']!r} should end in {word!r}")
    icon = row.get("icon")
    if check_icon and (not icon or Path(icon).name != f"{word}.svg"):
        problems.append(f"icon {icon!r} should be named {word}.svg")
    package_xml = folder / "package.xml"
    if package_xml.is_file():
        name = ET.parse(package_xml).getroot().findtext("name")
        if name != package:
            problems.append(f"package.xml <name> {name!r} should be {package!r}")
        setup = folder / "setup.py"
        if row.get("console_script") and f'"rosy-{word}={package}.cli:main"' not in setup.read_text(encoding="utf-8"):
            problems.append(f"setup.py should declare console script 'rosy-{word}'")
    gradle = folder / "app" / "build.gradle.kts"
    if gradle.is_file():
        text = gradle.read_text(encoding="utf-8")
        for key in ("applicationId", "namespace"):
            value = _gradle_value(text, key)
            if value != ANDROID_PREFIX + word:
                problems.append(f"{key} {value!r} should be {ANDROID_PREFIX + word!r}")
        settings = (folder / "settings.gradle.kts").read_text(encoding="utf-8")
        root_name = _gradle_value(settings, "rootProject.name")
        if root_name != f"rosy-{word}":
            problems.append(f"rootProject.name {root_name!r} should be 'rosy-{word}'")
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
    app = tmp_path / "operations/ui/cam"
    (app / "app").mkdir(parents=True)
    (app / "app/build.gradle.kts").write_text(
        'namespace = "io.github.livsbittt.rosy.cam"\n'
        'applicationId = "io.github.livsbittt.rosy.ceilingcamera"\n', encoding="utf-8")
    (app / "settings.gradle.kts").write_text('rootProject.name = "rosy-ceiling-camera"\n', encoding="utf-8")
    row = {"id": "cam", "path": "operations/ui/cam", "app_name": "Rosy 천장 카메라",
           "icon": "src/hmi/web_common/icons/ceiling-camera.svg"}
    problems = identity_problems(row, tmp_path)
    assert len(problems) == 4, problems
    assert any("applicationId" in p for p in problems)
    assert any("rootProject.name" in p for p in problems)
    assert any("icon" in p for p in problems)
    assert any("app_name" in p for p in problems)

    ros = tmp_path / "operations/vision"
    ros.mkdir(parents=True)
    (ros / "package.xml").write_text("<package><name>site_vision</name></package>", encoding="utf-8")
    row = {"id": "vision", "path": "operations/vision", "icon": "icons/vision.svg"}
    assert identity_problems(row, tmp_path) == ["package.xml <name> 'site_vision' should be 'rosy_vision'"]
    assert identity_problems({"id": "site-vision", "path": "x", "icon": None}, tmp_path)
    assert identity_problems({"id": "Pilot", "path": "x", "icon": None}, tmp_path)
