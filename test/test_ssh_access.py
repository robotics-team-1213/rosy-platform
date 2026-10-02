"""D-418: the root SSH access helper (rosy-ssh-access) on CORE's request.

The program runs over a temporary root. chpasswd, usermod, sshd -t and
systemctl are methods of `System` that a fake replaces, so the tests can assert
what was applied, in which order, and what never reached a file.
"""

from __future__ import annotations

import base64
from datetime import datetime, timedelta, timezone
import importlib.util
import json
import os
from pathlib import Path
import re
import stat
import subprocess
import sys

import pytest

ROOT = Path(__file__).resolve().parents[1]
NATIVE = ROOT / "deploy/robot/pinky_pro/native"
POSIX = pytest.mark.skipif(os.name != "posix", reason="symlinks and POSIX modes")
NOW = datetime(2026, 10, 2, 12, 30, 15, tzinfo=timezone.utc)


def _load():
    spec = importlib.util.spec_from_file_location("rosy_ssh_access", NATIVE / "rosy-ssh-access.py")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


ssh = _load()


def _string(value: bytes) -> bytes:
    return len(value).to_bytes(4, "big") + value


def _key(kind: str = "ssh-ed25519", body: bytes = b"\x00" * 32) -> str:
    """A public key blob shaped like OpenSSH's for `kind` (RFC 4253 strings)."""
    if kind.startswith("ecdsa-"):
        curve = kind.rsplit("-", 1)[1]
        size = {"nistp256": 32, "nistp384": 48, "nistp521": 66}[curve]
        parts = [curve.encode(), b"\x04" + (body * 5)[:2 * size]]
    elif kind.startswith("sk-"):
        parts = [body, b"ssh:"]
    else:
        parts = [body]
    blob = _string(kind.encode()) + b"".join(_string(part) for part in parts)
    return f"{kind} {base64.b64encode(blob).decode()}"


KEY_A = _key(body=b"\x01" * 32)
KEY_B = _key(body=b"\x02" * 32)


class FakeSystem(ssh.System):
    def __init__(self, root: Path, *, now: datetime = NOW, sshd_ok: bool = True, chpasswd_ok: bool = True,
                 ssh_active: bool = True, lock_ok: bool = True, timer_ok: bool = True,
                 boot: float | None = None, boot_id: str = "boot-1", ntp: bool = False) -> None:
        super().__init__(root)
        self.at = now
        self.boot = boot
        self.boot_ident = boot_id
        self.ntp = ntp
        self.sshd_ok = sshd_ok
        self.chpasswd_ok = chpasswd_ok
        self.ssh_active = ssh_active
        self.lock_ok = lock_ok
        self.timer_ok = timer_ok
        self.calls: list[tuple] = []

    def now(self) -> datetime:
        return self.at

    def boot_time(self) -> float:
        # Seconds since boot: follows the wall clock unless a test pins it.
        return self.boot if self.boot is not None else 1000.0 + (self.at - NOW).total_seconds()

    def boot_id(self) -> str:
        return self.boot_ident

    def ntp_synced(self) -> bool:
        return self.ntp

    def set_password(self, user: str, password: str) -> None:
        self.calls.append(("set_password", user, password))
        if not self.chpasswd_ok:
            raise ssh.HelperError("chpasswd failed")

    def lock_password(self, user: str) -> None:
        self.calls.append(("lock_password", user))
        if not self.lock_ok:
            raise ssh.HelperError("usermod failed")

    def sshd_check(self) -> tuple[bool, str]:
        self.calls.append(("sshd_check",))
        dropin = self.path(ssh.PASSWORD_DROPIN)
        self.calls.append(("dropin_at_check", dropin.is_file()))
        return self.sshd_ok, "" if self.sshd_ok else "line 2: Bad configuration option"

    def reload_sshd(self) -> None:
        self.calls.append(("reload_sshd", self.ssh_active))

    def expire_timer(self, start: bool) -> None:
        self.calls.append(("expire_timer", start))
        if start and not self.timer_ok:
            raise ssh.HelperError("timer failed")

    def core_group(self):
        return None

    def names(self) -> list[str]:
        return [call[0] for call in self.calls]


def _request(root: Path, action: str, *, request_id: str = "0123456789abcdef", by: str = "laptop admin",
             at: datetime = NOW, answer_in: float = 10.0, **params) -> Path:
    path = root / ssh.REQUEST
    path.parent.mkdir(parents=True, exist_ok=True)
    document = {"schema": 1, "request_id": request_id, "action": action, "by": by,
                "requested_at": at.strftime("%Y-%m-%dT%H:%M:%SZ"),
                "answer_by": at.timestamp() + answer_in, **params}
    path.write_text(json.dumps(document), encoding="utf-8")
    return path


def _response(root: Path) -> dict:
    return json.loads((root / ssh.RESPONSE).read_text(encoding="utf-8"))


def _run(root: Path, system: FakeSystem, action: str, **params) -> dict:
    _request(root, action, **params)
    assert ssh.main(["--root", str(root)], system=system) == 0
    return _response(root)


def _keys(root: Path) -> list[dict]:
    return json.loads((root / ssh.KEYS).read_text(encoding="utf-8"))["keys"]


def _history(root: Path) -> list[dict]:
    path = root / ssh.HISTORY
    if not path.is_file():
        return []
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]


# --- validation, independent of CORE --------------------------------------------


@pytest.mark.parametrize("kind", ["ssh-ed25519", "sk-ssh-ed25519@openssh.com", "ecdsa-sha2-nistp256",
                                  "ecdsa-sha2-nistp384", "ecdsa-sha2-nistp521"])
def test_allowed_key_types_validate_and_drop_the_comment(kind):
    key = _key(kind)
    assert ssh.validate_public_key(f"{key} someone@laptop") == tuple(key.split())


@pytest.mark.parametrize("text", [
    _key("ssh-rsa"),                                      # not on the allowlist
    _key("ssh-dss"),
    "ssh-ed25519 " + _key("ecdsa-sha2-nistp256").split()[1],  # body names another type
    "ssh-ed25519 AAAA$$$$",                                # not base64
    "ssh-ed25519 AAAAC3NzaC1lZDI1NTE5",                     # the type header and no key
    "ssh-ed25519 " + base64.b64encode(b"\x00\x00\x00\x0bssh-ed25519\x00\x00\x00\x10" + b"\x00" * 16).decode(),
    "ecdsa-sha2-nistp256 " + _key("ecdsa-sha2-nistp384").split()[1],  # header right, curve wrong
    _key("ssh-ed25519") + "A",                             # trailing garbage in the body
    "ssh-ed25519 " + _key("ssh-dss").split()[1],           # an ed25519-shaped body under another type name
    _key("sk-ssh-ed25519@openssh.com").rstrip("="),        # padding stripped: not strict base64
    "ecdsa-sha2-nistp256 " + base64.b64encode(              # a point of the wrong size
        _string(b"ecdsa-sha2-nistp256") + _string(b"nistp256") + _string(b"\x04" + b"\x01" * 1500)).decode(),
    "ecdsa-sha2-nistp256 " + base64.b64encode(              # a compressed point
        _string(b"ecdsa-sha2-nistp256") + _string(b"nistp256") + _string(b"\x02" + b"\x01" * 64)).decode(),
    'command="sh" ' + KEY_A,                               # options are never taken from a request
    KEY_A + "\n" + KEY_B,                                  # two lines
    KEY_A + " comment\nssh-ed25519 x",
    "ssh-ed25519 " + base64.b64encode(b"\x00\x00\x00\x0bssh-ed25519" + b"\x00" * 3000).decode(),  # too long
    "",
    None,
    42,
])
def test_disallowed_or_malformed_keys_are_refused(text):
    with pytest.raises(ssh.Invalid):
        ssh.validate_public_key(text)


@pytest.mark.parametrize("label", ["a", "team:alpha", "dev:my-laptop.2", "x" * 48, "0-9"])
def test_labels_on_the_contract_regex_pass(label):
    assert ssh.validate_label(label) == label


@pytest.mark.parametrize("label", ["", "A", "Team:alpha", "-dev", ":x", ".x", "x" * 49, "a b", "a\n", "a/b",
                                   "dev:é", None, 7])
def test_labels_off_the_contract_regex_are_refused(label):
    with pytest.raises(ssh.Invalid):
        ssh.validate_label(label)


@pytest.mark.parametrize("value,low,high,ok", [
    (1, 1, 365, True), (365, 1, 365, True), (0, 1, 365, False), (366, 1, 365, False),
    (True, 1, 365, False), ("5", 1, 365, False), (5.0, 1, 365, False), (None, 1, 365, False),
    (1, 1, 60, True), (60, 1, 60, True), (61, 1, 60, False), (-1, 1, 60, False),
])
def test_ranges_are_strict_integers(value, low, high, ok):
    if ok:
        assert ssh.bounded_int(value, low, high, "x") == value
    else:
        with pytest.raises(ssh.Invalid):
            ssh.bounded_int(value, low, high, "x")


def test_the_fingerprint_is_openssh_sha256_without_padding():
    blob = base64.b64decode(KEY_A.split()[1])
    import hashlib
    expected = "SHA256:" + base64.b64encode(hashlib.sha256(blob).digest()).decode().rstrip("=")
    assert ssh.fingerprint(KEY_A.split()[1]) == expected


def test_key_types_match_the_card_operator_allowlist():
    sys.path.insert(0, str(ROOT))
    from deploy.robot.pinky_pro.sd.personalization import OPERATOR_KEY_TYPES

    assert set(ssh.KEY_TYPES) == set(OPERATOR_KEY_TYPES)


def test_password_alphabet_is_the_ap_password_alphabet():
    sys.path.insert(0, str(ROOT / "deploy/robot/pinky_pro/release"))
    from network import READABLE_ALPHABET

    assert ssh.PASSWORD_ALPHABET == READABLE_ALPHABET
    assert len(set(ssh.PASSWORD_ALPHABET)) == 31


def test_generated_passwords_have_the_contract_shape_and_use_the_whole_alphabet():
    seen = set()
    for _ in range(300):
        password = ssh.generate_password()
        assert re.fullmatch(r"rosy-[a-z2-9]{4}-[a-z2-9]{4}-[a-z2-9]{4}", password), password
        seen |= set(password[5:].replace("-", ""))
    assert seen == set(ssh.PASSWORD_ALPHABET)


# --- the request file, read strictly ----------------------------------------------


def test_a_request_with_extra_keys_or_wrong_params_is_ignored(tmp_path):
    system = FakeSystem(tmp_path)
    for params in ({"label": "a", "extra": 1}, {}, {"label": "a", "public_key": KEY_A}):
        _request(tmp_path, "revoke", **params)
        assert ssh.main(["--root", str(tmp_path)], system=system) == 0
        assert not (tmp_path / ssh.RESPONSE).exists()


@pytest.mark.parametrize("change", [
    {"action": "shell"}, {"request_id": "XYZ"}, {"request_id": "0" * 8}, {"schema": 2},
    {"by": "x" * 129}, {"by": 5}, {"by": "line\nbreak"},
    {"answer_by": None}, {"answer_by": True}, {"answer_by": "1"}, {"answer_by": NOW.timestamp() - 1},
    {"answer_by": NOW.timestamp() + 60}, {"answer_by": float("nan")},
])
def test_a_request_with_a_bad_header_is_ignored(tmp_path, change):
    document = {"schema": 1, "request_id": "0123456789abcdef", "action": "list", "by": "a",
                "requested_at": NOW.strftime("%Y-%m-%dT%H:%M:%SZ"), "answer_by": NOW.timestamp() + 10, **change}
    path = tmp_path / ssh.REQUEST
    path.parent.mkdir(parents=True)
    path.write_text(json.dumps(document), encoding="utf-8")
    assert ssh.read_request(path, NOW.timestamp()) is None


@pytest.mark.parametrize("age_s,accepted", [(0, True), (29, True), (31, False), (-10, False)])
def test_a_stale_or_future_request_is_ignored(tmp_path, age_s, accepted):
    path = _request(tmp_path, "list", at=NOW - timedelta(seconds=age_s))
    assert (ssh.read_request(path, NOW.timestamp()) is not None) is accepted


def test_an_oversized_request_is_ignored(tmp_path):
    path = _request(tmp_path, "list", by="a")
    path.write_text(path.read_text(encoding="utf-8") + " " * ssh.MAX_REQUEST_BYTES, encoding="utf-8")
    assert ssh.read_request(path, NOW.timestamp()) is None


@POSIX
def test_a_symlinked_request_is_never_followed(tmp_path):
    real = _request(tmp_path, "list")
    moved = tmp_path / "elsewhere.json"
    real.rename(moved)
    real.symlink_to(moved)
    assert ssh.read_request(real, NOW.timestamp()) is None


def test_the_request_is_consumed_so_a_second_trigger_does_nothing(tmp_path):
    system = FakeSystem(tmp_path)
    first = _run(tmp_path, system, "password_on", minutes=10)
    assert not (tmp_path / ssh.REQUEST).exists()
    (tmp_path / ssh.RESPONSE).unlink()
    assert ssh.main(["--root", str(tmp_path)], system=system) == 0
    assert not (tmp_path / ssh.RESPONSE).exists()
    assert system.names().count("set_password") == 1 and first["status"] == 200


# --- keys ---------------------------------------------------------------------------


def test_add_writes_the_contract_line_metadata_and_history(tmp_path):
    system = FakeSystem(tmp_path)
    response = _run(tmp_path, system, "add", public_key=KEY_A + " me@laptop", label="dev:laptop",
                    expires_days=30)

    expires = "2026-11-01T12:30:00Z"
    assert response["request_id"] == "0123456789abcdef" and response["status"] == 201
    assert response["result"] == {"label": "dev:laptop", "fingerprint": ssh.fingerprint(KEY_A.split()[1]),
                                  "expires_at": expires}
    line = (tmp_path / ssh.AUTHORIZED).read_text(encoding="utf-8")
    assert line == f'expiry-time="202611011230Z" {KEY_A} rosy-managed:dev:laptop\n'
    [entry] = _keys(tmp_path)
    assert entry == {"label": "dev:laptop", "type": "ssh-ed25519", "key": KEY_A.split()[1],
                     "fingerprint": response["result"]["fingerprint"], "added_at": "2026-10-02T12:30:15Z",
                     "expires_at": expires, "added_by": "laptop admin"}
    [event] = _history(tmp_path)
    assert event["event"] == "add" and event["label"] == "dev:laptop" and event["by"] == "laptop admin"
    assert ("reload_sshd", True) in system.calls  # the managed-keys drop-in was installed
    dropin = (tmp_path / ssh.KEYS_DROPIN).read_text(encoding="utf-8")
    assert "AuthorizedKeysFile .ssh/authorized_keys /var/lib/rosy/ssh/authorized_keys" in dropin
    assert "Match User rosy" in dropin


@POSIX
def test_managed_files_have_the_modes_sshd_and_privacy_need(tmp_path):
    _run(tmp_path, FakeSystem(tmp_path), "add", public_key=KEY_A, label="a", expires_days=1)
    mode = lambda relative: stat.S_IMODE((tmp_path / relative).stat().st_mode)  # noqa: E731
    assert mode(ssh.AUTHORIZED) == 0o644   # sshd reads it as rosy
    assert mode(ssh.KEYS) == 0o600 and mode(ssh.HISTORY) == 0o600
    assert mode(ssh.STATE_DIR) == 0o755


def test_listing_shows_the_contract_fields(tmp_path):
    system = FakeSystem(tmp_path)
    _run(tmp_path, system, "add", public_key=KEY_A, label="team:blue", expires_days=90)
    response = _run(tmp_path, system, "list")
    assert response["status"] == 200
    [row] = response["result"]["keys"]
    assert set(row) == {"label", "type", "fingerprint", "added_at", "expires_at", "added_by"}


def test_a_label_or_key_already_enrolled_is_a_conflict(tmp_path):
    system = FakeSystem(tmp_path)
    _run(tmp_path, system, "add", public_key=KEY_A, label="a", expires_days=1)
    again = _run(tmp_path, system, "add", public_key=KEY_B, label="a", expires_days=1)
    assert (again["status"], again["error"]) == (409, "SSH_LABEL_EXISTS")
    same_key = _run(tmp_path, system, "add", public_key=KEY_A, label="b", expires_days=1)
    assert (same_key["status"], same_key["error"]) == (409, "SSH_KEY_EXISTS")
    assert [entry["label"] for entry in _keys(tmp_path)] == ["a"]


def test_the_33rd_managed_key_is_refused(tmp_path):
    system = FakeSystem(tmp_path)
    for index in range(ssh.MAX_KEYS):
        response = _run(tmp_path, system, "add", public_key=_key(body=bytes([index]) * 32),
                        label=f"k{index}", expires_days=1)
        assert response["status"] == 201, response
    full = _run(tmp_path, system, "add", public_key=_key(body=b"\xff" * 32), label="one-more", expires_days=1)
    assert (full["status"], full["error"]) == (409, "SSH_KEYS_FULL")
    assert len((tmp_path / ssh.AUTHORIZED).read_text(encoding="utf-8").splitlines()) == ssh.MAX_KEYS


@pytest.mark.parametrize("params", [
    {"public_key": _key("ssh-rsa"), "label": "a", "expires_days": 1},
    {"public_key": KEY_A, "label": "A", "expires_days": 1},
    {"public_key": KEY_A, "label": "a", "expires_days": 0},
    {"public_key": KEY_A, "label": "a", "expires_days": 366},
    {"public_key": KEY_A, "label": "a", "expires_days": True},
])
def test_the_helper_refuses_what_core_should_have_refused(tmp_path, params):
    system = FakeSystem(tmp_path)
    response = _run(tmp_path, system, "add", **params)
    assert (response["status"], response["error"]) == (422, "SSH_INVALID")
    assert not (tmp_path / ssh.AUTHORIZED).exists() or not (tmp_path / ssh.AUTHORIZED).read_text(encoding="utf-8")


@pytest.mark.parametrize("minutes", [0, 61, "10", True])
def test_password_minutes_out_of_range_are_refused(tmp_path, minutes):
    system = FakeSystem(tmp_path)
    response = _run(tmp_path, system, "password_on", minutes=minutes)
    assert (response["status"], response["error"]) == (422, "SSH_INVALID")
    assert "set_password" not in system.names()


def test_revoke_removes_the_line_and_records_it(tmp_path):
    system = FakeSystem(tmp_path)
    _run(tmp_path, system, "add", public_key=KEY_A, label="a", expires_days=1)
    _run(tmp_path, system, "add", public_key=KEY_B, label="b", expires_days=1)
    response = _run(tmp_path, system, "revoke", label="a")
    assert (response["status"], response["result"]) == (204, None)
    text = (tmp_path / ssh.AUTHORIZED).read_text(encoding="utf-8")
    assert "rosy-managed:a\n" not in text and "rosy-managed:b\n" in text
    assert [entry["label"] for entry in _keys(tmp_path)] == ["b"]
    assert [event["event"] for event in _history(tmp_path)] == ["add", "add", "revoke"]
    missing = _run(tmp_path, system, "revoke", label="a")
    assert (missing["status"], missing["error"]) == (404, "SSH_KEY_NOT_FOUND")


def test_a_failed_replace_leaves_the_old_file_and_no_temporary(tmp_path, monkeypatch):
    system = FakeSystem(tmp_path)
    _run(tmp_path, system, "add", public_key=KEY_A, label="a", expires_days=1)
    before = (tmp_path / ssh.AUTHORIZED).read_text(encoding="utf-8")

    real = os.replace

    def broken(source, target):
        if Path(target).name == "authorized_keys":
            raise OSError("disk full")
        return real(source, target)

    monkeypatch.setattr(ssh.os, "replace", broken)
    response = _run(tmp_path, system, "revoke", label="a")
    assert (response["status"], response["error"]) == (503, "SSH_ACCESS_UNAVAILABLE")
    assert (tmp_path / ssh.AUTHORIZED).read_text(encoding="utf-8") == before
    left = sorted(p.name for p in (tmp_path / ssh.STATE_DIR).iterdir() if p.name != ".lock")
    assert left == ["authorized_keys", "clock.json", "history.jsonl", "keys.json"]


def test_expired_keys_are_pruned_and_recorded(tmp_path):
    system = FakeSystem(tmp_path)
    _run(tmp_path, system, "add", public_key=KEY_A, label="short", expires_days=1)
    _run(tmp_path, system, "add", public_key=KEY_B, label="long", expires_days=30)
    later = FakeSystem(tmp_path, now=NOW + timedelta(days=2))
    response = _run(tmp_path, later, "list", at=NOW + timedelta(days=2))
    assert [row["label"] for row in response["result"]["keys"]] == ["long"]
    assert "rosy-managed:short" not in (tmp_path / ssh.AUTHORIZED).read_text(encoding="utf-8")
    assert _history(tmp_path)[-1]["event"] == "expire" and _history(tmp_path)[-1]["label"] == "short"


def test_the_managed_file_is_rebuilt_from_metadata(tmp_path):
    """A line someone appended by hand (or a half-finished add) does not survive the next run."""
    system = FakeSystem(tmp_path)
    _run(tmp_path, system, "add", public_key=KEY_A, label="a", expires_days=1)
    with (tmp_path / ssh.AUTHORIZED).open("a", encoding="utf-8") as handle:
        handle.write(KEY_B + " planted\n")
    _run(tmp_path, system, "list")
    assert "planted" not in (tmp_path / ssh.AUTHORIZED).read_text(encoding="utf-8")


# --- temporary password ----------------------------------------------------------


def _settled(tmp_path: Path) -> FakeSystem:
    """A helper that already installed the managed-keys drop-in (and reloaded for it)."""
    system = FakeSystem(tmp_path)
    _run(tmp_path, system, "list")
    (tmp_path / ssh.RESPONSE).unlink()
    system.calls.clear()
    return system


def test_password_on_sets_it_writes_the_match_dropin_and_never_records_it(tmp_path, capsys):
    system = _settled(tmp_path)
    response = _run(tmp_path, system, "password_on", minutes=15)

    assert response["status"] == 200
    password = response["result"]["password"]
    assert response["result"] == {"user": "rosy", "password": password, "expires_at": "2026-10-02T12:45:15Z"}
    assert ("set_password", "rosy", password) in system.calls
    dropin = (tmp_path / ssh.PASSWORD_DROPIN).read_text(encoding="utf-8")
    assert dropin.splitlines()[-5:] == [
        "Match User rosy Address 10.0.0.0/8,172.16.0.0/12,192.168.0.0/16",
        "    PasswordAuthentication yes",
        "    MaxAuthTries 3",
        "Match User rosy",
        "    PasswordAuthentication no",
    ]
    # sshd -t ran with the drop-in in place, before the reload; the timer watches the expiry.
    names = system.names()
    assert names.index("set_password") < names.index("sshd_check") < names.index("reload_sshd")
    assert ("dropin_at_check", True) in system.calls and ("expire_timer", True) in system.calls
    state = json.loads((tmp_path / ssh.PASSWORD_STATE).read_text(encoding="utf-8"))
    assert state == {"enabled": True, "expires_at": "2026-10-02T12:45:15Z", "by": "laptop admin",
                     "boot_id": "boot-1", "boot_deadline": 1000.0 + 15 * 60}
    assert _history(tmp_path)[-1]["event"] == "password_on"
    # Nowhere but the response CORE reads once (and shadow, through chpasswd).
    for path in tmp_path.rglob("*"):
        if path.is_file() and path != tmp_path / ssh.RESPONSE:
            assert password not in path.read_text(encoding="utf-8", errors="replace"), path
    assert password not in capsys.readouterr().out


def test_password_status_reports_without_the_password(tmp_path):
    system = FakeSystem(tmp_path)
    assert _run(tmp_path, system, "password_status")["result"] == {"enabled": False, "expires_at": None,
                                                                   "lock_pending": False}
    _run(tmp_path, system, "password_on", minutes=5)
    status = _run(tmp_path, system, "password_status")
    assert status["result"] == {"enabled": True, "expires_at": "2026-10-02T12:35:15Z", "lock_pending": False}


def test_password_off_locks_first_then_removes_the_dropin(tmp_path):
    system = FakeSystem(tmp_path)
    _run(tmp_path, system, "password_on", minutes=5)
    system.calls.clear()
    response = _run(tmp_path, system, "password_off")

    assert (response["status"], response["result"]) == (204, None)
    names = system.names()
    assert names.index("lock_password") < names.index("reload_sshd")
    assert ("lock_password", "rosy") in system.calls and ("expire_timer", False) in system.calls
    assert not (tmp_path / ssh.PASSWORD_DROPIN).exists()
    assert json.loads((tmp_path / ssh.PASSWORD_STATE).read_text(encoding="utf-8"))["enabled"] is False
    assert _history(tmp_path)[-1]["event"] == "password_off"


def test_a_config_sshd_rejects_rolls_the_password_back(tmp_path):
    system = _settled(tmp_path)
    system.sshd_ok = False
    response = _run(tmp_path, system, "password_on", minutes=5)
    assert (response["status"], response["error"]) == (503, "SSH_ACCESS_UNAVAILABLE")
    assert "password" not in json.dumps(response.get("result") or {})
    assert not (tmp_path / ssh.PASSWORD_DROPIN).exists()
    assert ("lock_password", "rosy") in system.calls
    assert "reload_sshd" not in system.names()


def test_a_failed_chpasswd_writes_no_dropin(tmp_path):
    system = FakeSystem(tmp_path, chpasswd_ok=False)
    response = _run(tmp_path, system, "password_on", minutes=5)
    assert response["status"] == 503
    assert not (tmp_path / ssh.PASSWORD_DROPIN).exists()


def test_expire_mode_turns_an_expired_password_off_only(tmp_path):
    system = FakeSystem(tmp_path)
    _run(tmp_path, system, "password_on", minutes=5)
    early = FakeSystem(tmp_path, now=NOW + timedelta(minutes=4))
    assert ssh.main(["--root", str(tmp_path), "--expire"], system=early) == 0
    assert "lock_password" not in early.names() and (tmp_path / ssh.PASSWORD_DROPIN).exists()

    late = FakeSystem(tmp_path, now=NOW + timedelta(minutes=5, seconds=1))
    assert ssh.main(["--root", str(tmp_path), "--expire"], system=late) == 0
    assert ("lock_password", "rosy") in late.calls and ("expire_timer", False) in late.calls
    assert not (tmp_path / ssh.PASSWORD_DROPIN).exists()
    event = _history(tmp_path)[-1]
    assert event["event"] == "password_off" and event["reason"] == "expired"


def test_any_request_after_expiry_turns_the_password_off_first(tmp_path):
    system = FakeSystem(tmp_path)
    _run(tmp_path, system, "password_on", minutes=5)
    late = FakeSystem(tmp_path, now=NOW + timedelta(minutes=6))
    status = _run(tmp_path, late, "password_status", at=NOW + timedelta(minutes=6))
    assert status["result"] == {"enabled": False, "expires_at": None, "lock_pending": False}
    assert ("lock_password", "rosy") in late.calls


def test_boot_forces_the_password_off_and_installs_the_keys_dropin(tmp_path):
    system = FakeSystem(tmp_path)
    _run(tmp_path, system, "password_on", minutes=60)
    (tmp_path / ssh.KEYS_DROPIN).unlink()
    boot = FakeSystem(tmp_path, now=NOW + timedelta(minutes=1), ssh_active=False)
    assert ssh.main(["--root", str(tmp_path), "--boot"], system=boot) == 0

    assert ("lock_password", "rosy") in boot.calls
    assert not (tmp_path / ssh.PASSWORD_DROPIN).exists()
    assert (tmp_path / ssh.KEYS_DROPIN).is_file()
    event = _history(tmp_path)[-1]
    assert event["event"] == "password_off" and event["reason"] == "boot"


def test_boot_locks_the_password_even_with_no_record_of_it(tmp_path):
    boot = FakeSystem(tmp_path)
    assert ssh.main(["--root", str(tmp_path), "--boot"], system=boot) == 0
    assert ("lock_password", "rosy") in boot.calls
    assert _history(tmp_path) == []


# --- the program as the units run it ----------------------------------------------


def test_the_units_run_the_program_isolated():
    source = (NATIVE / "rosy-ssh-access.py").read_text(encoding="utf-8")
    assert "import yaml" not in source and "subprocess.run(" in source
    # The password reaches chpasswd on stdin, never on a command line.
    assert '"/usr/sbin/chpasswd"' in source and "input=" in source
    completed = subprocess.run([sys.executable, "-I", "-B", str(NATIVE / "rosy-ssh-access.py"), "--help"],
                               capture_output=True, text=True, timeout=30, check=False)
    assert completed.returncode == 0 and "rosy-ssh-access" in completed.stdout


# --- review fixes: fail closed, whatever else is broken ------------------------------


def _corrupt_keys(root: Path) -> None:
    (root / ssh.KEYS).write_text("{not json", encoding="utf-8")


def _password_was_turned_off(root: Path, system: FakeSystem) -> bool:
    state = json.loads((root / ssh.PASSWORD_STATE).read_text(encoding="utf-8"))
    return ("lock_password", "rosy") in system.calls and not (root / ssh.PASSWORD_DROPIN).exists() \
        and state["enabled"] is False


def test_boot_turns_the_password_off_even_with_a_corrupt_keys_record(tmp_path):
    _run(tmp_path, FakeSystem(tmp_path), "password_on", minutes=60)
    _corrupt_keys(tmp_path)
    boot = FakeSystem(tmp_path, now=NOW + timedelta(minutes=1), ssh_active=False)
    # Non-zero: the keys record is broken and the journal says so; the password is off anyway.
    assert ssh.main(["--root", str(tmp_path), "--boot"], system=boot) == 1
    assert _password_was_turned_off(tmp_path, boot)
    assert (tmp_path / ssh.KEYS_DROPIN).is_file()


def test_the_expiry_timer_turns_the_password_off_even_with_a_corrupt_keys_record(tmp_path):
    _run(tmp_path, FakeSystem(tmp_path), "password_on", minutes=5)
    _corrupt_keys(tmp_path)
    late = FakeSystem(tmp_path, now=NOW + timedelta(minutes=6))
    ssh.main(["--root", str(tmp_path), "--expire"], system=late)
    assert _password_was_turned_off(tmp_path, late)


def test_password_off_on_request_works_with_a_corrupt_keys_record(tmp_path):
    system = FakeSystem(tmp_path)
    _run(tmp_path, system, "password_on", minutes=5)
    _corrupt_keys(tmp_path)
    system.calls.clear()
    response = _run(tmp_path, system, "password_off")
    assert (response["status"], response["error"]) == (204, None)
    assert _password_was_turned_off(tmp_path, system)
    # The broken record still answers 503 where it is needed.
    listed = _run(tmp_path, system, "list")
    assert (listed["status"], listed["error"]) == (503, "SSH_ACCESS_UNAVAILABLE")


def test_boot_with_a_failing_usermod_denies_the_password_in_sshd_and_retries(tmp_path):
    _run(tmp_path, FakeSystem(tmp_path), "password_on", minutes=60)
    boot = FakeSystem(tmp_path, now=NOW + timedelta(minutes=1), lock_ok=False)
    assert ssh.main(["--root", str(tmp_path), "--boot"], system=boot) != 0
    dropin = (tmp_path / ssh.PASSWORD_DROPIN).read_text(encoding="utf-8")
    assert "PasswordAuthentication yes" not in dropin
    assert [line.strip() for line in dropin.splitlines() if not line.startswith("#")] == \
        ["Match User rosy", "PasswordAuthentication no"]
    names = boot.names()
    assert names.index("lock_password") < names.index("reload_sshd")
    assert ("expire_timer", True) in boot.calls  # the timer runs --expire, which retries the lock
    assert json.loads((tmp_path / ssh.PASSWORD_STATE).read_text(encoding="utf-8"))["enabled"] is False

    retry = FakeSystem(tmp_path, now=NOW + timedelta(minutes=2))
    assert ssh.main(["--root", str(tmp_path), "--expire"], system=retry) == 0
    assert ("lock_password", "rosy") in retry.calls and ("expire_timer", False) in retry.calls
    assert not (tmp_path / ssh.PASSWORD_DROPIN).exists()


def test_a_failing_usermod_on_request_denies_the_password_and_answers_503(tmp_path):
    system = FakeSystem(tmp_path)
    _run(tmp_path, system, "password_on", minutes=5)
    system.lock_ok = False
    response = _run(tmp_path, system, "password_off")
    assert (response["status"], response["error"]) == (503, "SSH_ACCESS_UNAVAILABLE")
    assert "PasswordAuthentication yes" not in (tmp_path / ssh.PASSWORD_DROPIN).read_text(encoding="utf-8")


def test_a_password_that_would_reach_core_too_late_is_rolled_back(tmp_path):
    """CORE stops waiting after 10 s; a password written after that would only sit in /run/rosy."""

    class Slow(FakeSystem):
        def set_password(self, user, password):
            super().set_password(user, password)
            self.at += timedelta(seconds=2.5)

    system = Slow(tmp_path)
    # CORE waited for its lock first: only 3 s were left of its 10 s when it wrote the request.
    response = _run(tmp_path, system, "password_on", minutes=5, answer_in=3.0)
    [(_, _, password)] = [call for call in system.calls if call[0] == "set_password"]
    assert (response["status"], response["error"], response["result"]) == (503, "SSH_ACCESS_UNAVAILABLE", None)
    assert password not in (tmp_path / ssh.RESPONSE).read_text(encoding="utf-8")
    names = system.names()
    assert names.index("set_password") < len(names) - 1 - names[::-1].index("lock_password")
    assert not (tmp_path / ssh.PASSWORD_DROPIN).exists()
    assert json.loads((tmp_path / ssh.PASSWORD_STATE).read_text(encoding="utf-8"))["enabled"] is False


def test_a_password_answered_in_time_is_not_rolled_back(tmp_path):
    class Quick(FakeSystem):
        def set_password(self, user, password):
            super().set_password(user, password)
            self.at += timedelta(seconds=2.5)

    response = _run(tmp_path, Quick(tmp_path), "password_on", minutes=5, answer_in=4.0)
    assert response["status"] == 200 and response["result"]["password"].startswith("rosy-")


def test_a_failed_timer_start_rolls_the_password_back(tmp_path):
    system = _settled(tmp_path)
    system.timer_ok = False
    response = _run(tmp_path, system, "password_on", minutes=5)
    assert (response["status"], response["error"], response["result"]) == (503, "SSH_ACCESS_UNAVAILABLE", None)
    assert ("lock_password", "rosy") in system.calls
    assert not (tmp_path / ssh.PASSWORD_DROPIN).exists()
    # Never live without the timer: sshd was not reloaded with the password block.
    assert "reload_sshd" not in system.names()


def test_an_os_error_while_turning_the_password_on_is_503_with_rollback(tmp_path, monkeypatch):
    system = _settled(tmp_path)
    real = ssh.write_atomic

    def failing(path, content, mode, group=None):
        if Path(path).name == Path(ssh.PASSWORD_STATE).name and "true" in content:
            raise OSError("disk full")
        return real(path, content, mode, group)

    monkeypatch.setattr(ssh, "write_atomic", failing)
    response = _run(tmp_path, system, "password_on", minutes=5)
    assert (response["status"], response["error"], response["result"]) == (503, "SSH_ACCESS_UNAVAILABLE", None)
    assert ("lock_password", "rosy") in system.calls
    assert not (tmp_path / ssh.PASSWORD_DROPIN).exists()


def test_an_os_error_while_adding_a_key_is_503(tmp_path, monkeypatch):
    system = _settled(tmp_path)
    real = ssh.write_atomic

    def failing(path, content, mode, group=None):
        if Path(path).name == "authorized_keys":
            raise OSError("read-only file system")
        return real(path, content, mode, group)

    monkeypatch.setattr(ssh, "write_atomic", failing)
    response = _run(tmp_path, system, "add", public_key=KEY_A, label="a", expires_days=1)
    assert (response["status"], response["error"]) == (503, "SSH_ACCESS_UNAVAILABLE")


def test_keys_are_pruned_against_the_newest_time_seen_when_the_clock_is_behind(tmp_path):
    """No RTC: after a power cut the clock may restart in the past; key expiry must not run backwards."""
    _run(tmp_path, FakeSystem(tmp_path), "add", public_key=KEY_A, label="short", expires_days=1)
    saved = {name: (tmp_path / name).read_bytes() for name in (ssh.KEYS, ssh.AUTHORIZED)}
    later = FakeSystem(tmp_path, now=NOW + timedelta(days=2))
    assert ssh.main(["--root", str(tmp_path), "--expire"], system=later) == 0
    for name, content in saved.items():  # the record comes back (a restored or lost write)
        (tmp_path / name).write_bytes(content)

    behind = FakeSystem(tmp_path, now=NOW + timedelta(hours=1))
    response = _run(tmp_path, behind, "list", at=NOW + timedelta(hours=1))
    assert response["result"] == {"keys": []}
    assert (tmp_path / ssh.AUTHORIZED).read_text(encoding="utf-8") == ""


def test_new_key_expiries_count_from_the_newest_time_seen_and_passwords_from_the_clock(tmp_path):
    later = FakeSystem(tmp_path, now=NOW + timedelta(days=1))
    assert ssh.main(["--root", str(tmp_path), "--expire"], system=later) == 0
    behind = FakeSystem(tmp_path)
    added = _run(tmp_path, behind, "add", public_key=KEY_A, label="a", expires_days=1)
    assert added["result"]["expires_at"] == "2026-10-04T12:30:00Z"
    issued = _run(tmp_path, behind, "password_on", minutes=5)
    assert issued["result"]["expires_at"] == "2026-10-02T12:35:15Z"


def test_a_request_written_while_the_helper_runs_is_answered_before_it_exits(tmp_path):
    class Busy(FakeSystem):
        def core_group(self):
            if not getattr(self, "queued", False):
                self.queued = True
                _request(tmp_path, "password_status", request_id="fedcba9876543210")
            return super().core_group()

    _run(tmp_path, Busy(tmp_path), "list")
    assert _response(tmp_path)["request_id"] == "fedcba9876543210"
    assert not (tmp_path / ssh.REQUEST).exists()


def test_an_invalid_request_is_removed(tmp_path):
    _request(tmp_path, "shell")
    assert ssh.main(["--root", str(tmp_path)], system=FakeSystem(tmp_path)) == 0
    assert not (tmp_path / ssh.REQUEST).exists() and not (tmp_path / ssh.RESPONSE).exists()


def test_the_history_keeps_only_its_newest_mebibyte(tmp_path):
    system = FakeSystem(tmp_path)
    (tmp_path / ssh.STATE_DIR).mkdir(parents=True)
    old = json.dumps({"at": "2026-01-01T00:00:00Z", "event": "add", "label": "x" * 200}) + "\n"
    (tmp_path / ssh.HISTORY).write_text(old * (ssh.HISTORY_MAX_BYTES // len(old) + 50), encoding="utf-8")
    _run(tmp_path, system, "add", public_key=KEY_A, label="a", expires_days=1)
    raw = (tmp_path / ssh.HISTORY).read_bytes()
    assert len(raw) <= ssh.HISTORY_MAX_BYTES
    events = [json.loads(line) for line in raw.decode("utf-8").splitlines()]
    assert events[-1]["event"] == "add" and events[-1]["label"] == "a" and len(events) > 100


def test_sshd_check_creates_the_privilege_separation_directory_first(tmp_path, monkeypatch):
    """With ssh.socket, /run/sshd exists only once sshd ran; `sshd -t` refuses without it."""
    system = ssh.System(tmp_path)
    (tmp_path / "run").mkdir()
    seen = []

    def run(argv, stdin=None):
        seen.append((argv, (tmp_path / "run/sshd").is_dir()))
        return subprocess.CompletedProcess(argv, 0, "", "")

    monkeypatch.setattr(system, "_run", run)
    assert system.sshd_check() == (True, "")
    assert seen == [([ssh.SSHD, "-t"], True)]
    if os.name == "posix":
        assert stat.S_IMODE((tmp_path / "run/sshd").stat().st_mode) == 0o755


def test_a_rollback_whose_lock_fails_keeps_the_retry_timer_running(tmp_path):
    system = _settled(tmp_path)
    system.sshd_ok, system.lock_ok = False, False
    response = _run(tmp_path, system, "password_on", minutes=5)
    assert response["status"] == 503
    assert [call for call in system.calls if call[0] == "expire_timer"][-1] == ("expire_timer", True)
    assert "PasswordAuthentication yes" not in (tmp_path / ssh.PASSWORD_DROPIN).read_text(encoding="utf-8")


def test_a_timer_that_does_not_start_is_a_helper_error_and_a_stop_is_only_logged(tmp_path, monkeypatch):
    system = ssh.System(tmp_path)
    monkeypatch.setattr(system, "_run", lambda argv, stdin=None: subprocess.CompletedProcess(argv, 1, "", ""))
    with pytest.raises(ssh.HelperError):
        system.expire_timer(True)
    system.expire_timer(False)


# --- second review: clocks ahead, CORE's real deadline, the response write ----------------


def _state(root: Path) -> dict:
    return json.loads((root / ssh.PASSWORD_STATE).read_text(encoding="utf-8"))


def test_a_clock_that_once_ran_a_year_ahead_never_keeps_a_password_on(tmp_path):
    """Reproduces the review probe: a high-water mark a year ahead must not stretch a 5-minute password."""
    ahead = FakeSystem(tmp_path, now=NOW + timedelta(days=365))
    ssh.main(["--root", str(tmp_path), "--expire"], system=ahead)
    issued = _run(tmp_path, FakeSystem(tmp_path), "password_on", minutes=5)
    assert issued["result"]["expires_at"] == "2026-10-02T12:35:15Z"
    later = FakeSystem(tmp_path, now=NOW + timedelta(minutes=6))
    ssh.main(["--root", str(tmp_path), "--expire"], system=later)
    assert _state(tmp_path)["enabled"] is False and ("lock_password", "rosy") in later.calls


def test_the_boot_clock_expires_a_password_when_the_wall_clock_goes_back(tmp_path):
    _run(tmp_path, FakeSystem(tmp_path, boot=1000.0), "password_on", minutes=5)
    assert _state(tmp_path)["boot_id"] == "boot-1"
    # NTP stepped the wall clock a day back; 6 minutes passed on the boot clock.
    back = FakeSystem(tmp_path, now=NOW - timedelta(days=1), boot=1000.0 + 6 * 60)
    ssh.main(["--root", str(tmp_path), "--expire"], system=back)
    assert _state(tmp_path)["enabled"] is False
    still = FakeSystem(tmp_path, now=NOW - timedelta(days=1), boot=1000.0 + 4 * 60)
    _run(tmp_path, FakeSystem(tmp_path, boot=1000.0), "password_on", minutes=5)
    ssh.main(["--root", str(tmp_path), "--expire"], system=still)
    assert _state(tmp_path)["enabled"] is True


def test_a_password_from_another_boot_is_expired(tmp_path):
    _run(tmp_path, FakeSystem(tmp_path), "password_on", minutes=60)
    other = FakeSystem(tmp_path, now=NOW + timedelta(minutes=1), boot_id="boot-2", boot=5.0)
    ssh.main(["--root", str(tmp_path), "--expire"], system=other)
    assert _state(tmp_path)["enabled"] is False


def test_a_mark_more_than_two_days_ahead_never_deletes_keys(tmp_path):
    ahead = FakeSystem(tmp_path, now=NOW + timedelta(days=365))
    ssh.main(["--root", str(tmp_path), "--expire"], system=ahead)
    real = FakeSystem(tmp_path)
    _run(tmp_path, real, "add", public_key=KEY_A, label="a", expires_days=30)
    listed = _run(tmp_path, real, "list")
    assert [row["label"] for row in listed["result"]["keys"]] == ["a"]
    assert "rosy-managed:a" in (tmp_path / ssh.AUTHORIZED).read_text(encoding="utf-8")
    # The bogus mark was reset, not kept.
    assert ssh.trusted_now(FakeSystem(tmp_path)) == NOW.replace(microsecond=0)


def test_ntp_sync_resets_the_mark_to_the_clock(tmp_path):
    _run(tmp_path, FakeSystem(tmp_path), "add", public_key=KEY_A, label="a", expires_days=1)
    ahead = FakeSystem(tmp_path, now=NOW + timedelta(days=1, hours=12))
    ssh.trusted_now(ahead)  # a mark 1.5 days ahead, within the 2-day bound
    synced = FakeSystem(tmp_path, now=NOW + timedelta(hours=12), ntp=True)
    listed = _run(tmp_path, synced, "list", at=NOW + timedelta(hours=12))
    assert [row["label"] for row in listed["result"]["keys"]] == ["a"]
    assert ssh.trusted_now(FakeSystem(tmp_path, now=NOW)) == NOW + timedelta(hours=12)


def test_the_mark_is_written_only_when_it_rises_a_minute(tmp_path):
    ssh.ensure_state_dir(FakeSystem(tmp_path))
    ssh.trusted_now(FakeSystem(tmp_path))
    first = (tmp_path / ssh.CLOCK).read_bytes()
    ssh.trusted_now(FakeSystem(tmp_path, now=NOW + timedelta(seconds=59)))
    assert (tmp_path / ssh.CLOCK).read_bytes() == first
    ssh.trusted_now(FakeSystem(tmp_path, now=NOW + timedelta(seconds=61)))
    assert (tmp_path / ssh.CLOCK).read_bytes() != first


def test_a_mark_that_cannot_be_written_still_gives_a_time(tmp_path, monkeypatch):
    ssh.ensure_state_dir(FakeSystem(tmp_path))

    def failing(*_args, **_kwargs):
        raise OSError("read-only file system")

    monkeypatch.setattr(ssh, "write_atomic", failing)
    assert ssh.trusted_now(FakeSystem(tmp_path)) == NOW.replace(microsecond=0)


def test_a_failed_response_write_after_password_on_turns_the_password_off(tmp_path, monkeypatch):
    system = _settled(tmp_path)
    real = ssh.write_atomic

    def failing(path, content, mode, group=None):
        if Path(path).name == Path(ssh.RESPONSE).name:
            raise OSError("no space left")
        return real(path, content, mode, group)

    monkeypatch.setattr(ssh, "write_atomic", failing)
    _request(tmp_path, "password_on", minutes=5)
    assert ssh.main(["--root", str(tmp_path)], system=system) == 0
    assert _state(tmp_path)["enabled"] is False and not (tmp_path / ssh.PASSWORD_DROPIN).exists()
    assert ("lock_password", "rosy") in system.calls
    assert _history(tmp_path)[-1]["reason"] == "undelivered"


def test_a_failed_lock_is_reported_as_lock_pending_and_recorded(tmp_path):
    system = FakeSystem(tmp_path)
    _run(tmp_path, system, "password_on", minutes=5)
    system.lock_ok = False
    _run(tmp_path, system, "password_off")
    status = _run(tmp_path, system, "password_status")
    assert status["result"] == {"enabled": False, "expires_at": None, "lock_pending": True}
    assert any(event["event"] == "password_deny" for event in _history(tmp_path))
    system.lock_ok = True
    assert ssh.main(["--root", str(tmp_path), "--expire"], system=system) == 0
    assert _run(tmp_path, system, "password_status")["result"]["lock_pending"] is False


def test_a_request_written_while_the_last_one_is_read_is_not_lost(tmp_path, monkeypatch):
    """CORE may replace the file between the helper's read and its removal."""
    real = ssh.read_request
    written = []

    def racing(path, now):
        data = real(path, now)
        if not written:
            written.append(True)
            _request(tmp_path, "password_status", request_id="fedcba9876543210")
        return data

    monkeypatch.setattr(ssh, "read_request", racing)
    _run(tmp_path, FakeSystem(tmp_path), "list")
    assert _response(tmp_path)["request_id"] == "fedcba9876543210"
    assert not (tmp_path / ssh.REQUEST).exists()
    assert [p.name for p in (tmp_path / "run/rosy").iterdir()] == ["ssh-access.response"]


# --- third review: a bare lock_pending, NTP under chrony, the boot id --------------------


def test_a_failed_lock_whose_deny_write_also_failed_is_retried_next_tick(tmp_path, monkeypatch):
    """Rollback unlinked the permit block, usermod failed and the deny block could not be written:
    only lock_pending remains, and the next --expire must still retry the lock."""
    system = _settled(tmp_path)
    system.sshd_ok, system.lock_ok = False, False

    def no_deny(_system):
        raise OSError("read-only file system")

    monkeypatch.setattr(ssh, "_write_deny_dropin", no_deny)
    assert _run(tmp_path, system, "password_on", minutes=5)["status"] == 503
    assert not (tmp_path / ssh.PASSWORD_DROPIN).exists() and _state(tmp_path).get("lock_pending") is True

    retry = FakeSystem(tmp_path, now=NOW + timedelta(seconds=30))
    assert ssh.main(["--root", str(tmp_path), "--expire"], system=retry) == 0
    assert ("lock_password", "rosy") in retry.calls
    assert ssh.password_state(retry)["lock_pending"] is False


def test_password_off_on_request_retries_a_bare_pending_lock(tmp_path, monkeypatch):
    system = _settled(tmp_path)
    system.sshd_ok, system.lock_ok = False, False
    monkeypatch.setattr(ssh, "_write_deny_dropin", lambda _system: (_ for _ in ()).throw(OSError("ro")))
    _run(tmp_path, system, "password_on", minutes=5)
    system.lock_ok = True
    system.calls.clear()
    assert _run(tmp_path, system, "password_off")["status"] == 204
    assert ("lock_password", "rosy") in system.calls and ssh.password_state(system)["lock_pending"] is False


@pytest.mark.parametrize("stdout,code,expected", [("yes\n", 0, True), ("no\n", 0, False), ("", 1, False),
                                                  ("yes\n", 1, False), ("maybe\n", 0, False)])
def test_ntp_sync_comes_from_timedated_whatever_the_ntp_daemon(tmp_path, monkeypatch, stdout, code, expected):
    """chrony on the image never writes timesyncd's flag; timedated reads the kernel's STA_UNSYNC."""
    system = ssh.System(tmp_path)
    seen = []

    def run(argv, stdin=None):
        seen.append(argv)
        return subprocess.CompletedProcess(argv, code, stdout, "")

    monkeypatch.setattr(system, "_run", run)
    assert system.ntp_synced() is expected
    assert seen == [[ssh.TIMEDATECTL, "show", "-p", "NTPSynchronized", "--value"]]


def test_ntp_sync_detection_that_fails_means_not_synced(tmp_path, monkeypatch):
    system = ssh.System(tmp_path)

    def run(argv, stdin=None):
        raise ssh.HelperError("timedatectl: FileNotFoundError")

    monkeypatch.setattr(system, "_run", run)
    assert system.ntp_synced() is False


def test_the_helper_never_calls_adjtimex_itself():
    """The units' seccomp filter (@system-service, ProtectClock=true) kills the process with SIGSYS
    on adjtimex (twin, 2026-10-03): no try/except can catch that. timedated asks the kernel instead."""
    source = (NATIVE / "rosy-ssh-access.py").read_text(encoding="utf-8")
    assert "import ctypes" not in source and "adjtimex(" not in source and "CDLL" not in source


def test_password_on_refuses_without_a_boot_id(tmp_path):
    system = _settled(tmp_path)
    system.boot_ident = ""
    response = _run(tmp_path, system, "password_on", minutes=5)
    assert (response["status"], response["error"], response["result"]) == (503, "SSH_ACCESS_UNAVAILABLE", None)
    assert "set_password" not in system.names() and not (tmp_path / ssh.PASSWORD_DROPIN).exists()


def test_a_password_state_without_a_boot_id_is_expired(tmp_path):
    """A state from before the upgrade has no boot bound: turn it off at the next check."""
    system = FakeSystem(tmp_path)
    _run(tmp_path, system, "password_on", minutes=60)
    state = _state(tmp_path)
    del state["boot_id"], state["boot_deadline"]
    (tmp_path / ssh.PASSWORD_STATE).write_text(json.dumps(state), encoding="utf-8")
    later = FakeSystem(tmp_path, now=NOW + timedelta(minutes=1))
    ssh.main(["--root", str(tmp_path), "--expire"], system=later)
    assert _state(tmp_path)["enabled"] is False and ("lock_password", "rosy") in later.calls
