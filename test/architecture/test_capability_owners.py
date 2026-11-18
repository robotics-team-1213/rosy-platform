"""Capability view: every root names one role Epic, and CODEOWNERS follows it.

``tools/harness/platform_parts.yaml`` gives each root a ``capability:`` whose
``owners`` are GitHub logins. ``.github/CODEOWNERS`` must route each owned root
to those owners (last matching line, as GitHub reads it), and no line may name
a root without also naming that root's owners. ``platform`` has no role owners;
a root with exactly one consuming role may carry ``reviewers:`` proxies beside
the ``*`` default. Paths only; the logins themselves are not checked
against GitHub here.
"""

from __future__ import annotations

import subprocess
from collections import Counter
from pathlib import Path

import yaml

from affected_repo import app_of

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


def _reviewers(root: dict) -> set[str]:
    return set(root.get("reviewers", []))


def test_reviewers_only_on_platform_roots_and_known_people():
    bad = [f"{r['path']}: reviewers on {r['capability']}" for r in MANIFEST["roots"]
           if _reviewers(r) and r["capability"] != "platform"]
    assert bad == [], bad
    people = {login for cap in MANIFEST["capabilities"].values() for login in cap["owners"]}
    unknown = sorted({o for r in MANIFEST["roots"] for o in _reviewers(r)} - people)
    assert unknown == [], unknown


def test_proxied_roots_reach_reviewers_in_codeowners():
    rules = _rules()
    bad = []
    for root in MANIFEST["roots"]:
        wanted = _reviewers(root)
        if not wanted:
            continue
        effective = [owners for pattern, owners in rules if _matches(pattern, root["path"])][-1]
        if not wanted <= effective:
            bad.append(f"{root['path']} proxy {sorted(wanted)} reviews go to {sorted(effective)}")
    assert bad == [], bad


def test_signing_paths_stay_lead_only():
    lead = {"livsbittt"}
    bad = []
    for pattern, owners in _rules():
        for guarded in ("deploy", "tools/release"):
            inside = pattern.strip("/")
            deep = inside.startswith(guarded + "/")
            image_lane = inside == "deploy/robot" or inside.startswith("deploy/robot/")
            if (_matches(pattern, guarded) or deep) and owners - lead and not image_lane:
                bad.append(
                    f"{pattern} names {sorted(owners - lead)} beside the signing path {guarded}/"
                    " (deploy/robot image lanes keep their §5.1 joint review)"
                )
    assert bad == [], bad

def test_every_root_and_subtree_names_a_known_app():
    apps = MANIFEST["apps"]
    assert len(apps) == len(set(apps)) and "core" in apps, apps
    subtrees = MANIFEST["app_subtrees"]
    bad = [f"{r['path']}: {r.get('app')!r}" for r in MANIFEST["roots"] if r.get("app") not in apps]
    bad += [f"{path}: {app!r}" for path, app in subtrees.items() if app not in apps or not (ROOT / path).is_dir()]
    assert bad == [], bad
    entries = [r["path"] for r in MANIFEST["roots"]] + list(subtrees)
    # Unique entry paths make the deepest match unique, so every path has exactly one app.
    assert len(entries) == len(set(entries)), "a path is either a root or an app subtree, once"


def test_every_tracked_path_maps_to_exactly_one_app():
    tracked = subprocess.run(["git", "ls-files"], cwd=ROOT, capture_output=True, text=True,
                             encoding="utf-8", check=True).stdout.splitlines()
    counts = Counter(app_of(path, MANIFEST) for path in tracked)
    assert set(counts) == set(MANIFEST["apps"]), f"apps without a tracked file or unknown apps: {counts}"


def test_app_of_takes_the_deepest_entry_and_defaults_to_core():
    parts = {"roots": [{"path": "deploy", "app": "core"}, {"path": "ops/fleet", "app": "site-fleet"}],
             "app_subtrees": {"deploy/robot/omx": "omx-cell"}}
    assert app_of("deploy/robot/omx/x.py", parts) == "omx-cell"
    assert app_of("deploy/robot/omxy/x.py", parts) == "core"
    assert app_of("ops/fleet/a/b.py", parts) == "site-fleet"
    assert app_of("README.md", parts) == "core"
