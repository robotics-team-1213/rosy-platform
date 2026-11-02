"""A committed candidate using the real browser chunker, sharder and environment recipe."""

from pathlib import Path
import shutil
import subprocess

import land_cache

ROOT = Path(__file__).resolve().parents[1]
BROWSERS = [
    ["ROSY_RUN_BROWSER_TESTS=1", "ROSY_BROWSER_ALONE=1",
     "operations/fleet/test/test_site_map_browser.py"],
    ["ROSY_RUN_BROWSER_TESTS=1", "test/test_dashboard_browser.py"],
]
FULL = [["learning/registry/policy/test"], ["test"], *BROWSERS]


def candidate_files(local):
    """The harness's small fixture plan; browser, splitting, deps and verdict code are production copies."""
    copies = [*ROOT.glob("tools/remote/*.py"), ROOT / "tools/remote/serial_suites.txt",
              ROOT / "tools/land_cache.py", ROOT / "tools/land_selection.py", ROOT / "tools/land_browser.py",
              ROOT / "test/browser_scope.py", ROOT / "test/known_failures.py"]
    for source in copies:
        target = local / source.relative_to(ROOT)
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(source, target)
    files = {
        "tools/harness/affected_tests.py": "# canonical harness is present\n",
        "tools/harness/rosy_harness.py": "import json\nprint(json.dumps(" + repr(
            {"mode": "full", "full_invocations": FULL[:2]}) + "))\n",
        ".github/workflows/ci.yml": '--wheel-dir "$wheelhouse" \\\n  fixture-wheel\n',
        "fixture-wheel/setup.py": "# fixture wheel\n",
        "test/known_failures.txt": "",
        "test/flaky_quarantine.txt": "",
        "learning/registry/policy/test/test_one.py": "def test_one(): pass\n",
        "operations/fleet/test/test_site_map_browser.py": "def test_map(): pass\n",
        "test/test_dashboard_browser.py": "def test_dashboard(): pass\n",
    }
    for name in (land_cache.remote_pytest.DEVICE_REQ, land_cache.remote_pytest.CRYPTO_REQ,
                 land_cache.remote_pytest.FLEET_REQ, land_cache.remote_pytest.VISION_REQ):
        files[name] = "# fixture requirements\n"
    for name, text in files.items():
        path = local / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")
    paths = [str(source.relative_to(ROOT)) for source in copies] + list(files)
    subprocess.run(["git", "-C", str(local), "add", "--", *paths], check=True, capture_output=True)
    subprocess.run(["git", "-C", str(local), "commit", "-qm", "candidate test contracts"], check=True,
                   capture_output=True)


def qualified_record(tool, local, sha, base, invocations=None, *, prepared=None):
    invocations = FULL if invocations is None else invocations
    env = land_cache.env_id(local, sha)
    assert env
    tree = tool.git(local, "rev-parse", f"{sha}^{{tree}}").stdout.strip()
    folder = land_cache.path(local).parent / "publish-test-logs" / sha
    folder.mkdir(parents=True, exist_ok=True)
    logs = []
    for i, inv in enumerate(invocations):
        log = folder / f"run-{i}.txt"
        log.write_text("1 passed in 0.01s\n", encoding="utf-8")
        land_cache.record(local, sha, tree, env, inv, log)
        logs.append(str(log))
    tool.land_record.write(local, sha, base, invocations, logs, tier="full", prepared=prepared)
    return logs
