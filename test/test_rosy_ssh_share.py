"""D-418 tools/ssh/rosy_ssh_share.py: team key bundle, registration, revoke and list against fake CORE robots.

Nothing here reaches a robot. The bundle test uses the real ssh-keygen when it is on PATH (so the
"encrypted" claim is checked by OpenSSH itself) and a fake one that writes the OpenSSH key format otherwise.
"""

from __future__ import annotations

import base64
import importlib.util
from pathlib import Path
import shutil
import struct
import subprocess
import zipfile

import pytest

from fake_core_ssh import FakeCore, ed25519_public_key, isolate_home, real_ssh_snapshot

ROOT = Path(__file__).resolve().parents[1]
_SPEC = importlib.util.spec_from_file_location("rosy_ssh_share", ROOT / "tools" / "ssh" / "rosy_ssh_share.py")
tool = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(tool)

R1, R2 = "192.0.2.11", "192.0.2.12"
H1, H2 = "rosy-pinky-aaaa", "rosy-pinky-bbbb"
CODE1, CODE2 = "AAAA-1111", "BBBB-2222"
TEAM = "lab-a"
LABEL = "team:lab-a"
KEY_NAME = "id_ed25519_rosy_lab-a"
TYPED = "typed passphrase 42"
REAL_KEYGEN = shutil.which("ssh-keygen")


def _string(data: bytes) -> bytes:
    return struct.pack(">I", len(data)) + data


class FakeKeygen:
    """Writes an OpenSSH-format private key: bcrypt/aes256-ctr when -N is non-empty, none/none otherwise."""

    def __init__(self, ignore_lock: bool = False):
        self.ignore_lock = ignore_lock
        self.calls: list[list[str]] = []

    def __call__(self, argv: list[str]) -> tuple[int, str, str]:
        self.calls.append(argv)
        path = Path(argv[argv.index("-f") + 1])
        passphrase = "" if self.ignore_lock else argv[argv.index("-N") + 1]
        public = ed25519_public_key(b"team", argv[argv.index("-C") + 1])
        blob = base64.b64decode(public.split()[1])
        if passphrase:
            header = _string(b"aes256-ctr") + _string(b"bcrypt") + _string(_string(b"s" * 16) + struct.pack(">I", 16))
        else:
            header = _string(b"none") + _string(b"none") + _string(b"")
        data = b"openssh-key-v1\0" + header + struct.pack(">I", 1) + _string(blob) + _string(b"\x01" * 64)
        body = base64.b64encode(data).decode("ascii")
        lines = [body[i:i + 70] for i in range(0, len(body), 70)]
        path.write_text(tool.OPENSSH_BEGIN + "\n" + "\n".join(lines)
                        + "\n" + tool.OPENSSH_END + "\n", encoding="ascii")
        Path(str(path) + ".pub").write_text(public + "\n", encoding="ascii")
        return 0, "", ""


@pytest.fixture(scope="module", autouse=True)
def real_profile_untouched():
    before = real_ssh_snapshot()
    yield
    assert real_ssh_snapshot() == before, "a test wrote into the real ~/.ssh"


@pytest.fixture(autouse=True)
def home(tmp_path, monkeypatch):
    return isolate_home(tmp_path, monkeypatch)


def test_create_writes_nothing_into_home(home, robots, tmp_path, capsys):
    out = tmp_path / "out"
    status, _ = _create(robots, out, lock_answers=(TYPED, TYPED))
    assert status == 0, _text(capsys)[1]
    assert list(home.rglob("*")) == []
    assert sorted(p.name for p in out.iterdir()) == [f"rosy-{TEAM}.robots.txt", f"rosy-{TEAM}.zip"]


@pytest.fixture
def robots():
    with FakeCore(codes={CODE1: "administrator"}, hostname=H1) as one, \
            FakeCore(codes={CODE2: "administrator"}, hostname=H2) as two:
        yield {R1: one, R2: two}


def run(robots: dict, *argv: str, codes: dict | None = None, lock_answers=("", ""), keygen=None, ssh=None):
    codes = codes if codes is not None else {R1: CODE1, R2: CODE2}
    asked: list[str] = []

    def ask_code(prompt: str) -> str:
        robot = next(r for r in robots if r in prompt)
        asked.append(robot)
        return codes[robot]

    answers = iter(lock_answers)
    status = tool.main(list(argv), ask_code=ask_code, ask_lock=lambda prompt: next(answers),
                       keygen=keygen or FakeKeygen(),
                       client_for=lambda robot: tool.enroll.CoreClient(robots[robot].base_url), ssh=ssh)
    return status, asked


def _text(capsys) -> tuple[str, str]:
    captured = capsys.readouterr()
    return captured.out, captured.err


def _assert_clean(robots: dict, *texts: str) -> None:
    for core in robots.values():
        assert core.logged_out == core.issued
        for token in core.issued:
            assert all(token not in text for text in texts)


def _create(robots, out: Path, *extra: str, **kwargs):
    return run(robots, "create", "--name", TEAM, "--robot", R1, "--robot", R2, "--out", str(out), *extra, **kwargs)


def _encrypted_by_format(key: bytes) -> bool:
    lines = key.decode("ascii").strip().splitlines()
    assert lines[0] == tool.OPENSSH_BEGIN and lines[-1] == tool.OPENSSH_END
    data = base64.b64decode("".join(lines[1:-1]))
    assert data.startswith(b"openssh-key-v1\0")
    offset = len(b"openssh-key-v1\0")
    cipher_len = struct.unpack(">I", data[offset:offset + 4])[0]
    cipher = data[offset + 4:offset + 4 + cipher_len]
    offset += 4 + cipher_len
    kdf_len = struct.unpack(">I", data[offset:offset + 4])[0]
    kdf = data[offset + 4:offset + 4 + kdf_len]
    return cipher != b"none" and kdf == b"bcrypt"


@pytest.mark.parametrize("keygen_kind", ["real", "fake"])
def test_create_builds_a_locked_bundle_and_registers_the_team_key(keygen_kind, robots, tmp_path, capsys):
    if keygen_kind == "real" and REAL_KEYGEN is None:
        pytest.skip("ssh-keygen is not on PATH")
    keygen = tool.enroll.run_tool if keygen_kind == "real" else FakeKeygen()
    out = tmp_path / "out"
    status, asked = _create(robots, out, "--contact", "운영자 홍길동", lock_answers=(TYPED, TYPED), keygen=keygen)
    stdout, stderr = _text(capsys)
    assert status == 0, stderr
    assert asked == [R1, R2]

    bundle = out / f"rosy-{TEAM}.zip"
    # the work folder is gone; beside the zip only the non-secret robots list
    assert sorted(p.name for p in out.iterdir()) == [f"rosy-{TEAM}.robots.txt", bundle.name]
    with zipfile.ZipFile(bundle) as archive:
        entries = {info.filename: archive.read(info) for info in archive.infolist()}
        modes = {info.filename: (info.external_attr >> 16) & 0o777 for info in archive.infolist()}
    assert set(entries) == {KEY_NAME, KEY_NAME + ".pub", "config", "known_hosts", "README.md"}
    assert modes[KEY_NAME] == 0o600

    # The private key is locked, and the passphrase is in no file of the bundle.
    assert _encrypted_by_format(entries[KEY_NAME])
    for name, data in entries.items():
        assert TYPED.encode("utf-8") not in data, name
    assert TYPED not in stdout + stderr
    if keygen_kind == "real":
        key = tmp_path / "check" / KEY_NAME
        key.parent.mkdir()
        key.write_bytes(entries[KEY_NAME])
        key.chmod(0o600)  # as the README tells recipients; OpenSSH on POSIX refuses a readable key
        empty = subprocess.run([REAL_KEYGEN, "-y", "-P", "", "-f", str(key)], capture_output=True)
        assert empty.returncode != 0
        right = subprocess.run([REAL_KEYGEN, "-y", "-P", TYPED, "-f", str(key)], capture_output=True)
        assert right.returncode == 0
        assert right.stdout.split()[:2] == entries[KEY_NAME + ".pub"].split()[:2]

    public = entries[KEY_NAME + ".pub"].decode("ascii").strip()
    for robot, core in robots.items():
        assert core.public_keys == {LABEL: public}
        body = next(b for m, p, b in core.requests if m == "POST" and p == "/api/v1/host/ssh/keys")
        assert body["expires_days"] == 90 and body["label"] == LABEL

    config = entries["config"].decode("utf-8")
    for robot, host in ((R1, H1), (R2, H2)):
        assert f"Host {host}\n    HostName {robot}\n    User rosy\n" in config
    assert f'IdentityFile "~/.ssh/rosy-{TEAM}/{KEY_NAME}"' in config
    assert f'UserKnownHostsFile "~/.ssh/rosy-{TEAM}/known_hosts"' in config
    assert config.count("IdentitiesOnly yes") == 2

    known = entries["known_hosts"].decode("ascii").splitlines()
    assert known == [f"{H1},{R1} " + " ".join(robots[R1].host_keys[0].split()[:2]),
                     f"{H2},{R2} " + " ".join(robots[R2].host_keys[0].split()[:2])]

    readme = entries["README.md"].decode("utf-8")
    for needle in ("Windows", "macOS", "Linux", "ssh-add", "ssh -F config", H1, H2, "Termius",
                   "다른 사람에게 넘기지", "운영자 홍길동", "SHA256:"):
        assert needle in readme, needle
    assert "passphrase" in readme  # it explains the passphrase without containing it
    _assert_clean(robots, stdout, stderr, *(data.decode("utf-8", "replace") for data in entries.values()))


def test_a_generated_passphrase_is_shown_once_and_never_saved(robots, tmp_path, capsys):
    status, _ = _create(robots, tmp_path, lock_answers=("",))
    stdout, stderr = _text(capsys)
    assert status == 0, stderr
    shown = [line for line in stderr.splitlines() if line.startswith("Passphrase")]
    assert len(shown) == 1
    passphrase = shown[0].rsplit(": ", 1)[1].strip()
    assert tool.GENERATED.fullmatch(passphrase)
    assert stderr.count(passphrase) == 1 and passphrase not in stdout  # stderr: kept out of piped stdout
    assert "not a terminal" in stderr  # pytest captures stderr, so the tool warns
    assert passphrase not in (tmp_path / f"rosy-{TEAM}.robots.txt").read_text(encoding="utf-8")
    with zipfile.ZipFile(tmp_path / f"rosy-{TEAM}.zip") as archive:
        for info in archive.infolist():
            assert passphrase.encode("ascii") not in archive.read(info)


def test_a_short_or_mistyped_passphrase_is_refused_before_anything(robots, tmp_path, capsys):
    assert _create(robots, tmp_path, lock_answers=("short", "short"))[0] == 1
    assert "at least" in _text(capsys)[1]
    assert _create(robots, tmp_path, lock_answers=(TYPED, TYPED + "x"))[0] == 1
    assert "did not match" in _text(capsys)[1]
    assert all(core.requests == [] for core in robots.values())
    assert list(tmp_path.iterdir()) == []


def test_an_unencrypted_key_is_never_bundled_or_registered(robots, tmp_path, capsys):
    status, _ = _create(robots, tmp_path, lock_answers=(TYPED, TYPED), keygen=FakeKeygen(ignore_lock=True))
    assert status == 1
    assert "not encrypted" in _text(capsys)[1]
    assert all(core.requests == [] for core in robots.values())
    assert list(tmp_path.iterdir()) == []


def test_a_failure_on_a_later_robot_builds_no_bundle_and_names_the_revoke(robots, tmp_path, capsys):
    status, _ = _create(robots, tmp_path, lock_answers=(TYPED, TYPED), codes={R1: CODE1, R2: "WRNG-CODE"})
    stdout, stderr = _text(capsys)
    assert status == 1
    assert list(tmp_path.iterdir()) == []
    assert LABEL in robots[R1].keys and robots[R2].keys == {}
    assert f"revoke --name {TEAM} --robot {R1}" in stderr
    _assert_clean(robots, stdout, stderr)


def test_an_existing_bundle_is_not_overwritten(robots, tmp_path, capsys):
    (tmp_path / f"rosy-{TEAM}.zip").write_bytes(b"old")
    assert _create(robots, tmp_path, lock_answers=(TYPED, TYPED))[0] == 1
    assert (tmp_path / f"rosy-{TEAM}.zip").read_bytes() == b"old"
    assert all(core.requests == [] for core in robots.values())
    assert "exists" in _text(capsys)[1]


def test_revoke_deletes_the_label_on_every_robot(robots, tmp_path, capsys):
    robots[R1].keys[LABEL] = {"label": LABEL}
    robots[R1].public_keys[LABEL] = "x"
    robots[R1].keys["dev:keep"] = {"label": "dev:keep"}
    robots[R1].public_keys["dev:keep"] = "y"
    status, _ = run(robots, "revoke", "--name", TEAM, "--robot", R1, "--robot", R2)
    stdout, stderr = _text(capsys)
    assert status == 0, stderr
    assert ("DELETE", f"/api/v1/host/ssh/keys/{LABEL}", None) in robots[R1].requests
    assert set(robots[R1].keys) == {"dev:keep"}
    assert f"{R1}: revoked {LABEL}" in stdout
    assert f"{R2}: {LABEL} was not present" in stdout
    _assert_clean(robots, stdout, stderr)


def test_list_shows_the_managed_keys(robots, capsys):
    robots[R1].keys = {
        LABEL: {"label": LABEL, "type": "ssh-ed25519", "fingerprint": "SHA256:team", "added_at": "a",
                "expires_at": "2026-12-31T00:00:00Z", "added_by": "ssh-share"},
        "dev:pc": {"label": "dev:pc", "type": "ssh-ed25519", "fingerprint": "SHA256:dev", "added_at": "a",
                   "expires_at": "2026-11-30T00:00:00Z", "added_by": "ssh-enroll"}}
    status, _ = run(robots, "list", "--robot", R1, "--robot", R2)
    stdout, stderr = _text(capsys)
    assert status == 0, stderr
    assert LABEL in stdout and "SHA256:team" in stdout and "2026-12-31T00:00:00Z" in stdout
    assert "dev:pc" in stdout and "SHA256:dev" in stdout
    assert f"{R2}: no managed keys" in stdout
    robots[R1].codes["CCCC-3333"] = "administrator"
    status, _ = run(robots, "list", "--robot", R1, "--name", TEAM, codes={R1: "CCCC-3333"})
    filtered, _ = _text(capsys)
    assert status == 0 and LABEL in filtered and "dev:pc" not in filtered
    _assert_clean(robots, stdout, stderr, filtered)


def test_via_operator_key_reads_the_code_over_ssh_and_never_prints_it(robots, tmp_path, capsys):
    calls: list[list[str]] = []
    key = tmp_path / "operator-key"

    def fake_ssh(argv: list[str]) -> tuple[int, str, str]:
        calls.append(argv)
        robot = argv[-2].split("@")[1]
        code = {R1: CODE1, R2: CODE2}[robot]
        return 0, f"Login code {code}  (administrator, valid 5 min, one use)\n", ""

    status, asked = run(robots, "list", "--robot", R1, "--robot", R2, "--via-operator-key", str(key), ssh=fake_ssh)
    stdout, stderr = _text(capsys)
    assert status == 0, stderr
    assert asked == []
    assert len(calls) == 2
    argv = calls[0]
    assert argv[argv.index("-i") + 1] == str(key)
    for option in ("BatchMode=yes", "IdentitiesOnly=yes", "PasswordAuthentication=no",
                   "StrictHostKeyChecking=accept-new"):
        assert option in argv
    assert argv[-2] == f"rosy@{R1}"
    assert argv[-1] == "sudo -n rosy-login-code --role administrator --minutes 5"
    assert CODE1 not in stdout + stderr and CODE2 not in stdout + stderr
    _assert_clean(robots, stdout, stderr)


def test_via_operator_key_failure_is_reported_without_output(robots, tmp_path, capsys):
    def failing_ssh(argv):
        return 255, "", "Permission denied (publickey)."

    status, _ = run(robots, "list", "--robot", R1, "--via-operator-key", str(tmp_path / "k"), ssh=failing_ssh)
    assert status == 1
    assert "Permission denied" in _text(capsys)[1]
    assert robots[R1].requests == []


@pytest.mark.parametrize("argv", [
    ["create", "--name", "Lab", "--robot", R1, "--out", "x"],
    ["create", "--name", "a" * 44, "--robot", R1, "--out", "x"],
    ["create", "--name", TEAM, "--out", "x"],
    ["create", "--name", TEAM, "--robot", R1, "--out", "x", "--days", "400"],
    ["revoke", "--name", "dev:x", "--robot", R1],
    ["list", "--robot", "192.0.2.1\nHost *"],
])
def test_bad_arguments_are_refused(argv, robots):
    with pytest.raises(SystemExit) as exit_info:
        run(robots, *argv)
    assert exit_info.value.code == 2
    assert all(core.requests == [] for core in robots.values())


# --- review 2026-10-02 -------------------------------------------------------------------


def test_the_zip_extracts_to_exactly_the_folder_config_names(robots, tmp_path, capsys):
    """Flat entries in rosy-<team>.zip: Windows "Extract All" and macOS Archive Utility both make a folder
    named after the zip, and `unzip -d ~/.ssh/rosy-<team>` does the same, which is the folder config uses."""
    status, _ = _create(robots, tmp_path, lock_answers=(TYPED, TYPED))
    assert status == 0, _text(capsys)[1]
    bundle = tmp_path / f"rosy-{TEAM}.zip"
    with zipfile.ZipFile(bundle) as archive:
        names = archive.namelist()
        config = archive.read("config").decode("utf-8")
        readme = archive.read("README.md").decode("utf-8")
    assert all("/" not in name and "\\" not in name for name in names)
    folders = {line.split('"')[1].rsplit("/", 1)[0] for line in config.splitlines()
               if line.strip().startswith(("IdentityFile", "UserKnownHostsFile"))}
    assert folders == {f"~/.ssh/{bundle.stem}"}
    for name in names:
        if name != "README.md":
            assert any(line.split('"')[1].endswith("/" + name) for line in config.splitlines() if '"' in line) \
                or name in (f"id_ed25519_rosy_{TEAM}.pub", "config")
    for needle in (f"%USERPROFILE%\\.ssh", "압축 풀기", f"~/.ssh/{bundle.stem}",
                   f"unzip {bundle.name} -d ~/.ssh/{bundle.stem}", f"cd $HOME\\.ssh\\{bundle.stem}"):
        assert needle in readme, needle


def test_duplicate_robot_hostnames_are_refused(tmp_path, capsys):
    with FakeCore(codes={CODE1: "administrator"}, hostname=H1) as one, \
            FakeCore(codes={CODE2: "administrator"}, hostname=H1) as two:
        robots = {R1: one, R2: two}
        status, _ = _create(robots, tmp_path, lock_answers=(TYPED, TYPED))
    stdout, stderr = _text(capsys)
    assert status == 1
    assert "duplicate" in stderr and H1 in stderr
    assert two.keys == {}  # refused before registering on the second robot
    assert f"revoke --name {TEAM} --robot {R1}" in stderr
    assert list(tmp_path.iterdir()) == []


def test_create_prints_the_revoke_command_and_writes_a_robots_list(robots, tmp_path, capsys):
    status, _ = _create(robots, tmp_path, lock_answers=(TYPED, TYPED))
    stdout, stderr = _text(capsys)
    assert status == 0, stderr
    revoke = f"revoke --name {TEAM} --robot {R1} --robot {R2}"
    assert revoke in stdout
    listing = (tmp_path / f"rosy-{TEAM}.robots.txt").read_text(encoding="utf-8")
    for needle in (revoke, H1, H2, R1, R2, LABEL, "SHA256:"):
        assert needle in listing, needle
    assert TYPED not in listing and "PRIVATE KEY" not in listing


def test_a_bundle_write_failure_names_the_revoke(robots, tmp_path, monkeypatch, capsys):
    def broken(*args, **kwargs):
        raise OSError(28, "No space left on device")

    monkeypatch.setattr(tool, "write_bundle", broken)
    status, _ = _create(robots, tmp_path, lock_answers=(TYPED, TYPED))
    stdout, stderr = _text(capsys)
    assert status == 1
    assert "No space left" in stderr
    assert f"revoke --name {TEAM} --robot {R1} --robot {R2}" in stderr
    assert list(tmp_path.iterdir()) == []
    _assert_clean(robots, stdout, stderr)


def test_revoke_by_device_label(robots, capsys):
    robots[R1].keys["dev:laptop"] = {"label": "dev:laptop"}
    robots[R1].public_keys["dev:laptop"] = "x"
    status, _ = run(robots, "revoke", "--label", "dev:laptop", "--robot", R1)
    stdout, stderr = _text(capsys)
    assert status == 0, stderr
    assert robots[R1].keys == {}
    assert f"{R1}: revoked dev:laptop" in stdout
    _assert_clean(robots, stdout, stderr)


@pytest.mark.parametrize("argv", [
    ["revoke", "--label", "admin", "--robot", R1],
    ["revoke", "--label", "Dev:x", "--robot", R1],
    ["revoke", "--name", TEAM, "--label", "dev:x", "--robot", R1],
    ["revoke", "--robot", R1],
])
def test_revoke_needs_exactly_one_valid_target(argv, robots):
    with pytest.raises(SystemExit) as exit_info:
        run(robots, *argv)
    assert exit_info.value.code == 2
    assert all(core.requests == [] for core in robots.values())
