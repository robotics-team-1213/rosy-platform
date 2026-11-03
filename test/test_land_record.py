"""D-553 addendum 3: pre-push reuses land.py's green results only through an unbroken record chain."""

from __future__ import annotations

import importlib.util
from pathlib import Path
import subprocess

import pytest

ROOT = Path(__file__).resolve().parents[1]
_SPEC = importlib.util.spec_from_file_location("land_record", ROOT / "tools" / "hooks" / "land_record.py")
tool = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(tool)
FAST = ["test/fast_a.py", "test/fast_b.py"]


def test_prepared_and_turn_timing_jobs_form_one_plan_but_preserve_execution_provenance(repo):
    from harness.affected_exclusive import DEDICATED
    path, c = repo
    ordinary = ['test/test_other.py']
    prepared = {'invocations': [DEDICATED, ordinary], 'tier': 'full',
                'candidate': c[2], 'main': c[1]}
    tool.write(path, c[3], c[2], [DEDICATED, ordinary], ['fresh-turn-log'], prepared=prepared)
    record = tool.read(path, c[3])
    assert record['invocations'] == [DEDICATED, ordinary, ordinary]
    assert record['logs'] == ['fresh-turn-log']
    assert record['prepared_candidate'] == c[2] and record['prepared_on'] == c[1]


def test_duplicate_timing_jobs_inside_a_single_plan_are_not_hidden(repo):
    from harness.affected_exclusive import DEDICATED
    path, c = repo
    prepared = {'invocations': [DEDICATED, DEDICATED], 'tier': 'full',
                'candidate': c[2], 'main': c[1]}
    with pytest.raises(ValueError):
        tool.write(path, c[3], c[2], [], [], prepared=prepared)


def test_composition_validates_each_context_and_only_normalizes_cross_context_timing():
    from harness import affected_exclusive as exclusive
    root = ['test', '--ignore=' + exclusive.TARGET]
    ordinary = ['pkg/test']
    got = exclusive.compose([root, exclusive.DEDICATED, ordinary], [exclusive.DEDICATED],
                            [ordinary, exclusive.DEDICATED])
    assert got == [root, exclusive.DEDICATED, ordinary, ordinary]
    assert exclusive.compose([['test']], [['pkg/test']], available=False) == [['test'], ['pkg/test']]


@pytest.mark.parametrize('bad', ['duplicate', 'partial', 'missing'])
def test_a_bad_context_cannot_borrow_timing_completeness_from_another(bad):
    from harness import affected_exclusive as exclusive
    contexts = {'duplicate': [exclusive.DEDICATED, exclusive.DEDICATED],
                'partial': [exclusive.DEDICATED + ['-k', 'one']],
                'missing': [['test', '--ignore=' + exclusive.TARGET]]}
    with pytest.raises(ValueError):
        exclusive.compose([exclusive.DEDICATED], contexts[bad])


def _git(repo: Path, *args: str) -> str:
    return subprocess.run(["git", "-C", str(repo), *args], check=True, capture_output=True, text=True).stdout.strip()


@pytest.fixture
def repo(tmp_path):
    _git(tmp_path, "init", "-q", "-b", "main")
    _git(tmp_path, "config", "user.email", "t@example.com")
    _git(tmp_path, "config", "user.name", "t")
    commits = []
    for i in range(4):
        (tmp_path / "f.txt").write_text(str(i))
        _git(tmp_path, "add", "f.txt")
        _git(tmp_path, "commit", "-q", "-m", f"c{i}")
        commits.append(_git(tmp_path, "rev-parse", "HEAD"))
    _git(tmp_path, "update-ref", "refs/remotes/origin/main", commits[0])
    return tmp_path, commits


def test_a_full_chain_back_to_origin_reuses_results_and_owes_unran_fast_suites(repo):
    path, c = repo
    tool.write(path, c[2], c[0], [["test/fast_a.py", "pkg/test"]], [])
    tool.write(path, c[3], c[2], [["other/test"]], [])
    assert tool.owed(path, c[3], "origin/main", FAST) == ["test/fast_b.py"]


def test_a_missing_record_breaks_the_chain(repo):
    path, c = repo
    tool.write(path, c[3], c[2], [["test/fast_a.py", "test/fast_b.py"]], [])
    assert tool.owed(path, c[3], "origin/main", FAST) is None  # c[1]..c[2] were never landed by land.py


def test_a_record_whose_base_is_not_an_ancestor_is_ignored(repo):
    path, c = repo
    tool.write(path, c[1], c[3], [["x"]], [])
    assert tool.owed(path, c[1], "origin/main", FAST) is None


def test_a_publish_push_reuses_the_heads_own_record_without_the_chain(repo, monkeypatch, capsys):
    path, c = repo
    tool.write(path, c[3], c[2], [["test/fast_a.py"]], [])  # c[1]..c[2] have no record: the chain is broken
    monkeypatch.chdir(path)
    assert tool.main(["owed", "--head", c[3], *FAST]) == 3
    assert tool.main(["owed", "--head", c[3], "--own", *FAST]) == 0
    assert capsys.readouterr().out.split() == ["test/fast_b.py"]
    assert tool.main(["owed", "--head", c[2], "--own", *FAST]) == 3  # no own record: the full gate as before
    hook = (ROOT / "tools" / "hooks" / "pre-push").read_text(encoding="utf-8")
    assert "${PUBLISH_REF:+--own}" in hook[hook.index("land_record.py owed"):][:200]


def test_nothing_past_origin_runs_the_gate_as_before(repo):
    path, c = repo
    assert tool.owed(path, c[0], "origin/main", FAST) is None


def test_the_hook_falls_back_when_the_helper_says_not_covered():
    hook = (ROOT / "tools" / "hooks" / "pre-push").read_text(encoding="utf-8")
    reuse = hook.index("land_record.py owed")
    assert reuse < hook.index('AFFECTED_BASE="$(git merge-base')
    assert "exit 0" in hook[reuse:hook.index('AFFECTED_BASE="$(git merge-base')]


def test_a_record_names_the_tier_the_landing_ran(repo):
    """The publish script finds a green FULL landing by this field, not by guessing from the invocations."""
    root, commits = repo
    tool.write(root, commits[1], commits[0], [["test"]], [], "full")
    tool.write(root, commits[2], commits[1], [["pkg/test"]], [])
    assert tool.read(root, commits[1])["tier"] == "full" and "tier" not in tool.read(root, commits[2])


def test_record_plan_is_pure_and_is_reused_by_the_writer(repo, monkeypatch):
    from harness.affected_exclusive import DEDICATED
    path, c = repo
    prepared = {'invocations': [DEDICATED], 'tier': 'full', 'candidate': c[2], 'main': c[1]}
    before = list(path.rglob('*'))
    assert tool.plan([DEDICATED], prepared, available=False) == [DEDICATED]
    assert list(path.rglob('*')) == before
    calls, plan = [], tool.plan
    def inspect(*args, **kwargs):
        calls.append((args, kwargs))
        return plan(*args, **kwargs)
    monkeypatch.setattr(tool, 'plan', inspect)
    tool.write(path, c[3], c[2], [DEDICATED], [], prepared=prepared)
    assert len(calls) == 1


@pytest.mark.parametrize('row', [{'pkg/test': 0}, 'pkg/test', [1], [''], []])
def test_record_plan_rejects_non_plan_shapes_instead_of_coercing_them(row):
    from harness.affected_exclusive import DEDICATED
    with pytest.raises(ValueError):
        tool.plan([DEDICATED, row], available=False)
