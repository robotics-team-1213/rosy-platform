"""D-406 tools/release/publish_payload_release.py with a fake gh, fake ssh and a fake clock.

Nothing here reaches GitHub or a robot. The signing key pair is generated per test
with openssl (the same tool signing.py shells out to).
"""

from __future__ import annotations

import datetime as dt
import importlib.util
import io
import json
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
            return 0, "", ""
        if command == "download":
            target = Path(flags["--dir"][0])
            target.mkdir(parents=True, exist_ok=True)
            for pattern in flags["--pattern"]:
                (target / pattern).write_bytes(self.releases[tag]["assets"][pattern])
            return 0, "", ""
        raise AssertionError(argv)

    def rollout(self, tag=TAG) -> dict:
        return json.loads(self.releases[tag]["assets"]["rollout.json"])


def status(phase="idle", current="2026.10.01-021", candidate=None, last=None) -> dict:
    return {"schema": 1, "updated_at": "2026-10-01T15:00:00Z", "hostname": CANARY,
            "current_release": current, "candidate": candidate, "phase": phase, "reason": "",
            "last_result": last}


COMMITTED = status("committed", RELEASE_ID, None,
                   {"release_id": RELEASE_ID, "outcome": "committed", "at": "Z", "detail": "healthy"})


class FakeSsh:
    def __init__(self, statuses=(COMMITTED,), hostname=CANARY, others=None):
        self.statuses = list(statuses)
        self.hostname = hostname
        self.others = others or {}
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


def _tarball(path: Path, release_id=RELEASE_ID, revision=REVISION) -> Path:
    files = {"manifest.json": json.dumps({"release_id": release_id}) + "\n",
             "source-revision.txt": revision + "\n", "SHA256SUMS": "", "SHA256SUMS.sig": ""}
    path.parent.mkdir(parents=True, exist_ok=True)
    with tarfile.open(path, "w:gz") as tar:
        for name, text in files.items():
            data = text.encode("utf-8")
            info = tarfile.TarInfo(name)
            info.size = len(data)
            tar.addfile(info, io.BytesIO(data))
    return path


@pytest.fixture
def tarball(tmp_path):
    return _tarball(tmp_path / "out" / f"{RELEASE_ID}.tar.gz")


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
    other = _tarball(tmp_path / "a" / f"{RELEASE_ID}.tar.gz", release_id="2026.10.01-099")
    short = _tarball(tmp_path / "b" / f"{RELEASE_ID}.tar.gz", revision="abc")

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
    assert len(ssh.status_polls()) == 5 and clock.t == 4 * 30
    out = capsys.readouterr().out
    for phase in ("staged", "applying", "unreachable", "committed"):
        assert phase in out


@pytest.mark.parametrize("outcome", ["rolled_back", "refused"])
def test_canary_rollback_or_refusal_withdraws(tarball, keys, tmp_path, outcome):
    gh = FakeGh()
    failed = status("rolled_back", "2026.10.01-021", None,
                    {"release_id": RELEASE_ID, "outcome": outcome, "at": "Z", "detail": "core not ready"})

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
    assert len(ssh.status_polls()) == 21


@pytest.mark.parametrize("canary_status", [
    # an older release's commit is not this release's
    status("committed", RELEASE_ID, None,
           {"release_id": "2026.10.01-021", "outcome": "committed", "at": "Z", "detail": ""}),
    # this release committed but the robot is not on it any more
    status("idle", "2026.10.01-021", None,
           {"release_id": RELEASE_ID, "outcome": "committed", "at": "Z", "detail": ""}),
    # an older release rolled back: not a failure of this one
    status("rolled_back", "2026.10.01-021", None,
           {"release_id": "2026.10.01-020", "outcome": "rolled_back", "at": "Z", "detail": ""}),
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
