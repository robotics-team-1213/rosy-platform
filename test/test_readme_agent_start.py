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

WORKTREE = "git worktree add --relative-paths .worktrees/<짧은이름> -b <type>/<topic> main"


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
    assert "X:\\DevTemp\\<이름>\\run-1.txt" in section
    assert "pytest는 이 노트북에서 돌리지 않는다" in section
    assert "git merge --ff-only <브랜치>" in section
    assert "force-push는 하지 않는다" in section
    assert "rosy-land-on-main/SKILL.md" in section
    assert "AGENTS.md" in section
    assert "D-372" in section


def test_agents_md_records_the_shared_checkout_commands():
    section = _agents_section(AGENTS.read_text(encoding="utf-8"))

    assert WORKTREE in section
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
    assert "X:/DevTemp/<name>/run-1.txt" in section
    assert "tools/remote/remote_pytest.py" in section
    assert "git merge --ff-only <브랜치>" in section
    assert "python tools/harness/rosy_harness.py generate" in section
    assert "force-push는 하지 않는다" in section
    assert "D-372" in section
