"""D-436 change-scoped test selection (``rosy_harness.py affected``).

Table-driven over a small synthetic git repository that mirrors the real
shapes: gateway (``core``) imports sensing (``control``) and both ship a
``test_battery.py``; ``deploy`` owns the whole root ``test/`` suite; the guard
set exists; a tools/ssh script is named by its test. The last cases run the
real repository through the CLI so the registry and the selector stay in step.
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path, PurePosixPath

import pytest

import affected_ros
import affected_pack
import affected_tests as affected
import rosy_harness as harness

ROOT = Path(__file__).resolve().parents[1]
GUARDS = set(affected.GUARD_SET)


def test_fleet_development_module_selects_application_contracts():
    repo = affected.Repo.load(ROOT)
    module = repo.module_for('applications/fleet/dev/sample/engine.py')
    assert module['tests'] == ['applications/fleet/test']
    matrix = affected.ci_matrix(repo, affected.Selection('full', []))['include']
    assert any('applications/fleet/test' in inv for entry in matrix for inv in entry['invocations'])


def test_external_drive_holders_select_their_installing_distribution():
    repo = affected.Repo.load(ROOT)
    behavior = 'middleware/drive/behaviors/line_follow/manager.py'
    assert repo.module_for(behavior)['name'] == 'core_features'
    assert repo.module_for('middleware/drive/runtime/goal_node.py')['name'] == 'control'
    assert repo.module_for('middleware/drive/planning/nav2/package.xml')['name'] == 'navigation'
    selection = affected.select(repo, [behavior])
    assert 'middleware/core/services/test' in selection.reasons
    assert 'middleware/core/gateway/test' in selection.reasons

@pytest.mark.parametrize("changed", ["learning/curation/perception/review_app_web/camera.html",
                                     "applications/fleet/web/console.js"])
def test_a_surface_tree_change_selects_the_registry_contract_suites(changed):
    # 2026-10-18: the D-792 camera page landed red because these suites never name review_app_web.
    selection = affected.select(affected.Repo.load(ROOT), [changed])
    assert {"shared/web/test/test_ui_token_contracts.py", "shared/web/test/test_shared_controls.py"} <= set(
        selection.reasons)


HARNESS_YAML = """\
modules:
  - name: core
    path: middleware/core/gateway
    tests: [middleware/core/gateway/test]
  - name: control
    path: middleware/perception
    tests: [middleware/perception/test]
  - name: core_common
    path: contracts/foundation
    tests: [contracts/foundation/test]
  - name: core_api_web
    path: middleware/core/api
    tests: [middleware/core/api/test]
  - name: deploy
    path: deploy
    tests: [test]
    functional: [test/test_robot_runtime.py]
  - name: docs
    path: docs
    tests: [test/test_network_topology_contracts.py, test/test_harness_contracts.py]
"""

PARTS_YAML = """\
roots:
  - path: contracts/foundation
    import_prefix: [core_common]
  - path: middleware/core/gateway
    import_prefix: [core]
  - path: middleware/perception
    import_prefix: [control]
  - path: middleware/core/api
    import_prefix: [core_api_web]
  - path: tools
  - path: docs
"""

FILES = {
    "tools/harness/harness.yaml": HARNESS_YAML,
    "tools/harness/platform_parts.yaml": PARTS_YAML,
    "contracts/foundation/core_common/__init__.py": "",
    "contracts/foundation/core_common/schemas.py": "from .power import P  # re-export\nX = 1\n",
    "contracts/foundation/core_common/power.py": "P = 1\n",
    "contracts/foundation/core_common/orphan.py": "Z = 1\n",
    "contracts/foundation/config/rosy_default.yaml": "a: 1\n",
    "contracts/foundation/config/rosy_dev_auth.yaml": "b: 1\n",
    "middleware/core/gateway/test/test_runtime_config.py": "DEFAULTS = 'rosy_default.yaml'\n",
    "contracts/foundation/test/test_schemas.py": "import core_common\n",
    "middleware/perception/control/battery.py": "from core_common import schemas\n",
    "middleware/perception/test/test_battery.py": "from control import battery\n",
    "middleware/core/gateway/core/node.py": "from control.battery import read\n",
    "middleware/core/gateway/test/test_battery.py": "import core\n",
    "middleware/core/gateway/test/conftest.py": "",
    "middleware/core/api/core_api_web/app.py": "import core\n",
    "middleware/core/api/test/test_app.py": "import core_api_web\n",
    "deploy/robot/run.sh": "echo run\n",
    "deploy/robot/pinky_pro/udev/99-rosy.rules": "# pinky\n",
    "deploy/robot/omx/udev/99-rosy.rules": "# omx\n",
    "deploy/robot/pinky_pro/compose.yaml": "services: {}\n",
    "deploy/site/compose.yaml": "services: {}\n",
    "test/test_udev_rules.py": 'RULES = ROOT / "deploy" / "robot" / "pinky_pro" / "udev" / "99-rosy.rules"\n',
    "docs/adr/D-1-sample.md": "## D-1 sample\n",
    "docs/reference/line-follow.md": "# line follow\n",
    "tools/AGENTS.md": "# tools\n",
    "tools/ssh/rosy_ssh_enroll.py": "print('enroll')\n",
    "tools/mystery/run.sh": "echo ?\n",
    "test/fake_core_ssh.py": "PORT = 1\n",
    "test/test_rosy_ssh_enroll.py": "SCRIPT = 'tools/ssh/rosy_ssh_enroll.py'\n",
    "test/test_ssh_access.py": "import fake_core_ssh\n",
    "test/test_robot_runtime.py": "def test_x():\n    pass\n",
    "test/test_unrelated.py": "def test_y():\n    pass\n",
    "test/test_line_follow_contract_docs.py": "DOC = 'docs/reference/line-follow.md'\n",
    "test/test_network_topology_contracts.py": 'ADR = ROOT / "docs" / "reference" / "ROSY ADR Log.md"\n',
    ".github/workflows/ci.yml": "name: ci\n",
    ".github/workflows/release.yml": "name: release\n",
    "test/test_release_workflow.py": "WORKFLOW = '.github/workflows/release.yml'\n",
    **{guard: "" for guard in affected.GUARD_SET},
}


def _git(repo: Path, *args: str) -> str:
    return subprocess.run(["git", "-C", str(repo), *args], check=True, capture_output=True, text=True).stdout


@pytest.fixture(scope="module")
def sample(tmp_path_factory) -> Path:
    repo = tmp_path_factory.mktemp("affected")
    _git(repo, "init", "-q", "-b", "main")
    _git(repo, "config", "user.email", "t@example.invalid")
    _git(repo, "config", "user.name", "t")
    for rel, text in FILES.items():
        path = repo / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-q", "-m", "base")
    return repo


def _select(sample: Path, *changed: str) -> affected.Selection:
    return affected.select(affected.Repo.load(sample), list(changed))


@pytest.mark.parametrize("consumer", ["package_export", "transitive_runtime", "broad_owner"])
def test_foundation_indirect_runtime_consumers_keep_full(sample, consumer):
    repo = affected.Repo.load(sample)
    power = "contracts/foundation/core_common/power.py"
    repo._texts["contracts/foundation/core_common/schemas.py"] = "X = 1\n"
    repo._texts["middleware/perception/control/battery.py"] = "X = 1\n"
    if consumer == "package_export":
        repo._texts["contracts/foundation/core_common/__init__.py"] = "from .power import P\n"
        repo._texts["middleware/core/gateway/core/node.py"] = "from core_common import P\n"
    elif consumer == "transitive_runtime":
        repo._texts["middleware/perception/control/battery.py"] = "from core_common.power import P\n"
    else:
        runtime = "deploy/robot/runtime.py"
        repo.tracked.append(runtime)
        repo._texts[runtime] = "from core_common.power import P\n"
    selection = affected.select(repo, [power])
    assert selection.mode == "full", "unresolved runtime consumers must not narrow the foundation gate"
    selected = {path for invocation in selection.invocations for path in invocation}
    assert {"middleware/core/gateway/test", "middleware/core/api/test", "test"} <= selected


# (case, changed files, expected mode, expected selection beyond the guard set)
CASES = [
    ("tools/ssh only -> guards + the tests naming the script",
     ["tools/ssh/rosy_ssh_enroll.py"], "affected", {"test/test_rosy_ssh_enroll.py"}),
    # D-762 stage 0: contracts/foundation and .github/workflows select their real readers.
    ("core_common runtime consumer -> full until downstream coverage is resolved",
     ["contracts/foundation/core_common/schemas.py"], "full", None),
    ("core_common module re-exported (relative import) -> the re-exporter's importers too",
     ["contracts/foundation/core_common/power.py"], "full", None),
    ("core_common module nobody imports -> full (unresolved)", ["contracts/foundation/core_common/orphan.py"],
     "full", None),
    ("core_common __init__ exports -> full", ["contracts/foundation/core_common/__init__.py"], "full", None),
    ("core_common module removed in the working tree -> full", ["contracts/foundation/core_common/gone.py"],
     "full", None),
    ("foundation packaging -> full", ["contracts/foundation/setup.py"], "full", None),
    ("foundation test file -> only that file", ["contracts/foundation/test/test_schemas.py"], "affected",
     {"contracts/foundation/test/test_schemas.py"}),
    ("foundation config textual reader does not establish all runtime consumers",
     ["contracts/foundation/config/rosy_default.yaml"], "full", None),
    ("foundation config no test reads -> full (fallback)", ["contracts/foundation/config/rosy_dev_auth.yaml"],
     "full", None),
    ("workflow textual reader does not establish execution coverage",
     [".github/workflows/release.yml"], "full", None),
    ("unmapped file -> full (unknown never means nothing)", ["tools/mystery/run.sh"], "full", None),
    ("sensing -> sensing suite + direct reverse dependent gateway (api_web is two hops: not pulled)",
     ["middleware/perception/control/battery.py"], "affected",
     {"middleware/perception/test", "middleware/core/gateway/test"}),
    ("ADR only -> the ADR Log readers (guards cover the ADR index)",
     ["docs/adr/D-1-sample.md"], "affected", {"test/test_network_topology_contracts.py"}),
    ("doc read by a contract test -> that test too",
     ["docs/reference/line-follow.md"], "affected",
     {"test/test_network_topology_contracts.py", "test/test_line_follow_contract_docs.py"}),
    ("Markdown note outside modules -> guards only", ["tools/AGENTS.md"], "affected", set()),
    ("changed test file -> only that file", ["middleware/perception/test/test_battery.py"], "affected",
     {"middleware/perception/test/test_battery.py"}),
    ("test helper -> the tests importing it", ["test/fake_core_ssh.py"], "affected", {"test/test_ssh_access.py"}),
    ("deploy file named by path parts -> that test + deploy functional, not the whole root test/",
     ["deploy/robot/pinky_pro/udev/99-rosy.rules"], "affected",
     {"test/test_udev_rules.py", "test/test_robot_runtime.py"}),
    ("deploy file no test names -> whole root suite (narrowing needs a referencing test)",
     ["deploy/robot/run.sh"], "affected", {"test"}),
    ("deploy compose manifest -> full (tests reach it through path constants)",
     ["deploy/robot/pinky_pro/compose.yaml"], "full", None),
    ("native unit manifest -> full", ["deploy/robot/pinky_pro/native/rosy-x.service"], "full", None),
    ("conftest -> full", ["middleware/core/gateway/test/conftest.py"], "full", None),
    ("workflow no test reads -> full (fallback)", [".github/workflows/ci.yml"], "full", None),
    ("selector config -> full", ["tools/harness/harness.yaml"], "full", None),
    ("requirements pin -> full", ["deploy/robot/device-python-requirements.txt"], "full", None),
    ("nothing changed -> guards only", [], "affected", set()),
    # D-762 stage 0: source layout and guard rules escalate; records under a trigger do not.
    ("package manifest -> full", ["middleware/perception/package.xml"], "full", None),
    ("source layout -> full", ["middleware/perception/control/_source_layout.py"], "full", None),
    # Rule 6 (design 0.7): a guard rule change runs the whole guard directory, not FULL.
    ("architecture guard -> the whole test/architecture", ["test/architecture/test_module_structure.py"],
     "affected", {"test/architecture"}),
    ("architecture guard removed -> full", ["test/architecture/test_layout.py"], "full", None),
    ("architecture conftest -> full", ["test/architecture/conftest.py"], "full", None),
    ("known failures list without a base -> full", ["test/known_failures.txt"], "full", None),
    ("module record -> its readers, not the module suite", ["contracts/foundation/logs.md"], "affected", set()),
]


@pytest.mark.parametrize("case, changed, mode, extra", CASES, ids=[c[0] for c in CASES])
def test_selection_table(sample, case, changed, mode, extra):
    sel = _select(sample, *changed)
    assert sel.mode == mode, case
    if mode == "full":
        assert sel.escalations, "a full selection must say why it escalated"
        assert "test" in sel.reasons, "the full tier includes the root suite"
    else:
        assert not sel.escalations
        assert set(sel.reasons) == GUARDS | extra, case
        assert all(sel.reasons[p] for p in sel.reasons), "every suite carries a reason"


def test_full_local_uses_deploy_functional_tests_and_leaves_root_suite_to_ci(sample):
    sel = _select(sample, "deploy/robot/run.sh", ".github/workflows/ci.yml")
    local = {path for invocation in sel.local_invocations for path in invocation}
    full = {path for invocation in sel.invocations for path in invocation}
    assert sel.mode == "full"
    assert "test" not in local
    assert "test/test_robot_runtime.py" in local
    assert "test" in full


def test_pack_bounds_remote_command_length_without_dropping_tests():
    class FakeRepo:
        @staticmethod
        def test_import_names(path):
            return {PurePosixPath(path).name: path}

    paths = [f"test/test_case_{i:04d}_{'x' * 24}.py" for i in range(200)]
    groups = affected.pack(FakeRepo(), paths)
    assert len(groups) > 1
    assert sorted(path for group in groups for path in group) == paths
    assert all(sum(len(path) + 1 for path in group) <= affected.MAX_INVOCATION_CHARS
               for group in groups)


def test_a_serial_suite_never_keeps_other_suites_off_xdist(tmp_path):
    """remote_pytest drops -n for a whole invocation when one path is serial (2026-10-28: gazebo kept ten
    suites on one core and every turn ran past the cap)."""
    (tmp_path / "tools/remote").mkdir(parents=True)
    (tmp_path / affected_pack.SERIAL_FILE).write_text("sim/test  # ROS ports\ntools\n", encoding="utf-8")

    class FakeRepo:
        root = tmp_path

        @staticmethod
        def test_import_names(path):
            return {path: path}  # no import clash: only the serial rule may split them

    groups = affected.pack(FakeRepo(), ["a/test", "sim/test", "b/test", "tools/x/test", "c/test"])
    assert sorted(path for group in groups for path in group) == ["a/test", "b/test", "c/test", "sim/test",
                                                                   "tools/x/test"]
    for group in groups:
        kinds = {affected_pack.is_serial(p, ["sim/test", "tools"]) for p in group}
        assert len(kinds) == 1, group  # serial and parallel suites never mixed
    assert ["a/test", "b/test", "c/test"] in groups


def test_duplicate_basenames_run_in_separate_invocations(sample):
    sel = _select(sample, "middleware/perception/control/battery.py")
    owners = {path: i for i, inv in enumerate(sel.invocations) for path in inv}
    assert owners["middleware/perception/test"] != owners["middleware/core/gateway/test"]
    repo = affected.Repo.load(sample)
    for inv in sel.invocations:
        names = [PurePosixPath(t).name for p in inv for t in repo.test_files_under(p)]
        assert len(names) == len(set(names)), inv


def test_pack_separates_transitively_imported_test_helpers(tmp_path):
    files = {
        'a/test_lease.py': 'VALUE = 1\n',
        'b/test_lease.py': 'VALUE = 2\n',
        'b/test_bridge.py': 'from test_lease import VALUE\n',
        'b/test_job.py': 'from test_bridge import VALUE\n',
    }
    for name, source in files.items():
        path = tmp_path / name
        path.parent.mkdir(exist_ok=True)
        path.write_text(source, encoding='utf-8')
    subprocess.run([sys.executable, "-c", "from test_job import VALUE; assert VALUE == 2"],
                   cwd=tmp_path / "b", check=True)
    repo = affected.Repo(tmp_path, modules=[], owners=[], tracked=list(files), test_files=list(files))
    groups = affected.pack(repo, ['a/test_lease.py', 'b/test_job.py'])
    assert groups == [['a/test_lease.py'], ['b/test_job.py']]
    assert affected.pack(repo, ['b/test_job.py', 'b/test_bridge.py']) == [
        ['b/test_job.py', 'b/test_bridge.py']]



def test_reasons_name_the_reverse_dependency(sample):
    sel = _select(sample, "middleware/perception/control/battery.py")
    assert any("reverse dependent core" in why for why in sel.reasons["middleware/core/gateway/test"])


def test_cli_json_diffs_against_base_and_working_tree(sample, capsys):
    _git(sample, "checkout", "-q", "-b", "feature")
    try:
        (sample / "tools/ssh/rosy_ssh_enroll.py").write_text("print('v2')\n", encoding="utf-8")
        _git(sample, "commit", "-q", "-am", "ssh")
        (sample / "test/fake_core_ssh.py").write_text("PORT = 2\n", encoding="utf-8")  # unstaged
        assert harness.main(["affected", "--repo", str(sample), "--base", "main", "--json"]) == 0
        out = json.loads(capsys.readouterr().out)
        assert out["mode"] == "affected"
        assert out["changed"] == ["test/fake_core_ssh.py", "tools/ssh/rosy_ssh_enroll.py"]
        assert {"test/test_rosy_ssh_enroll.py", "test/test_ssh_access.py"} <= set(out["reasons"])
    finally:
        _git(sample, "checkout", "-q", "--", ".")
        _git(sample, "checkout", "-q", "main")


@pytest.mark.parametrize("change, mode", [
    (("git", "mv", "middleware/perception/control/battery.py", "middleware/perception/nodes/battery.py"), "full"),
    (("git", "rm", "-q", "middleware/core/gateway/core/node.py"), "full"),           # import path gone
    (("git", "mv", "tools/ssh/rosy_ssh_enroll.py", "tools/ssh/enroll.py"), "affected"),  # same folder
])
def test_committed_folder_moves_escalate(sample, capsys, change, mode):
    """D-762 stage 0: the 2026-10-13 S3..S10 restructure shape (renames across folders) is FULL."""
    _git(sample, "checkout", "-q", "-b", "move")
    try:
        (sample / "middleware/perception/nodes").mkdir(exist_ok=True)
        _git(sample, *change[1:])
        _git(sample, "commit", "-q", "-m", "move")
        assert harness.main(["affected", "--repo", str(sample), "--base", "main", "--json"]) == 0
        out = json.loads(capsys.readouterr().out)
        assert out["mode"] == mode, out["escalations"]
        assert bool(out["full_invocations"]) == (mode == "full")
    finally:
        _git(sample, "checkout", "-q", "main")
        _git(sample, "branch", "-q", "-D", "move")


def test_real_repo_wide_ordinary_edits_stay_affected():
    """D-762 stage 0: an API version bump (its pin files), ADR-gap records and D-766 size data are not FULL."""
    repo = affected.Repo.load(ROOT)
    pins = ["middleware/core/api/core_api_web/api/app.py", "docs/reference/ROSY API & Protocol Reference.md",
            "operations/fleet/test/test_lane_route.py", "operations/fleet/test/test_mission_progress.py",
            "test/test_line_follow_contract_docs.py"]
    for changed in (pins, ["tools/harness/adr_gaps.txt"], ["test/architecture/size_ratchet.txt"],
                    ["test/architecture/size_units.txt"]):  # D-766 4: ratchet rows and units are data
        sel = affected.select(repo, changed)
        assert sel.mode == "affected", sel.escalations


@pytest.mark.parametrize("changed", [
    ["middleware/robot_ui/pilot/package.xml"],        # was: pilot/test ran; must still run
    ["contracts/foundation/core_common/__init__.py"],
    ["tools/harness/platform_parts.yaml"],
])
def test_real_repo_full_tier_covers_every_module_suite_and_the_local_selection(changed):
    """D-762 stage 0: a FULL landing never runs fewer suites than the old guards + mapped path."""
    repo = affected.Repo.load(ROOT)
    sel = affected.select(repo, changed)
    assert sel.mode == "full"
    full = [p for inv in sel.full_invocations for p in inv if not p.startswith("-")]
    covered = lambda path: any(affected._under(path, f) for f in full)  # noqa: E731
    local = [p for inv in sel.local_invocations for p in inv]
    assert local and all(map(covered, local)), [p for p in local if not covered(p)]
    assert all(map(covered, affected._full_paths(repo))), [p for p in affected._full_paths(repo) if not covered(p)]
    assert covered("middleware/robot_ui/pilot/test") and covered("middleware/core/api/test")


def test_missing_base_escalates_to_full(sample, capsys):
    assert harness.main(["affected", "--repo", str(sample), "--base", "no-such-ref", "--json"]) == 0
    out = json.loads(capsys.readouterr().out)
    assert out["mode"] == "full"
    assert "no-such-ref" in out["escalations"][0]


def test_real_registry_guard_set_exists():
    matrix = [p for e in affected.CI_FULL_MATRIX for inv in e["invocations"] for p in inv
              if not p.startswith("-")]
    missing = [p for p in (*affected.GUARD_SET, *affected.FULL_SUITES, *matrix) if not (ROOT / p).exists()]
    assert not missing, f"D-436 guard/full paths moved: {missing}"


def test_real_repo_selector_paths_escalate():
    """The selector's own files and the harness config always escalate."""
    repo = affected.Repo.load(ROOT)
    for path in ("tools/harness/affected_tests.py", "tools/harness/harness.yaml",
                 "contracts/foundation/core_common/__init__.py", "contracts/foundation/setup.py"):
        assert affected.select(repo, [path]).mode == "full", path


def test_real_repo_ci_workflow_keeps_full_execution_coverage():
    """Textual readers do not establish coverage of the jobs a workflow changes."""
    sel = affected.select(affected.Repo.load(ROOT), [".github/workflows/ci.yml"])
    assert sel.mode == "full", sel.escalations
    assert "test" in sel.reasons


# --- D-430 5 safety paths: FULL through safety_review.is_safety, never a copied prefix list ---------


def _safety_escalations(sel):
    return [e for e in sel.escalations if e.endswith(affected.SAFETY_TRIGGER)]


def test_real_repo_safety_paths_escalate_to_full_and_are_never_narrowed():
    repo = affected.Repo.load(ROOT)
    # A concern: safety root file, and a safety_modules entry under the narrowable foundation.
    for path in ("middleware/drive/motion_limits/actuation.py",
                 "contracts/foundation/core_common/protocol/swarm_freshness.py"):
        sel = affected.select(repo, [path])
        assert sel.mode == "full", path
        assert _safety_escalations(sel) == [f"{path}: {affected.SAFETY_TRIGGER}"], sel.escalations


def test_real_repo_non_safety_path_and_safety_markdown_are_not_escalated_by_the_safety_rule():
    repo = affected.Repo.load(ROOT)
    for path in ("middleware/perception/control/battery.py",
                 "middleware/drive/motion_limits/AGENTS.md"):  # NOT_TRIGGERS: Markdown is not FULL
        assert not _safety_escalations(affected.select(repo, [path])), path


def test_safety_rule_follows_deepest_root_wins(tmp_path):
    """is_safety's intended rule: the deepest owning root decides, so a deeper root without
    concern under a safety root is not safety (the real manifest has no such nesting today)."""
    repo = affected.Repo(tmp_path, modules=[], owners=[], tracked=[], test_files=[],
                         safety_roots=[{"path": "a", "concern": "safety"}, {"path": "a/b"}])
    assert _safety_escalations(affected.select(repo, ["a/x.py"]))
    assert not _safety_escalations(affected.select(repo, ["a/b/x.py"]))


# --- D-436 4: GitHub runs the full tier as a parallel matrix; local --run does not -------------


def test_ci_full_matrix_runs_every_root_test_once_with_the_overlay(sample):
    repo = affected.Repo.load(sample)
    matrix = affected.ci_matrix(repo, _select(sample, ".github/workflows/ci.yml"))["include"]
    shards = [e for e in matrix if e["name"].startswith("root-test-")]
    assert len(shards) == affected.ROOT_SHARDS
    assert all(e["ros"] == "overlay" for e in shards), "root deploy/release contracts need install/"
    shard_files = [t for e in shards for inv in e["invocations"] for t in inv]
    root_tests = sorted(t for t in repo.test_files if t.startswith("test/"))
    assert sorted(shard_files) == root_tests, "each root test file in exactly one shard"
    assert [e["name"] for e in matrix].count("build-smoke") == 1


def test_ci_full_matrix_shards_slow_suites_by_file(sample):
    repo = affected.Repo.load(sample)
    matrix = affected.ci_matrix(repo, _select(sample, ".github/workflows/ci.yml"))["include"]
    for name, n in affected.SUITE_SHARDS.items():
        suite = next(e for e in affected.CI_FULL_MATRIX if e["name"] == name)["invocations"][0][0]
        files = sorted(t for t in repo.test_files if t.startswith(suite + "/"))
        shards = [e for e in matrix if e["name"] == name or e["name"].startswith(name + "-")]
        if len(files) < n:
            assert [e["invocations"] for e in shards] == [[[suite]]]
            continue
        assert len(shards) == n
        assert sorted(t for e in shards for inv in e["invocations"] for t in inv) == files


def test_ci_full_matrix_keeps_gateway_and_sensing_on_separate_runners():
    owner = {path: entry["name"] for entry in affected.CI_FULL_MATRIX
             for inv in entry["invocations"] for path in inv}
    assert owner["middleware/core/gateway/test"] != owner["middleware/perception/test"]
    for entry in affected.CI_FULL_MATRIX:
        assert entry["ros"] in {"none", "base", "overlay"}, entry["name"]


def test_standalone_app_tests_are_required_in_full_and_affected_ci():
    repo = affected.Repo.load(ROOT)
    path = 'applications/fleet/test'
    for selection in (affected.Selection('full', []), affected.select(repo, [path + '/test_sample_browser.py'])):
        matrix = affected.ci_matrix(repo, selection)['include']
        owners = [entry for entry in matrix if any(
            p == path or p.startswith(path + '/') for inv in entry['invocations'] for p in inv)]
        assert owners and all(entry['gating'] and entry['ros'] == 'none' for entry in owners)
        if selection.mode == 'full':
            assert len(owners) == 1
            assert owners[0]['invocations'] == [[path]]


def test_ci_fleet_shards_balance_measured_slow_files_without_losing_tests():
    # Main CI 38807338775 (2026-10-15) took 224/528/168/275 s with the 2026-10-10 weights;
    # the measured table must keep the slowest shard near a quarter of the suite.
    costs = json.loads((ROOT / "tools/harness/fleet_test_seconds.json").read_text(encoding="utf-8"))
    assert costs["test_signal_supervision.py"] >= 50, "a slowest Fleet file must be weighed"
    repo = affected.Repo.load(ROOT)
    selection = affected.Selection("full", [])
    matrix = affected.ci_matrix(repo, selection)["include"]
    shards = [e for e in matrix if e["name"].startswith("fleet-")]
    paths = [p for e in shards for inv in e["invocations"] for p in inv]
    expected = sorted(p for p in repo.test_files if p.startswith("operations/fleet/test/"))
    assert sorted(paths) == expected
    loads = [sum(costs.get(PurePosixPath(p).name, 1) for inv in e["invocations"] for p in inv)
             for e in shards]
    assert max(loads) <= 1.1 * sum(loads) / len(loads), loads
    assert all(e["gating"] and e["ros"] == "none" for e in shards)
    repo.test_files.reverse()
    assert affected.ci_matrix(repo, selection)["include"] == matrix


def test_ci_full_matrix_reaches_every_registered_module_suite():
    """D-762 stage 1: CI's full tier runs every registered test file, bar the reasoned exclusions."""
    repo = affected.Repo.load(ROOT)
    matrix = affected.ci_matrix(repo, affected.Selection("full", []))["include"]
    args = [p for e in matrix for inv in e["invocations"] for p in inv]
    ignored = {p.removeprefix("--ignore=") for p in args if p.startswith("--ignore=")}
    assert ignored == set(affected.CI_FULL_EXCLUDED), "every --ignore needs a CI_FULL_EXCLUDED reason"
    assert all(affected.CI_FULL_EXCLUDED.values())
    ran = {t for p in args if not p.startswith("-") for t in repo.test_files_under(p)} - ignored
    registered = {t for p in affected._full_paths(repo) for t in repo.test_files_under(p)}
    missing = sorted(registered - ran - set(affected.CI_FULL_EXCLUDED))
    assert not missing, f"registered suites CI's full tier never runs: {missing}"
    for suite in ("middleware/core/api/test", "middleware/robot_ui/pilot/test", "operations/apps/games/test"):
        assert any(affected._under(t, suite) for t in ran), suite


def test_ci_affected_whole_fleet_suite_uses_the_full_tier_groups():
    """PR #60 (2026-10-17): one affected runner for all of operations/fleet/test outlasted the 25 min limit."""
    repo = affected.Repo.load(ROOT)
    full = [e["invocations"][0] for e in affected.ci_matrix(repo, affected.Selection("full", []))["include"]
            if e["name"].startswith("fleet-")]
    sel = affected.Selection("affected", [], invocations=[
        ["operations/fleet/test", "test/test_land.py"], ["test/test_affected_tests.py"]])
    matrix = [e for e in affected.ci_matrix(repo, sel)["include"] if e["kind"] == "pytest"]
    invocations = [e["invocations"][0] for e in matrix]
    assert invocations == [["test/test_land.py"], *full, ["test/test_affected_tests.py"]]
    assert [e["name"] for e in matrix] == [f"affected-{i + 1}" for i in range(len(matrix))]
    assert all(e["gating"] for e in matrix)
    assert [e["ros"] for e in matrix] == ["overlay", *["none"] * len(full), "overlay"]
    fleet = [p for inv in full for p in inv]
    assert sorted(fleet) == sorted(p for p in repo.test_files if p.startswith("operations/fleet/test/"))


def test_ci_affected_matrix_uses_the_full_tier_ros_environment_per_path():
    """PR #96 (2026-10-18): gateway rclpy tests that main runs under ros: none ran under overlay on a PR."""
    repo = affected.Repo.load(ROOT)
    sel = affected.Selection("affected", [], invocations=[
        ["middleware/core/gateway/test/test_node_wiring.py", "test/test_land.py", "--ignore=x"]])
    matrix = [e for e in affected.ci_matrix(repo, sel)["include"] if e["kind"] == "pytest"]
    assert [(e["ros"], e["invocations"][0]) for e in matrix] == [
        ("none", ["middleware/core/gateway/test/test_node_wiring.py", "--ignore=x"]),
        ("overlay", ["test/test_land.py", "--ignore=x"])]
    assert affected_ros.full_tier_ros("integrations/simulation/gazebo/test/test_x.py", affected.CI_FULL_MATRIX) == "overlay"
    assert affected_ros.full_tier_ros("middleware/devices/pinky/bringup/test/test_y.py", affected.CI_FULL_MATRIX) == "base"


@pytest.mark.parametrize("flags", [[], ["--ignore=test/test_host_recovery.py"]])
def test_ci_affected_whole_root_suite_uses_the_full_tier_groups(flags):
    """PR #95: the unsplit root suite reached only 60% before the 25-minute limit."""
    repo = affected.Repo.load(ROOT)
    full = [e["invocations"][0] for e in affected.ci_matrix(repo, affected.Selection("full", []))["include"]
            if e["name"].startswith("root-test-")]
    other = "learning/registry/policy/test"
    sel = affected.Selection("affected", [], invocations=[["test", other, *flags]])
    matrix = [e for e in affected.ci_matrix(repo, sel)["include"] if e["kind"] == "pytest"]
    assert [e["invocations"][0] for e in matrix] == [[other, *flags], *[group + flags for group in full]]
    assert all(e["gating"] for e in matrix)
    assert [e["ros"] for e in matrix] == ["none", *["overlay"] * len(full)]
    assert sorted(p for group in full for p in group) == sorted(p for p in repo.test_files if p.startswith("test/"))


def test_ci_affected_matrix_is_one_runner_per_invocation(sample):
    sel = _select(sample, "middleware/perception/control/battery.py")
    matrix = affected.ci_matrix(affected.Repo.load(sample), sel)["include"]
    pytest_entries = [e for e in matrix if e["kind"] == "pytest"]
    # Each invocation becomes one runner per ROS environment; every selected path runs exactly once.
    assert sorted(p for e in pytest_entries for p in e["invocations"][0]) == sorted(p for inv in sel.invocations for p in inv)
    assert all(len({affected_ros.full_tier_ros(p, affected.CI_FULL_MATRIX) for p in e["invocations"][0]}) == 1 for e in pytest_entries)


def test_ci_matrix_cli_forces_full_for_non_pr_events(sample, capsys):
    assert harness.main(["affected", "--repo", str(sample), "--base", "HEAD", "--full", "--ci-matrix"]) == 0
    out = json.loads(capsys.readouterr().out)
    assert out["mode"] == "full"
    assert any(e["name"].startswith("root-test-") for e in out["matrix"]["include"])


def test_local_run_of_a_full_selection_runs_only_guards_and_direct_suites(sample, monkeypatch):
    sel = _select(sample, "contracts/foundation/core_common/orphan.py", "tools/ssh/rosy_ssh_enroll.py")
    assert sel.mode == "full"
    ran = []

    class Done:
        returncode = 0

    monkeypatch.setattr(affected.subprocess, "run", lambda cmd, cwd: ran.append(cmd) or Done())
    assert affected.run(sample, sel) == 0
    local = {p for cmd in ran for p in cmd[3:] if not p.startswith("-")}
    # core_common's own suite and its direct reverse dependent (sensing imports core_common)
    # run locally; the rest of the full tier stays on GitHub.
    assert local == GUARDS | {"test/test_rosy_ssh_enroll.py", "contracts/foundation/test",
                              "middleware/perception/test"}, "FULL stays on GitHub by default"
    assert "test" not in local and "middleware/core/gateway/test" not in local
    ran.clear()
    affected.run(sample, sel, allow_full=True)
    assert "test" in {p for cmd in ran for p in cmd}


def test_escalated_paths_are_still_mapped_for_the_local_run(sample):
    """Review fix: a FULL selection runs locally as guards + the escalated module's own suites."""
    sel = _select(sample, "contracts/foundation/core_common/orphan.py")
    assert sel.mode == "full"
    local = {p for inv in sel.local_invocations for p in inv}
    assert "contracts/foundation/test" in local, "core_common's own suite must run locally"
    assert GUARDS <= local
    assert not any("maps to no module" in e for e in sel.escalations), "a trigger is not also 'unknown'"


def test_parts_match_selects_a_shared_basename_by_its_parent(sample):
    repo = affected.Repo.load(sample)
    assert "test/test_udev_rules.py" in repo.referencing_tests("deploy/robot/pinky_pro/udev/99-rosy.rules")
    assert "test/test_udev_rules.py" not in repo.referencing_tests("deploy/robot/pinky_pro/compose.yaml")


def test_skip_drops_paths_the_caller_already_ran(sample, monkeypatch):
    sel = _select(sample, "tools/ssh/rosy_ssh_enroll.py")
    ran = []

    class Done:
        returncode = 0

    monkeypatch.setattr(affected.subprocess, "run", lambda cmd, cwd: ran.append(cmd) or Done())
    affected.run(sample, sel, skip=frozenset(GUARDS))
    paths = {p for cmd in ran for p in cmd[3:] if not p.startswith("-")}
    assert paths == {"test/test_rosy_ssh_enroll.py"}


def test_full_ci_includes_learning_policy_registry_and_omx_helpers():
    suites = {'learning/registry/policy/test', 'learning/training/omx/test', 'learning/curation/omx/test',
              'learning/curation/pinky/test', 'learning/training/pinky/test',
              'learning/training/world_model/test', 'learning/evaluation/world_model/test',
              'operations/prediction/world_model/test'}
    entries = [e for e in affected.CI_FULL_MATRIX if e['name'] == 'learning-policy']
    assert len(entries) == 1
    assert {p for inv in entries[0]['invocations'] for p in inv} == suites
    assert entries[0]['ros'] == 'none'
    assert suites <= set(affected.FULL_SUITES)


@pytest.mark.parametrize('target', [
    'learning/training/omx/test',
    'learning/training/omx/test/test_act_inference_native.py',
    'learning/training/omx/test/test_act_inference_native.py::test_actual_act_weights_consume_snapshot_and_keep_queue_source',
])
def test_affected_act_tests_also_require_the_actual_cpu_runner(target):
    repo = affected.Repo.load(ROOT)
    matrix = affected.ci_matrix(repo, affected.Selection('affected', [], invocations=[[target]]))['include']
    native = [e for e in matrix if e['name'] == 'omx-act-cpu']
    assert len(native) == 1 and native[0]['gating'] and native[0]['ros'] == 'none'
    assert any(target in paths for e in matrix if e['name'] != 'omx-act-cpu' for paths in e['invocations'])


def test_unrelated_affected_tests_do_not_install_act_cpu_dependencies():
    repo = affected.Repo.load(ROOT)
    matrix = affected.ci_matrix(repo, affected.Selection(
        'affected', [], invocations=[['operations/world/test']]))['include']
    assert all(e['name'] != 'omx-act-cpu' for e in matrix)


def test_modules_runner_gates():
    """D-762 stage 1: `modules` gates since 2026-10-27; only sensing still reports."""
    repo = affected.Repo.load(ROOT)
    matrix = affected.ci_matrix(repo, affected.Selection("full", []))["include"]
    assert sorted(e["name"] for e in matrix if not e["gating"] and not e["name"].startswith("sensing")) == []


def test_unknown_paths_are_listed_with_a_hint_in_json_and_print(sample, capsys):
    """An "unknown -> full" path is named in ``unmapped`` and printed with how to map it."""
    sel = _select(sample, "tools/mystery/run.sh", "deploy/robot/run.sh")
    assert sel.mode == "full"
    assert sel.unmapped == ["tools/mystery/run.sh"], "only the path no module/test names"
    assert sel.to_json()["unmapped"] == ["tools/mystery/run.sh"]
    text = affected.render(sel)
    assert "  tools/mystery/run.sh\n      hint: name this path literally in the test that loads it" in text
    assert "deploy/robot/run.sh\n      hint" not in text
    assert _select(sample, "deploy/robot/run.sh").unmapped == []

# 2026-10-26: a five-line `modules:` addition went FULL and held the land lock 45+ minutes.
REAL_HARNESS = (ROOT / "tools/harness/harness.yaml").read_text(encoding="utf-8")
NEW_MODULE = "  - name: zz_added\n    path: operations/zz_added\n    tests: [test/architecture]\n"


def _harness_with(entry: str, base: str = REAL_HARNESS) -> str:
    assert "\nmodules:\n" in base
    return base.replace("\nmodules:\n", "\nmodules:\n" + entry, 1)


def _harness_select(head: str, base: str = REAL_HARNESS):
    return affected.select(affected.Repo.load(ROOT), ["tools/harness/harness.yaml"], harness_texts=(base, head))


def test_harness_yaml_module_added_only_selects_its_suites_not_full():
    sel = _harness_select(_harness_with(NEW_MODULE))
    assert sel.mode == "affected", sel.escalations
    assert {"test/architecture", "test/test_harness_contracts.py", "test/test_affected_tests.py"} <= set(sel.reasons)
    assert "harness.yaml: module(s) added: zz_added" in sel.reasons["test/architecture"]
    assert "test/architecture/test_folder_layout.py" in sel.reasons


@pytest.mark.parametrize("head, why", [
    (REAL_HARNESS.replace("    path: middleware/core/services\n", "    path: middleware/core/servicez\n", 1),
     "existing module entry changed"),
    (_harness_with("  - name: zz_added\n    path: middleware/core/services/src\n    tests: [test/architecture]\n"),
     "overlaps module core_features"),
    (_harness_with("  - name: core_features\n    path: operations/zz_added\n    tests: [test/architecture]\n"),
     "name missing or duplicated"),
    (_harness_with("  - name: zz_added\n    path: operations/zz_added\n    tests: &t [test/architecture]\n"),
     "anchor"),
    (_harness_with("  - name: zz_added\n    path: operations/zz_added\n    tests: [operations/zz_added/test]\n"),
     "no test function"),
    (_harness_with(NEW_MODULE) + "zz_new_key: 1\n", "other than modules"),
    (REAL_HARNESS + "modules: [\n", "does not parse"),
    (_harness_with(NEW_MODULE + "    tests: [operations/fleet/test]\n"), "duplicate key 'tests'"),
    (_harness_with("  - name: zz_added\n    path: &p operations/zz_added\n    tests: [test/architecture]\n"
                   "    functional: [*p]\n"), "anchor, alias or merge key"),
    (_harness_with("  - name: zz_added\n    path: operations/zz_added\n    <<: {tests: [test/architecture]}\n"),
     "anchor, alias or merge key"),
    (_harness_with("  - name: zz_added\n    path: operations/zz_added\n    tests: [middleware/perception/test]\n"),
     "not in CI's gating full matrix"),
], ids=["modified", "overlap", "duplicate", "anchor", "no-tests", "other-key", "unparsable",
        "duplicate-key", "alias", "merge-key", "not-ci-gated"])
def test_harness_yaml_other_changes_stay_full(head, why):
    _assert_harness_full(_harness_select(head), why)


def _assert_harness_full(sel, why):
    assert sel.mode == "full"
    [escalation] = [e for e in sel.escalations if e.startswith("tools/harness/harness.yaml")]
    assert why in escalation and escalation.endswith(": harness configuration or the selector itself"), escalation
    local = [p for inv in sel.local_invocations for p in inv]
    assert "test/architecture/test_folder_layout.py" in local, local


def test_harness_yaml_module_deletion_is_full():
    _assert_harness_full(_harness_select(REAL_HARNESS, base=_harness_with(NEW_MODULE)), "removed")


def test_harness_yaml_without_a_base_is_full():
    sel = affected.select(affected.Repo.load(ROOT), ["tools/harness/harness.yaml"])
    _assert_harness_full(sel, "no base to compare")


def test_harness_yaml_added_suite_without_test_functions_is_full():
    """A test_*.py with no `def test_` collects nothing, so it does not show the module is tested."""
    repo, target = affected.Repo.load(ROOT), "test/test_rosy_games_surface.py"
    head = _harness_with(f"  - name: zz_added\n    path: operations/zz_added\n    tests: [{target}]\n")
    assert affected.affected_narrow.harness_modules_added(repo, REAL_HARNESS, head)[0]
    text = repo.text
    repo.text = lambda path: "HELPER = 1\n" if path == target else text(path)
    added, why = affected.affected_narrow.harness_modules_added(repo, REAL_HARNESS, head)
    assert not added and "no test function" in why


@pytest.mark.parametrize("path, mode", [
    ("tools/harness/sim2real_gaps.yaml", "affected"), ("tools/harness/perception_gaps.yaml", "affected"),
    ("tools/harness/log_repairs.yaml", "full"), ("tools/harness/platform_parts.yaml", "full"),
    ("tools/harness/platform_dependencies.yaml", "full"), ("tools/harness/affected_narrow.py", "full"),
    ("tools/harness/zz_unknown.json", "full"),
])
def test_harness_data_registries_are_not_full_but_code_and_manifests_are(path, mode):
    sel = affected.select(affected.Repo.load(ROOT), [path])
    assert sel.mode == mode, sel.escalations
    if mode == "affected":
        assert "test/test_harness_contracts.py" in sel.reasons


def test_harness_yaml_added_module_taking_tracked_files_is_full():
    """A source_paths entry inside an existing module counts as an overlap, like path."""
    head = _harness_with("  - name: zz_added\n    path: operations/zz_added\n"
                         "    source_paths: [middleware/core/services/core_features]\n    tests: [test/architecture]\n")
    added, why = affected.affected_narrow.harness_modules_added(affected.Repo.load(ROOT), REAL_HARNESS, head)
    assert not added and "overlaps module core_features" in why


@pytest.mark.parametrize("path", ["operations/fleet/index.md", "operations/fleet/logs.md", "docs/logs.md",
                                  "docs/index.md", "STATUS.md", "deploy/logs.md"])
def test_records_select_only_their_readers(path):
    """2026-10-26: docs/logs.md selected tests that name it only in a comment or a fixture string."""
    sel = affected.select(affected.Repo.load(ROOT), [path])
    assert sel.mode == "affected" and set(sel.reasons) == GUARDS | set(affected.RECORD_READERS), sorted(sel.reasons)


def test_a_module_record_read_by_a_contract_test_selects_it():
    sel = affected.select(affected.Repo.load(ROOT), ["operations/apps/games/progress.md"])
    assert set(sel.reasons) == GUARDS | set(affected.RECORD_READERS) | {"test/test_rosy_games_surface.py"}


@pytest.mark.parametrize("path, record", [
    ("docs/logs.md", True), ("operations/fleet/index.md", True), ("STATUS.md", True),
    ("operations/fleet/docs/logs.md", False), ("docs/plans/index.md", False), ("operations/progress.md", False),
])
def test_records_are_status_and_module_root_records_only(path, record):
    assert affected.is_record(affected.Repo.load(ROOT), path) is record


def test_generated_module_index_does_not_select_the_module_suite():
    """2026-10-26: operations/fleet/index.md selected ~7,900 tests in three commits."""
    assert "operations/fleet/test" not in affected.select(affected.Repo.load(ROOT), ["operations/fleet/index.md"]).reasons


def test_module_note_markdown_selects_readers_not_the_module_suite():
    sel = affected.select(affected.Repo.load(ROOT), ["operations/fleet/docs/call-map.md"])
    assert "operations/fleet/test" not in sel.reasons


@pytest.mark.parametrize("path, expected", [
    ("operations/fleet/AGENTS.md", "operations/fleet/test"),
    ("docs/reference/ROSY API & Protocol Reference.md", "test/test_network_topology_contracts.py"),
    ("docs/adr/D-161-ubuntu-server-native-ros-runtime.md", "test/test_ubuntu_native_runtime_contract.py"),
    ("docs/reference/ROSY ADR Log.md", "test/test_rosy_games_surface.py"),
    ("docs/adr/D-161-ubuntu-server-native-ros-runtime.md", "test/test_network_topology_contracts.py"),
])
def test_contract_checked_markdown_keeps_its_selection(path, expected):
    assert expected in affected.select(affected.Repo.load(ROOT), [path]).reasons


# --- Rule 8 (design 0.7): leaf tools select their tests; the gate tools stay FULL -------------------


# The narrowed case is CASES' tools/ssh row (a leaf tool its test names); the unknown one tools/mystery.


GATE_TOOLS = ["tools/land.py", "tools/land_queue.py", "tools/land_cache.py", "tools/worktrees.py",
              "tools/worktree_rules.py", "tools/hooks/pre-push", "tools/hooks/land_record.py",
              "tools/remote/remote_pytest.py", "tools/remote/remote_job.py", "tools/remote/host_probe.py",
              "tools/remote/xdist_plan.py", "test/known_failures.py", "tools/harness/affected_tests.py",
              "test/browser_scope.py", "tools/remote/serial_suites.txt"]


@pytest.mark.parametrize("path", GATE_TOOLS)
def test_real_repo_gate_tools_stay_full(path):
    """A gate tool may not be tested by the narrow selection it would itself make."""
    sel = affected.select(affected.Repo.load(ROOT), [path])
    assert sel.mode == "full"
    assert f"{path}: harness configuration or the selector itself" in sel.escalations, sel.escalations


def test_real_repo_gate_tool_markdown_is_not_full():
    assert affected.select(affected.Repo.load(ROOT), ["tools/hooks/AGENTS.md"]).mode == "affected"


def test_head_files_are_read_at_head_not_from_the_checkout(sample, capsys):
    """2026-10-26: --head feat/publish-automation from main was unknown -> full, its test being only on head."""
    _git(sample, "checkout", "-q", "-b", "leaf")
    try:
        for rel, text in {"tools/sim/zz_leaf.sh": "echo leaf\n",
                          "test/test_zz_leaf.py": "SCRIPT = 'tools/sim/zz_leaf.sh'\n"}.items():
            (sample / rel).parent.mkdir(parents=True, exist_ok=True)
            (sample / rel).write_text(text, encoding="utf-8")
        _git(sample, "add", "tools/sim/zz_leaf.sh", "test/test_zz_leaf.py")
        _git(sample, "commit", "-q", "-m", "leaf")
        _git(sample, "checkout", "-q", "main")
        assert harness.main(["affected", "--repo", str(sample), "--base", "main", "--head", "leaf", "--json"]) == 0
        out = json.loads(capsys.readouterr().out)
        assert out["mode"] == "affected", out["escalations"]
        assert "test/test_zz_leaf.py" in out["reasons"]
        repo = affected.Repo.load(sample, "leaf")
        assert repo.exists("tools/sim") and repo.exists("test/test_zz_leaf.py") and not repo.exists("tools/zz")
        # a directory and a missing path (with a space) read empty and keep the batch stream in step
        assert repo.text("tools/sim") == "" and repo.text("zz missing.txt") == ""
        assert repo.text("tools/sim/zz_leaf.sh") == "echo leaf\n"
    finally:
        _git(sample, "checkout", "-q", "main")
        _git(sample, "branch", "-q", "-D", "leaf")


# --- Rule 7 (design 0.7): a known_failures edit runs the ids it adds or removes ---------------------

KF = "test/known_failures.txt"
KF_HEADER = "# header\n"
PLAIN = "test/test_unrelated.py::test_y"


def _kf_select(head: str, base: str = KF_HEADER, changed=(KF,), repo=None):
    repo = repo or affected.Repo.load(ROOT)
    repo._texts[KF] = head
    return affected.select(repo, list(changed), base_text=lambda path: base if path == KF else None)


@pytest.mark.parametrize("base, head", [(f"{KF_HEADER}{PLAIN}  # r\n", KF_HEADER),
                                        (KF_HEADER, f"{KF_HEADER}{PLAIN}  # flake\n")],
                         ids=["removed", "added"])
def test_known_failures_line_selects_that_test_not_full(sample, base, head):
    sel = _kf_select(head, base, repo=affected.Repo.load(sample))
    assert sel.mode == "affected", sel.escalations
    assert set(sel.reasons) == GUARDS | {"test/test_unrelated.py"}
    assert any(PLAIN in why for why in sel.reasons["test/test_unrelated.py"])


def test_known_failures_reason_or_comment_edit_runs_only_guards_and_readers(sample):
    sel = _kf_select(f"# new header\n{PLAIN}  # new reason\n", f"{KF_HEADER}{PLAIN}  # r\n",
                     repo=affected.Repo.load(sample))
    assert sel.mode == "affected" and set(sel.reasons) == GUARDS


@pytest.mark.parametrize("head, changed, why, on_sample", [
    (f"{KF_HEADER}{PLAIN}  # r\n", (KF, "test/test_unrelated.py"),
     "other changes on this branch select test/test_unrelated.py", True),
    # the source the test covers changed, not the test: the selector's own mapping decides
    (f"{KF_HEADER}test/test_rosy_ssh_enroll.py::test_x  # r\n", (KF, "tools/ssh/rosy_ssh_enroll.py"),
     "other changes on this branch select test/test_rosy_ssh_enroll.py", True),
    (f"{KF_HEADER}middleware/devices/omx/adapter/omx_adapter/real/dynamixel_stop_test.py::test_x  # r\n", (KF,),
     "adds safety-tagged", False),
    (f"{KF_HEADER}test/test_zz_missing.py::test_x  # r\n", (KF,), "test file does not exist", False),
], ids=["same-branch-test", "same-branch-source", "safety", "missing-file"])
def test_known_failures_added_line_needing_a_person_stays_full(sample, head, changed, why, on_sample):
    sel = _kf_select(head, changed=changed, repo=affected.Repo.load(sample) if on_sample else None)
    assert sel.mode == "full"
    [escalation] = [e for e in sel.escalations if e.startswith(KF)]
    assert why in escalation and escalation.endswith(": known failures list"), escalation


def test_flaky_quarantine_stays_full_as_a_safety_root():
    sel = affected.select(affected.Repo.load(ROOT), ["test/flaky_quarantine.txt"], base_text=lambda path: "")
    assert sel.mode == "full" and _safety_escalations(sel)
