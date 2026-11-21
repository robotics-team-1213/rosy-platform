"""D-1061 records cutover: unnumbered API fragments, the bot's numbering, the PR lint rule, ADR guard."""

from __future__ import annotations

import datetime as dt
import os
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))
sys.path.insert(0, str(ROOT / "tools" / "harness"))

import new_record  # noqa: E402
import records_rules as rules  # noqa: E402

REF_TEXT = """# ROSY API & Protocol Reference

**Document ID:** ROSY-API-REF-001
**Version:** v1.433
**Status:** Approved

### v1.433 old change

old body

# 11. 변경 이력

| 버전 | 일자 | 내용 |
|---|---|---|
| v1.433 | 2026-11-21 | old |
"""


def _git(repo: Path, *args: str, date: str | None = None) -> str:
    env = dict(os.environ, GIT_AUTHOR_DATE=date, GIT_COMMITTER_DATE=date) if date else None
    return subprocess.run(["git", "-C", str(repo), *args], check=True, capture_output=True, text=True,
                          encoding="utf-8", env=env).stdout


def _repo(tmp_path: Path) -> Path:
    repo = tmp_path / "repo"
    (repo / "docs" / "reference").mkdir(parents=True)
    (repo / "docs" / "adr").mkdir(parents=True)
    (repo / rules.API_REF).write_text(REF_TEXT, encoding="utf-8")
    contract = repo / rules.CONTRACT_FILE
    contract.parent.mkdir(parents=True)
    contract.write_text('CONTRACT = "ROSY-API-REF-001 v1.433"\n', encoding="utf-8")
    (repo / rules.ADR_LOG).write_text("| ID | 제목 | Status |\n|---|---|---|\n| D-1 | one | Accepted |\n", encoding="utf-8")
    (repo / "docs" / "adr" / "D-1-one.md").write_text("## D-1 one\n", encoding="utf-8")
    (repo / "mod").mkdir()
    (repo / "mod" / "logs.md").write_text("# logs\n", encoding="utf-8")
    _git(repo, "init", "-q", "-b", "main")
    _git(repo, "config", "user.email", "t@example.com")
    _git(repo, "config", "user.name", "T")
    _git(repo, "add", ".")
    _git(repo, "commit", "-qm", "base", date="2026-11-20T00:00:00+00:00")
    return repo


def test_two_fragments_on_one_surface_get_consecutive_numbers_in_date_slug_order(tmp_path):
    repo = _repo(tmp_path)
    new_record.write_api_fragment(repo, "zeta-field", surface="core", title="zeta (v1.next)", body="see v1.next",
                                  date="2026-11-21")
    new_record.write_api_fragment(repo, "alpha-field", surface="core", title="alpha", history="Additive: a|b",
                                  date="2026-11-21")
    new_record.write_api_fragment(repo, "drop-old", surface="fleet", title="drop old", kind="breaking",
                                  reason="no consumer left", date="2026-11-22")
    assigned = new_record.consolidate_api(repo, today="2026-11-23")
    assert assigned == [("alpha-field", "v1.434"), ("zeta-field", "v1.435"), ("drop-old", "v1.436")]
    ref = (repo / rules.API_REF).read_text(encoding="utf-8")
    assert "**Version:** v1.436" in ref and "**Version:** v1.433" not in ref
    # newest first, above the old sections; the placeholder takes the assigned number
    order = [ref.index(h) for h in ("### v1.436 drop old (Fleet, breaking)", "### v1.435 zeta (v1.435) (CORE)",
                                    "### v1.434 alpha (CORE)", "### v1.433 old change")]
    assert order == sorted(order)
    assert "see v1.435" in ref and "**Breaking.** 사유: no consumer left" in ref
    rows = [ln for ln in ref.splitlines() if ln.startswith("| v1.")]
    assert rows[:3] == ["| v1.436 | 2026-11-23 | [Fleet, breaking] drop old |",
                        "| v1.435 | 2026-11-23 | [CORE] zeta (v1.435) |",
                        "| v1.434 | 2026-11-23 | [CORE] Additive: a\\|b |"]
    assert (repo / rules.CONTRACT_FILE).read_text(encoding="utf-8") == 'CONTRACT = "ROSY-API-REF-001 v1.436"\n'
    assert not list((repo / rules.API_CHANGES).glob("*.md"))
    assert new_record.consolidate_api(repo) == []  # nothing left: a second run changes nothing


def test_fragment_validation(tmp_path):
    ok = "---\nsurface: cell\nkind: additive\nslug: x\ndate: 2026-11-21\ntitle: t\n---\nbody\n"
    assert rules.validate_fragment("x.md", ok) == []
    assert rules.validate_fragment("y.md", ok) == ["slug 'x' differs from the file name"]
    breaking = ok.replace("additive", "breaking")
    assert rules.validate_fragment("x.md", breaking) == ["breaking fragment needs a reason"]
    assert rules.validate_fragment("x.md", ok.replace("cell", "robot"))[0].startswith("surface 'robot'")
    with pytest.raises(SystemExit):
        new_record.write_api_fragment(tmp_path, "v1.440-x", surface="core", title="t")
    assert not (tmp_path / rules.API_CHANGES).exists()


def _pr_commit(repo: Path, date: str, edit) -> str:
    base = _git(repo, "rev-parse", "HEAD").strip()
    edit(repo)
    _git(repo, "add", ".")
    _git(repo, "commit", "-qm", "pr", date=date)
    return base


def _bump_header(repo: Path) -> None:
    path = repo / rules.API_REF
    path.write_text(path.read_text(encoding="utf-8").replace("v1.433\n**Status", "v1.434\n**Status"), encoding="utf-8")


CUT = dt.datetime(2026, 11, 21, 6, tzinfo=dt.timezone.utc)


def test_new_pr_editing_shared_lines_fails_and_grandfathered_or_bot_pass(tmp_path):
    repo = _repo(tmp_path)
    base = _pr_commit(repo, "2026-11-21T07:00:00+00:00", _bump_header)
    logs = ["mod/logs.md"]
    errors, _ = rules.cutover_findings(repo, base, logs, branch_name="feat/x", event="pull_request", cut=CUT)
    assert len(errors) == 1 and "Version" in errors[0] and "new_record.py" in errors[0]
    # bot branch, merge queue, and no cutover yet: not enforced
    assert rules.cutover_findings(repo, base, logs, branch_name="bot/records-refresh", event="pull_request", cut=CUT) == ([], [])
    assert rules.cutover_findings(repo, base, logs, branch_name="feat/x", event="merge_group", cut=CUT) == ([], [])
    assert rules.cutover_findings(repo, base, logs, branch_name="feat/x", event="", cut=None) == ([], [])
    # a PR whose first own commit predates the cutover keeps the old way, even after more commits
    assert rules.cutover_findings(repo, base, logs, branch_name="feat/x", event="pull_request",
                                  cut=CUT + dt.timedelta(hours=2)) == ([], [])


def test_new_pr_editing_logs_contract_or_adr_rows_fails_but_fragments_pass(tmp_path):
    repo = _repo(tmp_path)

    def edit(r: Path) -> None:
        (r / "mod" / "logs.md").write_text("# logs\n\n## new\n", encoding="utf-8")
        (r / rules.CONTRACT_FILE).write_text('CONTRACT = "ROSY-API-REF-001 v1.434"\n', encoding="utf-8")
        log = r / rules.ADR_LOG
        log.write_text(log.read_text(encoding="utf-8") + "| D-2 | two | Accepted |\n", encoding="utf-8")

    base = _pr_commit(repo, "2026-11-21T07:00:00+00:00", edit)
    errors, _ = rules.cutover_findings(repo, base, ["mod/logs.md"], branch_name="feat/x", event="", cut=CUT)
    assert [e.split(":")[0] for e in errors] == ["mod/logs.md", rules.CONTRACT_FILE, rules.ADR_LOG]

    repo2 = _repo(tmp_path / "two")
    base2 = _pr_commit(repo2, "2026-11-21T07:00:00+00:00", lambda r: new_record.write_api_fragment(
        r, "new-field", surface="core", title="new field", date="2026-11-21"))
    assert rules.cutover_findings(repo2, base2, ["mod/logs.md"], branch_name="feat/x", event="", cut=CUT) == ([], [])
    assert rules.fragment_findings(repo2) == []


def test_cutover_time_is_when_the_marker_reached_main(tmp_path):
    repo = _repo(tmp_path)
    assert rules.cutover_time(repo, "main") is None
    marker = repo / rules.MARKER
    marker.parent.mkdir(parents=True, exist_ok=True)
    marker.write_text("marker\n", encoding="utf-8")
    _git(repo, "add", ".")
    _git(repo, "commit", "-qm", "cutover", date="2026-11-21T06:00:00+00:00")
    assert rules.cutover_time(repo, "main") == CUT


def test_adr_number_guard(tmp_path):
    repo = _repo(tmp_path)
    _git(repo, "branch", "upstream")
    (repo / "docs" / "adr" / "D-1-other.md").write_text("## D-1 other\n", encoding="utf-8")
    errors = rules.adr_number_findings(repo, None)
    assert errors == ["docs/adr: D-1 used by D-1-one.md, D-1-other.md"]
    (repo / "docs" / "adr" / "D-1-other.md").unlink()
    # upstream got D-2 first; this PR adds a different D-2 file
    _git(repo, "switch", "-q", "upstream")
    (repo / "docs" / "adr" / "D-2-theirs.md").write_text("## D-2 theirs\n", encoding="utf-8")
    _git(repo, "add", ".")
    _git(repo, "commit", "-qm", "theirs")
    _git(repo, "switch", "-q", "main")
    base = _pr_commit(repo, "2026-11-21T07:00:00+00:00",
                      lambda r: (r / "docs" / "adr" / "D-2-mine.md").write_text("## D-2 mine\n", encoding="utf-8"))
    errors = rules.adr_number_findings(repo, base, refs=("upstream",))
    assert len(errors) == 1 and "D-2-mine.md: D-2 already taken by D-2-theirs.md" in errors[0]
    assert rules.adr_number_findings(repo, base, refs=()) == []


def test_lenient_findings_become_warnings_unless_strict():
    errors = ["D-9: body section missing from index", "D-3: duplicate index row"]
    lenient = lambda e: rules.LENIENT_ADR in e  # noqa: E731
    assert rules.split_strict(errors, True, lenient) == (errors, [])
    kept, warned = rules.split_strict(errors, False, lenient)
    assert kept == ["D-3: duplicate index row"] and warned[0].startswith("D-9")


def test_adr_log_row_sync_is_newest_first_with_link_and_status(tmp_path):
    repo = _repo(tmp_path)
    (repo / "docs" / "adr" / "D-2-two.md").write_text("## D-2 two things\n\n**Status:** Accepted (2026-11-21, 사용자)\n",
                                                      encoding="utf-8")
    assert new_record._sync_adr_log(repo, repo / rules.ADR_LOG) == ["D-2"]
    lines = (repo / rules.ADR_LOG).read_text(encoding="utf-8").splitlines()
    assert lines[2] == "| D-2 | two things. [전문](../adr/D-2-two.md) | Accepted (2026-11-21, 사용자) |"


def _entry(day: str, tag: str) -> str:
    return f"## {day} · uncommitted · feat(mod): {tag}\n\n- 변경: x\n- 증거: y\n- gate 변화: 없음"


def _fold(existing: list[str], shards: list[str]) -> list[str]:
    out = new_record._insert_by_date("# logs\n\n" + "\n\n".join(existing) + "\n", shards)
    return [ln for ln in out.splitlines() if ln.startswith("## ")]


def test_log_fold_normal_case_appends_in_order():
    heads = _fold([_entry("2026-11-20", "a")], [_entry("2026-11-21", "b"), _entry("2026-11-22", "c")])
    assert [h[3:13] for h in heads] == ["2026-11-20", "2026-11-21", "2026-11-22"]


def test_log_fold_inserts_older_shard_at_its_dated_position():
    heads = _fold([_entry("2026-11-19", "a"), _entry("2026-11-21", "b")], [_entry("2026-11-20", "late")])
    assert [h[3:13] for h in heads] == ["2026-11-19", "2026-11-20", "2026-11-21"]
    assert "late" in heads[1]


def test_log_fold_same_date_shards_follow_existing_and_keep_shard_order():
    heads = _fold([_entry("2026-11-20", "old"), _entry("2026-11-21", "new")],
                  [_entry("2026-11-20", "s1"), _entry("2026-11-20", "s2")])
    assert [h.rsplit(": ", 1)[1] for h in heads] == ["old", "s1", "s2", "new"]
    text = new_record._insert_by_date("# logs\n", [_entry("2026-11-20", "only")])
    assert text.startswith("# logs\n\n## 2026-11-20") and text.endswith("\n")
