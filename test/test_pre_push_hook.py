"""pre-push 훅의 지켜볼 것들 (D-346·D-347 회차).

훅 전체를 돌리는 건 push 자체와 같아서 시험로는 무겁다 — 여기선 두 가지만 고정한다:
파싱이 살아있고, '재생성됐지만 미커밋인 생성 기록은 push 를 막는다'는 가드가
스크립트에 존재한다. 가드의 실동 증명은 실제 push 에서 보인다(2026-09-29 두 건의
CI 적신이 이 가드의 명세다).
"""

from pathlib import Path
import shutil
import subprocess

import pytest

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "tools" / "hooks" / "pre-push"
BASH = shutil.which("bash")


@pytest.mark.skipif(BASH is None, reason="bash is required")
def test_the_hook_parses():
    assert subprocess.run([BASH, "-n", str(SCRIPT)], capture_output=True).returncode == 0


@pytest.mark.skipif(BASH is None, reason="bash is required")
def test_regenerated_but_uncommitted_records_block_the_push():
    text = SCRIPT.read_text(encoding="utf-8")
    assert "uncommitted generated records" in text, (
        "the dirty-generated guard must stay in the hook: a push with a "
        "regenerated-but-uncommitted index ships the stale committed copy "
        "(red CI on 2026-09-29, twice)"
    )
    assert "generated_targets(repo)" in text, (
        "the guard must enumerate the exact harness targets, not a glob — "
        "an unrelated index.md must never block a push"
    )
