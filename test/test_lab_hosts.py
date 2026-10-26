"""D-226: lab SSH endpoints load from gitignored private/lab-hosts.json."""

import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools" / "remote"))

import lab_hosts  # noqa: E402


def test_missing_file_loads_nothing(monkeypatch):
    monkeypatch.delenv("ROSY_LAB_HOSTS", raising=False)
    monkeypatch.setattr(lab_hosts, "host_file", lambda: None)
    assert lab_hosts.load() == {}
    assert lab_hosts.test_hosts() == []
    assert lab_hosts.site_host() == ""
    assert lab_hosts.robots() == {}


def test_override_path_is_the_only_source(monkeypatch, tmp_path):
    path = tmp_path / "lab-hosts.json"
    path.write_text(json.dumps({
        "test_hosts": ["model@lab", "  ", "ai@lab"],
        "site_host": " site@lab ",
        "robots": {"aa": "10.0.0.8", "bb": "  "},
    }), encoding="utf-8")
    monkeypatch.setenv("ROSY_LAB_HOSTS", str(path))
    assert lab_hosts.test_hosts() == ["model@lab", "ai@lab"]
    assert lab_hosts.site_host() == "site@lab"
    assert lab_hosts.robots() == {"aa": "10.0.0.8"}


def test_example_file_has_placeholders_only():
    example = json.loads((lab_hosts.ROOT / "tools" / "remote" / "hosts.example.json").read_text(encoding="utf-8"))
    text = json.dumps(example)
    assert "<model-pc>" in text and "<robot-ip>" in text
    for token in ("100.98.162.71", "100.108.76.123", "100.82.51.8", "192.168.1.201", "192.168.1.202"):
        assert token not in text


def test_worktree_private_dir_is_the_main_checkout(tmp_path):
    repo = tmp_path / "repo"
    gitdir = repo / ".git" / "worktrees" / "topic"
    gitdir.mkdir(parents=True)
    start = tmp_path / "topic"
    start.mkdir()
    (start / ".git").write_text(f"gitdir: {gitdir}\n", encoding="utf-8")
    assert lab_hosts.main_checkout(start) == repo.resolve()


def test_relative_gitdir_resolves_to_the_main_checkout(tmp_path):
    repo = tmp_path / "repo"
    (repo / ".git" / "worktrees" / "topic").mkdir(parents=True)
    start = repo / ".worktrees" / "topic"
    start.mkdir(parents=True)
    (start / ".git").write_text("gitdir: ../../.git/worktrees/topic\n", encoding="utf-8")
    assert lab_hosts.main_checkout(start) == repo.resolve()


def test_rejects_a_non_object(monkeypatch, tmp_path):
    path = tmp_path / "lab-hosts.json"
    path.write_text("[]", encoding="utf-8")
    monkeypatch.setenv("ROSY_LAB_HOSTS", str(path))
    with pytest.raises(SystemExit, match="JSON object"):
        lab_hosts.load()


@pytest.mark.parametrize('config, expected', [
    ({}, []), ({'site_host': 'site@lab'}, ['site@lab']),
    ({'site_host': 'site@lab', 'omx_hosts': []}, []),
    ({'site_host': 'site@lab', 'omx_hosts': ['arm@lab']}, ['arm@lab']),
    ({'site_host': 'site@lab', 'omx_hosts': ['site@lab', 'arm@lab']}, ['site@lab', 'arm@lab']),
])
def test_native_omx_placement_is_explicit_with_legacy_colocation(config, expected):
    assert lab_hosts.omx_hosts(config) == expected


@pytest.mark.parametrize('raw', [None, '', 'arm@lab', {}, [None], [{}], [''], [' '],
                                      ['arm@lab', 'arm@lab'], ['arm@lab', ' arm@lab '],
                                      ['arm@lab=site'], ['-option'], ['arm@lab command']])
def test_rejects_malformed_explicit_omx_placement(raw):
    with pytest.raises(SystemExit, match='omx_hosts'):
        lab_hosts.omx_hosts({'omx_hosts': raw})
