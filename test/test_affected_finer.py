"""Finer selection (2026-11-17): direct importers first, dotted-name import match.

Synthetic trees are read from tmp_path; the last cases run the real registry."""

from __future__ import annotations

from pathlib import Path

import affected_tests as affected

ROOT = Path(__file__).resolve().parents[1]


def _repo(tmp_path: Path, files: dict[str, str], owners=(), roots=()) -> affected.Repo:
    for path, text in files.items():
        (tmp_path / path).parent.mkdir(parents=True, exist_ok=True)
        (tmp_path / path).write_text(text, encoding="utf-8")
    tracked = sorted(files)
    return affected.Repo(tmp_path, [], list(owners), tracked,
                         [p for p in tracked if affected.TEST_FILE.search(p)], safety_roots=list(roots))


def test_direct_importer_test_wins_and_the_closure_only_extra_is_dropped(tmp_path):
    repo = _repo(tmp_path, {
        "lib/leaf.py": "X = 1\n", "lib/mid.py": "import leaf\n", "lib/top.py": "import mid\n",
        "lib/test/test_mid.py": "import mid\n", "lib/test/test_top.py": "import top\n"})
    assert repo.referencing_tests("lib/leaf.py") == ["lib/test/test_mid.py"]


def test_two_hop_chain_is_caught_by_the_closure_fallback(tmp_path):
    repo = _repo(tmp_path, {
        "lib/leaf.py": "X = 1\n", "lib/mid.py": "import leaf\n", "lib/top.py": "import mid\n",
        "lib/test/test_top.py": "import top\n"})
    assert repo.referencing_tests("lib/leaf.py") == ["lib/test/test_top.py"]


ROOTS = [{"path": "ops/fleet", "import_prefix": ["fleet"]}]
OWNERS = [("ops/fleet", ("fleet",))]


def _fleet(tmp_path):
    return _repo(tmp_path, {
        "ops/fleet/fleet/pipeline/__init__.py": "",
        "ops/fleet/fleet/pipeline/policy.py": "X = 1\n",
        "ops/fleet/fleet/pipeline/user.py": "from fleet.pipeline.policy import X\n",
        "ops/fleet/fleet/server/console.py": "",
        "elsewhere/test_direct.py": "import fleet.pipeline.policy\n",
        "elsewhere/test_hop.py": "import fleet.pipeline.user\n",
        "elsewhere/test_package.py": "from fleet.pipeline import policy\n",
        "elsewhere/test_other.py": "import fleet.server.console\n"}, OWNERS, ROOTS)


def test_dotted_name_selects_real_importers_not_the_whole_package(tmp_path):
    repo = _fleet(tmp_path)
    assert repo.dotted("ops/fleet/fleet/pipeline/policy.py") == "fleet.pipeline.policy"
    sel = affected.select(repo, ["ops/fleet/fleet/pipeline/policy.py"])
    chosen = {t for t in sel.reasons if t.startswith("elsewhere/")}
    assert chosen == {"elsewhere/test_direct.py", "elsewhere/test_hop.py", "elsewhere/test_package.py"}


def test_init_and_unresolvable_files_keep_the_coarse_package_rule(tmp_path):
    repo = _fleet(tmp_path)
    assert repo.dotted("ops/fleet/fleet/pipeline/__init__.py") is None
    assert repo.dotted("ops/fleet/README.py") is None
    sel = affected.select(repo, ["ops/fleet/fleet/pipeline/__init__.py"])
    assert {t for t in sel.reasons if t.startswith("elsewhere/")} == {
        "elsewhere/test_direct.py", "elsewhere/test_hop.py", "elsewhere/test_package.py", "elsewhere/test_other.py"}


def test_real_repo_dotted_names_follow_the_owning_root():
    repo = affected.Repo.load(ROOT)
    assert repo.dotted("operations/fleet/fleet/pipeline/omx_cell_policy.py") == "fleet.pipeline.omx_cell_policy"
    assert repo.dotted("middleware/core/gateway/core/system/ros_graph.py") == "core.system.ros_graph"


def test_real_repo_fleet_pipeline_change_does_not_pull_gazebo_tests():
    repo = affected.Repo.load(ROOT)
    sel = affected.select(repo, ["operations/fleet/fleet/pipeline/omx_cell_policy.py"])
    assert sel.mode == "affected", sel.escalations
    assert not any(t.startswith("integrations/simulation/gazebo/test/") for t in sel.reasons)
