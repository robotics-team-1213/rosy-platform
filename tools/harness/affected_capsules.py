"""Zero-FULL scoped capsules for formerly full-escalating changes (D-1052).

Replaces repo-wide FULL escalations with exact app/harness/packaging/safety/move
capsules plus ``test/architecture``, keeping ``ROSY_FULL_LEGACY=1`` as an escape.
"""

from __future__ import annotations

import re

import yaml

import affected_repo

_SAFE_ROOT = "test/architecture"


def _parts(repo) -> dict:
    if repo.parts:
        return repo.parts
    text = repo.text(f"{affected_repo.HARNESS}/platform_parts.yaml")
    if text:
        return yaml.safe_load(text) or {}
    return {"roots": repo.safety_roots}


def _module_suites(repo, module: dict) -> list[str]:
    import affected_tests as at

    tests = module.get("tests") or []
    if set(tests) & at.BROAD_TESTS:
        suites = [t for t in tests if t not in at.BROAD_TESTS] + (module.get("functional") or [])
    else:
        suites = list(tests)
    return [t for t in suites if repo.exists(t)]


def app_suites(repo, path: str) -> dict[str, str]:
    """Suites of every registered module owned by the same non-core app as ``path``."""
    parts = _parts(repo)
    app = affected_repo.app_of(path, parts)
    if app in ("core", "repo"):
        return {}
    found: dict[str, str] = {}
    for module in repo.modules:
        if affected_repo.app_of(module["path"], parts) == app:
            for suite in _module_suites(repo, module):
                found.setdefault(suite, f"app capsule ({app}: {path})")
    return found


def harness_capsule(repo, path: str) -> dict[str, str]:
    """Harness self-tests, architecture guards, and cross-app canaries."""
    import affected_narrow

    found: dict[str, str] = {}
    for test in repo.test_files:
        if affected_narrow.SELF_TEST.match(test):
            found[test] = f"selector self-test tier ({path})"
    if repo.exists(_SAFE_ROOT):
        found[_SAFE_ROOT] = f"selector self-test tier ({path})"
    for suite in affected_narrow.CANARY:
        if repo.exists(suite):
            found.setdefault(suite, f"harness canary ({path})")
    return found


def packaging_capsule(repo, path: str) -> dict[str, str]:
    """Owning module/folder/app suites + referencing tests + architecture guards + canaries."""
    import affected_narrow

    found: dict[str, str] = {}
    if repo.exists(_SAFE_ROOT):
        found[_SAFE_ROOT] = f"packaging guard ({path})"
    module = repo.module_for(path)
    if module is not None:
        for suite in _module_suites(repo, module):
            found.setdefault(suite, f"module {module['name']} ({path})")
    for suite, why in app_suites(repo, path).items():
        found.setdefault(suite, why)
    for suite, why in affected_narrow.folder_tests(repo, path).items():
        found.setdefault(suite, why)
    for test in repo.referencing_tests(path):
        found.setdefault(test, f"references {path}")
    for suite in affected_narrow.CANARY:
        if repo.exists(suite):
            found.setdefault(suite, f"packaging canary ({path})")
    return found


def safety_capsule(repo, path: str) -> dict[str, str]:
    """Safety change without repo-wide FULL: full owning app + folder + guards (+ core canary)."""
    import affected_narrow

    found: dict[str, str] = {}
    if repo.exists(_SAFE_ROOT):
        found[_SAFE_ROOT] = f"safety guard ({path})"
    for suite, why in app_suites(repo, path).items():
        found.setdefault(suite, why)
    for suite, why in affected_narrow.folder_tests(repo, path).items():
        found.setdefault(suite, why)
    for test in repo.referencing_tests(path):
        found.setdefault(test, f"references {path}")
    if affected_repo.app_of(path, _parts(repo)) == "core":
        for suite in affected_narrow.CANARY:
            if repo.exists(suite):
                found.setdefault(suite, f"core safety canary ({path})")
    return found


def moved_capsule(repo, moved: list[str]) -> dict[str, str]:
    """Dual-endpoint union of source and target paths for cross-folder moves or removed modules."""
    import affected_narrow

    found: dict[str, str] = {}
    if repo.exists(_SAFE_ROOT):
        found[_SAFE_ROOT] = "layout/move architecture guards"
    for suite in affected_narrow.CANARY:
        if repo.exists(suite):
            found.setdefault(suite, "layout/move canary")
    for item in moved:
        raw = item.split(":", 1)[0].strip()
        for endpoint in (p.strip() for p in re.split(r"\s*->\s*", raw) if p.strip()):
            for suite, why in packaging_capsule(repo, endpoint).items():
                found.setdefault(suite, why)
            if endpoint.startswith(("tools/", "test/")):
                for suite, why in harness_capsule(repo, endpoint).items():
                    found.setdefault(suite, why)
    return found
