"""The signing PC's green-main pointer: newest first-parent main commit whose required checks are green."""
import importlib.util
import json
from pathlib import Path
import subprocess
import sys

import pytest

ROOT = Path(__file__).parents[1]
spec = importlib.util.spec_from_file_location("green_main_pointer", ROOT / "deploy/site/green_main_pointer.py")
g = importlib.util.module_from_spec(spec)
spec.loader.exec_module(g)


def run(name, status="completed", conclusion="success", slug="github-actions", id=1):
    return {"name": name, "status": status, "conclusion": conclusion, "app": {"slug": slug}, "id": id}


def commit(sha, parents=(), verified=True):
    return {"sha": sha, "parents": [{"sha": s} for s in parents], "commit": {"verification": {"verified": verified}}}


def fetcher(commits, runs):
    def fetch(path):
        if "/check-runs" in path:
            return {"check_runs": runs.get(path.split("/commits/")[1].split("/")[0], [])}
        assert path == "repos/o/r/commits?sha=main&per_page=100"
        return commits
    return fetch


# main: m3 (merge of PR commit p1) -> m2 -> m1; p1 is a second parent
MAIN = [commit("m3", ("m2", "p1")), commit("p1", ("m1",)), commit("m2", ("m1",), verified=False), commit("m1")]


@pytest.mark.parametrize("runs, expected", [
    ({"m3": [run("ci-result")]}, "m3"),
    ({"m3": [run("ci-result", status="in_progress", conclusion=None)], "m2": [run("ci-result")]}, "m2"),
    ({"m3": [run("ci-result", id=2, conclusion="failure"), run("ci-result", id=1)], "m2": [run("ci-result")]}, "m2"),
    ({"m3": [run("ci-result", id=1, conclusion="failure"), run("ci-result", id=2)]}, "m3"),  # a green rerun counts
    ({"m3": [run("ci-result", slug="someone-else")], "m2": [run("ci-result")]}, "m2"),  # only Actions reports
    ({"p1": [run("ci-result")], "m1": [run("ci-result")]}, "m1"),  # a PR commit is never a main state
    ({"m3": [run("other")]}, None),
])
def test_the_newest_green_first_parent_commit_is_chosen(runs, expected):
    pointer = g.newest_green("o/r", "main", ["ci-result"], 20, fetcher(MAIN, runs))
    assert (pointer or {}).get("source_commit") == expected
    if expected == "m2":
        assert pointer["commit_verified"] is False and pointer["required_checks"] == ["ci-result"]


def test_depth_bounds_the_walk():
    assert g.newest_green("o/r", "main", ["ci-result"], 1, fetcher(MAIN, {"m2": [run("ci-result")]})) is None


@pytest.mark.skipif(sys.platform == "win32", reason="openssl on the test PC")
def test_the_written_pointer_verifies_on_the_cell(tmp_path, monkeypatch):
    priv, pub = tmp_path / "k.pem", tmp_path / "k.pub.pem"
    subprocess.run(["openssl", "genpkey", "-algorithm", "ed25519", "-out", str(priv)], check=True)
    subprocess.run(["openssl", "pkey", "-in", str(priv), "-pubout", "-out", str(pub)], check=True)
    monkeypatch.setattr(g, "gh_json", lambda gh, path: fetcher(MAIN, {"m3": [run("ci-result")]})(path))
    out = tmp_path / "out"
    assert g.main(["--repo", "o/r", "--key-id", "rosy-green-main-v1", "--private-key", str(priv),
                   "--public-key", str(pub), "--out-dir", str(out)]) == 0
    data, sig = (out / "green-main.json").read_bytes(), (out / "green-main.json.sig").read_bytes()
    assert json.loads(data)["source_commit"] == "m3" and json.loads(data)["schema"] == "rosy-green-main/1"
    from candidate_signing import verify_manifest_signature
    verify_manifest_signature(data, sig, trusted_key_id="rosy-green-main-v1", public_key=pub)
    assert g.main(["--repo", "o/r", "--key-id", "rosy-green-main-v1", "--private-key", str(priv),
                   "--public-key", str(pub), "--out-dir", str(out)]) == 0
    assert (out / "green-main.json").read_bytes() == data  # an unchanged main rewrites the same bytes


def test_no_green_commit_and_gh_failure_exit_without_writing(tmp_path, monkeypatch):
    monkeypatch.setattr(g, "gh_json", lambda gh, path: fetcher(MAIN, {})(path))
    assert g.main(["--repo", "o/r", "--dry-run"]) == 3
    monkeypatch.setattr(g, "gh_json", lambda gh, path: (_ for _ in ()).throw(subprocess.CalledProcessError(1, "gh")))
    assert g.main(["--repo", "o/r", "--dry-run"]) == 2
    with pytest.raises(SystemExit):
        g.main(["--repo", "o/r"])  # signing needs the key and an output folder
