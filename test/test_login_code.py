"""D-193 S2: the root login-code issuer (rosy-login-code) and its hand-offs.

The issuer runs over a temporary root: /run/rosy-boot, /run/rosy, the boot id
and /etc/rosy are files under tmp_path, the monotonic clock is fake, groups are
the test user's own group and `agetty --reload` is recorded, not run.
"""

from __future__ import annotations

import importlib.util
import json
import os
from pathlib import Path
import re
import stat
import sys

import pytest

ROOT = Path(__file__).resolve().parents[1]
NATIVE = ROOT / "deploy/robot/native"
CORE_SRC = ROOT / "src/core"
BOOT_ID = "0b1f5d2e-8c3a-4f6e-9d7b-1a2b3c4d5e6f"
POSIX = pytest.mark.skipif(os.name != "posix", reason="POSIX modes, groups, symlinks and FIFOs")
#: scrypt(N=2^14, r=8, p=1, dklen=32) of "ABCD2345" with salt 00..0f: CORE and the issuer agree on it.
VECTOR_CODE = "ABCD" + "2345"
SCRYPT_VECTOR_DIGEST = "46e6b3348e6e9304103de07f942426b26fecb18a9fbcc0f062d76082c541235c"
FORMATTED = re.compile(r"\b[23456789ABCDEFGHJKMNPQRSTUVWXYZ]{4}-[23456789ABCDEFGHJKMNPQRSTUVWXYZ]{4}\b")


def _load(name: str, path: Path):
    sys.path.insert(0, str(path.parent))
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


@pytest.fixture
def issuer_module():
    return _load("rosy_login_code", NATIVE / "rosy-login-code.py")


class Clock:
    def __init__(self, now: float = 500.0) -> None:
        self.now = now

    def __call__(self) -> float:
        return self.now


def _root(tmp_path: Path) -> Path:
    root = tmp_path / "root"
    (root / "proc/sys/kernel/random").mkdir(parents=True)
    (root / "proc/sys/kernel/random/boot_id").write_text(BOOT_ID + "\n", encoding="ascii")
    (root / "run/rosy-boot").mkdir(parents=True)
    (root / "run/rosy").mkdir(parents=True)
    return root


def _issuer(module, root: Path, *, groups=("rosy-core", "rosy-display"), calls=None):
    gid = os.getgid() if hasattr(os, "getgid") else 0
    recorded = calls if calls is not None else []
    issuer = module.Issuer(root, clock=Clock(), run=recorded.append,
                           group=lambda name: gid if name in groups else None)
    return issuer, recorded


def _signal(root: Path, code_id: str, state: str) -> None:
    (root / "run/rosy/login-code-state.json").write_text(
        json.dumps({"code_id": code_id, "state": state}), encoding="ascii")


def _files(root: Path) -> dict[str, bool]:
    return {name: (root / "run/rosy-boot" / name).exists()
            for name in ("login-code.json", "login-display.txt", "login.issue")}


def _core_ready(root: Path, stage: str = "CORE_READY") -> None:
    (root / "run/rosy-boot/boot-status.json").write_text(json.dumps({"stage": stage}), encoding="utf-8")


# --- the code and its verifier --------------------------------------------------


def test_codes_use_only_the_unambiguous_alphabet(issuer_module):
    codes = {issuer_module.generate_code() for _ in range(200)}
    assert all(len(code) == 8 and set(code) <= set(issuer_module.ALPHABET) for code in codes)
    assert len(codes) == 200
    assert not set("01ILO") & set(issuer_module.ALPHABET)
    assert issuer_module.format_code(VECTOR_CODE) == "ABCD-2345"


def test_issuer_and_core_share_the_scrypt_vector_and_the_alphabet(issuer_module):
    sys.path[:0] = [str(CORE_SRC / name) for name in (
        "core", "core_common", "core_events", "core_features", "core_api_web")]
    from core_api_web.api.v1 import auth as core_auth

    salt = bytes(range(16))
    assert issuer_module.verifier(VECTOR_CODE, salt).hex() == SCRYPT_VECTOR_DIGEST
    assert core_auth.scrypt_digest(VECTOR_CODE, salt).hex() == SCRYPT_VECTOR_DIGEST
    assert issuer_module.ALPHABET == core_auth.ALPHABET
    assert issuer_module.CODE_LENGTH == core_auth.CODE_LENGTH
    assert {key: issuer_module.SCRYPT[key] for key in ("n", "r", "p", "dklen")} == {
        "n": core_auth.SCRYPT_N, "r": core_auth.SCRYPT_R, "p": core_auth.SCRYPT_P,
        "dklen": core_auth.SCRYPT_DKLEN}


def test_core_reads_what_the_issuer_writes_and_the_code_verifies(issuer_module, tmp_path):
    sys.path[:0] = [str(CORE_SRC / name) for name in (
        "core", "core_common", "core_events", "core_features", "core_api_web")]
    from core_api_web.api.v1 import auth as core_auth

    root = _root(tmp_path)
    issuer, _calls = _issuer(issuer_module, root)
    code = issuer.issue("operator", 10, "cli")

    state = core_auth.PairingState(clock=lambda: 500.0 + 599.0)
    state.code_file = str(root / "run/rosy-boot/login-code.json")
    state.boot_id_file = str(root / "proc/sys/kernel/random/boot_id")
    physical = state.physical_code()
    assert physical is not None and physical["role"] == "operator"
    assert core_auth.scrypt_digest(code, physical["salt"]) == physical["digest"]
    state.clock = lambda: 500.0 + 600.0
    assert state.physical_code() is None  # ten minutes on CORE's monotonic clock


def test_the_verifier_file_holds_no_plaintext(issuer_module, tmp_path):
    root = _root(tmp_path)
    issuer, _calls = _issuer(issuer_module, root)
    code = issuer.issue("administrator", 5, "cli")

    text = (root / "run/rosy-boot/login-code.json").read_text(encoding="utf-8")
    record = json.loads(text)
    assert code not in text and issuer_module.format_code(code) not in text
    assert set(record) == {"schema_version", "code_id", "role", "source", "issued_by", "kdf", "digest",
                           "boot_id", "expires_monotonic"}
    assert record["kdf"] == {"name": "scrypt", "n": 16384, "r": 8, "p": 1, "dklen": 32,
                             "salt": record["kdf"]["salt"]}
    assert record["role"] == "administrator" and record["source"] == "pair-physical"
    assert record["boot_id"] == BOOT_ID and record["expires_monotonic"] == 500.0 + 300.0
    assert issuer_module.verifier(code, bytes.fromhex(record["kdf"]["salt"])).hex() == record["digest"]
    # The display line and the console banner are the only places the code appears.
    assert (root / "run/rosy-boot/login-display.txt").read_text(encoding="utf-8") == \
        f"{issuer_module.format_code(code)}\nadministrator\n"
    assert issuer_module.format_code(code) in (root / "run/rosy-boot/login.issue").read_text(encoding="utf-8")


@POSIX
def test_modes_and_groups_follow_d190(issuer_module, tmp_path, monkeypatch):
    root = _root(tmp_path)
    issuer, calls = _issuer(issuer_module, root)
    chowned = []
    real_fchown = os.fchown

    def fchown(fd, uid, gid):
        chowned.append((os.fstat(fd).st_size, stat.S_IMODE(os.fstat(fd).st_mode), gid))
        return real_fchown(fd, uid, gid)

    monkeypatch.setattr(os, "fchown", fchown)
    issuer.issue("operator", 10, "boot")

    boot = root / "run/rosy-boot"
    for name, mode in (("login-code.json", 0o640), ("login-display.txt", 0o640), ("login.issue", 0o600)):
        info = (boot / name).stat()
        assert stat.S_IMODE(info.st_mode) == mode, name
    assert (boot / "login-code.json").stat().st_gid == os.getgid()
    # Group set on the still-empty file, before any byte (the D-190 _write pattern).
    assert chowned and all(size == 0 and mode == 0o600 for size, mode, _gid in chowned)
    assert calls == [["agetty", "--reload"]]
    assert not list(boot.glob(".login-*.json.*")), "no temporary file is left"


def test_without_the_display_group_the_lcd_line_is_not_written(issuer_module, tmp_path):
    root = _root(tmp_path)
    issuer, _calls = _issuer(issuer_module, root, groups=("rosy-core",))
    assert issuer.issue("operator", 10, "cli")
    assert _files(root) == {"login-code.json": True, "login-display.txt": False, "login.issue": True}


def test_without_cores_group_nothing_is_issued(issuer_module, tmp_path):
    root = _root(tmp_path)
    issuer, calls = _issuer(issuer_module, root, groups=("rosy-display",))
    assert issuer.issue("operator", 10, "cli") is None
    assert _files(root) == dict.fromkeys(_files(root), False)
    assert calls == []


# --- CORE's signal -----------------------------------------------------------


@pytest.mark.parametrize("state", ["used", "burned"])
def test_a_used_or_burned_signal_for_this_code_clears_the_files(issuer_module, tmp_path, state):
    root = _root(tmp_path)
    issuer, calls = _issuer(issuer_module, root)
    issuer.issue("operator", 10, "boot")
    code_id = json.loads((root / "run/rosy-boot/login-code.json").read_text(encoding="utf-8"))["code_id"]

    _signal(root, "f" * 16, state)
    assert issuer.poll() is None  # another code's signal clears nothing
    assert all(_files(root).values())

    _signal(root, code_id, state)
    assert issuer.poll() == state
    files = _files(root)
    assert not files["login-code.json"] and not files["login.issue"]
    assert calls[-1] == ["agetty", "--reload"]
    if state == "used":
        assert not files["login-display.txt"]
    else:
        # D-193 4: the LCD says the code was burned, briefly, then the line goes.
        assert (root / "run/rosy-boot/login-display.txt").read_text(encoding="utf-8") == "BURNED\n"
        issuer.clock.now += issuer_module.BURNED_NOTICE_S
        issuer.poll()
        assert not _files(root)["login-display.txt"]


def test_an_expired_code_or_a_new_boot_clears_the_files(issuer_module, tmp_path):
    root = _root(tmp_path)
    issuer, _calls = _issuer(issuer_module, root)
    issuer.issue("operator", 10, "boot")
    issuer.clock.now += 599.0
    assert issuer.poll() is None
    issuer.clock.now += 1.0
    assert issuer.poll() == "expired"
    assert not any(_files(root).values())

    issuer.issue("operator", 10, "cli")
    (root / "proc/sys/kernel/random/boot_id").write_text("another-boot\n", encoding="ascii")
    assert issuer.poll() == "expired"


@pytest.mark.parametrize("content", [
    "x" * 300,
    json.dumps({"code_id": "f" * 16, "state": "used", "pad": "x" * 250}),
    json.dumps({"code_id": "F" * 16, "state": "used"}),
    json.dumps({"code_id": "f" * 17, "state": "used"}),
    json.dumps({"code_id": "f" * 16, "state": "expired"}),
    json.dumps(["f" * 16, "used"]),
    "not json",
])
def test_a_malformed_or_oversized_signal_is_ignored(issuer_module, tmp_path, content):
    root = _root(tmp_path)
    (root / "run/rosy/login-code-state.json").write_text(content, encoding="ascii")
    assert issuer_module.read_core_state(root) is None


@POSIX
def test_a_symlinked_signal_is_never_followed(issuer_module, tmp_path):
    root = _root(tmp_path)
    issuer, _calls = _issuer(issuer_module, root)
    issuer.issue("operator", 10, "boot")
    code_id = json.loads((root / "run/rosy-boot/login-code.json").read_text(encoding="utf-8"))["code_id"]
    elsewhere = tmp_path / "elsewhere.json"
    elsewhere.write_text(json.dumps({"code_id": code_id, "state": "used"}), encoding="ascii")
    (root / "run/rosy/login-code-state.json").symlink_to(elsewhere)

    assert issuer_module.read_core_state(root) is None
    assert issuer.poll() is None
    assert all(_files(root).values())


@POSIX
def test_a_fifo_signal_does_not_block_the_issuer(issuer_module, tmp_path):
    root = _root(tmp_path)
    os.mkfifo(root / "run/rosy/login-code-state.json")
    assert issuer_module.read_core_state(root) is None


def test_a_valid_signal_is_read(issuer_module, tmp_path):
    root = _root(tmp_path)
    _signal(root, "a" * 16, "burned")
    assert issuer_module.read_core_state(root) == {"code_id": "a" * 16, "state": "burned"}


# --- daemon and command ----------------------------------------------------------


def test_the_daemon_issues_once_after_core_ready_and_never_prints_the_code(issuer_module, tmp_path, capsys):
    root = _root(tmp_path)
    issuer, _calls = _issuer(issuer_module, root)

    _core_ready(root, "PROVISIONED")
    issuer_module.daemon(issuer, once=True)
    assert not _files(root)["login-code.json"]

    _core_ready(root)
    issuer_module.daemon(issuer, once=True)
    code_line = (root / "run/rosy-boot/login-display.txt").read_text(encoding="utf-8").splitlines()
    assert FORMATTED.fullmatch(code_line[0]) and code_line[1] == "operator"
    first = json.loads((root / "run/rosy-boot/login-code.json").read_text(encoding="utf-8"))
    assert first["issued_by"] == "boot"

    # A restarted daemon (Restart=always) does not issue a second boot code.
    restarted, _ = _issuer(issuer_module, root)
    issuer_module.daemon(restarted, once=True)
    assert json.loads((root / "run/rosy-boot/login-code.json").read_text(encoding="utf-8")) == first

    output = capsys.readouterr()
    assert code_line[0] not in output.out + output.err
    assert code_line[0].replace("-", "") not in output.out + output.err
    assert not FORMATTED.search(output.out + output.err)
    assert '{"boot_code": "issued"}' in output.out


def test_boot_code_off_issues_nothing(issuer_module, tmp_path):
    root = _root(tmp_path)
    (root / "etc/rosy").mkdir(parents=True)
    (root / "etc/rosy/login-policy.json").write_text(json.dumps({"boot_code": "off"}), encoding="utf-8")
    issuer, _calls = _issuer(issuer_module, root)
    _core_ready(root)

    assert issuer_module.boot_step(issuer) == "off"
    assert not any(_files(root).values())
    (root / "etc/rosy/login-policy.json").write_text(json.dumps({"boot_code": "operator"}), encoding="utf-8")
    assert issuer_module.boot_step(issuer) is None  # decided once per boot


def test_the_card_policy_can_ask_for_an_administrator_boot_code(issuer_module, tmp_path):
    root = _root(tmp_path)
    (root / "etc/rosy").mkdir(parents=True)
    (root / "etc/rosy/defaults.yaml").write_bytes((NATIVE / "defaults.yaml").read_bytes())
    assert issuer_module.load_policy(root) == {"boot_code": "operator", "minutes": 10}
    (root / "etc/rosy/login-policy.json").write_text(json.dumps({"boot_code": "administrator"}),
                                                     encoding="utf-8")
    issuer, _calls = _issuer(issuer_module, root)
    _core_ready(root)

    assert issuer_module.boot_step(issuer) == "issued"
    assert json.loads((root / "run/rosy-boot/login-code.json").read_text(encoding="utf-8"))["role"] == \
        "administrator"
    (root / "etc/rosy/login-policy.json").write_text(json.dumps({"boot_code": "root"}), encoding="utf-8")
    assert issuer_module.load_policy(root)["boot_code"] == "operator"


def test_the_command_prints_the_code_to_its_own_terminal(issuer_module, tmp_path, capsys, monkeypatch):
    root = _root(tmp_path)
    gid = os.getgid() if hasattr(os, "getgid") else 0
    monkeypatch.setattr(issuer_module, "group_id", lambda name: gid)
    monkeypatch.setattr(issuer_module, "_run", lambda command: None)

    assert issuer_module.main(["--root", str(root), "--role", "administrator", "--minutes", "3"]) == 0

    out = capsys.readouterr().out
    printed = FORMATTED.search(out).group(0)
    record = json.loads((root / "run/rosy-boot/login-code.json").read_text(encoding="utf-8"))
    assert record["role"] == "administrator" and record["issued_by"] == "cli"
    assert issuer_module.verifier(printed.replace("-", ""), bytes.fromhex(record["kdf"]["salt"])).hex() == \
        record["digest"]
    assert "administrator" in out and "3 min" in out


@pytest.mark.parametrize("argv", [["--minutes", "0"], ["--minutes", "61"], ["--role", "viewer"],
                                  ["--role", "root"]])
def test_the_command_refuses_other_roles_and_lifetimes(issuer_module, tmp_path, argv):
    with pytest.raises(SystemExit) as refused:
        issuer_module.main(["--root", str(_root(tmp_path)), *argv])
    assert refused.value.code == 2


def test_rosy_config_apply_hands_the_login_policy_to_the_issuer(tmp_path):
    apply = _load("rosy_config_apply_login", NATIVE / "rosy-config-apply.py")
    root = tmp_path / "root"
    (root / "boot/firmware").mkdir(parents=True)
    (root / "etc/rosy").mkdir(parents=True)
    (root / "etc/rosy/defaults.yaml").write_bytes((NATIVE / "defaults.yaml").read_bytes())
    (root / "boot/firmware/rosy-config.yaml").write_text("schema_version: 1\nlogin:\n  boot_code: off\n",
                                                          encoding="utf-8")

    assert apply.apply(root, lambda command: "")["state"] == "applied"
    assert json.loads((root / "etc/rosy/login-policy.json").read_text(encoding="utf-8")) == {"boot_code": "off"}
