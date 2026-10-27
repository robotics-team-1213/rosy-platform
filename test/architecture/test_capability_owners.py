"""Capability view: every root names one role Epic, and CODEOWNERS follows it.

``tools/harness/platform_parts.yaml`` gives each root a ``capability:`` whose
``owners`` are GitHub logins. ``.github/CODEOWNERS`` must route each owned root
to those owners (last matching line, as GitHub reads it), and no line may name
a root without also naming that root's owners. ``platform`` has no owners and
stays with the ``*`` default. Paths only; the logins themselves are not checked
against GitHub here.
"""

from __future__ import annotations

from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[2]
MANIFEST = yaml.safe_load((ROOT / "tools" / "harness" / "platform_parts.yaml").read_text(encoding="utf-8"))
CODEOWNERS = ROOT / ".github" / "CODEOWNERS"


def _rules() -> list[tuple[str, set[str]]]:
    rules = []
    for line in CODEOWNERS.read_text(encoding="utf-8").splitlines():
        if not line.strip() or line.lstrip().startswith("#"):
            continue
        pattern, *owners = line.split()
        rules.append((pattern, {owner.removeprefix("@") for owner in owners}))
    return rules


def _owners(capability: str) -> set[str]:
    return set(MANIFEST["capabilities"][capability]["owners"])


def _matches(pattern: str, path: str) -> bool:
    """The directory patterns this file uses: ``*`` or ``/dir/``."""
    if pattern == "*":
        return True
    assert pattern.startswith("/") and pattern.endswith("/") and "*" not in pattern, pattern
    prefix = pattern.strip("/")
    return path == prefix or path.startswith(prefix + "/")


def _containing_root(path: str) -> dict:
    roots = [r for r in MANIFEST["roots"] if path == r["path"] or path.startswith(r["path"] + "/")]
    assert roots, f"{path} is under no platform_parts root"
    return max(roots, key=lambda r: len(r["path"]))


def test_every_root_has_a_known_capability():
    capabilities = MANIFEST["capabilities"]
    bad = [f"{r['path']}: {r.get('capability')!r}" for r in MANIFEST["roots"]
           if r.get("capability") not in capabilities]
    assert bad == [], bad
    used = {r["capability"] for r in MANIFEST["roots"]}
    assert used == set(capabilities), f"unused capability: {set(capabilities) - used}"
    assert capabilities["platform"]["owners"] == []


def test_codeowners_patterns_are_existing_directories():
    rules = _rules()
    assert rules[0] == ("*", {"livsbittt"}), "keep the default owner first"
    bad = [pattern for pattern, _ in rules[1:] if not (ROOT / pattern.strip("/")).is_dir()]
    assert bad == [], bad
    patterns = [pattern for pattern, _ in rules]
    assert len(patterns) == len(set(patterns)), "duplicate CODEOWNERS pattern"


def test_every_codeowners_line_names_the_owners_of_what_it_covers():
    bad = []
    for pattern, owners in _rules()[1:]:
        path = pattern.strip("/")
        covered = [r for r in MANIFEST["roots"] if _matches(pattern, r["path"])] or [_containing_root(path)]
        for root in covered:
            missing = _owners(root["capability"]) - owners
            if missing:
                bad.append(f"{pattern} covers {root['path']} ({root['capability']}) without {sorted(missing)}")
    assert bad == [], bad


def test_every_owned_root_reaches_its_owners():
    rules = _rules()
    bad = []
    for root in MANIFEST["roots"]:
        wanted = _owners(root["capability"])
        if not wanted:
            continue
        effective = [owners for pattern, owners in rules if _matches(pattern, root["path"])][-1]
        if not wanted <= effective:
            bad.append(f"{root['path']} ({root['capability']}) reviews go to {sorted(effective)}")
    assert bad == [], bad
