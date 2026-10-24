"""Managed physical scopes reject uncoordinated motion, including after Action success."""
from contextlib import closing
import sqlite3

import pytest

from omx_adapter.action_store import ActionStore
from omx_adapter.command_owner import ArmCommandOwner
from omx_adapter.control_seat_admission import ControlSeatAdmission
from test_omx_command_owner import FakeActionClient, make_config, make_command, make_state


def setup(tmp_path, *, managed=True):
    client = FakeActionClient()
    owner = ArmCommandOwner(make_config(allowed_owners=("pilot_sim", "rule_based", "moveit")),
                            client, monotonic=lambda: 100.0, session_id="session-01")
    owner.observe_joint_state(make_state())
    store = ActionStore(tmp_path / "managed.sqlite3")
    admission = ControlSeatAdmission(owner, store, monotonic=lambda: 100.0)
    owner.bind_control_admission(admission)
    if managed:
        enable = getattr(admission, "enable_managed_transfers", None)
        assert enable is not None, "managed physical authority profile is missing"
        enable("d" * 64)
    return owner, store, admission, client


def test_managed_owner_rejects_pilot_seat_and_raw_rule_based_commands(tmp_path):
    owner, _, admission, client = setup(tmp_path)
    with pytest.raises(PermissionError):
        admission.acquire("token", "seat", ttl_s=1.0)
    decision = owner.submit(make_command(owner="rule_based"))
    assert not decision.accepted and decision.reason == "control_seat_fenced"
    assert not client.commands


def test_unmanaged_owner_keeps_existing_pilot_acquisition(tmp_path):
    _, _, admission, _ = setup(tmp_path, managed=False)
    admission.acquire("token", "seat", ttl_s=1.0)
    admission.release("token", "seat")


def test_managed_mode_and_policy_survive_reopening_and_refuse_identity_changes(tmp_path):
    _, store, _, _ = setup(tmp_path)
    with closing(sqlite3.connect(store.path)) as connection:
        assert connection.execute("PRAGMA user_version").fetchone()[0] == 3
    reopened = ActionStore(store.path)
    owner = ArmCommandOwner(make_config(), FakeActionClient(), session_id="restart")
    admission = ControlSeatAdmission(owner, reopened)
    assert admission.managed_transfer_policy_digest == "d" * 64
    with pytest.raises(PermissionError):
        admission.acquire("token", "seat", ttl_s=1.0)
    other = ArmCommandOwner(make_config(instance_id="other"), FakeActionClient())
    with pytest.raises((ValueError, PermissionError, RuntimeError)):
        ControlSeatAdmission(other, reopened)


def test_policy_change_or_active_pilot_cannot_silently_enable_managed_mode(tmp_path):
    _, _, admission, _ = setup(tmp_path)
    with pytest.raises(PermissionError):
        admission.enable_managed_transfers("e" * 64)
    _, store, other, _ = setup(tmp_path / "pilot", managed=False)
    other.acquire("token", "seat", ttl_s=1.0)
    with pytest.raises(PermissionError):
        other.enable_managed_transfers("d" * 64)
    with closing(sqlite3.connect(store.path)) as connection:
        assert connection.execute("PRAGMA user_version").fetchone()[0] == 2


def test_managed_action_admission_requires_arm_kind_and_installed_policy(tmp_path):
    _, _, admission, _ = setup(tmp_path)
    calls = []
    with pytest.raises(PermissionError):
        admission.run_action_admission(lambda: calls.append(1))
    with pytest.raises(PermissionError):
        admission.run_action_admission(lambda: calls.append(1), action_kind="ARM_TRANSFER",
                                       resource_policy_digest="e" * 64)
    assert calls == []
    admission.run_action_admission(lambda: calls.append(1), action_kind="ARM_TRANSFER",
                                   resource_policy_digest="d" * 64)
    assert calls == [1]


def test_unresolved_action_blocks_activation_without_upgrading_journal(tmp_path):
    _, store, admission, _ = setup(tmp_path, managed=False)
    store.create_action(workcell_id="omx_01", instance_id="omx_01_control", principal_id="fleet",
                        request_key="a-1", action_kind="ARM_TRANSFER", configuration_revision="cfg-1",
                        observation_id="", owner_generation=1, payload={})
    with pytest.raises(PermissionError):
        admission.enable_managed_transfers("d" * 64)
    assert admission.managed_transfer_policy_digest is None
    with closing(sqlite3.connect(store.path)) as connection:
        assert connection.execute("PRAGMA user_version").fetchone()[0] == 2


@pytest.mark.parametrize("damage", ["missing-scope", "downgraded-version"])
def test_managed_journal_corruption_never_reopens_as_unmanaged(tmp_path, damage):
    _, store, _, _ = setup(tmp_path)
    with closing(sqlite3.connect(store.path)) as connection:
        if damage == "missing-scope":
            connection.execute("DELETE FROM omx_managed_transfer_scope")
        else:
            connection.execute("PRAGMA user_version=2")
        connection.commit()
    with pytest.raises(RuntimeError):
        ActionStore(store.path)


def test_concurrent_constructor_cannot_downgrade_managed_activation(tmp_path, monkeypatch):
    from concurrent.futures import ThreadPoolExecutor
    from threading import Event, get_ident

    _, store, admission, _ = setup(tmp_path, managed=False)
    original = ActionStore._connect
    main_thread = get_ident()
    paused, resume = Event(), Event()

    class PausedConnection:
        def __init__(self, connection):
            self.connection = connection

        def __getattr__(self, name):
            return getattr(self.connection, name)

        def executescript(self, script):
            paused.set()
            assert resume.wait(timeout=3)
            return self.connection.executescript(script)

    def connect(instance):
        connection = original(instance)
        return connection if get_ident() == main_thread else PausedConnection(connection)

    monkeypatch.setattr(ActionStore, "_connect", connect)
    with ThreadPoolExecutor(max_workers=1) as pool:
        constructor = pool.submit(ActionStore, store.path)
        try:
            assert paused.wait(timeout=3)
            admission.enable_managed_transfers("d" * 64)
        finally:
            resume.set()
        constructor.result(timeout=3)
    with closing(sqlite3.connect(store.path)) as connection:
        assert connection.execute("PRAGMA user_version").fetchone()[0] == 3
