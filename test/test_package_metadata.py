"""package.xml manifests must carry real metadata, not scaffolding placeholders.

The upstream ROS generate-a-package templates ship ``TODO: Package description``
and ``TODO: License declaration``; the manifest is what release tooling and
``ros2 pkg`` read, so a placeholder there misstates the artifact. Every package
description must name what the package actually does.

Licence reality check (open question, reported 2026-09-23): the repository root
``LICENSE`` is Apache-2.0 and most manifests say ``Apache-2.0``, but five core
manifests declare ``Proprietary``. Adjudicating that split is an owner decision,
not a test's — so the guard pins the *known* set explicitly instead of silently
rewriting either side. A placeholder, empty or newly-invented value still fails.

Mutation-proven: reintroduce a ``TODO`` line in any manifest and the first test
goes red (test/AGENTS.md rule).
"""

from __future__ import annotations

import xml.etree.ElementTree as ET
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SKIP_DIRS = {"build", "install", "log", "__pycache__"}
# Declared by the manifests today: most of the repo is Apache-2.0 (root LICENSE),
# five core packages still say Proprietary — see module docstring.
ALLOWED_LICENCES = {"Apache-2.0", "Proprietary"}


def _manifests() -> list[Path]:
    return sorted(
        path
        for path in (ROOT / "src").rglob("package.xml")
        if not SKIP_DIRS.intersection(path.relative_to(ROOT).parts)
    )


def _relative(path: Path) -> str:
    return str(path.relative_to(ROOT))


def test_no_todo_placeholders_survive_in_any_manifest() -> None:
    offenders = [
        _relative(path)
        for path in _manifests()
        if "TODO" in path.read_text(encoding="utf-8")
    ]
    assert offenders == [], f"scaffolding TODO left in: {offenders}"


def test_every_manifest_declares_a_known_licence() -> None:
    offenders: list[str] = []
    for path in _manifests():
        root = ET.parse(path).getroot()
        licences = [
            (el.text or "").strip() for el in root.findall("license")
        ]
        if not licences or not any(licences):
            offenders.append(f"{_relative(path)}: missing ({licences})")
            continue
        unknown = [value for value in licences if value not in ALLOWED_LICENCES]
        if unknown:
            offenders.append(f"{_relative(path)}: {unknown}")
    assert offenders == [], f"licence not in {sorted(ALLOWED_LICENCES)}: {offenders}"


def test_every_description_says_what_the_package_does() -> None:
    offenders: list[str] = []
    for path in _manifests():
        root = ET.parse(path).getroot()
        descriptions = [
            (el.text or "").strip() for el in root.findall("description")
        ]
        if not descriptions or not descriptions[0]:
            offenders.append(f"{_relative(path)}: empty")
            continue
        if descriptions[0].startswith("TODO"):
            offenders.append(f"{_relative(path)}: {descriptions[0]}")
    assert offenders == [], f"description is not a real summary: {offenders}"
