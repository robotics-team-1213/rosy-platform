"""Publication needs executed canonical FULL evidence, including real browser chunks."""

from argparse import Namespace
import hashlib
import json
from pathlib import Path
import sys

import pytest

from test_publish_main import FULL, _commit, _git, _view, repo, tool
from publish_fixtures import qualified_record
import land_cache
from harness import affected_exclusive as exclusive


def _timing_proof(repo):
    local, _ = repo
    source = Path(__file__).resolve().parents[1] / 'tools/harness/affected_exclusive.py'
    _commit(local, 'tools/harness/affected_exclusive.py', source.read_text(encoding='utf-8'))
    full = [['learning/registry/policy/test'], ['test', '--ignore=' + exclusive.TARGET],
            exclusive.DEDICATED, *FULL[2:]]
    # The fixture's browser chunks are appended by the actual immutable-candidate consumer.
    from publish_fixtures import BROWSERS
    full = full[:3] + BROWSERS
    script = 'import json\nprint(json.dumps(' + repr({'mode': 'full', 'full_invocations': full[:3]}) + '))\n'
    sha = _commit(local, 'tools/harness/rosy_harness.py', script)
    logs = qualified_record(tool, local, sha, _git(local, 'rev-parse', f'{sha}^'), full)
    log = Path(logs[2])
    log.write_text('[g1-timing-gate] expected=2 collected=2 passed=2 skipped=0 clean=1\n'
                   '2 passed in 0.01s\n', encoding='utf-8')
    _record_updated_log(local, log)
    return local, sha, log


def test_canonical_exclusive_full_with_hash_bound_strict_receipt_qualifies(repo):
    local, sha, _ = _timing_proof(repo)
    assert tool.green_full(local, sha)


@pytest.mark.parametrize('damage', ['missing', 'skip', 'partial', 'quarantine', 'hash', 'ignore-only'])
def test_publication_requires_complete_strict_dedicated_evidence(repo, damage):
    local, sha, log = _timing_proof(repo)
    if damage == 'ignore-only':
        record = tool.land_record.read(local, sha)
        record['invocations'].remove(exclusive.DEDICATED)
        (tool.land_record.folder(local) / f'{sha}.json').write_text(json.dumps(record), encoding='utf-8')
    else:
        text = {'missing': '2 passed in 0.01s\n',
                'skip': '[g1-timing-gate] expected=2 collected=2 passed=1 skipped=1 clean=0\n1 passed, 1 skipped in 0.01s\n',
                'partial': '[g1-timing-gate] expected=2 collected=1 passed=1 skipped=0 clean=0\n1 passed in 0.01s\n',
                'quarantine': '2 passed in 0.01s\nLOAD-FLAKY\n',
                'hash': '999 passed in 0.01s\n'}[damage]
        log.write_text(text, encoding='utf-8')
        if damage != 'hash':
            _record_updated_log(local, log)
    assert not tool.green_full(local, sha)


@pytest.mark.parametrize('mode', ['exact', 'narrow', 'no-cache'])
def test_dedicated_execution_mapping_never_replaces_a_fresh_run(repo, monkeypatch, tmp_path, mode):
    local, _ = repo
    sha = _git(local, 'rev-parse', 'HEAD')
    monkeypatch.setattr(land_cache, 'env_id', lambda *_: 'fixture-env')
    tree = _git(local, 'rev-parse', 'HEAD^{tree}')
    previous = tmp_path / 'previous.txt'
    previous.write_text('2 passed in 0.01s\n', encoding='utf-8')
    land_cache.record(local, sha, tree, 'fixture-env', exclusive.DEDICATED, previous)
    if mode == 'narrow':
        sha = _commit(local, 'unrelated.py', '# unrelated\n')
    reused, todo, keep = land_cache.split(local, Namespace(no_cache=mode == 'no-cache', tests='auto'),
                                         [exclusive.DEDICATED], sha, sys.executable,
                                         lambda *a, **k: ([], False))
    assert reused == [] and todo == [exclusive.DEDICATED]
    fresh = tmp_path / 'fresh.txt'
    fresh.write_text('2 passed in 0.01s\n', encoding='utf-8')
    keep(exclusive.DEDICATED, fresh)
    assert land_cache.entries(local)[-1]['log_sha256'] == hashlib.sha256(fresh.read_bytes()).hexdigest()


@pytest.mark.parametrize("legacy", [False, True])
def test_tier_or_root_test_marker_without_execution_proof_never_qualifies(repo, monkeypatch, legacy):
    local, _ = repo
    sha = _commit(local, "app.py", "unproven FULL")
    tool.land_record.write(local, sha, _git(local, "rev-parse", f"{sha}^"), FULL, [],
                           tier=None if legacy else "full")
    assert tool.publish_sha(local) is None
    calls = []
    monkeypatch.setattr(tool, "run_gh", lambda _, *args: calls.append(args) or _view(local, sha))
    with pytest.raises(tool.Stop, match="no green FULL"):
        tool.merge_when_green(local, "7", True, tool.datetime.now(tool.timezone.utc))
    assert not any(args[:2] == ("pr", "merge") for args in calls)


def test_no_cache_forbids_reuse_but_preserves_fresh_exact_execution_proof(repo, monkeypatch, tmp_path):
    local, _ = repo
    sha = _commit(local, "app.py", "fresh evidence")
    inv = ["test"]
    monkeypatch.setattr(land_cache, "env_id", lambda *_: "fixture-env")
    reused, todo, keep = land_cache.split(local, Namespace(no_cache=True, tests="full"), [inv],
                                         sha, sys.executable, None)
    log = tmp_path / "fresh.txt"
    log.write_text("1 passed in 0.01s\n", encoding="utf-8")
    keep(inv, log)
    assert reused == [] and todo == [inv]
    row, = land_cache.entries(local)
    assert (row["commit"], row["tree"], row["env"], row["argv"], row["log"]) == (
        sha, _git(local, "rev-parse", f"{sha}^{{tree}}"), "fixture-env", inv, str(log))
    assert row["log_sha256"] == hashlib.sha256(log.read_bytes()).hexdigest()


def _proof(repo):
    local, _ = repo
    sha = _commit(local, "app.py", "qualified FULL")
    logs = qualified_record(tool, local, sha, _git(local, "rev-parse", f"{sha}^"))
    return local, sha, logs


def _rewrite_rows(local, change):
    rows = land_cache.entries(local)
    change(rows)
    land_cache.path(local).write_text("".join(json.dumps(row) + "\n" for row in rows), encoding="utf-8")


def _record_updated_log(local, log):
    row = next(row for row in land_cache.entries(local) if row["log"] == str(log))
    land_cache.record(local, row["commit"], row["tree"], row["env"], row["argv"], log)


def _deny_selection_and_merge(local, sha, monkeypatch):
    assert tool.publish_sha(local) != sha
    calls = []
    monkeypatch.setattr(tool, "run_gh", lambda _, *args: calls.append(args) or _view(local, sha))
    with pytest.raises(tool.Stop, match="no green FULL"):
        tool.merge_when_green(local, "7", True, tool.datetime.now(tool.timezone.utc))
    assert not any(args[:2] == ("pr", "merge") for args in calls)


def test_canonical_full_with_every_exact_opted_in_browser_chunk_qualifies(repo):
    local, sha, _ = _proof(repo)
    assert tool.green_full(local, sha)
    assert tool.publish_sha(local) == sha


def test_another_clean_execution_on_the_same_candidate_preserves_the_recorded_log_mapping(repo):
    local, sha, logs = _proof(repo)
    row = land_cache.entries(local)[-1]
    log = Path(logs[-1]).with_name("later-clean.txt")
    log.write_text("1 passed in 0.01s\n", encoding="utf-8")
    land_cache.record(local, sha, row["tree"], row["env"], row["argv"], log)
    assert tool.green_full(local, sha)


@pytest.mark.parametrize("damage", ["opt-in", "alone", "missing", "duplicate", "ordinary-invocation"])
def test_canonical_full_and_browser_chunks_cannot_be_replaced_by_partial_or_duplicate_coverage(
        repo, monkeypatch, damage):
    local, sha, _ = _proof(repo)
    record = tool.land_record.read(local, sha)
    invs = record["invocations"]
    if damage == "opt-in":
        invs[-1].remove("ROSY_RUN_BROWSER_TESTS=1")
    elif damage == "alone":
        invs[-2].remove("ROSY_BROWSER_ALONE=1")
    elif damage == "duplicate":
        invs[-1] = invs[-2][:]
    elif damage == "ordinary-invocation":
        invs.pop(0)
    else:
        invs.pop()
    (tool.land_record.folder(local) / f"{sha}.json").write_text(json.dumps(record), encoding="utf-8")
    _deny_selection_and_merge(local, sha, monkeypatch)


@pytest.mark.parametrize("damage", ["commit", "tree", "env", "argv", "log-missing", "log-empty",
                                   "all-skip", "partial-skip", "failure", "error", "load-flaky", "zero-tests"])
def test_exact_execution_mapping_and_usable_browser_verdict_are_required(repo, monkeypatch, damage):
    local, sha, logs = _proof(repo)
    if damage in ("commit", "tree", "env", "argv"):
        value = ["test/test_dashboard_browser.py"] if damage == "argv" else "a" * 40
        _rewrite_rows(local, lambda rows: rows[-1].update({damage: value}))
    else:
        log = Path(logs[-1])
        if damage == "log-missing":
            log.unlink()
        else:
            text = {"log-empty": "", "all-skip": "1 skipped in 0.01s\n",
                    "partial-skip": "1 passed, 1 skipped in 0.01s\n",
                    "failure": "FAILED test/test_dashboard_browser.py::test_dashboard - bad\n1 failed in 0.01s\n",
                    "error": "ERROR test/test_dashboard_browser.py::test_dashboard - bad\n1 error in 0.01s\n",
                    "load-flaky": "1 passed in 0.01s\nLOAD-FLAKY test_dashboard\n",
                    "zero-tests": "no tests ran in 0.01s\n"}[damage]
            log.write_text(text, encoding="utf-8")
            _record_updated_log(local, log)
    _deny_selection_and_merge(local, sha, monkeypatch)


def test_real_work_queue_shards_are_complete_proof_but_one_missing_shard_is_not(repo, monkeypatch):
    import work_queue
    local, _ = repo
    for n in range(5):
        _commit(local, f"test/test_shard_{n}.py", f"def test_{n}(): pass\n" + "# size\n" * n)
    sha = _git(local, "rev-parse", "HEAD")
    logs = qualified_record(tool, local, sha, _git(local, "rev-parse", f"{sha}^"))
    root = ["test"]
    parts = work_queue.split(local, [root], seen={tuple(root): 3 * work_queue.SPLIT_S})
    assert len(parts) == 3
    _rewrite_rows(local, lambda rows: rows.remove(next(r for r in rows if r["argv"] == root)))
    tree, env = _git(local, "rev-parse", f"{sha}^{{tree}}"), land_cache.env_id(local, sha)
    folder = Path(logs[0]).parent
    shard_logs = []
    for n, part in enumerate(parts):
        log = folder / f"shard-{n}.txt"
        log.write_text("2 passed in 0.01s\n", encoding="utf-8")
        land_cache.record(local, sha, tree, env, part, log)
        shard_logs.append(str(log))
    record = tool.land_record.read(local, sha)
    record["logs"] = [log for log in logs if log != logs[1]] + shard_logs
    (tool.land_record.folder(local) / f"{sha}.json").write_text(json.dumps(record), encoding="utf-8")
    assert tool.green_full(local, sha)
    _rewrite_rows(local, lambda rows: rows.pop())
    _deny_selection_and_merge(local, sha, monkeypatch)


@pytest.mark.parametrize("changed", [None, "plan", "environment"])
def test_prepared_full_proof_requires_matching_final_plan_and_environment(repo, monkeypatch, changed):
    local, prepared, _ = _proof(repo)
    base = _git(local, "rev-parse", f"{prepared}^")
    if changed == "plan":
        harness = local / "tools/harness/rosy_harness.py"
        text = harness.read_text(encoding="utf-8").replace("'full_invocations': [", "'full_invocations': [['new/test'], ")
        sha = _commit(local, str(harness.relative_to(local)), text)
    elif changed == "environment":
        sha = _commit(local, "fixture-wheel/setup.py", "# changed installed wheel\n")
    else:
        _git(local, "checkout", "-qb", "peer", base)
        final_base = _commit(local, "peer.py", "main advanced")
        _git(local, "checkout", "-q", "main")
        _git(local, "merge", "-q", "--no-ff", "--no-edit", "peer")
        sha = _git(local, "rev-parse", "HEAD")
    delta = [["test/test_dashboard_browser.py"]]
    qualified_record(tool, local, sha, prepared if changed else final_base, delta,
                     prepared={"candidate": prepared, "main": base, "tier": "full", "invocations": FULL})
    if changed:
        _deny_selection_and_merge(local, sha, monkeypatch)
    else:
        assert tool.green_full(local, sha)


@pytest.mark.parametrize("change", ["own-commit", "manual-merge"])
def test_prepared_proof_cannot_cover_new_branch_code_or_a_hand_edited_merge(repo, monkeypatch, change):
    local, prepared, _ = _proof(repo)
    on = _git(local, "rev-parse", f"{prepared}^")
    if change == "own-commit":
        sha = _commit(local, "app.py", "untested branch code")
        base = on
    else:
        _git(local, "checkout", "-qb", "peer", on)
        base = _commit(local, "peer.py", "main advanced")
        _git(local, "checkout", "-q", "main")
        _git(local, "merge", "-q", "--no-ff", "--no-commit", "peer")
        sha = _commit(local, "app.py", "manual merge changed untested code")
    qualified_record(tool, local, sha, base, [["test/test_dashboard_browser.py"]],
                     prepared={"candidate": prepared, "main": on, "tier": "full", "invocations": FULL})
    _deny_selection_and_merge(local, sha, monkeypatch)


@pytest.mark.parametrize("change", ["hashless-legacy", "same-path-clean-overwrite"])
def test_execution_proof_binds_the_original_log_bytes(repo, monkeypatch, change):
    local, sha, logs = _proof(repo)
    if change == "hashless-legacy":
        _rewrite_rows(local, lambda rows: [row.pop("log_sha256", None) for row in rows])
    else:
        Path(logs[-1]).write_text("999 passed in 0.02s\n", encoding="utf-8")
    _deny_selection_and_merge(local, sha, monkeypatch)


def test_normal_ros_only_skip_and_approved_quarantine_rerun_keep_existing_verdict_policy(repo):
    import known_failures
    local, _ = repo
    nodeid = "learning/registry/policy/test/test_one.py::test_one"
    sha = _commit(local, "test/flaky_quarantine.txt", nodeid + "  # fixture approved rerun\n")
    logs = qualified_record(tool, local, sha, _git(local, "rev-parse", f"{sha}^"))
    Path(logs[0]).write_text("1 skipped in 0.01s\n", encoding="utf-8")
    _record_updated_log(local, Path(logs[0]))
    assert tool.green_full(local, sha)
    Path(logs[0]).write_text(f"FAILED {nodeid} - transient\n1 failed in 0.01s\n"
                            f"{known_failures.RERUN_MARKER}\nPASSED {nodeid}\n1 passed in 0.01s\n",
                            encoding="utf-8")
    _record_updated_log(local, Path(logs[0]))
    assert tool.green_full(local, sha)
