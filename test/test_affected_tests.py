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
from pathlib import Path, PurePosixPath

import pytest

import affected_tests as affected
import rosy_harness as harness

ROOT = Path(__file__).resolve().parents[1]
GUARDS = set(affected.GUARD_SET)

HARNESS_YAML = """\
modules:
  - name: core
    path: src/runtime/gateway
    tests: [src/runtime/gateway/test]
  - name: control
    path: src/runtime/sensing
    tests: [src/runtime/sensing/test]
  - name: core_common
    path: src/contracts/foundation
    tests: [src/contracts/foundation/test]
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
  - path: src/contracts/foundation
    import_prefix: [core_common]
  - path: src/runtime/gateway
    import_prefix: [core]
  - path: src/runtime/sensing
    import_prefix: [control]
  - path: tools
  - path: docs
"""

FILES = {
    "tools/harness/harness.yaml": HARNESS_YAML,
    "tools/harness/platform_parts.yaml": PARTS_YAML,
    "src/contracts/foundation/core_common/schemas.py": "X = 1\n",
    "src/contracts/foundation/test/test_schemas.py": "import core_common\n",
    "src/runtime/sensing/control/battery.py": "from core_common import schemas\n",
    "src/runtime/sensing/test/test_battery.py": "from control import battery\n",
    "src/runtime/gateway/core/node.py": "from control.battery import read\n",
    "src/runtime/gateway/test/test_battery.py": "import core\n",
    "src/runtime/gateway/test/conftest.py": "",
    "deploy/robot/run.sh": "echo run\n",
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
    "test/test_network_topology_contracts.py": "",
    ".github/workflows/ci.yml": "name: ci\n",
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


# (case, changed files, expected mode, expected selection beyond the guard set)
CASES = [
    ("tools/ssh only -> guards + the tests naming the script",
     ["tools/ssh/rosy_ssh_enroll.py"], "affected", {"test/test_rosy_ssh_enroll.py"}),
    ("core_common -> full", ["src/contracts/foundation/core_common/schemas.py"], "full", None),
    ("unmapped file -> full (unknown never means nothing)", ["tools/mystery/run.sh"], "full", None),
    ("sensing -> sensing suite + reverse dependent gateway",
     ["src/runtime/sensing/control/battery.py"], "affected",
     {"src/runtime/sensing/test", "src/runtime/gateway/test"}),
    ("ADR only -> docs module contracts (guards cover the ADR index)",
     ["docs/adr/D-1-sample.md"], "affected", {"test/test_network_topology_contracts.py"}),
    ("doc read by a contract test -> that test too",
     ["docs/reference/line-follow.md"], "affected",
     {"test/test_network_topology_contracts.py", "test/test_line_follow_contract_docs.py"}),
    ("Markdown note outside modules -> guards only", ["tools/AGENTS.md"], "affected", set()),
    ("changed test file -> only that file", ["src/runtime/sensing/test/test_battery.py"], "affected",
     {"src/runtime/sensing/test/test_battery.py"}),
    ("test helper -> the tests importing it", ["test/fake_core_ssh.py"], "affected", {"test/test_ssh_access.py"}),
    ("deploy -> functional, not the whole root test/", ["deploy/robot/run.sh"], "affected",
     {"test/test_robot_runtime.py"}),
    ("conftest -> full", ["src/runtime/gateway/test/conftest.py"], "full", None),
    ("CI workflow -> full", [".github/workflows/ci.yml"], "full", None),
    ("selector config -> full", ["tools/harness/harness.yaml"], "full", None),
    ("requirements pin -> full", ["deploy/robot/device-python-requirements.txt"], "full", None),
    ("nothing changed -> guards only", [], "affected", set()),
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


def test_duplicate_basenames_run_in_separate_invocations(sample):
    sel = _select(sample, "src/runtime/sensing/control/battery.py")
    owners = {path: i for i, inv in enumerate(sel.invocations) for path in inv}
    assert owners["src/runtime/sensing/test"] != owners["src/runtime/gateway/test"]
    repo = affected.Repo.load(sample)
    for inv in sel.invocations:
        names = [PurePosixPath(t).name for p in inv for t in repo.test_files_under(p)]
        assert len(names) == len(set(names)), inv


def test_reasons_name_the_reverse_dependency(sample):
    sel = _select(sample, "src/runtime/sensing/control/battery.py")
    assert any("reverse dependent core" in why for why in sel.reasons["src/runtime/gateway/test"])


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


def test_missing_base_escalates_to_full(sample, capsys):
    assert harness.main(["affected", "--repo", str(sample), "--base", "no-such-ref", "--json"]) == 0
    out = json.loads(capsys.readouterr().out)
    assert out["mode"] == "full"
    assert "no-such-ref" in out["escalations"][0]


def test_real_registry_guard_set_exists():
    missing = [p for p in affected.GUARD_SET + affected.FULL_SUITES if not (ROOT / p).exists()]
    assert not missing, f"D-436 guard/full paths moved: {missing}"


def test_real_repo_selector_paths_escalate():
    """The selector's own files and the harness config always escalate."""
    repo = affected.Repo.load(ROOT)
    for path in ("tools/harness/affected_tests.py", "tools/harness/harness.yaml",
                 "src/contracts/foundation/core_common/__init__.py", ".github/workflows/ci.yml"):
        assert affected.select(repo, [path]).mode == "full", path
