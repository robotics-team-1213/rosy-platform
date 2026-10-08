from __future__ import annotations

import io
import json
import os
import sys
from hashlib import sha256
from pathlib import Path

import pytest
import yaml

from deploy.site import site_users
from deploy.site.site_users import (
    SiteUsersError,
    add_user,
    list_users,
    main,
    remove_user,
    validate_users_document,
)

TOKEN = "standin-operator-token-issued-by-the-secret-manager"


def _entry(principal: str = "operator-1", role: str = "operator",
           token: str = "tok-1") -> dict:
    return {"principal_id": principal, "role": role,
            "token_sha256": sha256(token.encode()).hexdigest()}


def _seed(path: Path, *entries: dict) -> bytes:
    text = yaml.safe_dump({"users": list(entries)}, sort_keys=False)
    path.write_text(text, encoding="utf-8")
    return path.read_bytes()


def _stdin(monkeypatch, token: str) -> None:
    monkeypatch.setattr(sys, "stdin", io.StringIO(token))


def _no_temp_files_left(tmp_path: Path) -> None:
    assert list(tmp_path.glob(".*.tmp")) == []
    assert list(tmp_path.glob("*.tmp")) == []


def test_add_list_remove_roundtrip_loads_in_the_real_fleet_loader(
        tmp_path, monkeypatch, capsys):
    from fleet.server.site_users import load_site_users

    path = tmp_path / "site-users.yaml"
    _seed(path, _entry())
    _stdin(monkeypatch, TOKEN)

    assert main(["add", str(path), "--principal", "temp-operator",
                 "--role", "operator", "--token-stdin"]) == 0

    listed = list_users(path)
    assert [user["principal_id"] for user in listed] == ["operator-1", "temp-operator"]
    assert listed[1]["token_sha256"] == sha256(TOKEN.encode()).hexdigest()
    # The published file must satisfy the strict loader Fleet runs at startup.
    assert load_site_users(path)[sha256(TOKEN.encode()).hexdigest()] == {
        "principal_id": "temp-operator", "role": "operator"}
    captured = capsys.readouterr()
    assert TOKEN not in captured.out and TOKEN not in captured.err

    assert main(["list", str(path)]) == 0
    assert json.loads(capsys.readouterr().out) == listed

    assert main(["remove", str(path), "--principal", "temp-operator"]) == 0
    assert [user["principal_id"] for user in list_users(path)] == ["operator-1"]
    if os.name == "posix":
        # The atomic publish lands with the group-readable, other-closed mode.
        assert path.stat().st_mode & 0o777 == 0o440
    _no_temp_files_left(tmp_path)


def test_add_hashes_only_the_delivered_token(tmp_path, monkeypatch):
    path = tmp_path / "site-users.yaml"
    _seed(path, _entry())
    _stdin(monkeypatch, TOKEN + "\r\n")

    result = add_user(path, "newline-operator", "operator",
                      site_users._read_token(sys.stdin))

    assert result["entry"]["token_sha256"] == sha256(TOKEN.encode()).hexdigest()


def test_add_rejects_roles_outside_the_human_whitelist(tmp_path, monkeypatch):
    path = tmp_path / "site-users.yaml"
    original = _seed(path, _entry())

    for role in ("admin", "service", "Viewer"):
        _stdin(monkeypatch, TOKEN)
        with pytest.raises(SystemExit):
            main(["add", str(path), "--principal", "x", "--role", role, "--token-stdin"])

    assert path.read_bytes() == original
    assert len(list_users(path)) == 1


def test_add_rejects_empty_or_whitespace_token_input(tmp_path, monkeypatch):
    path = tmp_path / "site-users.yaml"
    original = _seed(path, _entry())

    for raw in ("", "\n", "   \n"):
        _stdin(monkeypatch, raw)
        with pytest.raises(SystemExit):
            main(["add", str(path), "--principal", "x", "--role", "viewer", "--token-stdin"])

    assert path.read_bytes() == original


def test_add_rejects_duplicate_principal_and_reused_token(tmp_path, monkeypatch, capsys):
    path = tmp_path / "site-users.yaml"
    original = _seed(path, _entry("operator-1", "operator", "tok-1"))

    _stdin(monkeypatch, "tok-2")
    with pytest.raises(SystemExit):
        main(["add", str(path), "--principal", "operator-1", "--role", "viewer",
              "--token-stdin"])
    assert "already exists" in capsys.readouterr().err
    _stdin(monkeypatch, "tok-1")
    with pytest.raises(SystemExit):
        main(["add", str(path), "--principal", "someone-else", "--role", "viewer",
              "--token-stdin"])
    assert "another principal" in capsys.readouterr().err

    assert path.read_bytes() == original


@pytest.mark.parametrize("corrupt", [
    "users: [\n  broken",
    "users: []",
    "users:\nextra: 1",
    "not-a-mapping",
])
def test_corrupt_or_wrong_shape_registry_is_refused_without_touching_it(
        tmp_path, monkeypatch, corrupt):
    path = tmp_path / "site-users.yaml"
    path.write_text(corrupt, encoding="utf-8")
    original = path.read_bytes()

    _stdin(monkeypatch, TOKEN)
    with pytest.raises(SystemExit):
        main(["add", str(path), "--principal", "x", "--role", "viewer", "--token-stdin"])
    with pytest.raises(SystemExit):
        main(["remove", str(path), "--principal", "operator-1"])
    with pytest.raises(SystemExit):
        main(["list", str(path)])

    assert path.read_bytes() == original
    _no_temp_files_left(tmp_path)


def test_add_refuses_when_an_existing_digest_is_not_a_sha256_hex(tmp_path, monkeypatch):
    path = tmp_path / "site-users.yaml"
    original = _seed(path, {"principal_id": "operator-1", "role": "operator",
                            "token_sha256": "NOT-A-DIGEST"})

    _stdin(monkeypatch, TOKEN)
    with pytest.raises(SystemExit):
        main(["add", str(path), "--principal", "x", "--role", "viewer", "--token-stdin"])

    assert path.read_bytes() == original


def test_remove_refuses_unknown_principal_and_the_last_entry(tmp_path, capsys):
    path = tmp_path / "site-users.yaml"
    _seed(path, _entry("operator-1", "operator", "tok-1"), _entry("viewer-1", "viewer", "tok-2"))
    before = path.read_bytes()

    with pytest.raises(SystemExit):
        main(["remove", str(path), "--principal", "ghost"])
    assert "not registered" in capsys.readouterr().err
    assert path.read_bytes() == before

    assert main(["remove", str(path), "--principal", "operator-1"]) == 0
    with pytest.raises(SystemExit):
        main(["remove", str(path), "--principal", "viewer-1"])
    assert "last principal" in capsys.readouterr().err
    assert [user["principal_id"] for user in list_users(path)] == ["viewer-1"]


def test_dry_run_reports_the_change_but_never_writes(tmp_path, monkeypatch):
    path = tmp_path / "site-users.yaml"
    original = _seed(path, _entry("operator-1", "operator", "tok-1"),
                     _entry("viewer-1", "viewer", "tok-2"))

    _stdin(monkeypatch, TOKEN)
    assert main(["add", str(path), "--principal", "temp-operator", "--role", "operator",
                 "--token-stdin", "--dry-run"]) == 0
    assert main(["remove", str(path), "--principal", "operator-1", "--dry-run"]) == 0

    assert path.read_bytes() == original
    assert len(list_users(path)) == 2
    _no_temp_files_left(tmp_path)


def test_add_prints_the_ownership_hint_when_it_cannot_chown(tmp_path, monkeypatch, capsys):
    path = tmp_path / "site-users.yaml"
    _seed(path, _entry())
    _stdin(monkeypatch, TOKEN)

    assert main(["add", str(path), "--principal", "temp-operator", "--role", "operator",
                 "--token-stdin"]) == 0

    out = capsys.readouterr().out
    if os.name != "posix" or os.geteuid() != 0:
        assert f"chown 0:10001 {path} && chmod 440 {path}" in out
    else:
        assert "ownership applied" in out


def test_validate_gates_restart_on_content_and_ownership(tmp_path, capsys):
    path = tmp_path / "site-users.yaml"
    _seed(path, _entry())
    if os.name == "posix":
        path.chmod(0o440)  # the published mode; a fresh file follows the umask (0644 under 022)

    gid = ["--gid", str(path.stat().st_gid)] if os.name == "posix" else []
    assert main(["validate", str(path), *gid]) == 0
    report = json.loads(capsys.readouterr().out)
    assert report["principals"] == 1

    if os.name == "posix":
        actual_gid = path.stat().st_gid
        if actual_gid != site_users.FLEET_GID:
            with pytest.raises(SystemExit):
                main(["validate", str(path)])  # wrong owning group, the 2026-10-07 incident
        path.chmod(0o644)
        with pytest.raises(SystemExit):
            main(["validate", str(path), "--gid", str(actual_gid)])  # other-readable
        path.chmod(0o460)
        with pytest.raises(SystemExit):
            main(["validate", str(path), "--gid", str(actual_gid)])  # group-writable
        path.chmod(0o640)  # owner-writable again: only root can write through 0460

    path.write_text("users: [\n  broken", encoding="utf-8")
    with pytest.raises(SystemExit):
        main(["validate", str(path)])


@pytest.mark.parametrize("document", [
    "not-a-mapping",
    {},
    {"users": []},
    {"users": [], "extra": 1},
    {"users": [{"principal_id": "a", "role": "viewer"}]},
    {"users": [{"principal_id": "a", "role": "viewer", "token_sha256": "x" * 64, "extra": 1}]},
    {"users": [{"principal_id": "", "role": "viewer", "token_sha256": "a" * 64}]},
    {"users": [{"principal_id": "a", "role": "viewer", "token_sha256": "A" * 64}]},
    {"users": [{"principal_id": "a", "role": "viewer", "token_sha256": "a" * 63}]},
    {"users": [{"principal_id": "a", "role": "admin", "token_sha256": "a" * 64}]},
    {"users": [{"principal_id": "a", "role": "viewer", "token_sha256": "a" * 64},
               {"principal_id": "a", "role": "operator", "token_sha256": "b" * 64}]},
    {"users": [{"principal_id": "a", "role": "viewer", "token_sha256": "a" * 64},
               {"principal_id": "b", "role": "viewer", "token_sha256": "a" * 64}]},
])
def test_validate_users_document_rejects_every_loader_violation(document):
    with pytest.raises(SiteUsersError):
        validate_users_document(document)


def test_validate_users_document_accepts_service_rows_and_normalizes_spaces():
    users = validate_users_document({"users": [
        {"principal_id": "  cell-1  ", "role": "service", "token_sha256": "a" * 64}]})
    assert users == [{"principal_id": "cell-1", "role": "service", "token_sha256": "a" * 64}]
