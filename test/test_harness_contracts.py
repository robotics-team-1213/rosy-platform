"""Contracts for the module harness documents (design 2026-09-15, ADR D-61).

Each harness module keeps three records beside its ``AGENTS.md``:
``progress.md`` (overwritten gate snapshot), ``logs.md`` (append-only
journal) and a generated ``index.md``. Hand-maintained status drifted before —
70 of 96 AGENTS.md files stopped at 2026-09-02 and the workspace progress log
carried the same entries twice — so the shape is pinned here rather than left
to review.

The first half exercises the checker on small in-memory samples; the second
half runs it against the modules listed in ``tools/harness/harness.yaml``.
"""

from __future__ import annotations

import warnings
from pathlib import Path

import pytest

import rosy_harness as harness

ROOT = Path(__file__).resolve().parents[1]

GOOD_PROGRESS = """---
module: sample
logical_modules: [M03]
owner: CORE
last_verified: { commit: "084b93c", date: 2026-09-15 }
gates:
  SOURCE: { state: GO, evidence: "10 passed", cmd: "pytest sample" }
  LOCAL: { state: N/A }
  ROS-SIM: { state: N/A }
  ARTIFACT: { state: N/A }
  DEVICE: { state: HOLD, blocker: "Pi readback" }
  FIELD: { state: PARKED }
adrs: [D-1, D-2]
plans: []
---
## 지금 상태
ok
"""

GOOD_LOG = """# sample logs

## 2026-09-14 · 084b93c · feat: first
- 변경: a
- 증거: `pytest` 1 passed
- gate 변화: 없음

## 2026-09-15 · uncommitted · docs: second
- 변경: b
- 증거: 미실행 — 문서만 변경
- gate 변화: 없음
"""

GOOD_ADR = """# ROSY ADR Log

| ID | 제목 | Status |
|---|---|---|
| D-1 | one | Accepted |
| D-2 | two | Superseded by D-4 |
| D-4 | four | Accepted |

---

## D-1 one

**Status:** Accepted

## D-2 two

**Status:** Superseded by D-4

## D-4 four

**Status:** Accepted
"""


def _progress_meta(text: str = GOOD_PROGRESS) -> dict:
    meta, _ = harness.split_frontmatter(text)
    return meta


# --- frontmatter -----------------------------------------------------------


def test_frontmatter_is_split_from_the_body():
    meta, body = harness.split_frontmatter(GOOD_PROGRESS)
    assert meta["module"] == "sample"
    assert meta["gates"]["SOURCE"]["state"] == "GO"
    assert body.startswith("## 지금 상태")


def test_frontmatter_survives_a_windows_bom():
    meta, _ = harness.split_frontmatter("﻿" + GOOD_PROGRESS.replace("\n", "\r\n"))
    assert meta["module"] == "sample"


def test_missing_frontmatter_is_an_error():
    with pytest.raises(harness.HarnessError):
        harness.split_frontmatter("## no frontmatter\n")


# --- progress.md -----------------------------------------------------------


def test_valid_progress_has_no_errors():
    assert harness.validate_progress(_progress_meta(), known_adrs={"D-1", "D-2"}) == []


def test_evidence_from_an_uncommitted_tree_is_allowed():
    meta = _progress_meta()
    meta["last_verified"]["commit"] = "uncommitted"
    assert harness.validate_progress(meta) == []


def test_go_gate_needs_evidence():
    meta = _progress_meta()
    del meta["gates"]["SOURCE"]["evidence"]
    errors = harness.validate_progress(meta)
    assert any("SOURCE" in e and "evidence" in e for e in errors)


def test_go_gate_needs_a_rerunnable_command():
    meta = _progress_meta()
    del meta["gates"]["SOURCE"]["cmd"]
    errors = harness.validate_progress(meta)
    assert any("SOURCE" in e and "cmd" in e for e in errors)


def test_hold_gate_needs_a_blocker():
    meta = _progress_meta()
    del meta["gates"]["DEVICE"]["blocker"]
    errors = harness.validate_progress(meta)
    assert any("DEVICE" in e and "blocker" in e for e in errors)


@pytest.mark.parametrize(
    "mutate, fragment",
    [
        (lambda m: m["gates"].update({"PROD": {"state": "GO", "evidence": "x", "cmd": "y"}}), "PROD"),
        (lambda m: m["gates"].pop("LOCAL"), "LOCAL"),
        (lambda m: m["gates"]["FIELD"].update({"state": "DONE"}), "DONE"),
        (lambda m: m["last_verified"].pop("commit"), "last_verified"),
        (lambda m: m["last_verified"].update({"commit": 1234567}), "last_verified"),
        (lambda m: m.pop("owner"), "owner"),
        (lambda m: m.update({"adrs": ["D-99"]}), "D-99"),
        (lambda m: m.update({"adrs": ["ADR-1"]}), "ADR-1"),
    ],
)
def test_malformed_progress_is_reported(mutate, fragment):
    meta = _progress_meta()
    mutate(meta)
    errors = harness.validate_progress(meta, known_adrs={"D-1", "D-2"})
    assert any(fragment in e for e in errors), errors


# --- logs.md ---------------------------------------------------------------


def test_valid_log_has_no_errors():
    assert harness.validate_log(GOOD_LOG) == []
    assert [e.summary for e in harness.parse_log(GOOD_LOG)] == ["feat: first", "docs: second"]


def test_append_only_logs_accept_legacy_evidence_label():
    legacy = GOOD_LOG.replace("- 증거:", "- 근거:")
    assert harness.validate_log(legacy) == []


def test_headings_inside_code_fences_are_entry_text():
    assert harness.validate_log(GOOD_LOG + "\n```markdown\n## not an entry\n```\n") == []


def test_duplicate_log_entries_are_rejected():
    entry = GOOD_LOG.split("\n## 2026-09-15")[0].split("# sample logs\n")[1]
    errors = harness.validate_log(GOOD_LOG + entry)
    assert any("duplicate" in e for e in errors), errors


@pytest.mark.parametrize(
    "broken, fragment",
    [
        (GOOD_LOG.replace("## 2026-09-14 · 084b93c · feat: first", "## 2026/09/14 feat: first"), "heading"),
        (GOOD_LOG.replace("2026-09-14 · 084b93c", "2026-19-45 · 084b93c"), "date"),
        (GOOD_LOG.replace("- 증거: `pytest` 1 passed\n", ""), "증거"),
        (GOOD_LOG.replace("2026-09-15 · uncommitted", "2026-09-13 · uncommitted"), "order"),
    ],
)
def test_malformed_logs_are_reported(broken, fragment):
    errors = harness.validate_log(broken)
    assert any(fragment in e for e in errors), errors


def test_logs_must_not_lose_or_edit_committed_entries():
    # 항목 보존(순서 무관) — 끝 추가·병합 재배열은 합격, 내용 변형은 위반.
    assert harness.is_append_only(GOOD_LOG, GOOD_LOG + "\n## 2026-09-16 · abcdef0 · x\n")
    assert harness.is_append_only(GOOD_LOG.replace("\n", "\r\n"), GOOD_LOG)
    assert not harness.is_append_only(GOOD_LOG, GOOD_LOG.replace("- 변경: a", "- 변경: rewritten"))


def test_logs_tolerate_merge_reordering_but_not_loss_or_edits():
    """두 세션이 각자 항목을 추가한 브랜치를 병합하면 순서가 섞인다 — 보존만 되면 합격."""
    a = GOOD_LOG + "\n## 2026-09-20 · abcdef1 · a-entry\n\n- 변경: a1\n"
    b = GOOD_LOG + "\n## 2026-09-20 · abcdef2 · b-entry\n\n- 변경: b1\n"
    merged = GOOD_LOG + "\n## 2026-09-20 · abcdef2 · b-entry\n\n- 변경: b1\n\n## 2026-09-20 · abcdef1 · a-entry\n\n- 변경: a1\n"
    assert harness.is_append_only(a, merged)   # a 의 항목이 가운데 끼여도 보존이다
    assert harness.is_append_only(b, merged)   # 반대 방향에서도 같다
    lost = merged.replace("## 2026-09-20 · abcdef1 · a-entry\n\n- 변경: a1\n", "", 1)
    assert not harness.is_append_only(merged, lost)          # 항목 유실은 위반
    edited = merged.replace("- 변경: b1", "- 변경: b1 (변형)", 1)
    assert not harness.is_append_only(merged, edited)        # 본문 변형도 위반


# --- ADR log ---------------------------------------------------------------


def test_consistent_adr_log_with_declared_gap_passes():
    adr = harness.parse_adr_log(GOOD_ADR)
    assert adr.index["D-2"] == ("two", "Superseded by D-4")
    assert harness.validate_adr_log(adr, gaps={"D-3": "reserved"}) == []


def test_colon_style_adr_heading_is_still_a_body_section():
    # D-36 was recorded as "## D-36: title (date)"; the log is append-only, so
    # the checker reads that form instead of asking for the heading to change.
    adr = harness.parse_adr_log(GOOD_ADR.replace("## D-4 four", "## D-4: four (2026-09-08)"))
    assert adr.bodies["D-4"] == "four (2026-09-08)"
    assert harness.validate_adr_log(adr, gaps={"D-3": "reserved"}) == []


def test_undeclared_adr_gap_is_reported():
    errors = harness.validate_adr_log(harness.parse_adr_log(GOOD_ADR), gaps={})
    assert any("D-3" in e for e in errors), errors


def test_declared_gap_that_now_exists_is_reported():
    errors = harness.validate_adr_log(harness.parse_adr_log(GOOD_ADR), gaps={"D-3": "r", "D-4": "r"})
    assert any("D-4" in e for e in errors), errors


@pytest.mark.parametrize(
    "broken, fragment",
    [
        (GOOD_ADR.replace("| D-4 | four | Accepted |\n", ""), "index"),
        (GOOD_ADR.replace("| D-4 | four | Accepted |", "| D-4 | four | Accepted | extra |"), "index"),
        (GOOD_ADR.replace("## D-4 four", "## four"), "body"),
    ],
)
def test_adr_index_and_bodies_must_match(broken, fragment):
    errors = harness.validate_adr_log(harness.parse_adr_log(broken), gaps={"D-3": "r"})
    assert any(fragment in e and "D-4" in e for e in errors), errors


# --- the repository --------------------------------------------------------


@pytest.fixture(scope="module")
def config() -> dict:
    return harness.load_config(ROOT)


@pytest.fixture(scope="module")
def adr_log(config):
    return harness.parse_adr_log((ROOT / config["adr_log"]).read_text(encoding="utf-8"), ROOT / "docs" / "adr")


def test_config_names_existing_modules(config):
    assert config["modules"], "harness.yaml lists no modules"
    for module in config["modules"]:
        base = ROOT / module["path"]
        for name in ("AGENTS.md", "progress.md", "logs.md", "index.md"):
            assert (base / name).is_file(), f"{module['name']}: missing {name}"
        for test_path in module.get("tests", []):
            assert (ROOT / test_path).exists(), f"{module['name']}: missing test path {test_path}"


def test_module_agents_point_at_the_harness_records(config):
    for module in config["modules"]:
        agents = (ROOT / module["path"] / "AGENTS.md").read_text(encoding="utf-8")
        assert "progress.md" in agents and "logs.md" in agents, module["name"]


def test_every_progress_snapshot_is_valid(config, adr_log):
    known = set(adr_log.index)
    for module in config["modules"]:
        text = (ROOT / module["path"] / "progress.md").read_text(encoding="utf-8")
        meta, _ = harness.split_frontmatter(text)
        errors = harness.validate_progress(meta, known_adrs=known)
        assert meta.get("module") == module["name"], f"{module['name']}: module field mismatch"
        for plan in meta.get("plans") or []:
            if not (ROOT / plan).is_file():
                errors.append(f"plan not found: {plan}")
        assert errors == [], f"{module['name']}: {errors}"


def test_every_module_log_is_valid(config):
    for module in config["modules"]:
        text = (ROOT / module["path"] / "logs.md").read_text(encoding="utf-8")
        errors = harness.validate_log(text)
        assert errors == [], f"{module['name']}: {errors}"


def test_repository_adr_log_is_contiguous_and_indexed(config, adr_log):
    assert harness.validate_adr_log(adr_log, gaps=config.get("adr_gaps") or {}) == []


def test_generated_records_are_current():
    stale = harness.check_generated(ROOT)
    assert stale == [], (
        f"regenerate with `python tools/harness/rosy_harness.py generate`: {stale}"
    )


def test_empty_ci_base_ref_falls_back_to_the_merge_base(monkeypatch):
    # CI passes `${{ github.event.pull_request.base.sha || github.event.before }}`,
    # which can be empty; that must not silently shrink the check to HEAD only.
    monkeypatch.setenv("HARNESS_BASE_REF", "")
    monkeypatch.setattr(harness, "_git", lambda repo, *args: "abc1234\n" if args[0] == "merge-base" else None)
    refs, note = harness._history_refs(ROOT)
    assert refs == ["abc1234", "HEAD"] and note is None


@pytest.mark.parametrize("bad_ref", ["0" * 40, "deadbeef" * 5])
def test_unresolvable_ci_base_ref_falls_back_with_a_warning(monkeypatch, bad_ref):
    # A new-branch push sends 40 zeros; a force-push leaves `before` unfetched.
    # Either must widen to the merge base and say so, not silently skip the check.
    monkeypatch.setenv("HARNESS_BASE_REF", bad_ref)
    monkeypatch.setattr(harness, "_git", lambda repo, *args: "abc1234\n" if args[0] == "merge-base" else None)
    refs, note = harness._history_refs(ROOT)
    assert refs == ["abc1234", "HEAD"]
    assert note and bad_ref[:12] in note


def test_valid_ci_base_ref_is_checked_alongside_the_merge_base(monkeypatch):
    monkeypatch.setenv("HARNESS_BASE_REF", "feedfac")
    answers = {"merge-base": "abc1234\n", "rev-parse": "feedfac0000\n"}
    monkeypatch.setattr(harness, "_git", lambda repo, *args: answers.get(args[0]))
    refs, note = harness._history_refs(ROOT)
    assert refs == ["feedfac", "abc1234", "HEAD"] and note is None


def test_session_brief_carries_status_and_the_loop():
    brief = harness.render_brief(ROOT)
    for module in harness.load_config(ROOT)["modules"]:
        assert module["name"] in brief
    assert "logs.md" in brief and "generate" in brief


def test_session_brief_survives_a_malformed_record(tmp_path):
    # The brief exists to show what is broken; one bad record must not blank it.
    (tmp_path / "tools" / "harness").mkdir(parents=True)
    (tmp_path / "tools" / "harness" / "harness.yaml").write_text(
        "modules:\n  - {name: good, path: good}\n  - {name: bad, path: bad}\n", encoding="utf-8"
    )
    (tmp_path / "good").mkdir()
    (tmp_path / "good" / "progress.md").write_text(GOOD_PROGRESS, encoding="utf-8")
    (tmp_path / "bad").mkdir()
    (tmp_path / "bad" / "progress.md").write_text("---\nmodule: bad\ngates: {SOURCE: GO}\n---\n", encoding="utf-8")
    brief = harness.render_brief(tmp_path)
    assert "SOURCE=GO" in brief and "DEVICE=HOLD" in brief
    assert "- bad" in brief and "invalid progress.md" in brief


def test_conflict_markers_are_found_only_at_line_starts():
    text = "a\n<<<<<<< ours\nb\n=======\nc\n>>>>>>> theirs\nprose `=======` inline\n"
    assert harness.find_conflict_markers(text) == [2, 4, 6]
    assert harness.find_conflict_markers(GOOD_ADR + GOOD_LOG) == []


def test_full_lint_including_git_history_checks():
    # Append-only and staleness need git history; without it lint says so as a
    # warning instead of passing silently.
    errors, notes = harness.lint(ROOT)
    for note in notes:
        warnings.warn(note, stacklevel=1)
    assert errors == []
