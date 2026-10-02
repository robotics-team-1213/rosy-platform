"""D-410 tools/release/publish_payload_release.py with a fake gh, fake ssh and a fake clock.

Nothing here reaches GitHub or a robot. The signing key pair is generated per test
with openssl (the same tool signing.py shells out to).
"""

from __future__ import annotations

import datetime as dt
import hashlib
import importlib.util
import io
import json
import os
from pathlib import Path
import shutil
import subprocess
import tarfile

import pytest

ROOT = Path(__file__).resolve().parents[1]
_SPEC = importlib.util.spec_from_file_location(
    "publish_payload_release", ROOT / "tools" / "release" / "publish_payload_release.py")
tool = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(tool)

import signing  # noqa: E402  (conftest puts deploy/robot/pinky_pro/release on sys.path)

RELEASE_ID = "2026.10.01-022"
TAG = f"payload-{RELEASE_ID}"
REVISION = "b" * 40
CANARY_IP = "192.168.1.202"
OTHER_IP = "192.168.1.201"
CANARY = "rosy-pinky-8kcn"
REPO = "livsbittt/rosy-os"
START = dt.datetime(2026, 10, 1, 15, 0, 0, tzinfo=dt.timezone.utc)

pytestmark = pytest.mark.skipif(shutil.which("openssl") is None, reason="openssl is required")


# --- fakes -----------------------------------------------------------------

class FakeClock:
    def __init__(self):
        self.t = 0.0

    def now(self) -> dt.datetime:
        return START + dt.timedelta(seconds=self.t)

    def monotonic(self) -> float:
        return self.t

    def sleep(self, seconds: float) -> None:
        self.t += seconds


_VALUE_FLAGS = {"--repo", "--target", "--title", "--notes", "--pattern", "--dir"}


class FakeGh:
    """An in-memory GitHub: tags, releases and their assets."""

    def __init__(self):
        self.tags: set[str] = set()
        self.releases: dict[str, dict] = {}
        self.calls: list[list[str]] = []
        self.fail_upload = False
        self.after_upload = None  # called once, right after the next successful upload

    @staticmethod
    def _parse(tokens):
        flags, positional, i = {}, [], 0
        while i < len(tokens):
            token = tokens[i]
            if token in _VALUE_FLAGS:
                flags.setdefault(token, []).append(tokens[i + 1])
                i += 2
            elif token.startswith("--"):
                flags[token] = [True]
                i += 1
            else:
                positional.append(token)
                i += 1
        return flags, positional

    def __call__(self, argv):
        self.calls.append(list(argv))
        assert argv[0] == "gh"
        if argv[1] == "api":
            prefix = argv[2].rsplit("/tags/", 1)[1]
            refs = [{"ref": f"refs/tags/{t}"} for t in sorted(self.tags) if t.startswith(prefix)]
            return 0, json.dumps(refs), ""
        assert argv[1] == "release"
        command, tag = argv[2], argv[3]
        flags, files = self._parse(argv[4:])
        assert flags["--repo"] == [REPO]
        if command == "create":
            if tag in self.tags:
                return 1, "", "a release with the same tag name already exists"
            self.tags.add(tag)
            self.releases[tag] = {"target": flags["--target"][0], "title": flags["--title"][0],
                                  "notes": flags["--notes"][0],
                                  "assets": {Path(f).name: Path(f).read_bytes() for f in files}}
            return 0, f"https://github.com/{REPO}/releases/tag/{tag}\n", ""
        if tag not in self.releases:
            return 1, "", "release not found"
        if command == "upload":
            if self.fail_upload:
                return 1, "", "HTTP 502"
            assert flags.get("--clobber") == [True]
            for f in files:
                self.releases[tag]["assets"][Path(f).name] = Path(f).read_bytes()
            if self.after_upload is not None:
                hook, self.after_upload = self.after_upload, None
                hook()
            return 0, "", ""
        if command == "download":
            # Like gh: the assets that exist are downloaded; only no match at all is an error.
            target = Path(flags["--dir"][0])
            target.mkdir(parents=True, exist_ok=True)
            found = [p for p in flags["--pattern"] if p in self.releases[tag]["assets"]]
            if not found:
                return 1, "", "no assets match the file pattern"
            for pattern in found:
                (target / pattern).write_bytes(self.releases[tag]["assets"][pattern])
            return 0, "", ""
        raise AssertionError(argv)

    def rollout(self, tag=TAG) -> dict:
        return json.loads(self.releases[tag]["assets"]["rollout.json"])


def status(phase="idle", current="2026.10.01-021", candidate=None, last=None, hostname=CANARY) -> dict:
    return {"schema": 1, "updated_at": "2026-10-01T15:00:00Z", "hostname": hostname,
            "current_release": current, "candidate": candidate, "phase": phase, "reason": "",
            "last_result": last}


def result(outcome, release_id=RELEASE_ID, at="2026-10-01T15:00:30Z", detail="healthy") -> dict:
    return {"release_id": release_id, "outcome": outcome, "at": at, "detail": detail}


COMMITTED = status("committed", RELEASE_ID, None, result("committed"))
# T2's rosy_auto_update.py status --json before its first run (no status.json yet).
NOT_RUN_YET = {"phase": None, "reason": "the updater has not run yet"}


class FakeSsh:
    """The first canary status poll is the publisher's baseline, taken before the release exists."""

    def __init__(self, statuses=(status(), COMMITTED), hostname=CANARY, others=None, on_poll=None):
        self.statuses = list(statuses)
        self.hostname = hostname
        self.others = others or {}
        self.on_poll = on_poll
        self.calls: list[list[str]] = []

    def __call__(self, argv):
        self.calls.append(list(argv))
        host = next(a for a in argv if a.startswith("rosy@")).split("@", 1)[1]
        command = argv[-1]
        if command == "hostname":
            return 0, self.hostname + "\n", ""
        assert command == "sudo -n python3 /opt/rosy/native-runtime/rosy_auto_update.py status --json"
        if host != CANARY_IP:
            return 0, json.dumps(self.others.get(host, status())), ""
        if self.on_poll is not None:
            self.on_poll(len(self.status_polls()))
        item = self.statuses.pop(0) if len(self.statuses) > 1 else self.statuses[0]
        if item is None:
            return 255, "", "ssh: connect to host port 22: Connection timed out"
        return 0, json.dumps(item) + "\n", ""

    def status_polls(self):
        return [c for c in self.calls if c[-1].endswith("status --json") and f"rosy@{CANARY_IP}" in c]


# --- fixtures --------------------------------------------------------------

@pytest.fixture
def keys(tmp_path, monkeypatch):
    appdata = tmp_path / "appdata"
    signing_dir = appdata / "Rosy" / "signing"
    signing_dir.mkdir(parents=True)
    private = signing_dir / "rosy-release-2026-01.private.pem"
    public = tmp_path / "pub.pem"
    subprocess.run(["openssl", "genpkey", "-algorithm", "ed25519", "-out", str(private)],
                   check=True, capture_output=True)
    subprocess.run(["openssl", "pkey", "-in", str(private), "-pubout", "-out", str(public)],
                   check=True, capture_output=True)
    monkeypatch.setenv("LOCALAPPDATA", str(appdata))
    return {"private": private, "public": public}


def _tarball(path: Path, private: Path, release_id=RELEASE_ID, revision=REVISION, tamper=False) -> Path:
    """A signed release tarball shaped like build_payload_release.py pack: no top-level directory."""
    files = {"manifest.json": json.dumps({"release_id": release_id}) + "\n",
             "source-revision.txt": revision + "\n", "install/.rosy-release": release_id + "\n"}
    sums = "".join(f"{hashlib.sha256(text.encode()).hexdigest()}  {name}\n"
                   for name, text in sorted(files.items())).encode()
    files["SHA256SUMS"] = sums.decode()
    files["SHA256SUMS.sig"] = signing.sign_checksums(sums, private)
    if tamper:
        files["manifest.json"] = json.dumps({"release_id": release_id, "x": 1}) + "\n"
    path.parent.mkdir(parents=True, exist_ok=True)
    with tarfile.open(path, "w:gz") as tar:
        for name, text in files.items():
            data = text.encode("utf-8")
            info = tarfile.TarInfo(name)
            info.size = len(data)
            tar.addfile(info, io.BytesIO(data))
    return path


@pytest.fixture
def tarball(tmp_path, keys):
    return _tarball(tmp_path / "out" / f"{RELEASE_ID}.tar.gz", keys["private"])


def _run(args, keys, tmp_path, gh, ssh, clock=None):
    clock = clock or FakeClock()
    argv = [*args, "--public-key", str(keys["public"]), "--evidence-dir", str(tmp_path / "evidence")]
    return tool.main(argv, gh_runner=gh, ssh_runner=ssh, now=clock.now,
                     monotonic=clock.monotonic, sleep=clock.sleep)


def _publish(tarball, keys, tmp_path, gh, ssh, *extra, clock=None):
    return _run(["--tarball", str(tarball), "--canary", CANARY_IP, *extra], keys, tmp_path, gh, ssh, clock)


def _verified(gh, keys, tag=TAG) -> dict:
    assets = gh.releases[tag]["assets"]
    assert signing.verify_signature(assets["rollout.json"], assets["rollout.json.sig"].decode("ascii"),
                                    keys["public"]) == []
    return json.loads(assets["rollout.json"])


def _signed_release(gh, keys, tmp_path, **changes) -> None:
    """Put an existing release with a signed rollout into the fake GitHub."""
    rollout = tool.build_rollout(RELEASE_ID, "c" * 64, REVISION, "2026-10-01T14:00:00Z", CANARY, 600)
    rollout.update(changes)
    data = tool.rollout_bytes(rollout)
    gh.tags.add(TAG)
    gh.releases[TAG] = {"target": REVISION, "title": TAG, "notes": "",
                        "assets": {f"{RELEASE_ID}.tar.gz": b"x", "rollout.json": data,
                                   "rollout.json.sig": signing.sign_checksums(data, keys["private"]).encode()}}


# --- rollout bytes and signature --------------------------------------------

def test_rollout_bytes_are_sorted_lf_utf8_without_bom():
    rollout = tool.build_rollout(RELEASE_ID, "a" * 64, REVISION, "2026-10-01T15:00:00Z", CANARY, 600)
    data = tool.rollout_bytes(rollout)

    assert not data.startswith(b"\xef\xbb\xbf")
    assert b"\r" not in data and data.endswith(b"\n")
    parsed = json.loads(data.decode("utf-8"))
    assert list(parsed) == sorted(parsed)
    assert parsed == {"schema": 1, "release_id": RELEASE_ID, "tarball": f"{RELEASE_ID}.tar.gz",
                      "tarball_sha256": "a" * 64, "source_revision": REVISION,
                      "published_at": "2026-10-01T15:00:00Z", "canary": [CANARY], "canary_ok": False,
                      "wave_delay_s": 600, "withdrawn": False, "reason": ""}
    # Deterministic: the same content always signs the same bytes.
    assert tool.rollout_bytes(dict(reversed(list(rollout.items())))) == data


def test_signature_round_trips_through_signing_verify(keys):
    data = tool.rollout_bytes(tool.build_rollout(RELEASE_ID, "a" * 64, REVISION, "Z", CANARY, 600))
    signature = tool.sign_rollout(data, keys["private"], keys["public"])

    assert signing.verify_signature(data, signature, keys["public"]) == []
    assert signature.isascii() and "\n" not in signature


def test_self_verify_rejects_a_tampered_rollout(keys):
    data = tool.rollout_bytes(tool.build_rollout(RELEASE_ID, "a" * 64, REVISION, "Z", CANARY, 600))

    def tampering_signer(_data, private_key):
        return signing.sign_checksums(data.replace(b'"withdrawn": false', b'"withdrawn": true'), private_key)

    with pytest.raises(tool.PublishError, match="SIGNATURE_INVALID"):
        tool.sign_rollout(data, keys["private"], keys["public"], signer=tampering_signer)


# --- publish -----------------------------------------------------------------

def test_publish_creates_the_release_with_the_contract_argv_and_assets(tarball, keys, tmp_path):
    gh, ssh = FakeGh(), FakeSsh()

    assert _publish(tarball, keys, tmp_path, gh, ssh) == 0

    (create,) = [c for c in gh.calls if c[1:3] == ["release", "create"]]
    assert create[:4] == ["gh", "release", "create", TAG]
    flags, files = FakeGh._parse(create[4:])
    assert flags["--repo"] == [REPO] and flags["--target"] == [REVISION] and flags["--title"] == [TAG]
    assert RELEASE_ID in flags["--notes"][0]
    assert [Path(f).name for f in files] == [f"{RELEASE_ID}.tar.gz", "rollout.json", "rollout.json.sig"]
    assert Path(files[0]) == tarball
    assert "--draft" not in create and "--prerelease" not in create
    release = gh.releases[TAG]
    assert release["assets"][f"{RELEASE_ID}.tar.gz"] == tarball.read_bytes()


def test_first_upload_is_canary_only_and_signed(tarball, keys, tmp_path):
    gh = FakeGh()
    ssh = FakeSsh(statuses=[status(), COMMITTED])
    snapshots = []
    original = gh.__call__

    def recording(argv):
        result = original(argv)
        if argv[1:3] == ["release", "create"]:
            snapshots.append(dict(gh.releases[TAG]["assets"]))
        return result

    assert _publish(tarball, keys, tmp_path, recording, ssh) == 0

    (assets,) = snapshots
    assert signing.verify_signature(assets["rollout.json"], assets["rollout.json.sig"].decode(), keys["public"]) == []
    first = json.loads(assets["rollout.json"])
    assert first["canary"] == [CANARY] and first["canary_ok"] is False and first["withdrawn"] is False
    assert first["published_at"] == "2026-10-01T15:00:00Z"
    assert first["tarball_sha256"] == signing.sha256_file(tarball)
    assert first["source_revision"] == REVISION
    assert first["wave_delay_s"] == 600


def test_an_existing_tag_is_refused_without_resume(tarball, keys, tmp_path, capsys):
    gh, ssh = FakeGh(), FakeSsh()
    gh.tags.add(TAG)

    assert _publish(tarball, keys, tmp_path, gh, ssh) != 0

    assert not [c for c in gh.calls if c[1:3] == ["release", "create"]]
    err = capsys.readouterr().err
    assert "already exists" in err and "--resume" in err


def test_a_tag_that_only_shares_a_prefix_is_not_an_existing_tag(tarball, keys, tmp_path):
    gh, ssh = FakeGh(), FakeSsh()
    gh.tags.add(TAG + "1")

    assert _publish(tarball, keys, tmp_path, gh, ssh) == 0
    assert TAG in gh.releases


@pytest.mark.parametrize("hostname", ["evil;reboot", "pinky-8kcn", "ROSY-PINKY", ""])
def test_a_canary_hostname_outside_the_pattern_is_refused(tarball, keys, tmp_path, hostname):
    gh, ssh = FakeGh(), FakeSsh(hostname=hostname)

    assert _publish(tarball, keys, tmp_path, gh, ssh) != 0
    assert TAG not in gh.releases


def test_the_tarball_must_carry_a_matching_manifest_and_full_revision(tmp_path, keys):
    gh, ssh = FakeGh(), FakeSsh()
    other = _tarball(tmp_path / "a" / f"{RELEASE_ID}.tar.gz", keys["private"], release_id="2026.10.01-099")
    short = _tarball(tmp_path / "b" / f"{RELEASE_ID}.tar.gz", keys["private"], revision="abc")

    assert _publish(other, keys, tmp_path, gh, ssh) != 0
    assert _publish(short, keys, tmp_path, gh, ssh) != 0
    assert gh.releases == {}


def test_wave_delay_below_60_is_rejected(tarball, keys, tmp_path):
    with pytest.raises(SystemExit) as raised:
        _publish(tarball, keys, tmp_path, FakeGh(), FakeSsh(), "--wave-delay-s", "59")
    assert raised.value.code == 2


def test_ssh_uses_the_operator_key_and_strict_host_checking(tarball, keys, tmp_path):
    gh, ssh = FakeGh(), FakeSsh()

    _publish(tarball, keys, tmp_path, gh, ssh)

    appdata = tmp_path / "appdata" / "Rosy"
    for argv in ssh.calls:
        assert argv[0] == "ssh" and f"rosy@{CANARY_IP}" in argv
        assert str(appdata / "ssh" / "rosy-operator-ed25519") in argv
        for option in ("IdentitiesOnly=yes", "BatchMode=yes", "StrictHostKeyChecking=yes", "ConnectTimeout=5",
                       f'UserKnownHostsFile="{appdata / "known_hosts"}"'):
            assert option in argv


# --- canary watch ------------------------------------------------------------

def test_canary_commit_sets_canary_ok_and_reuploads(tarball, keys, tmp_path, capsys):
    gh = FakeGh()
    ssh = FakeSsh(statuses=[status(), status("staged", candidate=RELEASE_ID), status("applying", candidate=RELEASE_ID),
                            None, COMMITTED])
    clock = FakeClock()

    assert _publish(tarball, keys, tmp_path, gh, ssh, clock=clock) == 0

    final = _verified(gh, keys)
    assert final["canary_ok"] is True and final["withdrawn"] is False
    assert final["published_at"] == "2026-10-01T15:00:00Z"  # never changes
    (upload,) = [c for c in gh.calls if c[1:3] == ["release", "upload"]]
    flags, files = FakeGh._parse(upload[4:])
    assert upload[3] == TAG and flags["--clobber"] == [True]
    assert [Path(f).name for f in files] == ["rollout.json", "rollout.json.sig"]
    assert len(ssh.status_polls()) == 5 and clock.t == 3 * 30  # the first poll is the baseline
    out = capsys.readouterr().out
    for phase in ("staged", "applying", "unreachable", "committed"):
        assert phase in out


@pytest.mark.parametrize("outcome", ["rolled_back", "refused"])
def test_canary_rollback_or_refusal_withdraws(tarball, keys, tmp_path, outcome):
    gh = FakeGh()
    failed = status("rolled_back", "2026.10.01-021", None, result(outcome, detail="core not ready"))

    assert _publish(tarball, keys, tmp_path, gh, FakeSsh(statuses=[status(), failed])) != 0

    final = _verified(gh, keys)
    assert final["withdrawn"] is True and final["canary_ok"] is False
    assert outcome in final["reason"] and "core not ready" in final["reason"]
    assert final["published_at"] == "2026-10-01T15:00:00Z"


def test_canary_timeout_withdraws(tarball, keys, tmp_path):
    gh = FakeGh()
    ssh = FakeSsh(statuses=[status("held", candidate=RELEASE_ID)])
    clock = FakeClock()

    assert _publish(tarball, keys, tmp_path, gh, ssh, "--canary-timeout-min", "10", clock=clock) != 0

    final = _verified(gh, keys)
    assert final["withdrawn"] is True and final["canary_ok"] is False
    assert "10 min" in final["reason"] and "held" in final["reason"]
    assert 600 <= clock.t <= 630
    assert len(ssh.status_polls()) == 1 + 21  # baseline, then the watch


@pytest.mark.parametrize("canary_status", [
    # an older release's commit is not this release's
    status("committed", RELEASE_ID, None,
           result("committed", "2026.10.01-021")),
    # this release committed but the robot is not on it any more
    status("idle", "2026.10.01-021", None,
           result("committed")),
    # an older release rolled back: not a failure of this one
    status("rolled_back", "2026.10.01-021", None,
           result("rolled_back", "2026.10.01-020")),
])
def test_only_this_release_decides_the_canary(tarball, keys, tmp_path, canary_status):
    gh = FakeGh()

    _publish(tarball, keys, tmp_path, gh, FakeSsh(statuses=[canary_status]), "--canary-timeout-min", "1")

    final = _verified(gh, keys)
    assert final["canary_ok"] is False and final["withdrawn"] is True
    assert "did not commit within 1 min" in final["reason"]


def test_after_canary_ok_the_other_robots_are_shown(tarball, keys, tmp_path, capsys):
    gh = FakeGh()
    ssh = FakeSsh(others={OTHER_IP: status("waiting", candidate=RELEASE_ID)})

    assert _publish(tarball, keys, tmp_path, gh, ssh, "--robot", OTHER_IP) == 0

    out = capsys.readouterr().out
    assert OTHER_IP in out and "waiting" in out
    assert "2026-10-01T15:10:00Z" in out  # published_at + wave_delay_s


def test_evidence_log_records_each_phase(tarball, keys, tmp_path):
    gh = FakeGh()

    _publish(tarball, keys, tmp_path, gh, FakeSsh(statuses=[status(), COMMITTED]))

    log = tmp_path / "evidence" / "2026-10-01" / "rollout.jsonl"
    events = [json.loads(line) for line in log.read_text(encoding="utf-8").splitlines()]
    names = [e["event"] for e in events]
    for name in ("release-created", "canary-phase", "canary-ok"):
        assert name in names
    assert all(e["release_id"] == RELEASE_ID and e["at"].endswith("Z") for e in events)


def test_no_key_material_is_printed(tarball, keys, tmp_path, capsys):
    _publish(tarball, keys, tmp_path, FakeGh(), FakeSsh())

    captured = capsys.readouterr()
    body = "".join(keys["private"].read_text().splitlines()[1:-1])
    assert body[:20] not in captured.out + captured.err
    assert "PRIVATE KEY" not in captured.out + captured.err


def test_a_failed_reupload_exits_non_zero(tarball, keys, tmp_path):
    gh = FakeGh()
    gh.fail_upload = True

    assert _publish(tarball, keys, tmp_path, gh, FakeSsh()) != 0


# --- resume and withdraw ------------------------------------------------------

def test_resume_reattaches_and_finishes_the_canary(keys, tmp_path):
    gh = FakeGh()
    _signed_release(gh, keys, tmp_path)

    code = _run(["--release-id", RELEASE_ID, "--out-dir", str(tmp_path / "w"), "--canary", CANARY_IP, "--resume"],
                keys, tmp_path, gh, FakeSsh())

    assert code == 0
    assert not [c for c in gh.calls if c[1:3] == ["release", "create"]]
    final = _verified(gh, keys)
    assert final["canary_ok"] is True
    assert final["published_at"] == "2026-10-01T14:00:00Z"
    assert final["tarball_sha256"] == "c" * 64


def test_resume_refuses_a_rollout_whose_signature_does_not_verify(keys, tmp_path):
    gh = FakeGh()
    _signed_release(gh, keys, tmp_path)
    assets = gh.releases[TAG]["assets"]
    assets["rollout.json"] = assets["rollout.json"].replace(b'"wave_delay_s": 600', b'"wave_delay_s": 60')

    code = _run(["--release-id", RELEASE_ID, "--out-dir", str(tmp_path / "w"), "--canary", CANARY_IP, "--resume"],
                keys, tmp_path, gh, FakeSsh())

    assert code != 0
    assert not [c for c in gh.calls if c[1:3] == ["release", "upload"]]


def test_resume_refuses_a_canary_not_named_in_the_rollout(keys, tmp_path):
    gh = FakeGh()
    _signed_release(gh, keys, tmp_path)

    code = _run(["--release-id", RELEASE_ID, "--out-dir", str(tmp_path / "w"), "--canary", CANARY_IP, "--resume"],
                keys, tmp_path, gh, FakeSsh(hostname="rosy-pinky-9dfk"))

    assert code != 0
    assert not [c for c in gh.calls if c[1:3] == ["release", "upload"]]


def test_resume_of_a_withdrawn_release_does_nothing(keys, tmp_path):
    gh = FakeGh()
    _signed_release(gh, keys, tmp_path, withdrawn=True, reason="canary rolled back")

    code = _run(["--release-id", RELEASE_ID, "--out-dir", str(tmp_path / "w"), "--canary", CANARY_IP, "--resume"],
                keys, tmp_path, gh, FakeSsh())

    assert code != 0
    assert not [c for c in gh.calls if c[1:3] == ["release", "upload"]]


def test_manual_withdraw_rewrites_and_resigns(keys, tmp_path):
    gh = FakeGh()
    _signed_release(gh, keys, tmp_path, canary_ok=True)
    ssh = FakeSsh()

    code = _run(["--release-id", RELEASE_ID, "--out-dir", str(tmp_path / "w"), "--withdraw",
                 "--reason", "bad lane-keep gains"], keys, tmp_path, gh, ssh)

    assert code == 0
    final = _verified(gh, keys)
    assert final["withdrawn"] is True and final["reason"] == "bad lane-keep gains"
    assert final["canary_ok"] is True and final["published_at"] == "2026-10-01T14:00:00Z"
    assert ssh.calls == []  # a withdraw never touches a robot


def test_withdraw_needs_a_reason(keys, tmp_path):
    with pytest.raises(SystemExit) as raised:
        _run(["--release-id", RELEASE_ID, "--withdraw"], keys, tmp_path, FakeGh(), FakeSsh())
    assert raised.value.code == 2


# --- review fixes (H1, M1, M4, M5, L1-L3, L6, L7) ---------------------------------

def _uploads(gh):
    return [c for c in gh.calls if c[1:3] == ["release", "upload"]]


def _rewrite_remote(gh, keys, **changes):
    rollout = json.loads(gh.releases[TAG]["assets"]["rollout.json"])
    rollout.update(changes)
    data = tool.rollout_bytes(rollout)
    gh.releases[TAG]["assets"].update(
        {"rollout.json": data, "rollout.json.sig": signing.sign_checksums(data, keys["private"]).encode()})


def test_a_watch_never_undoes_a_withdraw_made_meanwhile(tarball, keys, tmp_path, capsys):
    """H1: someone withdraws by hand while this process watches; the commit that follows must not
    put canary_ok=true over it."""
    gh = FakeGh()

    def withdraw_by_hand(poll_number):
        if poll_number == 2:  # after the baseline and the first watch poll
            _rewrite_remote(gh, keys, withdrawn=True, reason="withdrawn by hand")

    ssh = FakeSsh(statuses=[status(), status("staged", candidate=RELEASE_ID), COMMITTED], on_poll=withdraw_by_hand)

    assert _publish(tarball, keys, tmp_path, gh, ssh) == 3

    final = _verified(gh, keys)
    assert final["withdrawn"] is True and final["reason"] == "withdrawn by hand"
    assert final["canary_ok"] is False
    assert _uploads(gh) == []
    assert "withdrawn meanwhile" in capsys.readouterr().out


def test_a_watch_that_fails_keeps_a_withdraw_made_meanwhile(tarball, keys, tmp_path):
    gh = FakeGh()

    def withdraw_by_hand(poll_number):
        if poll_number == 2:
            _rewrite_remote(gh, keys, withdrawn=True, reason="withdrawn by hand")

    failed = status("rolled_back", last=result("rolled_back"))
    ssh = FakeSsh(statuses=[status(), status("staged", candidate=RELEASE_ID), failed], on_poll=withdraw_by_hand)

    assert _publish(tarball, keys, tmp_path, gh, ssh) != 0
    assert _verified(gh, keys)["reason"] == "withdrawn by hand"
    assert _uploads(gh) == []


def test_a_remote_rollout_that_changed_otherwise_is_not_overwritten(tarball, keys, tmp_path, capsys):
    gh = FakeGh()

    def change_wave(poll_number):
        if poll_number == 2:
            _rewrite_remote(gh, keys, wave_delay_s=900)

    ssh = FakeSsh(statuses=[status(), status("staged", candidate=RELEASE_ID), COMMITTED], on_poll=change_wave)

    assert _publish(tarball, keys, tmp_path, gh, ssh) != 0
    assert _uploads(gh) == []
    assert _verified(gh, keys)["wave_delay_s"] == 900
    assert "changed" in capsys.readouterr().err


def test_a_running_publish_holds_a_lock_per_release(tarball, keys, tmp_path, capsys):
    lock = tarball.parent / f"publish-{RELEASE_ID}" / ".lock"
    lock.parent.mkdir(parents=True)
    lock.write_text("4242\n", encoding="ascii")
    gh = FakeGh()

    assert _publish(tarball, keys, tmp_path, gh, FakeSsh()) != 0
    assert gh.releases == {}
    assert ".lock" in capsys.readouterr().err
    assert lock.read_text(encoding="ascii") == "4242\n"  # someone else's lock is left alone

    for args in (["--canary", CANARY_IP, "--resume"], ["--withdraw", "--reason", "x"]):
        other = FakeGh()
        _signed_release(other, keys, tmp_path)
        code = _run(["--release-id", RELEASE_ID, "--out-dir", str(tarball.parent), *args],
                    keys, tmp_path, other, FakeSsh())
        assert code != 0 and _uploads(other) == []


def test_the_lock_is_removed_after_a_run(tarball, keys, tmp_path):
    assert _publish(tarball, keys, tmp_path, FakeGh(), FakeSsh()) == 0
    assert not (tarball.parent / f"publish-{RELEASE_ID}" / ".lock").exists()


def test_a_stale_commit_of_a_reused_id_is_not_a_canary_success(tarball, keys, tmp_path):
    """M1: the canary already reports a commit of this id from before the publish."""
    old = status("committed", RELEASE_ID, None, result("committed", at="2026-10-01T09:00:00Z"))
    fresh_but_unchanged = [old, dict(old)]  # baseline, then the same last_result
    gh = FakeGh()

    _publish(tarball, keys, tmp_path, gh, FakeSsh(statuses=[status(), old]), "--canary-timeout-min", "1")
    assert _verified(gh, keys)["canary_ok"] is False

    gh = FakeGh()
    _publish(tarball, keys, tmp_path, gh, FakeSsh(statuses=fresh_but_unchanged), "--canary-timeout-min", "1")
    assert _verified(gh, keys)["canary_ok"] is False


def test_an_unchanged_last_result_is_not_a_canary_success(tarball, keys, tmp_path):
    """M1: same at as published_at, but it was already there before the release was created."""
    before = status("committed", RELEASE_ID, None, result("committed", at="2026-10-01T15:00:00Z"))
    gh = FakeGh()

    _publish(tarball, keys, tmp_path, gh, FakeSsh(statuses=[before]), "--canary-timeout-min", "1")

    assert _verified(gh, keys)["canary_ok"] is False


def test_a_stale_rollback_of_a_reused_id_does_not_withdraw(tarball, keys, tmp_path):
    old = status("idle", "2026.10.01-021", None, result("rolled_back", at="2026-10-01T09:00:00Z"))
    gh = FakeGh()

    assert _publish(tarball, keys, tmp_path, gh, FakeSsh(statuses=[status(), old, COMMITTED])) == 0
    assert _verified(gh, keys)["canary_ok"] is True


def test_a_new_commit_after_an_old_one_is_a_success(tarball, keys, tmp_path):
    old = status("committed", RELEASE_ID, None, result("committed", at="2026-10-01T09:00:00Z"))
    gh = FakeGh()

    assert _publish(tarball, keys, tmp_path, gh, FakeSsh(statuses=[old, old, COMMITTED])) == 0
    assert _verified(gh, keys)["canary_ok"] is True


def test_a_commit_within_the_clock_skew_counts(tarball, keys, tmp_path):
    skewed = status("committed", RELEASE_ID, None, result("committed", at="2026-10-01T14:59:00Z"))
    gh = FakeGh()

    assert _publish(tarball, keys, tmp_path, gh, FakeSsh(statuses=[status(), skewed])) == 0
    assert _verified(gh, keys)["canary_ok"] is True


def test_a_status_from_another_host_is_not_the_canary(tarball, keys, tmp_path):
    """L2."""
    other = status("committed", RELEASE_ID, None, result("committed"), hostname="rosy-pinky-9dfk")
    gh = FakeGh()

    _publish(tarball, keys, tmp_path, gh, FakeSsh(statuses=[status(), other]), "--canary-timeout-min", "1")

    final = _verified(gh, keys)
    assert final["canary_ok"] is False and "did not commit" in final["reason"]


def test_a_not_run_yet_status_keeps_waiting(tarball, keys, tmp_path):
    gh = FakeGh()

    assert _publish(tarball, keys, tmp_path, gh, FakeSsh(statuses=[NOT_RUN_YET, NOT_RUN_YET, COMMITTED])) == 0


def test_a_failed_phase_for_this_release_withdraws_early(tarball, keys, tmp_path):
    """L3: "failed" is T2's definitive outcome for a candidate."""
    gh = FakeGh()
    clock = FakeClock()
    broken = dict(status("failed", candidate=RELEASE_ID), reason="sha256 mismatch")

    assert _publish(tarball, keys, tmp_path, gh, FakeSsh(statuses=[status(), broken]), clock=clock) != 0

    final = _verified(gh, keys)
    assert final["withdrawn"] is True and "failed" in final["reason"] and "sha256 mismatch" in final["reason"]
    assert clock.t == 0


def test_an_error_phase_for_this_release_keeps_watching(tarball, keys, tmp_path):
    """T2 reports transient problems (network, activator timeout, busy) as "error": not a verdict."""
    gh = FakeGh()
    transient = dict(status("error", candidate=RELEASE_ID), reason="github unreachable")

    assert _publish(tarball, keys, tmp_path, gh, FakeSsh(statuses=[status(), transient, transient, COMMITTED])) == 0
    assert _verified(gh, keys)["canary_ok"] is True


def test_an_error_phase_that_never_clears_withdraws_only_at_the_timeout(tarball, keys, tmp_path):
    gh = FakeGh()
    clock = FakeClock()
    transient = dict(status("error", candidate=RELEASE_ID), reason="activator timeout")

    assert _publish(tarball, keys, tmp_path, gh, FakeSsh(statuses=[status(), transient]),
                    "--canary-timeout-min", "2", clock=clock) != 0

    final = _verified(gh, keys)
    assert "did not commit within 2 min" in final["reason"] and "error" in final["reason"]
    assert clock.t >= 120


def test_a_failed_phase_for_another_candidate_does_not_withdraw(tarball, keys, tmp_path):
    gh = FakeGh()
    other = dict(status("failed", candidate="2026.10.01-021"), reason="old failure")

    assert _publish(tarball, keys, tmp_path, gh, FakeSsh(statuses=[status(), other, COMMITTED])) == 0


def test_a_stale_failed_phase_of_a_reused_id_does_not_withdraw(tarball, keys, tmp_path):
    gh = FakeGh()
    stale = dict(status("failed", candidate=RELEASE_ID), updated_at="2026-10-01T09:00:00Z")

    assert _publish(tarball, keys, tmp_path, gh, FakeSsh(statuses=[status(), stale, COMMITTED])) == 0


def test_an_error_phase_for_another_candidate_does_not_withdraw(tarball, keys, tmp_path):
    gh = FakeGh()
    other = status("error", candidate=None)

    assert _publish(tarball, keys, tmp_path, gh, FakeSsh(statuses=[status(), other, COMMITTED])) == 0


def _all_output(capsys, tmp_path) -> str:
    captured = capsys.readouterr()
    evidence = "".join(p.read_text(encoding="utf-8") for p in (tmp_path / "evidence").rglob("*.jsonl"))
    return captured.out + captured.err + evidence


def test_a_missing_private_key_is_named_without_its_path(tarball, keys, tmp_path, capsys):
    """M4."""
    keys["private"].unlink()

    assert _publish(tarball, keys, tmp_path, FakeGh(), FakeSsh()) != 0

    text = _all_output(capsys, tmp_path)
    assert "rosy-release-2026-01" in text
    for needle in (str(keys["private"]), str(keys["private"].parent), "appdata"):
        assert needle not in text


def test_a_signer_failure_does_not_leak_the_key_path(tarball, keys, tmp_path, capsys):
    keys["private"].write_text("not a key\n", encoding="ascii")
    gh = FakeGh()

    assert _publish(tarball, keys, tmp_path, gh, FakeSsh()) != 0

    assert gh.releases == {}
    text = _all_output(capsys, tmp_path)
    assert "rosy-release-2026-01" in text
    assert str(keys["private"].parent) not in text and "appdata" not in text


def test_withdraw_falls_back_to_the_local_signed_rollout(keys, tmp_path, capsys):
    """M5: a half-finished --clobber upload left rollout.json and its .sig from different versions."""
    gh = FakeGh()
    _signed_release(gh, keys, tmp_path, canary_ok=True)
    work = tmp_path / "w" / f"publish-{RELEASE_ID}"
    work.mkdir(parents=True)
    local = gh.releases[TAG]["assets"]["rollout.json"]
    (work / "rollout.json").write_bytes(local)
    (work / "rollout.json.sig").write_bytes(gh.releases[TAG]["assets"]["rollout.json.sig"])
    gh.releases[TAG]["assets"]["rollout.json"] = local.replace(b'"canary_ok": true', b'"canary_ok": false')

    code = _run(["--release-id", RELEASE_ID, "--out-dir", str(tmp_path / "w"), "--withdraw", "--reason", "bad"],
                keys, tmp_path, gh, FakeSsh())

    assert code == 0
    final = _verified(gh, keys)
    assert final["withdrawn"] is True and final["canary_ok"] is True
    assert "local" in capsys.readouterr().out


def test_withdraw_without_a_verifiable_copy_anywhere_fails(keys, tmp_path):
    gh = FakeGh()
    _signed_release(gh, keys, tmp_path)
    gh.releases[TAG]["assets"]["rollout.json"] += b" "

    code = _run(["--release-id", RELEASE_ID, "--out-dir", str(tmp_path / "w"), "--withdraw", "--reason", "bad"],
                keys, tmp_path, gh, FakeSsh())

    assert code != 0 and _uploads(gh) == []


@pytest.mark.parametrize("statuses, expected", [
    ([status(), COMMITTED], "canary_ok"),
    ([status(), status("rolled_back", last=result("rolled_back"))], "--withdraw"),
])
def test_a_failed_final_upload_prints_the_recovery_command(tarball, keys, tmp_path, capsys, statuses, expected):
    gh = FakeGh()
    gh.fail_upload = True

    assert _publish(tarball, keys, tmp_path, gh, FakeSsh(statuses=statuses)) != 0

    err = capsys.readouterr().err
    work = tarball.parent / f"publish-{RELEASE_ID}"
    assert f"gh release upload {TAG} --repo {REPO} --clobber" in err
    assert str(work / "rollout.json") in err and str(work / "rollout.json.sig") in err
    assert expected in err


def test_ctrl_c_prints_the_resume_and_withdraw_commands(tarball, keys, tmp_path, capsys):
    """L1."""
    clock = FakeClock()

    def interrupted(_seconds):
        raise KeyboardInterrupt

    code = tool.main(["--tarball", str(tarball), "--canary", CANARY_IP, "--public-key", str(keys["public"]),
                      "--evidence-dir", str(tmp_path / "evidence")],
                     gh_runner=FakeGh(), ssh_runner=FakeSsh(statuses=[status()]), now=clock.now,
                     monotonic=clock.monotonic, sleep=interrupted)

    assert code == 130
    err = capsys.readouterr().err
    assert f"--release-id {RELEASE_ID}" in err and "--resume" in err and f"--canary {CANARY_IP}" in err
    assert "--withdraw --reason" in err
    assert not (tarball.parent / f"publish-{RELEASE_ID}" / ".lock").exists()


@pytest.mark.parametrize("flag, value", [
    ("--repo", "livsbittt/rosy-os;x"), ("--repo", "noslash"), ("--repo", "a/b/c"),
    ("--key-name", "../evil"), ("--key-name", "a b"),
])
def test_repo_and_key_name_are_validated(tarball, keys, tmp_path, flag, value):
    """L6."""
    with pytest.raises(SystemExit) as raised:
        _publish(tarball, keys, tmp_path, FakeGh(), FakeSsh(), flag, value)
    assert raised.value.code == 2


def test_a_tarball_whose_release_signature_fails_is_not_published(tmp_path, keys, capsys):
    """L7."""
    bad = _tarball(tmp_path / "bad" / f"{RELEASE_ID}.tar.gz", keys["private"], tamper=True)
    gh = FakeGh()

    assert _publish(bad, keys, tmp_path, gh, FakeSsh()) != 0

    assert gh.releases == {}
    assert "CHECKSUM_MISMATCH" in capsys.readouterr().err
    work = bad.parent / f"publish-{RELEASE_ID}"
    assert not work.exists() or [p.name for p in work.iterdir() if p.name.startswith(".verify")] == []


def test_a_tarball_signed_by_another_key_is_not_published(tmp_path, keys):
    other_key = tmp_path / "other.pem"
    subprocess.run(["openssl", "genpkey", "-algorithm", "ed25519", "-out", str(other_key)],
                   check=True, capture_output=True)
    bad = _tarball(tmp_path / "bad" / f"{RELEASE_ID}.tar.gz", other_key)
    gh = FakeGh()

    assert _publish(bad, keys, tmp_path, gh, FakeSsh()) != 0
    assert gh.releases == {}


# --- re-review fixes (N1, N2, N4, N7, N8, N9) ----------------------------------------

def _local_copy(tmp_path, keys, **changes) -> Path:
    """A rollout this PC signed earlier, in the work folder."""
    work = tmp_path / "w" / f"publish-{RELEASE_ID}"
    work.mkdir(parents=True, exist_ok=True)
    rollout = tool.build_rollout(RELEASE_ID, "c" * 64, REVISION, "2026-10-01T14:00:00Z", CANARY, 600)
    rollout.update(changes)
    data = tool.rollout_bytes(rollout)
    (work / "rollout.json").write_bytes(data)
    (work / "rollout.json.sig").write_bytes(signing.sign_checksums(data, keys["private"]).encode())
    return work


def _withdraw(gh, keys, tmp_path, reason="bad"):
    return _run(["--release-id", RELEASE_ID, "--out-dir", str(tmp_path / "w"), "--withdraw", "--reason", reason],
                keys, tmp_path, gh, FakeSsh())


def test_a_withdrawn_local_fallback_is_still_uploaded(keys, tmp_path):
    """N1: the local copy says withdrawn, but GitHub's copy is broken, so GitHub may not be withdrawn."""
    gh = FakeGh()
    _signed_release(gh, keys, tmp_path, canary_ok=True)
    _local_copy(tmp_path, keys, withdrawn=True, reason="earlier withdraw")
    gh.releases[TAG]["assets"]["rollout.json"] += b" "

    assert _withdraw(gh, keys, tmp_path, "again") == 0

    assert len(_uploads(gh)) == 1
    final = _verified(gh, keys)
    assert final["withdrawn"] is True and final["reason"] == "again"


def test_an_already_withdrawn_github_copy_is_left_alone(keys, tmp_path):
    gh = FakeGh()
    _signed_release(gh, keys, tmp_path, withdrawn=True, reason="first")

    assert _withdraw(gh, keys, tmp_path) == 0
    assert _uploads(gh) == []
    assert _verified(gh, keys)["reason"] == "first"


def test_a_missing_remote_signature_uses_the_local_copy(keys, tmp_path):
    """N2: GitHub has a withdrawn rollout.json but no .sig; a matching .sig left in downloaded/ by an
    earlier run must not make it look verified (robots cannot verify it)."""
    gh = FakeGh()
    _signed_release(gh, keys, tmp_path, withdrawn=True, reason="half uploaded")
    _local_copy(tmp_path, keys)
    stale = tmp_path / "w" / f"publish-{RELEASE_ID}" / "downloaded"
    stale.mkdir(parents=True)
    (stale / "rollout.json.sig").write_bytes(gh.releases[TAG]["assets"]["rollout.json.sig"])
    del gh.releases[TAG]["assets"]["rollout.json.sig"]

    assert _withdraw(gh, keys, tmp_path) == 0

    assert len(_uploads(gh)) == 1
    final = _verified(gh, keys)
    assert final["withdrawn"] is True and final["reason"] == "bad"


def test_no_rollout_assets_at_all_uses_the_local_copy(keys, tmp_path):
    gh = FakeGh()
    _signed_release(gh, keys, tmp_path)
    _local_copy(tmp_path, keys)
    for name in ("rollout.json", "rollout.json.sig"):
        del gh.releases[TAG]["assets"][name]

    assert _withdraw(gh, keys, tmp_path) == 0
    assert _verified(gh, keys)["withdrawn"] is True


def test_a_withdraw_whose_upload_fails_prints_the_recovery_command(keys, tmp_path, capsys):
    """N9."""
    gh = FakeGh()
    _signed_release(gh, keys, tmp_path)
    gh.fail_upload = True

    assert _withdraw(gh, keys, tmp_path, "bad gains") != 0

    err = capsys.readouterr().err
    work = tmp_path / "w" / f"publish-{RELEASE_ID}"
    assert f"gh release upload {TAG} --repo {REPO} --clobber" in err and str(work / "rollout.json.sig") in err
    assert "--withdraw --reason" in err and "bad gains" in err


def test_a_withdraw_racing_the_final_upload_wins(tarball, keys, tmp_path, capsys):
    """N4: a withdraw lands right after this process uploaded canary_ok."""
    gh = FakeGh()
    gh_calls = gh.__call__

    def arm(argv):
        if argv[1:3] == ["release", "upload"] and not _uploads(gh):
            gh.after_upload = lambda: _rewrite_remote(gh, keys, withdrawn=True, reason="withdrawn by hand")
        return gh_calls(argv)

    assert _publish(tarball, keys, tmp_path, arm, FakeSsh()) == 3

    final = _verified(gh, keys)
    assert final["withdrawn"] is True and final["reason"] == "withdrawn by hand"
    assert len(_uploads(gh)) == 1  # the visible withdraw is kept, not uploaded over
    assert "withdrawn" in capsys.readouterr().out


def test_a_rollout_broken_by_a_racing_upload_is_withdrawn(tarball, keys, tmp_path):
    """N4: after the upload the remote bytes are not ours (half of someone else's --clobber)."""
    gh = FakeGh()
    gh_calls = gh.__call__

    def arm(argv):
        if argv[1:3] == ["release", "upload"] and not _uploads(gh):
            def clobber_half():
                gh.releases[TAG]["assets"]["rollout.json"] += b" "
            gh.after_upload = clobber_half
        return gh_calls(argv)

    assert _publish(tarball, keys, tmp_path, arm, FakeSsh()) == 3

    final = _verified(gh, keys)
    assert final["withdrawn"] is True and final["canary_ok"] is True
    assert "changed during the final upload" in final["reason"]


def test_a_clean_final_upload_is_checked_once_more_and_kept(tarball, keys, tmp_path):
    gh = FakeGh()

    assert _publish(tarball, keys, tmp_path, gh, FakeSsh()) == 0

    downloads = [c for c in gh.calls if c[1:3] == ["release", "download"]]
    assert len(downloads) == 2  # before the upload and after it
    assert len(_uploads(gh)) == 1


def test_a_stale_lock_is_named_stale(tarball, keys, tmp_path, capsys):
    """N7."""
    lock = tarball.parent / f"publish-{RELEASE_ID}" / ".lock"
    lock.parent.mkdir(parents=True)
    lock.write_text("99999999\n", encoding="ascii")

    assert _publish(tarball, keys, tmp_path, FakeGh(), FakeSsh()) != 0

    err = capsys.readouterr().err
    assert "is stale: process 99999999 is not running" in err and str(lock) in err
    assert lock.exists()


def test_a_live_lock_is_named_running(tarball, keys, tmp_path, capsys):
    lock = tarball.parent / f"publish-{RELEASE_ID}" / ".lock"
    lock.parent.mkdir(parents=True)
    lock.write_text(f"{os.getpid()}\n", encoding="ascii")

    assert _publish(tarball, keys, tmp_path, FakeGh(), FakeSsh()) != 0

    err = capsys.readouterr().err
    assert "stale" not in err and f"process {os.getpid()}" in err and "running" in err


def test_a_status_without_hostname_reads_as_not_run_yet(tarball, keys, tmp_path, capsys):
    """N8."""
    _publish(tarball, keys, tmp_path, FakeGh(), FakeSsh(statuses=[status(), NOT_RUN_YET, COMMITTED]))

    out = capsys.readouterr().out
    assert "has not run yet (no status.json)" in out
    assert "not the canary" not in out and "None" not in out.split("has not run yet")[0].splitlines()[-1]
