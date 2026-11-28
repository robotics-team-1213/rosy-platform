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

import pytest
import yaml

from affected_repo import app_of, landing_apps

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
    assert len(apps) == len(set(apps)) and {"core", "repo"} <= set(apps), apps
    subtrees = MANIFEST["app_subtrees"]
    bad = [f"{r['path']}: {r.get('app')!r}" for r in MANIFEST["roots"] if r.get("app") not in apps]
    bad += [f"{path}: {app!r}" for path, app in subtrees.items() if app not in apps or not any(ROOT.glob(path))]
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


def test_app_of_reads_glob_subtrees_and_neutral_first():
    parts = {"roots": [{"path": "tools", "app": "core"}, {"path": "tools/sim", "app": "core"},
                       {"path": "ops/fleet", "app": "site-fleet"}],
             "app_subtrees": {"tools/sim/omx_*": "omx-cell", "tools/land*.py": "tooling"},
             "app_neutral": ["**/logs.md", "docs/adr/*"]}
    assert app_of("tools/sim/omx_world.py", parts) == "omx-cell"
    assert app_of("tools/sim/export_site_map.py", parts) == "core"
    assert app_of("tools/land_queue.py", parts) == "tooling"
    assert app_of("ops/fleet/logs.md", parts) == "neutral"  # neutral beats the deeper root
    assert landing_apps(["ops/fleet/logs.md", "docs/adr/D-1.md", "ops/fleet/a.py", "tools/sim/omx_w.py"],
                        parts) == ["omx-cell", "site-fleet"]
    assert landing_apps(["docs/adr/D-1.md"], parts) == []


@pytest.mark.parametrize(("path", "app"), [
    # D-1036 addendum 2: gate code and shipped shared code stay core; never-deployed paths are repo.
    # 2026-11-19 (release-split-1118): the landing/publish gate is tooling, omx sim tools and root omx tests are
    # omx-cell, folder notes and ADRs are neutral (the panel's 48 h sample of misattributed landing paths).
    ("tools/publish_main.py", "tooling"), ("tools/urgent_lane.py", "tooling"),
    ("tools/harness/platform_parts.yaml", "tooling"), ("tools/hooks/land_record.py", "tooling"),
    ("test/test_land_events.py", "tooling"), ("tools/sim/omx_two_arm_world.py", "omx-cell"),
    ("test/test_omx_two_arm_world.py", "omx-cell"), ("tools/sim/export_site_map.py", "core"),
    (".github/workflows/ci.yml", "core"), ("tools/release/x.py", "core"), ("deploy/hosts/services.yaml", "core"),
    ("test/flaky_quarantine.txt", "core"), ("operations/fleet/logs.md", "neutral"), ("tools/index.md", "neutral"),
    ("docs/adr/D-1036-publish-evidence-from-nightly-full.md", "neutral"), ("test/conftest.py", "repo"),
    ("test/architecture/test_capability_owners.py", "repo"), ("tools/remote/remote_pytest.py", "repo"),
    ("test/learning/test_x.py", "learning"),
    # 2026-11-20 (bn-C rank 1): folder guides and the contract version are neutral, cell twin assets are omx-cell,
    # incident tools are site-fleet.
    ("tools/AGENTS.md", "neutral"), ("deploy/hosts/README.md", "neutral"),
    ("middleware/core/api/core_api_web/api/contract_version.py", "neutral"),
    ("learning/envs/isaac/assets/x.usd", "omx-cell"), ("learning/envs/isaac/cell_physics.yaml", "omx-cell"),
    ("learning/envs/isaac/stacking_task.py", "learning"), ("tools/incident_reasoning.py", "site-fleet")])
def test_never_deployed_paths_are_repo_and_gates_stay_core(path, app):
    assert app_of(path, MANIFEST) == app
