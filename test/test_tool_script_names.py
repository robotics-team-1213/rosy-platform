"""Scripts under tools/ run with their own folder first on sys.path."""

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_no_tool_script_shadows_a_repo_package():
    # 2026-10-26: tools/release/deploy.py hid the deploy package (deploy.hosts) and turned main red.
    top = {p.name for p in ROOT.iterdir() if p.is_dir() and not p.name.startswith(".")}
    clashes = sorted(str(p.relative_to(ROOT)) for p in (ROOT / "tools").rglob("*.py") if p.stem in top)
    assert not clashes, clashes
