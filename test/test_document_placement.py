"""D-226: publication first, then the owning folder. CI runs this with test/."""

import re
import shutil
import subprocess
from pathlib import Path, PurePosixPath

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[1]

# D-226 table "gitignore로 막는 것": sample paths that must never be committable.
MUST_IGNORE = [
    "private/strategy-draft.md",
    ".env",
    "deploy/robot/.env",
    "deploy/robot/.env.site",
    "deploy/robot/site.local.env",
    "src/site/games/config/match.local.yaml",
    "deploy/sd/provision.json",
    "deploy/sd/rosy-config.yaml",
    "id_ed25519",
    "id_rsa.pub",
    "release.key",
    "rosy-diag-pinky-01-0a1b2c3d-20260925T000000Z.tar.gz",
    "pinky.img.xz",
    "ubuntu.iso",
    "run.mcap",
    "rosbag2_2026_09_25/metadata.yaml",
    "data/teleop/session.csv",
    "data/drive/run/track.csv",
    ".claude/worktrees/agent-x/README.md",
    ".worktrees/topic/README.md",
    "fleet.sqlite3",
]

# D-226 table "추적하는 것": templates and public material next to the secrets.
MUST_TRACK = [
    "deploy/robot/.env.example",
    "deploy/robot/native/rosy-runtime.env",
    "deploy/robot/native/rosy-diag",
    "deploy/sd/rosy-config.template.yaml",
    "deploy/sd/provision.schema.json",
    "deploy/release/public-keys/rosy-release-2026-01.pem",
    "firmware/signal/observer/config.example.json",
    "data/teleop/learning/teleop_20260919_151213_part01.mp4",
]

ROOT_FILES = {
    ".dockerignore", ".gitattributes", ".gitignore",
    "AGENTS.md", "CONCEPTS.md", "LICENSE", "README.md", "STATUS.md", "env.sh",
}
MODULE_ROOT_DOCS = {"README.md", "AGENTS.md", "CLAUDE.md", "progress.md", "logs.md", "index.md"}
# Accepted ADRs that name a module-root file keep it there until superseded.
MODULE_ROOT_EXCEPTIONS = {"src/runtime/control/STEPS.txt"}


def _git(*args: str) -> str:
    if shutil.which("git") is None or not (ROOT / ".git").exists():
        pytest.skip("D-226 boundary checks need a git checkout")
    done = subprocess.run(
        ["git", *args], cwd=ROOT, capture_output=True, text=True, encoding="utf-8", check=False,
    )
    assert done.returncode in (0, 1), done.stderr
    return done.stdout


def _tracked() -> list[str]:
    return [line for line in _git("ls-files").splitlines() if line]


def test_no_tracked_file_sits_under_an_ignore_rule():
    # A force-added secret or a rule that swallows a template both show up here.
    assert _git("ls-files", "-ci", "--exclude-standard").split() == []


def test_secret_and_internal_paths_are_ignored():
    ignored = set(_git("check-ignore", "--no-index", *MUST_IGNORE).splitlines())
    assert sorted(set(MUST_IGNORE) - ignored) == []


def test_templates_beside_the_secrets_stay_tracked():
    tracked = set(_tracked())
    assert sorted(set(MUST_TRACK) - tracked) == []
    assert _git("check-ignore", "--no-index", *MUST_TRACK).split() == []


def test_repo_root_carries_only_the_listed_files():
    root = {path for path in _tracked() if "/" not in path}
    assert sorted(root - ROOT_FILES) == []


def test_dated_evidence_does_not_live_inside_modules():
    # A result template is not evidence (D-226 rule 4); only dated entries move.
    dated = re.compile(r"/docs/validation/.*\d{4}-\d{2}-\d{2}")
    stray = [path for path in _tracked() if path.startswith("src/") and dated.search(path)]
    assert stray == []


def test_module_roots_carry_only_the_listed_documents():
    tracked = _tracked()
    registry = yaml.safe_load((ROOT / "tools" / "harness" / "harness.yaml").read_text(encoding="utf-8"))
    roots = {item["path"] for item in registry["modules"]}
    roots |= {str(PurePosixPath(path).parent) for path in tracked if path.endswith("/package.xml")}
    stray = []
    for path in tracked:
        pure = PurePosixPath(path)
        if str(pure.parent) not in roots or pure.suffix not in (".md", ".txt"):
            continue
        if pure.name in MODULE_ROOT_DOCS or pure.name.startswith(("requirements", "CMakeLists")):
            continue
        if path not in MODULE_ROOT_EXCEPTIONS:
            stray.append(path)
    assert stray == []
