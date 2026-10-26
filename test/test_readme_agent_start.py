"""The shared-checkout doc and AGENTS.md both record the shared-checkout procedure.

A fresh session that opens only this repository must be able to start from
either file. docs/reference/shared-checkout.md (moved out of README on
2026-10-06 so the GitHub landing page carries no lab-PC paths) carries the
start order; README links it. AGENTS.md carries that order plus the commands.
"""

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
README = ROOT / "README.md"
SHARED = ROOT / "docs" / "reference" / "shared-checkout.md"
AGENTS = ROOT / "AGENTS.md"

WORKTREE = "python tools/worktrees.py new <짧은이름> <type>/<topic>"  # D-761: the gateway, not a bare add


def _readme_section(text: str) -> str:
    start = text.index("## 같이 하는 깃")
    return text[start:]


def _agents_section(text: str) -> str:
    start = text.index("### 같이 하는 깃")
    end = text.index("### Working In This Directory")
    assert start < end
    return text[start:end]


def test_readme_publishes_the_shared_checkout_start_before_the_product_contract():
    section = _readme_section(SHARED.read_text(encoding="utf-8"))
    assert "docs/reference/shared-checkout.md" in README.read_text(encoding="utf-8")

    assert "공개 기준" in section
    assert WORKTREE in section
    assert "git worktree list" in section
    assert "브랜치가 `main`이 아닌 것" in section
    assert "`feat`, `fix`, `refactor`, `docs`, `uiux`" in section
    assert "git add -A" in section
    assert "list.txt" in section
    assert "python test/known_failures.py" in section
    assert "$ROSY_SCRATCH\\<이름>\\run-1.txt" in section
    assert "pytest는 이 노트북에서 돌리지 않는다" in section
    assert "git merge --ff-only <브랜치>" in section
    assert "force-push는 하지 않는다" in section
    assert "rosy-land-on-main/SKILL.md" in section
    assert "AGENTS.md" in section
    assert "D-372" in section


def test_agents_md_records_the_shared_checkout_commands():
    section = _agents_section(AGENTS.read_text(encoding="utf-8"))

    assert WORKTREE in section
    assert "python tools/worktrees.py prune --apply" in section
    assert "14개(main 포함 15개) 이상이면 만들지 않고" in section and "누가 만들었든 깨끗하고" in section
    assert "소유자 기록이 없는 것은 `--all`을 줘야 다룬다" in section
    assert "기다리지 않고 바로 지운다" in section and "명령 하나 `python tools/worktrees.py prune --apply`" in section
    # D-790: landed worktrees wait 1 h, the two states that need a person, and the load-flaky rerun.
    assert "1시간" in section and "`landed-dirty`" in section and "`stale-history`" in section
    assert "`LOAD-FLAKY`" in section and "`test/flaky_quarantine.txt`로 옮긴다" in section
    assert "git worktree remove .worktrees" not in section  # one command, not two
    assert "`prune --snapshot`" in section and "사람이나 디스패처만 돌린다" in section
    assert "--snapshot --" not in section  # no ready-to-paste snapshot command for every session
    assert "git worktree lock" in section
    assert "git add -A" in section
    assert "git diff --cached --name-only" in section
    assert "git commit --only" in section
    assert "git apply --cached --unidiff-zero" in section
    assert "list.txt" in section
    assert "python tools/harness/adr_reserve.py next" in section
    assert "tools/harness/adr_gaps.txt" in section
    assert "adr_gaps" in section
    assert "UTF-8 BOM" in section
    assert "CRLF" in section
    assert "python tools/harness/rosy_harness.py lint" in section
    assert "python test/known_failures.py" in section
    assert "$ROSY_SCRATCH/<name>/run-1.txt" in section
    assert "tools/remote/remote_pytest.py" in section
    assert "git merge --ff-only <브랜치>" in section
    assert "python tools/harness/rosy_harness.py generate" in section
    assert "force-push는 하지 않는다" in section
    assert "D-372" in section
