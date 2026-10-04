"""The GitHub README is the published shared-checkout procedure.

A fresh session that opens only this repository must be able to start work
from README section 「같이 하는 깃」. The lab umbrella Agents.md is outside
the git repo, so a pointer at a Windows path is not a start procedure.
"""

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
README = ROOT / "README.md"


def _section(text: str) -> str:
    start = text.index("## 같이 하는 깃")
    end = text.index("## 핵심 계약")
    assert start < end
    return text[start:end]


def test_readme_publishes_the_shared_checkout_start_before_the_product_contract():
    section = _section(README.read_text(encoding="utf-8"))

    assert "공개 기준" in section
    assert "git worktree add --relative-paths .worktrees/<짧은이름> -b <type>/<topic> main" in section
    assert "git worktree list" in section
    assert "브랜치가 `main`이 아닌 것" in section
    assert "`feat`, `fix`, `refactor`, `docs`, `uiux`" in section
    assert "git add -A" in section
    assert "list.txt" in section
    assert "python test/known_failures.py" in section
    assert "X:\\DevTemp\\<이름>\\run.txt" in section
    assert "git merge --ff-only <브랜치>" in section
    assert "force-push는 하지 않는다" in section
    assert "rosy-land-on-main/SKILL.md" in section
    assert "D-372" in section
