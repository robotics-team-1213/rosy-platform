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
from hashlib import sha256
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


def test_logs_accept_english_field_labels():
    english = """## 2026-09-27 · uncommitted · docs: local verification
- Change: record the candidate
- Evidence: smoke passed
- Gate: field acceptance remains open
"""
    assert harness.validate_log(english) == []


def test_exact_legacy_heading_is_ignored_even_if_it_matches_current_schema():
    legacy = """## 2026-09-26 · uncommitted · docs(adr): propose D-282 per-hardware ROS ownership
- 변경: one concurrent branch version
"""
    assert harness.validate_log(legacy) == []


def test_committed_role_g2_heading_is_preserved_as_legacy():
    legacy = """## 2026-09-28 - uiux/device-refresh-access - rerun latest-main role G2
- First attempt: browser readiness check ran before release readback completed
- Rerun: 60 browser cells passed
- Gate: physical stop and field acceptance remain HOLD
"""
    assert harness.validate_log(legacy) == []


def test_append_only_logs_accept_legacy_evidence_label():
    legacy = GOOD_LOG.replace("- 증거:", "- 근거:")
    assert harness.validate_log(legacy) == []


def test_append_only_logs_accept_lowercase_english_gate_without_omitting_it():
    legacy = GOOD_LOG.replace("- gate 변화:", "- gate:")
    assert harness.validate_log(legacy) == []
    assert harness.validate_log(legacy.replace("- gate:", "- unrelated:"))


def test_append_only_logs_accept_static_review_as_legacy_evidence_label():
    legacy = GOOD_LOG.replace("- 증거:", "- 정적 확인:")
    assert harness.validate_log(legacy) == []


def test_append_only_logs_accept_validation_as_legacy_evidence_label():
    legacy = GOOD_LOG.replace("- 증거:", "- 검증:")
    assert harness.validate_log(legacy) == []


def test_append_only_logs_accept_device_evidence_as_legacy_label():
    legacy = GOOD_LOG.replace("- 증거:", "- 장치 근거:")
    assert harness.validate_log(legacy) == []


def test_append_only_logs_accept_committed_local_evidence_label():
    legacy = GOOD_LOG.replace("- 증거:", "- Local evidence:")
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


def test_logs_allow_exact_reconciliation_of_concurrent_pending_evidence():
    heading = "## 2026-10-02 · uncommitted · test(fleet): track Mission event watermark across replay"
    pending = (
        GOOD_LOG
        + f"\n{heading}\n"
        + "- Change: extend the two-ledger restart replay to verify four phase snapshots plus one terminal event, "
        + "then a separate goal-confirmation event.\n"
        + "- Evidence: targeted Mission, dispatcher, service, progress, task, OMX ActionStore, and replay suites: "
        + "pending final worktree verification.\n"
        + "- Gate: SOURCE/LOCAL only; remaining interruption fixtures and expiry/occupancy cases are still open.\n"
    )
    verified = pending.replace(
        "pending final worktree verification.",
        "77 passed; known-failure comparison: 0 new, 0 known.",
    )
    assert harness.is_append_only(pending, verified)
    changed_scope = verified.replace("four phase snapshots", "three phase snapshots")
    assert not harness.is_append_only(pending, changed_scope)


def test_encoding_repair_accepts_only_the_pinned_old_and_new_blocks(monkeypatch):
    old = "## 2026-10-04 ? uncommitted ? broken encoding\n- Change: ??"
    new = "## 2026-10-04 · uncommitted · recovered encoding\n- Change: verified source"
    monkeypatch.setattr(harness, "KNOWN_LOG_ENCODING_REPAIRS", {
        sha256(old.encode()).hexdigest(): sha256(new.encode()).hexdigest(),
    }, raising=False)
    assert harness.is_append_only(old, new)
    assert not harness.is_append_only(old + " altered", new)
    assert not harness.is_append_only(old, new + " altered")
    assert not harness.is_append_only(old, "")
    assert not harness.is_append_only(old + "\n## another entry\noriginal", new)


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


# --- D-346: commit-time collision defenses ----------------------------------


def test_duplicate_adr_index_rows_are_errors():
    """Two `| D-n |` rows used to collapse silently in the index dict (D-337)."""
    text = (
        "| ID | 제목 | Status |\n|---|---|---|\n"
        "| D-1 | 하나 | Accepted |\n"
        "| D-1 | 둘 | Accepted |\n"
        "## D-1 하나\n\n본문\n"
    )
    adr = harness.parse_adr_log(text)
    assert adr.index_duplicates == ("D-1",)
    assert "D-1: duplicate index row" in harness.validate_adr_log(adr, gaps={})


def test_mojibake_question_runs_are_found():
    """A console codepage that ate Korean shows up as literal '??' (D-336/D-140)."""
    corrupt = "| D-9 | ARM64 ?? ??? ?? |\n| D-10 | 온전한 행 |"
    assert harness.find_mojibake(corrupt) == [1]
    assert harness.find_mojibake("| D-10 | 온전한 행 | 이어폰? 아니고 |") == []


# --- D-427 wave 0: append-only check follows a moved module -----------------


def _git_repo(tmp_path: Path):
    import shutil
    import subprocess

    if shutil.which("git") is None:
        pytest.skip("needs git")

    def git(*args: str) -> str:
        return subprocess.run(["git", "-C", str(tmp_path), *args], check=True,
                              capture_output=True, text=True, encoding="utf-8").stdout.strip()

    git("init", "-q")
    git("config", "user.email", "harness@test")
    git("config", "user.name", "harness")
    git("config", "core.autocrlf", "false")
    return git


def test_append_only_follows_a_moved_module_through_legacy(tmp_path):
    git = _git_repo(tmp_path)
    for module in ("old/pkg", "old/pkg/sub"):
        (tmp_path / module).mkdir(parents=True, exist_ok=True)
        (tmp_path / module / "logs.md").write_text(GOOD_LOG, encoding="utf-8", newline="\n")
    git("add", "-A")
    git("commit", "-q", "-m", "before move")
    base = git("rev-parse", "HEAD")
    (tmp_path / "new").mkdir()
    git("mv", "old/pkg", "new/pkg")
    git("commit", "-q", "-m", "move")
    moved = [{"path": "new/pkg", "legacy": "old/pkg"}]

    assert harness._committed_log(tmp_path, base, "new/pkg", []) is None  # what lint saw before
    for module in ("new/pkg", "new/pkg/sub"):
        committed = harness._committed_log(tmp_path, base, module, moved)
        assert committed == GOOD_LOG, module
        edited = GOOD_LOG.replace("- 변경: a", "- 변경: rewritten")
        assert not harness.is_append_only(committed, edited)
    assert harness._committed_log(tmp_path, base, "new/other", moved) is None


def test_unfollowable_moved_log_is_reported_not_silently_passed(tmp_path):
    """A nested logs.md rewritten below git's 50 % rename similarity in the move
    commit has no traceable history; lint must say the check was skipped."""
    git = _git_repo(tmp_path)
    (tmp_path / "old/pkg/sub").mkdir(parents=True)
    (tmp_path / "old/pkg/logs.md").write_text(GOOD_LOG, encoding="utf-8", newline="\n")
    (tmp_path / "old/pkg/sub/logs.md").write_text(GOOD_LOG, encoding="utf-8", newline="\n")
    git("add", "-A")
    git("commit", "-q", "-m", "before move")
    base = git("rev-parse", "HEAD")
    (tmp_path / "new").mkdir()
    git("mv", "old/pkg", "new/pkg")
    rewritten = "# sample logs\n\n## 2026-10-03 · abcdef0 · feat: unrelated\n- 변경: z\n- 증거: none\n- gate 변화: 없음\n"
    (tmp_path / "new/pkg/sub/logs.md").write_text(rewritten, encoding="utf-8", newline="\n")
    edited_root = GOOD_LOG.replace("- 변경: a", "- 변경: rewritten")
    (tmp_path / "new/pkg/logs.md").write_text(edited_root, encoding="utf-8", newline="\n")
    git("add", "-A")
    git("commit", "-q", "-m", "move and rewrite")
    moved = [{"path": "new/pkg", "legacy": "old/pkg"}]

    errors, warnings_ = harness._append_only_findings(tmp_path, [base], "sub", "new/pkg/sub", rewritten, moved)
    assert errors == []
    assert len(warnings_) == 1 and "append-only check skipped" in warnings_[0] and "sub/logs.md" in warnings_[0]
    errors, warnings_ = harness._append_only_findings(tmp_path, [base], "pkg", "new/pkg", edited_root, moved)
    assert len(errors) == 1 and "were edited" in errors[0] and warnings_ == []
    # A module outside every moved root stays quiet, as before D-427.
    assert harness._append_only_findings(tmp_path, [base], "x", "brand/new", rewritten, moved) == ([], [])


@pytest.mark.parametrize("mutation", ["exact", "old", "new", "missing", "other_edit", "other_delete"])
def test_logs_only_reconcile_exact_unrecoverable_g2_record(mutation):
    old = """## 2026-10-04 ? uncommitted ? fix(g2): reserved startup home before Cell admission

- ??: G2 ?? ?? ??? ?? owner? ?? Pilot seat? ???? ???? ??? ??? ???. ??? ROS goal UUID? ?? ??? ?? ? ??? 0.5? ???? ???? seat ???reconciliation? ??? ? UDS? ????. stop/reset??? ???Fleet grant ??? ??? ???.
- ??: r3 SDK prepare PASS ? ? Action? PHASE_RUNNER_START_UNKNOWN?? HOLD, phase goal ??? 0??? cleanup? PASS??. spawn ?? HOME_DEVIATION???? ?? gripper GRIPPER_NOT_OPEN? planner? ????? r3? ?? ??? ????? ????. ?? ?? ??? ????? exact UUID ?? RED, 10Hz ?? poll ?? RED?GREEN, ?? SQLite ??? intent ??? ????.
- gate ??: SOURCE/LOCAL?. box16 ?? ???fault matrix??? ??????? ??? ?? HOLD/NOT_RUN, full_g2=false?. ?? ?? ??? ???? ? ????? ?????."""
    new = """## 2026-10-04 · 230ccfc2a · docs: record unrecoverable G2 journal corruption

- Change: Replace the corrupted journal entry introduced in commit 230ccfc2ae78116fc185688ed2627c9c2aeb211f. The original Korean text was irreversibly converted to question marks; this entry does not reconstruct it. The commit title records measured-home preparation through reserved Pilot admission.
- Evidence: The immutable original remains in deploy/logs.md at that commit. Normalized original block SHA256: a5eecc71690d74036c9e393a2a47262843dfd369b71fe0d6ff92c40a24730c49. Source paths include g2_startup.py, g2_owner.py, g2_runner.py and test_cell_g2_startup.py. No test or runtime result is inferred from the damaged text.
- Gate: Provenance correction only; ROS-SIM, DEVICE and FIELD acceptance are not established by this entry."""
    baseline = GOOD_LOG + "\n\n" + old
    corrected = GOOD_LOG + "\n\n" + new
    if mutation == "old":
        baseline = baseline.replace("reserved startup", "changed startup", 1)
    elif mutation == "new":
        corrected = corrected.replace("Provenance correction only", "Accepted in production", 1)
    elif mutation == "missing":
        corrected = GOOD_LOG
    elif mutation == "other_edit":
        corrected = corrected.replace("- 변경: a", "- 변경: altered")
    elif mutation == "other_delete":
        corrected = new
    assert harness.is_append_only(baseline, corrected) is (mutation == "exact")
