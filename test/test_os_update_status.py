"""Operator status observes local OS state and common policy without admitting an update."""
import datetime as dt
import importlib
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from test_os_update_policy import _policy
from test_os_update_state import _advance, _begin, SOURCE_BOOT, TRANSACTION


def controller():
    return importlib.import_module("os_update_controller")


def snapshot(paths):
    return {path: (path.read_bytes(), path.stat().st_mtime_ns, path.stat().st_mode) for path in paths}


@pytest.mark.parametrize("pending", [False, True])
@pytest.mark.parametrize("slot", ["a", "b"])
def test_status_projects_local_slots_policy_and_pending_without_writes(tmp_path, monkeypatch, pending, slot):
    _, state, root, journal, verified, facts, directory, host = _policy(tmp_path, monkeypatch, slot=slot)
    config = directory / "config.json"
    config.write_text(json.dumps(dict(enabled=False, repo="example/robot-updates",
                                     api_base="https://catalog.invalid/private")))
    if pending:
        _begin(state, root, verified, facts)
    before = snapshot([journal, config])
    # No transport, CORE, claim, service or device-operation methods are available to status.
    result = controller().status(root, host=SimpleNamespace(now=host.now))
    assert result["schema_version"] == 1
    assert result["running_slot"] == slot
    assert result["committed"] == dict(slot=slot, release_id="2026.10.26-010")
    assert result["policy"] == dict(enabled=False, repo="example/robot-updates", hold="none")
    assert result["failed_versions"] == []
    expected = (dict(phase="PREPARED", release_id=verified["metadata"]["release_id"],
                     source_slot=slot, target_slot="b" if slot == "a" else "a") if pending else None)
    assert result["pending"] == expected
    assert not any(word in json.dumps(result) for word in ("api_base", "catalog.invalid", "source_boot_id", "manifest_sha256"))
    assert snapshot([journal, config]) == before
    assert not (directory / "hold.json").exists()


def test_status_reports_failed_versions_from_the_lifecycle_journal(tmp_path, monkeypatch):
    _, state, root, journal, verified, facts, _, host = _policy(tmp_path, monkeypatch)
    _begin(state, root, verified, facts)
    _advance(state, root, "TRIAL")
    with state.locked(root) as store:
        store.record_failure(TRANSACTION, SOURCE_BOOT, "a")
    before = snapshot([journal])
    result = controller().status(root, host=SimpleNamespace(now=host.now))
    assert result["failed_versions"] == [verified["metadata"]["release_id"]]
    assert result["pending"] is None
    assert snapshot([journal]) == before


@pytest.mark.parametrize("kind", ["active", "expired", "invalid"])
def test_status_never_expires_or_releases_a_hold(tmp_path, monkeypatch, kind):
    _, _, root, journal, _, _, directory, host = _policy(tmp_path, monkeypatch)
    path = directory / "hold.json"
    stamp = lambda value: value.isoformat().replace("+00:00", "Z")
    expires = host.now() + dt.timedelta(hours=1) if kind == "active" else host.now() - dt.timedelta(minutes=1)
    value = dict(created_at=stamp(host.now() - dt.timedelta(hours=1)), expires_at=stamp(expires),
                 holder="operator", reason="must stay local")
    if kind == "invalid": value["expires_at"] = "invalid"
    path.write_text(json.dumps(value))
    before = snapshot([journal, path])
    result = controller().status(root, host=SimpleNamespace(now=host.now))
    assert result["policy"]["hold"] == kind
    assert "must stay local" not in json.dumps(result)
    assert snapshot([journal, path]) == before


@pytest.mark.parametrize("raw", ["not JSON", '{"enabled":"yes"}'])
def test_bad_policy_cannot_be_displayed_as_healthy(tmp_path, monkeypatch, raw):
    _, _, root, journal, _, _, directory, host = _policy(tmp_path, monkeypatch)
    config = directory / "config.json"
    config.write_text(raw)
    before = snapshot([journal, config])
    with pytest.raises(ValueError, match="OS_STATUS_POLICY_HOLD"):
        controller().status(root, host=SimpleNamespace(now=host.now))
    assert snapshot([journal, config]) == before


@pytest.mark.parametrize("missing", [False, True])
def test_unreadable_journal_is_never_reinitialized_as_idle(tmp_path, monkeypatch, missing):
    _, _, root, journal, _, _, _, host = _policy(tmp_path, monkeypatch)
    if missing: journal.unlink()
    else: journal.write_text("not JSON")
    with pytest.raises(ValueError, match="OS_UPDATE_STATE_HOLD"):
        controller().status(root, host=SimpleNamespace(now=host.now))
    assert not journal.exists() if missing else journal.read_text() == "not JSON"


def test_cli_status_dispatches_only_the_read_only_owner(monkeypatch, capsys):
    m = controller()
    expected = dict(policy=dict(enabled=False))
    monkeypatch.setattr(m, "status", lambda: expected, raising=False)
    monkeypatch.setattr(m, "start", lambda *a, **k: pytest.fail("status attempted installation"))
    monkeypatch.setattr(m, "resume", lambda *a, **k: pytest.fail("status attempted resume"))
    assert m.main(["status"]) == 0
    assert json.loads(capsys.readouterr().out) == dict(ok=True, state=expected)


@pytest.mark.parametrize("argument", ["--bundle", "--metadata", "--signature"])
def test_cli_status_refuses_install_paths(monkeypatch, capsys, argument):
    m = controller()
    monkeypatch.setattr(m, "status", lambda: pytest.fail("invalid request reached status"), raising=False)
    assert m.main(["status", argument, str(Path("unused"))]) == 1
    assert "status does not accept install paths" in json.loads(capsys.readouterr().out)["error"]
