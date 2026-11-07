"""D-970 3: an explicit FULL and its publication reuse an ancestor's clean pass only where the delta reaches nothing."""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path
import subprocess
import sys
from types import SimpleNamespace

import pytest

ROOT = Path(__file__).resolve().parents[1]
_SPEC = importlib.util.spec_from_file_location("publish_main", ROOT / "tools" / "publish_main.py")
tool = importlib.util.module_from_spec(_SPEC)
sys.modules[_SPEC.name] = tool
_SPEC.loader.exec_module(tool)
import land_cache  # noqa: E402
from publish_fixtures import FULL, candidate_files, qualified_record  # noqa: E402

SUITE = ["learning/registry/policy/test"]
# the selector a candidate carries: --full gives the fixture plan, otherwise fixture-selection.json at that commit
HARNESS = ("import json, pathlib, sys\n"
           "if '--full' in sys.argv:\n"
           f"    print(json.dumps({{'mode': 'full', 'full_invocations': {FULL[:3]!r}}}))\n"
           "else:\n"
           "    print(pathlib.Path('fixture-selection.json').read_text())\n")


def _git(repo: Path, *args: str) -> str:
    return subprocess.run(["git", "-C", str(repo), *args], check=True, capture_output=True, text=True).stdout.strip()


def _commit(repo: Path, files: dict[str, str]) -> str:
    for name, text in files.items():
        (repo / name).parent.mkdir(parents=True, exist_ok=True)
        (repo / name).write_text(text, encoding="utf-8")
    _git(repo, "add", *files)
    _git(repo, "commit", "-q", "-m", ",".join(files))
    return _git(repo, "rev-parse", "HEAD")


def _selection(*paths: str) -> str:
    return json.dumps({"mode": "affected", "invocations": [[p] for p in paths]})


@pytest.fixture
def repo(tmp_path):
    local = tmp_path / "local"
    _git(tmp_path, "init", "-q", "-b", "main", str(local))
    for key, value in (("user.email", "t@example.com"), ("user.name", "t")):
        _git(local, "config", key, value)
    _commit(local, {"app.py": "0"})
    candidate_files(local)
    earlier = _commit(local, {"tools/harness/rosy_harness.py": HARNESS, "fixture-selection.json": _selection("pkg/test")})
    qualified_record(tool, local, earlier, _git(local, "rev-parse", f"{earlier}^"))  # every FULL invocation passed
    return local, earlier


def _final(local: Path, files: dict[str, str]) -> str:
    """A fix commit after the earlier FULL: only the root and timing invocations run on it."""
    sha = _commit(local, files)
    own = [inv for inv in FULL if inv[0] in ("test",) or land_cache._paths(inv) is None]
    logs = qualified_record(tool, local, sha, _git(local, "rev-parse", f"{sha}^"), own)
    tool.land_record.write(local, sha, _git(local, "rev-parse", f"{sha}^"), FULL, logs, tier="full")
    return sha


def _why(local: Path, sha: str) -> str | None:
    return tool.publish_evidence.reason(tool, local, sha, tool.land_record.read(local, sha))


def test_publish_accepts_an_ancestor_pass_the_recomputed_delta_does_not_reach(repo):
    local, _ = repo
    sha = _final(local, {"app.py": "1", "fixture-selection.json": _selection("pkg/test")})
    assert _why(local, sha) is None


def test_publish_refuses_when_the_delta_reaches_the_reused_suite(repo):
    local, _ = repo
    sha = _final(local, {"app.py": "1", "fixture-selection.json": _selection(SUITE[0] + "/test_one.py")})
    assert "missing clean exact execution/log proof for " + SUITE[0] in _why(local, sha)


def test_publish_refuses_when_a_known_failure_list_changed(repo):
    local, _ = repo
    sha = _final(local, {"test/known_failures.txt": "x::y\n"})
    assert _why(local, sha).startswith("missing clean exact execution/log proof")


@pytest.mark.parametrize("damage", ["dirty", "missing"])
def test_publish_refuses_an_ancestor_row_whose_log_is_not_clean(repo, damage):
    local, earlier = repo
    row = next(e for e in land_cache.entries(local) if e["commit"] == earlier and e["argv"] == SUITE)
    log = Path(row["log"])
    log.write_text("1 failed in 0.01s\n", encoding="utf-8") if damage == "dirty" else log.unlink()
    sha = _final(local, {"app.py": "1"})
    assert _why(local, sha).startswith("missing clean exact execution/log proof")


@pytest.mark.parametrize("selected, reused", [("pkg/test", True), (SUITE[0], False)])
def test_explicit_full_landing_reuses_only_suites_the_delta_does_not_reach(repo, selected, reused):
    local, _ = repo
    head = _commit(local, {"app.py": "1", "fixture-selection.json": _selection(selected)})
    args = SimpleNamespace(tests="full", no_cache=False)
    lines, todo, _ = land_cache.split(local, args, [SUITE], head, sys.executable, select=None)
    assert (todo == []) is reused and any(land_cache.NARROW in line for line in lines) is reused
