"""D-766 3 pure-move check (tools/harness/split_check.py) on a throwaway git repo."""

import shutil
import subprocess

import pytest

import split_check

pytestmark = pytest.mark.skipif(shutil.which("git") is None, reason="git is required")

ORIGINAL = '''"""Old module."""
import os

ROOT = "a/b"
MODE = "enforce"


def keep(x):
    return os.path.join(ROOT, x)


class Moved:
    def run(self):
        return keep("y")
'''


@pytest.fixture
def repo(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    for key, value in {"GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@x", "GIT_COMMITTER_NAME": "t",
                       "GIT_COMMITTER_EMAIL": "t@x"}.items():
        monkeypatch.setenv(key, value)

    def git(*args):
        return subprocess.run(["git", *args], capture_output=True, text=True, check=True).stdout.strip()

    def commit(files):
        for path, text in files.items():
            (tmp_path / path).parent.mkdir(parents=True, exist_ok=True)
            (tmp_path / path).write_text(text, encoding="utf-8")
        git("add", "-A")
        git("commit", "-q", "--no-verify", "-m", "c")
        return git("rev-parse", "HEAD")

    git("init", "-q", "-b", "main")
    git.base = commit({"pkg.py": ORIGINAL, "caller.py": "from pkg import Moved\n\nMoved().run()\n"})
    git.commit = commit
    return git


def test_moving_a_class_to_its_own_file_is_pure(repo, capsys):
    keep_only = ORIGINAL.split("class Moved")[0].rstrip() + "\n"
    moved = '"""New home."""\nfrom pkg import keep\n\n\nclass Moved:\n    def run(self):\n        return keep("y")\n'
    repo.commit({"pkg.py": keep_only, "moved.py": moved,
                 "caller.py": "from moved import Moved\n\nMoved().run()\n"})
    assert split_check.main([repo.base, "HEAD"]) == 0
    assert "AST identical, only imports/paths changed" in capsys.readouterr().out


def test_an_edit_during_the_move_is_named(repo, capsys):
    keep_only = ORIGINAL.split("class Moved")[0].rstrip() + "\n"
    moved = 'from pkg import keep\n\n\nclass Moved:\n    def run(self):\n        return keep("z")\n'
    repo.commit({"pkg.py": keep_only, "moved.py": moved})
    assert split_check.main([repo.base, "HEAD"]) == 1
    assert "differ: Moved" in capsys.readouterr().err


def test_a_dropped_definition_is_not_a_move(repo):
    repo.commit({"pkg.py": ORIGINAL.replace("def keep(x):\n    return os.path.join(ROOT, x)\n", "")})
    assert split_check.compare(repo.base, "HEAD")[2] == ["keep"]


def _keep_only():
    return ORIGINAL.split("class Moved")[0].rstrip() + "\n"


MOVED = 'from pkg import keep\n\n\nclass Moved:\n    def run(self):\n        return keep("y")\n'
CALLER_MOVED = "from moved import Moved\n\nMoved().run()\n"


def test_a_flipped_string_constant_is_not_a_move(repo, capsys):
    repo.commit({"pkg.py": _keep_only().replace('"enforce"', '"shadow"'), "moved.py": MOVED})
    assert split_check.main([repo.base, "HEAD"]) == 1
    assert "MODE = 'enforce' -> 'shadow'" in capsys.readouterr().err


def test_a_moved_path_string_may_change(repo):
    repo.commit({"pkg.py": _keep_only().replace('"a/b"', '"a/c"'), "moved.py": MOVED, "caller.py": CALLER_MOVED})
    assert split_check.compare(repo.base, "HEAD")[2] == []


def test_a_swapped_import_target_is_not_a_move(repo):
    repo.commit({"pkg.py": _keep_only(), "moved.py": MOVED,
                 "caller.py": "from elsewhere import Moved\n\nMoved().run()\n"})
    assert split_check.compare(repo.base, "HEAD")[2] == ["import Moved -> elsewhere:Moved"]


def test_reordered_definitions_are_not_a_move(repo):
    keep = "def keep(x):\n    return os.path.join(ROOT, x)\n"
    reordered = ORIGINAL.replace(keep + "\n\n", "") + "\n\n" + keep
    repo.commit({"pkg.py": reordered})
    assert any("order changed" in item for item in split_check.compare(repo.base, "HEAD")[2])


def test_a_changed_non_python_file_is_never_pure(repo, capsys):
    repo.commit({"pkg.py": _keep_only(), "moved.py": MOVED, "caller.py": CALLER_MOVED, "site/page.js": "x = 1;\n"})
    assert split_check.main([repo.base, "HEAD"]) == 1
    assert "non-.py files changed: site/page.js" in capsys.readouterr().err
