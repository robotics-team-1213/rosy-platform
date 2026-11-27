"""The OMX updater's platform source: a signed green-main pointer and local git ancestry, no GitHub REST API."""
import importlib.util
import json
from pathlib import Path
import subprocess
import sys

import pytest

ROOT = Path(__file__).parents[1]
pytestmark = pytest.mark.skipif(sys.platform == "win32", reason="POSIX fcntl/symlink host tool")


def load(name, rel):  # not put in sys.modules: test_omx_autoupdate loads its own copies the same way
    spec = importlib.util.spec_from_file_location(name, ROOT / rel)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


m = load("omx_autoupdate", "deploy/robot/omx/omx_autoupdate.py")  # puts deploy/robot/omx on sys.path
p = load("omx_autoupdate_platform", "deploy/robot/omx/omx_autoupdate_platform.py")
signing = load("candidate_signing", "deploy/site/candidate_signing.py")
shared = load("omx_autoupdate_tests", "test/test_omx_autoupdate.py")
FakeHost, updater = shared.FakeHost, shared.updater

KEY_ID = "rosy-green-main-v1"
SHA = "a" * 40


@pytest.fixture(scope="module")
def keys(tmp_path_factory):
    d = tmp_path_factory.mktemp("keys")
    subprocess.run(["openssl", "genpkey", "-algorithm", "ed25519", "-out", str(d / "k.pem")], check=True)
    subprocess.run(["openssl", "pkey", "-in", str(d / "k.pem"), "-pubout", "-out", str(d / "k.pub.pem")], check=True)
    return d / "k.pem", d / "k.pub.pem"


def publish(tmp_path, keys, sign_with=None, **fields):
    pointer = {"schema": "rosy-green-main/1", "repository": "o/r", "branch": "main", "source_commit": SHA,
               "required_checks": ["ci-result"], "commit_verified": False, **fields}
    data = (json.dumps(pointer, sort_keys=True) + "\n").encode()
    priv, pub = sign_with or keys
    (tmp_path / "green-main.json").write_bytes(data)
    (tmp_path / "green-main.json.sig").write_bytes(
        signing.sign_manifest_bytes(data, key_id=KEY_ID, private_key=priv, public_key=pub))
    return p.PlatformHost({"platform_url": (tmp_path / "green-main.json").as_uri(), "platform_key_id": KEY_ID,
                           "platform_public_key": str(keys[1]), "github_repo": "o/r", "branch": "main",
                           "root": str(tmp_path), "repo_url": str(tmp_path / "missing-repo")})


def test_a_signed_pointer_gives_head_checks_and_verification_without_github(tmp_path, keys, monkeypatch):
    monkeypatch.setattr(p.Host, "_api", lambda *a: pytest.fail("GitHub REST API called"))
    host = publish(tmp_path, keys, commit_verified=True)
    assert host.remote_head() == SHA
    assert host.checks(SHA) == {"ci-result": ("completed", "success", "github-actions")}
    assert host.checks("b" * 40) == {}  # green only for the signed commit
    assert host.verified(SHA) and not host.verified("b" * 40)


@pytest.mark.parametrize("change, reason", [
    ("forged", "bad_signature"), ("unsigned", "unreachable"), ("absent", "unreachable"),
    ("repository", "malformed"), ("branch", "malformed"), ("schema", "malformed"), ("short_sha", "malformed"),
])
def test_an_unreadable_or_untrusted_pointer_is_transient(tmp_path, keys, change, reason, tmp_path_factory):
    fields = {"repository": {"repository": "x/y"}, "branch": {"branch": "dev"}, "schema": {"schema": "rosy-green-main/0"},
              "short_sha": {"source_commit": "abc"}}.get(change, {})
    other = None
    if change == "forged":
        d = tmp_path_factory.mktemp("other")
        subprocess.run(["openssl", "genpkey", "-algorithm", "ed25519", "-out", str(d / "k.pem")], check=True)
        subprocess.run(["openssl", "pkey", "-in", str(d / "k.pem"), "-pubout", "-out", str(d / "k.pub.pem")], check=True)
        other = (d / "k.pem", d / "k.pub.pem")
    host = publish(tmp_path, keys, sign_with=other, **fields)
    if change == "unsigned":
        (tmp_path / "green-main.json.sig").unlink()
    if change == "absent":
        (tmp_path / "green-main.json").unlink()
    with pytest.raises(m.SourceUnavailable, match=reason):
        host.remote_head()


def test_a_transient_source_changes_nothing_and_exits_zero(tmp_path, capsys):
    for where in ("remote_head", "checks", "descends"):
        host = FakeHost()
        u = updater(tmp_path / where, host)
        (tmp_path / where).mkdir()
        u.save({"current": "old", "previous": None, "history": [], "current_sha": "c" * 40})
        before = (tmp_path / where / "state.json").read_text()
        setattr(host, where, lambda *a: (_ for _ in ()).throw(m.SourceUnavailable("unreachable")))
        capsys.readouterr()
        assert u.run() == "transient"
        assert '"step": "transient", "reason": "unreachable"' in capsys.readouterr().out
        assert host.archived == [] and (tmp_path / where / "state.json").read_text() == before


def git(repo, *args):
    return subprocess.run(["git", "-C", str(repo), *args], check=True, capture_output=True, text=True).stdout.strip()


def test_ancestry_comes_from_a_local_commit_only_mirror(tmp_path):
    origin = tmp_path / "origin"
    origin.mkdir()
    git(origin, "init", "-q", "-b", "main")
    shas = []
    for n in range(3):
        git(origin, "-c", "user.name=t", "-c", "user.email=t@t", "commit", "-q", "--allow-empty", "-m", str(n))
        shas.append(git(origin, "rev-parse", "HEAD"))
    git(origin, "checkout", "-q", "-b", "side", shas[0])
    git(origin, "-c", "user.name=t", "-c", "user.email=t@t", "commit", "-q", "--allow-empty", "-m", "side")
    side = git(origin, "rev-parse", "HEAD")
    git(origin, "checkout", "-q", "main")
    host = p.PlatformHost({"root": str(tmp_path / "root"), "branch": "main", "repo_url": str(origin)})
    (tmp_path / "root").mkdir()
    assert host.descends(shas[0], shas[2]) and host.descends(shas[2], shas[2])
    assert not host.descends(shas[2], shas[0])  # going back is never a descendant
    assert not host.descends(side, shas[2])  # not on the fetched branch
    assert not host.descends("f" * 40, shas[2])  # a hotfix floor that origin never had
    git(origin, "-c", "user.name=t", "-c", "user.email=t@t", "commit", "-q", "--allow-empty", "-m", "3")
    assert host.descends(shas[2], git(origin, "rev-parse", "HEAD"))  # the next run fetches the new tip
    bad = p.PlatformHost({"root": str(tmp_path / "root2"), "branch": "main", "repo_url": str(tmp_path / "nowhere")})
    (tmp_path / "root2").mkdir()
    with pytest.raises(m.SourceUnavailable, match="history_unreachable"):
        bad.descends(shas[0], shas[2])


def test_the_platform_is_the_default_once_a_pointer_url_is_configured(tmp_path, monkeypatch):
    monkeypatch.setenv("ROSY_OMX_HOME", str(tmp_path / "home"))
    path = tmp_path / "cfg.json"
    base = {"kind": "service", "repo_url": "u", "github_repo": "o/r", "base_python": "p", "paths": ["deploy/robot/omx"],
            "smoke": "s", "units": ["a.service"], "root": str(tmp_path / "devices")}
    path.write_text(json.dumps(base))
    cfg = m.load_config(path)
    assert cfg["trust_source"] == "github"  # unprovisioned configs keep working on the fallback
    assert "deploy/site/candidate_signing.py" in cfg["paths"]  # every cell release can verify a pointer
    path.write_text(json.dumps({**base, "platform_url": "file:///x"}))
    with pytest.raises(SystemExit, match="platform_public_key"):
        m.load_config(path)
    path.write_text(json.dumps({**base, "platform_url": "file:///x", "platform_public_key": "k", "platform_key_id": "i"}))
    assert m.load_config(path)["trust_source"] == "platform"
    path.write_text(json.dumps({**base, "trust_source": "gitlab"}))
    with pytest.raises(SystemExit, match="trust_source"):
        m.load_config(path)
    example = json.loads((ROOT / "deploy/robot/omx/omx-devices-autoupdate.json.example").read_text())
    assert example["trust_source"] == "platform" and example["platform_key_id"] == KEY_ID
