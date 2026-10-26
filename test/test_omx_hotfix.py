"""tools/remote/omx_hotfix.py: temp-index commit, test-log gate, idempotent deploy, atomic link switch.

subprocess.run is stubbed throughout: no git writes, no network, no remote pytest.
"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools" / "remote"))

import omx_hotfix as oh  # noqa: E402

SHA = "0123456789abcdef0123456789abcdef01234567"
SHORT = SHA[:10]


class Fake:
    """Records every call; answers git/ssh by the first matching rule (substring of the joined argv)."""

    def __init__(self, rules=None):
        self.calls, self.rules = [], dict(rules or {})

    def __call__(self, cmd, **kw):
        self.calls.append((cmd, kw))
        joined = " ".join(cmd)
        out = next((v for k, v in self.rules.items() if k in joined), "")
        if not kw.get("text"):
            out = out.encode() if isinstance(out, str) else out
        return subprocess.CompletedProcess(cmd, 0, out, b"" if not kw.get("text") else "")

    def joined(self):
        return [" ".join(cmd) for cmd, _ in self.calls]

    def ssh_scripts(self):
        return [cmd[-1] for cmd, _ in self.calls if cmd[0] == "ssh"]


@pytest.fixture
def fake(monkeypatch):
    stub = Fake({"rev-parse": SHA})
    monkeypatch.setattr(oh.subprocess, "run", stub)
    return stub


def passing_log(tmp_path, text="..\n3 passed, 1 skipped in 2.10s\n[remote-pytest] memory peak 90 MiB\n", sha=SHA):
    log = tmp_path / "run-1.txt"
    log.write_text(text, encoding="utf-8")
    (tmp_path / oh.SHA_FILE).write_text(sha + "\n", encoding="utf-8")
    return log


def test_commit_uses_a_temporary_index_and_the_wip_ref(fake, tmp_path):
    fake.rules.update({"ls-tree": "100755 blob aaaa\tdeploy/robot/omx/run.sh", "hash-object": "b" * 40,
                       "write-tree": "c" * 40, "commit-tree": "d" * 40})
    local = tmp_path / "run.sh"
    local.write_text("echo\n")
    sha = oh.commit("main", "arm-s", [("deploy/robot/omx/run.sh", str(local))], "fix arm S")
    assert sha == "d" * 40
    names = [cmd[1] for cmd, _ in fake.calls]
    assert names == ["rev-parse", "read-tree", "ls-tree", "hash-object", "update-index", "write-tree",
                     "commit-tree", "update-ref"]
    by = {cmd[1]: (cmd, kw) for cmd, kw in fake.calls}
    index = {kw["env"]["GIT_INDEX_FILE"] for name, (_, kw) in by.items()
             if name in ("read-tree", "update-index", "write-tree")}
    assert len(index) == 1 and ".git" not in index.pop()  # one temp index, never the shared one
    for name in ("hash-object", "commit-tree", "update-ref"):
        assert by[name][1].get("env") is None
    assert by["read-tree"][0][-1] == SHA
    assert by["update-index"][0][-1] == f"100755,{'b' * 40},deploy/robot/omx/run.sh"  # mode kept
    assert by["hash-object"][0][2:] == ["-w", "--path=deploy/robot/omx/run.sh", "--", str(local)]
    assert by["commit-tree"][0][2:] == ["c" * 40, "-p", SHA, "-m", "fix arm S"]
    assert by["update-ref"][0][2:] == ["refs/rosy-wip/arm-s", "d" * 40]


def test_new_file_gets_plain_mode(fake, tmp_path):
    fake.rules.update({"hash-object": "b" * 40})
    oh.commit("main", "x", [("deploy/robot/omx/new.py", __file__)], "m")
    assert [c for c in fake.joined() if "update-index" in c][0].endswith(f"100644,{'b' * 40},deploy/robot/omx/new.py")


@pytest.mark.parametrize("bad", ["/etc/passwd", "../x", "C:/x", "a\\b", ""])
def test_file_arg_rejects_paths_outside_the_repo(bad):
    with pytest.raises(SystemExit):
        oh._file_arg(f"{bad}={__file__}")


def test_test_runs_remote_pytest_only_and_records_the_sha(fake, tmp_path):
    assert oh.test("HEAD", tmp_path, ["test/test_omx_hotfix.py"]) == 0
    cmd = fake.calls[-1][0]
    assert cmd[1].endswith("remote_pytest.py") and cmd[2:] == [
        "--sha", SHA, "--log-dir", str(tmp_path), "--", "test/test_omx_hotfix.py"]
    assert (tmp_path / oh.SHA_FILE).read_text().strip() == SHA


@pytest.mark.parametrize("text, sha", [
    ("3 passed in 1.00s\n", "f" * 40),                          # log from another sha
    ("== 1 failed, 3 passed in 1.00s ==\n", SHA),
    ("3 passed, 1 error in 1.00s\n", SHA),
    ("2 passed in 1.0s\n...\n1 failed in 0.5s\n", SHA),         # only the last summary counts
    ("collected 0 items\nno tests ran in 0.01s\n", SHA),
    ("[remote-pytest] lost contact\n", SHA),
])
def test_deploy_refuses_without_a_passing_log_for_this_sha(fake, tmp_path, text, sha):
    with pytest.raises(SystemExit, match="refusing to deploy"):
        oh.deploy("HEAD", "user@host", passing_log(tmp_path, text, sha))
    assert fake.ssh_scripts() == [] and not any("archive" in c for c in fake.joined())


def test_deploy_refuses_a_log_without_the_sha_marker(fake, tmp_path):
    log = tmp_path / "run-1.txt"
    log.write_text("3 passed in 1.00s\n")
    with pytest.raises(SystemExit, match="refusing"):
        oh.deploy("HEAD", "user@host", log)
    assert fake.ssh_scripts() == []


def test_deploy_ships_archive_then_switches(fake, tmp_path):
    fake.rules.update({"archive": b"TARGZ", "readlink": "omx-tools-aaaaaaaaaa"})
    folder, previous = oh.deploy("HEAD", "user@host", passing_log(tmp_path))
    assert (folder, previous) == (f"~/rosy-test/omx-tools-{SHORT}", "omx-tools-aaaaaaaaaa")
    archive = [cmd for cmd, _ in fake.calls if "archive" in cmd][0]
    assert f"--add-virtual-file=omx-tools-{SHORT}/REVISION:{SHORT}\n" in archive
    assert archive[-3:] == [SHA, *oh.PATHS]
    unpack = [(cmd, kw) for cmd, kw in fake.calls if cmd[0] == "ssh" and "tar -xzf -" in cmd[-1]]
    assert len(unpack) == 1 and unpack[0][1]["input"] == b"TARGZ"
    assert f"mv .omx-tools-{SHORT}.part/omx-tools-{SHORT} omx-tools-{SHORT}" in unpack[0][0][-1]
    assert "mv -T" in fake.ssh_scripts()[-1]


def test_deploy_is_idempotent_when_revision_matches(fake, tmp_path):
    fake.rules.update({"REVISION": SHORT, "readlink": f"omx-tools-{SHORT}"})
    oh.deploy("HEAD", "user@host", passing_log(tmp_path))
    oh.deploy("HEAD", "user@host", passing_log(tmp_path))
    assert not any("archive" in c for c in fake.joined())
    assert not any("tar -xzf" in s for s in fake.ssh_scripts())
    assert sum("mv -T" in s for s in fake.ssh_scripts()) == 2  # link still (re)pointed


def test_switch_renames_a_temp_link_over_the_live_one():
    script = oh.switch_script(f"omx-tools-{SHORT}")
    ln = script.index(f"ln -sfn omx-tools-{SHORT} .omx-tools-current.tmp")
    mv = script.index("mv -T .omx-tools-current.tmp omx-tools-current")
    assert script.index("readlink omx-tools-current") < ln < mv
    assert "ln -sfn omx-tools-" + SHORT + " omx-tools-current" not in script  # never relink in place


def test_host_comes_from_flag_or_env_only(monkeypatch):
    monkeypatch.delenv(oh.HOST_ENV, raising=False)
    with pytest.raises(SystemExit, match=oh.HOST_ENV):
        oh.host_of(None)
    monkeypatch.setenv(oh.HOST_ENV, "u@h")
    assert oh.host_of(None) == "u@h" and oh.host_of("v@k") == "v@k"


def test_status_lists_link_and_recent_folders(fake):
    fake.rules.update({"readlink": "current: omx-tools-aaaaaaaaaa"})
    assert oh.status("u@h") == "current: omx-tools-aaaaaaaaaa"
    script = fake.ssh_scripts()[0]
    assert "readlink omx-tools-current" in script and "omx-tools-??????????" in script and "head -5" in script
