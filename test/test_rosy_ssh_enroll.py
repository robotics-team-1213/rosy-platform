"""D-418 tools/ssh/rosy_ssh_enroll.py against a fake CORE on localhost and a fake ssh-keygen.

Nothing here reaches a robot. The fake CORE (test/fake_core_ssh.py) speaks the shared contract in
docs/plans/2026-10-02-d418-robot-ssh-access.md.
"""

from __future__ import annotations

import base64
import importlib.util
import os
import re
from pathlib import Path
import shutil

import pytest

from fake_core_ssh import FakeCore, ed25519_public_key, fingerprint, isolate_home, real_ssh_snapshot

ROOT = Path(__file__).resolve().parents[1]
_SPEC = importlib.util.spec_from_file_location("rosy_ssh_enroll", ROOT / "tools" / "ssh" / "rosy_ssh_enroll.py")
tool = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(tool)

ROBOT = "192.0.2.10"
HOST = "rosy-pinky-test1"
# Assembled at runtime so no PEM header literal is tracked (secret_scan private-key rule).
PEM_BEGIN = "-----BEGIN " + "OPENSSH PRIVATE KEY-----"
PEM_END = "-----END " + "OPENSSH PRIVATE KEY-----"
ADMIN_CODE = "ABCD-EFGH"


class FakeKeygen:
    def __init__(self):
        self.calls: list[list[str]] = []

    def __call__(self, argv: list[str]) -> tuple[int, str, str]:
        self.calls.append(argv)
        path = Path(argv[argv.index("-f") + 1])
        comment = argv[argv.index("-C") + 1]
        path.write_text(PEM_BEGIN + "\nfake\n" + PEM_END + "\n",
                        encoding="ascii")
        Path(str(path) + ".pub").write_text(ed25519_public_key(b"device", comment) + "\n", encoding="ascii")
        return 0, "", ""


@pytest.fixture(scope="module", autouse=True)
def real_profile_untouched():
    before = real_ssh_snapshot()
    yield
    assert real_ssh_snapshot() == before, "a test wrote into the real ~/.ssh"


@pytest.fixture(autouse=True)
def home(tmp_path, monkeypatch):
    return isolate_home(tmp_path, monkeypatch)


@pytest.fixture
def paths(tmp_path):
    return {"key": tmp_path / "ssh" / "rosy_dev_laptop", "known_hosts": tmp_path / "ssh" / "known_hosts_rosy",
            "config": tmp_path / "ssh" / "config"}


class FakeSsh:
    """`ssh -G -F <file> <alias>` with OpenSSH's rule: for each option the first value obtained wins
    (IdentityFile accumulates). Host patterns match with fnmatch; Match blocks are not modelled.
    Keyword overrides replace a resolved value, to fake a config that resolves elsewhere."""

    def __init__(self, code: int = 0, **override):
        self.code, self.override = code, override
        self.calls: list[list[str]] = []

    def __call__(self, argv: list[str]) -> tuple[int, str, str]:
        import fnmatch

        self.calls.append(argv)
        if self.code:
            return self.code, "", "line 9: no argument after keyword \"proxycommand\""
        alias = argv[-1]
        found: dict[str, str] = {}
        identities: list[str] = []
        active = True
        for raw in Path(argv[argv.index("-F") + 1]).read_text(encoding="utf-8").splitlines():
            words = raw.split(None, 1)
            if not words or words[0].startswith("#"):
                continue
            key, value = words[0].lower(), (words[1].strip().strip('"') if len(words) > 1 else "")
            if key == "host":
                active = any(fnmatch.fnmatchcase(alias, pattern) for pattern in value.split())
            elif active and key == "identityfile":
                identities.append(value)
            elif active:
                found.setdefault(key, value)
        resolved = {"hostname": found.get("hostname", alias), "user": found.get("user", "me"),
                    "identityfile": identities or ["~/.ssh/id_ed25519"],
                    "userknownhostsfile": found.get("userknownhostsfile", "~/.ssh/known_hosts")}
        resolved.update(self.override)
        files = resolved["identityfile"]
        out = [f"host {alias}", f"hostname {resolved['hostname']}", f"user {resolved['user']}"]
        out += [f"identityfile {item}" for item in ([files] if isinstance(files, str) else files)]
        out.append(f"userknownhostsfile {resolved['userknownhostsfile']}")
        return 0, "\n".join(out) + "\n", ""


def run(core: FakeCore, paths: dict, *extra: str, code: str = ADMIN_CODE, keygen=None, lock_phrase: str = "",
        ssh=None, robot: str = ROBOT, timeout: float = 25.0):
    keygen = keygen or FakeKeygen()
    argv = [robot, "--label", "dev:laptop", "--key", str(paths["key"]),
            "--known-hosts", str(paths["known_hosts"]), "--ssh-config", str(paths["config"]), *extra]
    prompts: list[str] = []

    def ask_code(prompt: str) -> str:
        prompts.append(prompt)
        return code

    status = tool.main(argv, ask_code=ask_code, ask_lock=lambda prompt: lock_phrase, keygen=keygen,
                       client_for=lambda robot: tool.CoreClient(core.base_url, timeout=timeout),
                       ssh=ssh or FakeSsh())
    return status, keygen, prompts


def _no_token_leak(core: FakeCore, capsys, *files: Path) -> str:
    out = capsys.readouterr()
    text = out.out + out.err
    for token in core.issued:
        assert token not in text
        for path in files:
            if path.exists():
                assert token not in path.read_text(encoding="utf-8")
    return text


def test_happy_path_creates_key_registers_it_writes_known_hosts_and_config_and_logs_out(paths, capsys):
    with FakeCore(codes={ADMIN_CODE: "administrator"}) as core:
        status, keygen, prompts = run(core, paths, "--days", "30")

    assert status == 0
    assert len(keygen.calls) == 1
    argv = keygen.calls[0]
    assert argv[argv.index("-t") + 1] == "ed25519"
    assert argv[argv.index("-f") + 1] == str(paths["key"])
    assert argv[argv.index("-N") + 1] == ""
    assert "rosy-login-code --role administrator" in prompts[0]

    body = next(b for m, p, b in core.requests if m == "POST" and p == "/api/v1/host/ssh/keys")
    public = paths["key"].with_name("rosy_dev_laptop.pub").read_text(encoding="ascii").strip()
    assert body == {"public_key": public, "label": "dev:laptop", "expires_days": 30}
    assert core.keys["dev:laptop"]["fingerprint"] == fingerprint(public)

    known = paths["known_hosts"].read_text(encoding="ascii").splitlines()
    host_key = " ".join(core.host_keys[0].split()[:2])
    assert known == [f"{HOST},{ROBOT} {host_key}"]

    config = paths["config"].read_text(encoding="utf-8")
    assert f"Host {HOST}\n" in config
    assert f"    HostName {ROBOT}\n" in config
    assert "    User rosy\n" in config
    # Forward slashes: OpenSSH reads them on Windows too, and a backslash can be an escape in ssh_config.
    assert f'    IdentityFile "{paths["key"].as_posix()}"\n' in config
    assert f'    UserKnownHostsFile "{paths["known_hosts"].as_posix()}"\n' in config
    assert "    IdentitiesOnly yes\n" in config

    assert core.issued and core.logged_out == core.issued
    text = _no_token_leak(core, capsys, *paths.values())
    assert f'ssh -F "{paths["config"]}" {HOST}' in text


def test_defaults_write_only_inside_the_given_home(home, monkeypatch, capsys):
    """Guard for the 2026-10-02 leak: with default paths every write lands under HOME/USERPROFILE."""
    written: list[Path] = []
    write, backup = tool.write_private_text, tool.backup_file

    def record_write(path, text):
        written.append(Path(path))
        return write(path, text)

    def record_backup(path):
        copy = backup(path)
        written.append(Path(copy))
        return copy

    monkeypatch.setattr(tool, "write_private_text", record_write)
    monkeypatch.setattr(tool, "backup_file", record_backup)
    (home / ".ssh").mkdir()
    (home / ".ssh" / "config").write_text("Host other\n    HostName 192.0.2.99\n", encoding="utf-8")
    keygen = FakeKeygen()
    with FakeCore(codes={ADMIN_CODE: "administrator"}) as core:
        status = tool.main([ROBOT, "--label", "dev:laptop"], ask_code=lambda p: ADMIN_CODE,
                           ask_lock=lambda p: "", keygen=keygen,
                           client_for=lambda robot: tool.CoreClient(core.base_url), ssh=FakeSsh())
    assert status == 0
    written.append(Path(keygen.calls[0][keygen.calls[0].index("-f") + 1]))
    assert {path.name for path in written} >= {"rosy_dev_laptop", "known_hosts_rosy", "config"}
    for path in written:
        assert path.resolve().is_relative_to(home.resolve()), path
    assert (home / ".ssh" / "rosy_dev_laptop.pub").is_file()
    text = _no_token_leak(core, capsys)
    assert f"ssh {HOST}" in text and "ssh -F" not in text


def test_a_regression_in_argument_checks_still_cannot_write_a_bad_config(paths, monkeypatch, capsys):
    """The leak's bad line: a robot argument with a newline became a bare `ProxyCommand` in ~/.ssh/config."""
    import re

    monkeypatch.setattr(tool, "ROBOT", re.compile(r"(?s).+"))  # argparse check gone
    with FakeCore(codes={ADMIN_CODE: "administrator"}) as core:
        status = tool.main(["192.0.2.10\nProxyCommand", "--label", "dev:laptop", "--key", str(paths["key"]),
                            "--known-hosts", str(paths["known_hosts"]), "--ssh-config", str(paths["config"])],
                           ask_code=lambda p: ADMIN_CODE, ask_lock=lambda p: "", keygen=FakeKeygen(),
                           client_for=lambda robot: tool.CoreClient(core.base_url), ssh=FakeSsh())
    assert status == 1
    assert core.keys == {}
    assert not paths["config"].exists() and not paths["known_hosts"].exists()
    assert "refusing to write an invalid" in capsys.readouterr().err


@pytest.mark.parametrize("name", ["192.0.2.10\nProxyCommand", "", "a b", "*"])
def test_known_hosts_refuses_injected_names(name, tmp_path):
    with pytest.raises(tool.SshAccessError, match="invalid known_hosts name"):
        tool.plan_known_hosts(tmp_path / "kh", ["rosy-pinky-a", name], ["ssh-ed25519 AAAA"])


@pytest.mark.parametrize("alias, address, identity", [
    ("rosy-pinky-a", "192.0.2.10\nProxyCommand", "k"),
    ("rosy-pinky-a", "", "k"),
    ("rosy-pinky-a\nProxyCommand x", "192.0.2.10", "k"),
    ("rosy-pinky-a", "192.0.2.10", "k\nProxyCommand x"),
    ("rosy-pinky-a", "192.0.2.10", ""),
])
def test_host_block_refuses_empty_or_injected_values(alias, address, identity):
    with pytest.raises(tool.SshAccessError, match="invalid ssh config (line|value)"):
        tool.host_block(alias, address, Path(identity) if identity else Path(), Path("kh"))


def test_existing_config_is_backed_up_before_it_is_edited(paths, capsys):
    paths["config"].parent.mkdir(parents=True)
    paths["config"].write_text("Host other\n    HostName 192.0.2.99\n", encoding="utf-8")
    with FakeCore(codes={ADMIN_CODE: "administrator"}) as core:
        assert run(core, paths)[0] == 0
    backups = list(paths["config"].parent.glob("config.rosy-backup-*"))
    assert len(backups) == 1
    assert backups[0].read_text(encoding="utf-8") == "Host other\n    HostName 192.0.2.99\n"
    assert not list(paths["config"].parent.glob("*.rosy-tmp"))
    assert f"backup {backups[0]}" in _no_token_leak(core, capsys)


@pytest.mark.parametrize("ssh", [FakeSsh(code=255), FakeSsh(hostname="192.0.2.99"), FakeSsh(user="pinky"),
                                 FakeSsh(identityfile=["~/.ssh/id_ed25519"]),
                                 FakeSsh(userknownhostsfile="~/.ssh/known_hosts")],
                         ids=["parse-error", "elsewhere", "user", "identity", "known-hosts"])
def test_config_that_ssh_cannot_use_is_rolled_back(ssh, paths, capsys):
    paths["config"].parent.mkdir(parents=True)
    original = "Host other\n    HostName 192.0.2.99\n"
    paths["config"].write_text(original, encoding="utf-8")
    with FakeCore(codes={ADMIN_CODE: "administrator"}) as core:
        status, _, _ = run(core, paths, ssh=ssh)
    assert status == 1
    assert paths["config"].read_text(encoding="utf-8") == original
    assert ssh.calls[0][1:] == ["-G", "-F", str(paths["config"]), HOST]
    assert "restored" in _no_token_leak(core, capsys)


def test_a_new_config_that_ssh_cannot_parse_is_removed(paths, capsys):
    with FakeCore(codes={ADMIN_CODE: "administrator"}) as core:
        status, _, _ = run(core, paths, ssh=FakeSsh(code=255))
    assert status == 1
    assert not paths["config"].exists()
    _no_token_leak(core, capsys)


@pytest.mark.skipif(shutil.which("ssh") is None, reason="OpenSSH client not on PATH")
def test_the_real_ssh_client_parses_the_written_config(paths, capsys):
    with FakeCore(codes={ADMIN_CODE: "administrator"}) as core:
        status, _, _ = run(core, paths, ssh=tool.run_tool)
    assert status == 0, capsys.readouterr().err


def test_existing_key_is_reused_without_keygen(paths, capsys):
    paths["key"].parent.mkdir(parents=True)
    paths["key"].write_text("private", encoding="ascii")
    public = ed25519_public_key(b"existing", "me@pc")
    paths["key"].with_name("rosy_dev_laptop.pub").write_text(public + "\n", encoding="ascii")
    with FakeCore(codes={ADMIN_CODE: "administrator"}) as core:
        status, keygen, _ = run(core, paths)
    assert status == 0 and keygen.calls == []
    assert core.public_keys["dev:laptop"] == public
    _no_token_leak(core, capsys)


def test_passphrase_is_passed_to_keygen_and_never_printed(paths, capsys):
    with FakeCore(codes={ADMIN_CODE: "administrator"}) as core:
        status, keygen, _ = run(core, paths, lock_phrase="correct horse battery")
    assert status == 0
    argv = keygen.calls[0]
    assert argv[argv.index("-N") + 1] == "correct horse battery"
    assert "correct horse battery" not in _no_token_leak(core, capsys)


def test_passphrase_typed_differently_twice_is_refused(paths, capsys):
    answers = iter(["one-passphrase", "another-one"])
    with FakeCore(codes={ADMIN_CODE: "administrator"}) as core:
        status = tool.main([ROBOT, "--label", "dev:laptop", "--key", str(paths["key"]),
                            "--known-hosts", str(paths["known_hosts"]), "--ssh-config", str(paths["config"])],
                           ask_code=lambda p: ADMIN_CODE, ask_lock=lambda p: next(answers),
                           keygen=FakeKeygen(), client_for=lambda robot: tool.CoreClient(core.base_url))
    assert status == 1
    assert not paths["key"].exists()
    assert core.requests == []
    assert "did not match" in capsys.readouterr().err


def test_wrong_code_fails_without_registering_or_writing(paths, capsys):
    with FakeCore(codes={ADMIN_CODE: "administrator"}) as core:
        status, _, _ = run(core, paths, code="ZZZZ-ZZZZ")
    assert status == 1
    assert core.keys == {} and core.issued == []
    assert not paths["known_hosts"].exists() and not paths["config"].exists()
    err = _no_token_leak(core, capsys)
    assert "401" in err and "login code" in err


def test_an_empty_code_sends_nothing(paths, capsys):
    with FakeCore(codes={ADMIN_CODE: "administrator"}) as core:
        status, _, _ = run(core, paths, code="  ")
    assert status == 1
    assert core.requests == []
    assert "no login code" in capsys.readouterr().err


def test_operator_code_is_refused_and_its_token_logged_out(paths, capsys):
    with FakeCore(codes={ADMIN_CODE: "operator"}) as core:
        status, _, _ = run(core, paths)
    assert status == 1
    assert not any(path.startswith("/api/v1/host/ssh") for path in core.paths())  # refused before any SSH call
    assert core.issued and core.logged_out == core.issued
    assert "administrator" in _no_token_leak(core, capsys)


def test_label_taken_by_another_key_is_409_and_logs_out(paths, capsys):
    with FakeCore(codes={ADMIN_CODE: "administrator"}) as core:
        core.keys["dev:laptop"] = {"label": "dev:laptop", "type": "ssh-ed25519",
                                   "fingerprint": fingerprint(ed25519_public_key(b"someone else")),
                                   "added_at": "x", "expires_at": "y", "added_by": "z"}
        core.public_keys["dev:laptop"] = ed25519_public_key(b"someone else")
        status, _, _ = run(core, paths)
    assert status == 1
    assert core.logged_out == core.issued
    assert not paths["config"].exists() and not paths["known_hosts"].exists()
    err = _no_token_leak(core, capsys)
    assert "409" in err and "dev:laptop" in err


def test_full_key_store_is_409_and_reported(paths, capsys):
    with FakeCore(codes={ADMIN_CODE: "administrator"}) as core:
        core.max_keys = 0
        status, _, _ = run(core, paths)
    assert status == 1
    assert core.logged_out == core.issued
    assert "32 managed keys" in _no_token_leak(core, capsys)


def test_rerun_is_idempotent_and_replaces_changed_host_keys(paths, capsys):
    with FakeCore(codes={ADMIN_CODE: "administrator"}) as core:
        assert run(core, paths)[0] == 0
        # Same key again: the label is taken by this very key, so it is "already enrolled".
        core.codes["JKMN-PQRS"] = "administrator"
        assert run(core, paths, code="JKMN-PQRS")[0] == 0
        known_once = paths["known_hosts"].read_text(encoding="ascii")
        config_once = paths["config"].read_text(encoding="utf-8")
        # The card was re-flashed: changed host keys are refused until the operator accepts them.
        old_host_key = core.host_keys[0]
        core.host_keys = [ed25519_public_key(b"reflashed", "root@x")]
        core.codes["TUVW-XYZ2"] = "administrator"
        assert run(core, paths, code="TUVW-XYZ2")[0] == 1
        assert paths["known_hosts"].read_text(encoding="ascii") == known_once
        refused = capsys.readouterr()
        assert fingerprint(old_host_key) in refused.err and fingerprint(core.host_keys[0]) in refused.err
        assert "--accept-new-host-keys" in refused.err
        core.codes["ABCD-2345"] = "administrator"
        assert run(core, paths, "--accept-new-host-keys", code="ABCD-2345")[0] == 0
        assert core.logged_out == core.issued and len(core.issued) == 4
    assert known_once.count(HOST) == 1
    known = paths["known_hosts"].read_text(encoding="ascii").splitlines()
    assert known == [f"{HOST},{ROBOT} " + " ".join(core.host_keys[0].split()[:2])]
    config = paths["config"].read_text(encoding="utf-8")
    assert config == config_once
    assert config.count(f"Host {HOST}\n") == 1
    text = _no_token_leak(core, capsys)
    assert "already enrolled" in text and "replaced" in text
    assert "expires 2026-12-31T00:00:00Z" in text  # the existing expiry is shown on "already enrolled"


def test_other_known_hosts_and_config_entries_are_kept(paths, capsys):
    paths["config"].parent.mkdir(parents=True)
    paths["config"].write_text("Host other\n    HostName 192.0.2.99\n", encoding="utf-8")
    paths["known_hosts"].write_text("192.0.2.99 ssh-ed25519 AAAAother\n", encoding="ascii")
    with FakeCore(codes={ADMIN_CODE: "administrator"}) as core:
        assert run(core, paths)[0] == 0
    config = paths["config"].read_text(encoding="utf-8")
    assert "Host other\n    HostName 192.0.2.99\n" in config
    assert config.index(f"Host {HOST}\n") < config.index("Host other\n")  # the managed block goes first
    assert "192.0.2.99 ssh-ed25519 AAAAother" in paths["known_hosts"].read_text(encoding="ascii").splitlines()
    _no_token_leak(core, capsys)


def test_an_unmanaged_host_block_with_the_same_name_is_refused(paths, capsys):
    paths["config"].parent.mkdir(parents=True)
    paths["config"].write_text(f"Host {HOST}\n    HostName 192.0.2.50\n", encoding="utf-8")
    with FakeCore(codes={ADMIN_CODE: "administrator"}) as core:
        status, _, _ = run(core, paths)
    assert status == 1
    assert core.keys == {}  # the config is checked before the key is registered
    assert core.logged_out == core.issued
    assert paths["config"].read_text(encoding="utf-8") == f"Host {HOST}\n    HostName 192.0.2.50\n"
    assert "already has" in _no_token_leak(core, capsys)


def test_token_is_logged_out_when_host_keys_are_unusable(paths, capsys):
    with FakeCore(codes={ADMIN_CODE: "administrator"}, hostname="Bad Host\nProxyCommand x",
                  host_keys=[ed25519_public_key(b"host")]) as core:
        status, _, _ = run(core, paths)
    assert status == 1
    assert core.keys == {}  # host keys are checked before the key is registered
    assert core.logged_out == core.issued
    assert not paths["config"].exists()
    assert "unusable hostname" in _no_token_leak(core, capsys)


_REAL_HOST_KEY = ed25519_public_key(b"host")


@pytest.mark.parametrize("line", [
    _REAL_HOST_KEY + "\nHost *\n    ProxyCommand calc",            # newline injection after a real key
    "ssh-ed25519 " + base64.b64encode(b"\0\0\0\x07ssh-rsa" + bytes(8)).decode(),  # blob is another type
    "ssh-dss " + _REAL_HOST_KEY.split()[1],                           # type not allowed
    [],                                                               # not a string
])
def test_a_bad_host_key_line_is_refused(line, paths, capsys):
    with FakeCore(codes={ADMIN_CODE: "administrator"}, host_keys=[_REAL_HOST_KEY, line]) as core:
        status, _, _ = run(core, paths)
    assert status == 1
    assert core.keys == {}
    assert core.logged_out == core.issued
    assert not paths["known_hosts"].exists()
    _no_token_leak(core, capsys)


def test_rsa_or_unknown_public_key_is_refused_locally(paths, capsys):
    paths["key"].parent.mkdir(parents=True)
    paths["key"].write_text("private", encoding="ascii")
    paths["key"].with_name("rosy_dev_laptop.pub").write_text("ssh-rsa AAAAB3NzaC1yc2E= me\n", encoding="ascii")
    with FakeCore(codes={ADMIN_CODE: "administrator"}) as core:
        status, _, _ = run(core, paths)
    assert status == 1
    assert core.requests == []
    assert "ssh-rsa" in capsys.readouterr().err


@pytest.mark.parametrize("argv", [
    [ROBOT, "--label", "Dev:Laptop"],
    [ROBOT, "--label", "team:x"],
    [ROBOT, "--days", "0"],
    [ROBOT, "--days", "366"],
    ["192.0.2.10\nProxyCommand"],
])
def test_bad_arguments_are_refused_before_any_request(argv, capsys):
    with FakeCore(codes={ADMIN_CODE: "administrator"}) as core:
        with pytest.raises(SystemExit) as exit_info:
            tool.main(argv, ask_code=lambda p: ADMIN_CODE, ask_lock=lambda p: "", keygen=FakeKeygen(),
                      client_for=lambda robot: tool.CoreClient(core.base_url))
    assert exit_info.value.code == 2
    assert core.requests == []


def test_default_label_is_a_valid_device_label():
    label = tool.default_label("My Laptop_01.local")
    assert label.startswith("dev:") and tool.LABEL.fullmatch(label)
    assert tool.LABEL.fullmatch(tool.default_label("x" * 80))


def test_unreachable_robot_is_a_clean_error(paths, capsys):
    status = tool.main([ROBOT, "--label", "dev:laptop", "--key", str(paths["key"]),
                        "--known-hosts", str(paths["known_hosts"]), "--ssh-config", str(paths["config"])],
                       ask_code=lambda p: ADMIN_CODE, ask_lock=lambda p: "", keygen=FakeKeygen(),
                       client_for=lambda robot: tool.CoreClient("http://127.0.0.1:9", timeout=2))
    assert status == 1
    assert "not reachable" in capsys.readouterr().err


# --- review 2026-10-02 -------------------------------------------------------------------


@pytest.mark.parametrize("hostname", ["evil-host", "rosy", "rosy-", "rosy-Pinky", "other.rosy-pinky"])
def test_only_rosy_hostnames_become_aliases(hostname, paths, capsys):
    with FakeCore(codes={ADMIN_CODE: "administrator"}, hostname=hostname,
                  host_keys=[ed25519_public_key(b"host")]) as core:
        status, _, _ = run(core, paths)
    assert status == 1
    assert core.keys == {} and not paths["config"].exists()
    assert "unusable hostname" in _no_token_leak(core, capsys)


def test_a_managed_block_pointing_elsewhere_needs_replace(paths, capsys):
    with FakeCore(codes={ADMIN_CODE: "administrator", "JKMN-PQRS": "administrator",
                         "TUVW-XYZ2": "administrator"}) as core:
        assert run(core, paths)[0] == 0
        before = paths["config"].read_text(encoding="utf-8")
        assert run(core, paths, code="JKMN-PQRS", robot="192.0.2.20")[0] == 1
        assert paths["config"].read_text(encoding="utf-8") == before
        assert "--replace" in capsys.readouterr().err
        assert run(core, paths, "--replace", code="TUVW-XYZ2", robot="192.0.2.20")[0] == 0
    config = paths["config"].read_text(encoding="utf-8")
    assert "    HostName 192.0.2.20\n" in config and ROBOT not in config
    _no_token_leak(core, capsys)


@pytest.mark.parametrize("prelude", [
    "Host *\n    User pinky\n    IdentityFile ~/.ssh/other\n",
    "Host rosy-*\n    User pinky\n    UserKnownHostsFile ~/.ssh/known_hosts\n",
])
def test_the_managed_block_wins_over_earlier_blocks(prelude, paths, capsys):
    paths["config"].parent.mkdir(parents=True)
    paths["config"].write_text("# mine\n" + prelude, encoding="utf-8")
    ssh = FakeSsh()
    with FakeCore(codes={ADMIN_CODE: "administrator"}) as core:
        assert run(core, paths, ssh=ssh)[0] == 0, capsys.readouterr().err
    config = paths["config"].read_text(encoding="utf-8")
    assert config.startswith("# mine\n# >>> rosy-ssh ")
    assert config.endswith(prelude)
    out = ssh(["ssh", "-G", "-F", str(paths["config"]), HOST])[1]
    assert "user rosy\n" in out
    _no_token_leak(core, capsys)


@pytest.mark.skipif(shutil.which("ssh") is None, reason="OpenSSH client not on PATH")
def test_the_real_ssh_client_resolves_our_user_and_key_over_a_wildcard(paths, capsys):
    paths["config"].parent.mkdir(parents=True)
    paths["config"].write_text("Host *\n    User pinky\n    UserKnownHostsFile ~/.ssh/known_hosts\n",
                               encoding="utf-8")
    with FakeCore(codes={ADMIN_CODE: "administrator"}) as core:
        status, _, _ = run(core, paths, ssh=tool.run_tool)
    assert status == 0, capsys.readouterr().err
    out = tool.run_tool([shutil.which("ssh"), "-G", "-F", str(paths["config"]), HOST])[1]
    assert "user rosy" in out.splitlines()


@pytest.mark.parametrize("text", [
    f"# >>> rosy-ssh {HOST} >>>\n# >>> rosy-ssh {HOST} >>>\n# <<< rosy-ssh {HOST} <<<\n",
    f"# <<< rosy-ssh {HOST} <<<\n# >>> rosy-ssh {HOST} >>>\n",
    f"# >>> rosy-ssh {HOST} >>>\nHost x\n",
    f"# <<< rosy-ssh {HOST} <<<\n",
])
def test_corrupted_markers_are_refused(text, paths, capsys):
    paths["config"].parent.mkdir(parents=True)
    paths["config"].write_text(text, encoding="utf-8")
    with FakeCore(codes={ADMIN_CODE: "administrator"}) as core:
        status, _, _ = run(core, paths)
    assert status == 1
    assert core.keys == {}
    assert paths["config"].read_text(encoding="utf-8") == text
    assert "markers" in _no_token_leak(core, capsys)


def test_relative_and_tilde_paths_are_made_absolute(home, tmp_path, monkeypatch, capsys):
    monkeypatch.chdir(tmp_path)
    with FakeCore(codes={ADMIN_CODE: "administrator"}) as core:
        status = tool.main([ROBOT, "--label", "dev:laptop", "--key", "~/keys/rosy_dev_laptop",
                            "--known-hosts", "kh/known_hosts_rosy", "--ssh-config", "cfg/config"],
                           ask_code=lambda p: ADMIN_CODE, ask_lock=lambda p: "", keygen=FakeKeygen(),
                           client_for=lambda robot: tool.CoreClient(core.base_url), ssh=FakeSsh())
    assert status == 0, capsys.readouterr().err
    config = (tmp_path / "cfg" / "config").read_text(encoding="utf-8")
    key = (home / "keys" / "rosy_dev_laptop").resolve().as_posix()
    known = (tmp_path / "kh" / "known_hosts_rosy").resolve().as_posix()
    assert f'    IdentityFile "{key}"\n' in config
    assert f'    UserKnownHostsFile "{known}"\n' in config


def _symlink_or_skip(link: Path, target: Path) -> None:
    try:
        link.symlink_to(target)
    except (OSError, NotImplementedError):
        pytest.skip("symlinks are not available here")


@pytest.mark.skipif(os.name == "nt", reason="POSIX symlinked dotfiles; Windows symlinks need extra rights")
def test_a_symlinked_config_keeps_its_link_and_the_target_is_edited(paths, tmp_path, capsys):
    target = tmp_path / "dotfiles" / "ssh_config"
    target.parent.mkdir()
    target.write_text("Host other\n    HostName 192.0.2.99\n", encoding="utf-8")
    paths["config"].parent.mkdir(parents=True)
    _symlink_or_skip(paths["config"], target)
    with FakeCore(codes={ADMIN_CODE: "administrator"}) as core:
        assert run(core, paths)[0] == 0, capsys.readouterr().err
    assert paths["config"].is_symlink()
    assert f"Host {HOST}\n" in target.read_text(encoding="utf-8")
    assert list(target.parent.glob("ssh_config.rosy-backup-*"))


@pytest.mark.parametrize("name", ["rosy_dev_%h", "rosy_dev_${HOME}"])
def test_percent_and_dollar_paths_are_refused(name, paths, capsys):
    paths["key"] = paths["key"].with_name(name)
    with FakeCore(codes={ADMIN_CODE: "administrator"}) as core:
        status, _, _ = run(core, paths)
    assert status == 1
    assert core.keys == {} and not paths["config"].exists()
    assert "% or $" in _no_token_leak(core, capsys)


def test_unreadable_files_are_clean_errors(paths, capsys):
    paths["known_hosts"].mkdir(parents=True)  # a directory where the file should be
    with FakeCore(codes={ADMIN_CODE: "administrator"}) as core:
        status, _, _ = run(core, paths)
    assert status == 1
    err = _no_token_leak(core, capsys)
    assert "rosy_ssh_enroll:" in err and "Traceback" not in err


def test_a_non_utf8_config_is_a_clean_error(paths, capsys):
    paths["config"].parent.mkdir(parents=True)
    paths["config"].write_bytes(b"Host \xff\xfe\n")
    with FakeCore(codes={ADMIN_CODE: "administrator"}) as core:
        status, _, _ = run(core, paths)
    assert status == 1
    assert paths["config"].read_bytes() == b"Host \xff\xfe\n"
    assert "rosy_ssh_enroll:" in _no_token_leak(core, capsys)


def test_redirects_are_not_followed(paths, capsys):
    with FakeCore(codes={ADMIN_CODE: "administrator"}) as target, \
            FakeCore(codes={ADMIN_CODE: "administrator"}) as front:
        front.redirect = target.base_url
        status, _, _ = run(front, paths)
    assert status == 1
    assert target.requests == []
    assert "302" in capsys.readouterr().err


def test_a_slow_answer_says_the_change_may_have_been_applied(paths, capsys):
    assert tool.DEFAULT_TIMEOUT_S == 25
    with FakeCore(codes={ADMIN_CODE: "administrator"}, delay_keys=3.0) as core:
        status, _, _ = run(core, paths, timeout=1.0)
    assert status == 1
    assert "may have been applied" in capsys.readouterr().err


def test_non_ascii_pc_names_get_a_short_hash_suffix():
    first, second = tool.default_label("회의실PC"), tool.default_label("연구실PC")
    assert first != second
    for label in (first, second):
        assert tool.DEVICE_LABEL.fullmatch(label)
        assert re.fullmatch(r"dev:pc-[0-9a-f]{6}", label)
    assert tool.default_label("laptop") == "dev:laptop"
    assert tool.DEVICE_LABEL.fullmatch(tool.default_label("가" * 80))


@pytest.mark.parametrize("line", ['    IdentityFile "/a/%h"', '    UserKnownHostsFile "/a/${HOME}/k"',
                                  '    IdentityFile ""', '    ProxyCommand x', '    User pinky', '    HostName '])
def test_the_config_line_allowlist_is_a_second_layer(line):
    assert not tool.CONFIG_OPTION.fullmatch(line)
